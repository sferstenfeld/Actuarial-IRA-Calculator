"""What-if shadow calculations + required-return solver.

Never mutate the base-case request — always model_copy with one varied parameter.
"""

from __future__ import annotations

from .models import (
    CalculateRequest,
    RequiredReturnResult,
    ScenarioCase,
    ScenarioResults,
)


def _periodic_final(req: CalculateRequest, **updates) -> tuple[float, float]:
    from .engine import run_projection_balances

    shadow = req.model_copy(update=updates) if updates else req
    return run_projection_balances(shadow)


def _bisection(fn, lo: float, hi: float, *, tol: float = 1e-10, max_iter: int = 200) -> float:
    flo, fhi = fn(lo), fn(hi)
    if flo == 0:
        return lo
    if fhi == 0:
        return hi
    if flo * fhi > 0:
        raise ValueError("root not bracketed")
    a, b, fa = lo, hi, flo
    for _ in range(max_iter):
        mid = 0.5 * (a + b)
        fm = fn(mid)
        if abs(fm) < tol or abs(b - a) < tol:
            return mid
        if fa * fm <= 0:
            b = mid
        else:
            a, fa = mid, fm
    return 0.5 * (a + b)


def solve_required_return(req: CalculateRequest) -> RequiredReturnResult | None:
    if req.target_retirement_balance is None:
        return None

    from .engine import inflation_years_to_retirement, projection_years, run_projection_balances

    years = projection_years(req)
    infl_years = inflation_years_to_retirement(req)
    target = req.target_retirement_balance
    if req.target_balance_is_real:
        target = target * ((1.0 + req.annual_inflation) ** infl_years)

    def gap(r: float) -> float:
        shadow = req.model_copy(update={"annual_return": max(0.0, r)})
        nom, _ = run_projection_balances(shadow)
        return nom - target

    if gap(0.0) >= 0:
        return RequiredReturnResult(
            solved=True,
            required_annual_return=0.0,
            target_nominal=target,
            message="Target reachable at 0% return (or lower); reporting 0%.",
        )

    lo, hi = 0.0, 0.05
    ghi = gap(hi)
    for _ in range(40):
        if ghi >= 0:
            break
        hi *= 2.0
        if hi > 10.0:
            return RequiredReturnResult(
                solved=False,
                required_annual_return=None,
                target_nominal=target,
                message="Target not reachable within a 1000% annual return search bound.",
            )
        ghi = gap(hi)
    else:
        return RequiredReturnResult(
            solved=False,
            required_annual_return=None,
            target_nominal=target,
            message="Could not bracket a required return.",
        )

    try:
        r_star = _bisection(gap, lo, hi)
    except ValueError:
        return RequiredReturnResult(
            solved=False,
            required_annual_return=None,
            target_nominal=target,
            message="Root not bracketed for required-return solve.",
        )

    return RequiredReturnResult(
        solved=True,
        required_annual_return=r_star,
        target_nominal=target,
        message="Solved via bisection on periodic-engine final balance.",
    )


def build_scenarios(req: CalculateRequest, base_nominal: float, base_real: float) -> ScenarioResults:
    spread = req.return_spread
    bear_r = max(0.0, req.annual_return - spread)
    bull_r = req.annual_return + spread

    bear_nom, bear_real = _periodic_final(req, annual_return=bear_r)
    bull_nom, bull_real = _periodic_final(req, annual_return=bull_r)

    return_cases = [
        ScenarioCase(
            label="Bear",
            final_balance_nominal=bear_nom,
            final_balance_real=bear_real,
            parameter_value=bear_r,
        ),
        ScenarioCase(
            label="Base",
            final_balance_nominal=base_nominal,
            final_balance_real=base_real,
            parameter_value=req.annual_return,
        ),
        ScenarioCase(
            label="Bull",
            final_balance_nominal=bull_nom,
            final_balance_real=bull_real,
            parameter_value=bull_r,
        ),
    ]

    swing = req.inflation_swing
    low_i = max(0.0, req.annual_inflation - swing)
    high_i = req.annual_inflation + swing
    from .engine import inflation_years_to_retirement

    infl_years = inflation_years_to_retirement(req)

    def real_at(inflation: float) -> float:
        # Handoff §8: inflation swing does not change nominal; only the real figure.
        return (
            base_nominal / ((1.0 + inflation) ** infl_years) if infl_years else base_nominal
        )

    inflation_cases = [
        ScenarioCase(
            label="Low inflation",
            final_balance_nominal=base_nominal,
            final_balance_real=real_at(low_i),
            parameter_value=low_i,
        ),
        ScenarioCase(
            label="Base",
            final_balance_nominal=base_nominal,
            final_balance_real=base_real,
            parameter_value=req.annual_inflation,
        ),
        ScenarioCase(
            label="High inflation",
            final_balance_nominal=base_nominal,
            final_balance_real=real_at(high_i),
            parameter_value=high_i,
        ),
    ]

    gap_case = None
    if req.contribution_gap_length > 0 and req.contribution_gap_start_year is not None:
        no_gap_nom, _ = _periodic_final(
            req,
            contribution_gap_start_year=None,
            contribution_gap_length=0,
        )
        gap_case = ScenarioCase(
            label=(
                f"Gap {req.contribution_gap_length}y from y{req.contribution_gap_start_year} "
                f"(no-gap would be {no_gap_nom:,.0f})"
            ),
            final_balance_nominal=base_nominal,
            final_balance_real=base_real,
            parameter_value=float(req.contribution_gap_length),
        )

    early_case = None
    if req.early_stop_age is not None:
        # Contrast vs never stopping
        never_stop_nom, _ = _periodic_final(req, early_stop_age=None)
        early_case = ScenarioCase(
            label=(
                f"Early stop at age {req.early_stop_age} "
                f"(full contrib would be {never_stop_nom:,.0f})"
            ),
            final_balance_nominal=base_nominal,
            final_balance_real=base_real,
            parameter_value=float(req.early_stop_age),
        )

    return ScenarioResults(
        return_cases=return_cases,
        inflation_cases=inflation_cases,
        contribution_gap=gap_case,
        early_stop=early_case,
        required_return=solve_required_return(req),
    )
