"""Annual and periodic Roth IRA accumulation engines + vintage TV + milestones."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .actuary import build_salary_path
from .models import (
    CalculateRequest,
    CalculateResponse,
    CompoundingMilestone,
    ContributionTiming,
    Milestone,
    YearProjection,
    YearTaxBreakdown,
)
from .scenarios import build_scenarios
from .tax import (
    ASSUMPTIONS_NOTES,
    IRA_BASE_LIMIT_0,
    IRA_CATCHUP_LIMIT_0,
    compute_year_tax,
    ira_contribution_limit,
)

VINTAGE_TOLERANCE = 1e-6
BALANCE_MILESTONE_PERCENTAGES: tuple[float, ...] = (0.25, 0.50, 0.75)
NOMINAL_BALANCE_MILESTONE_THRESHOLDS: tuple[float, ...] = (
    500_000.0,
    1_000_000.0,
    2_000_000.0,
    5_000_000.0,
    10_000_000.0,
    20_000_000.0,
    50_000_000.0,
)
SALARY_MILESTONE_THRESHOLDS: tuple[float, ...] = (
    50_000.0,
    75_000.0,
    100_000.0,
    125_000.0,
    150_000.0,
    175_000.0,
    200_000.0,
    250_000.0,
    300_000.0,
    400_000.0,
    500_000.0,
)


def _fmt_dollars(amount: float) -> str:
    return f"${amount:,.0f}"


def projection_years(req: CalculateRequest) -> int:
    """Exclusive horizon: N = retirement_age − starting_age.

    Annuity-due contributions at times 0..N−1 (ages start .. retire−1), valued at time N.
    """
    return req.retirement_age - req.starting_age


def inflation_years_to_retirement(req: CalculateRequest) -> int:
    """Years of inflation from today to retirement for the *final* real KPI.

    Matches the exclusive investment horizon (retirement − starting).
    """
    return req.retirement_age - req.starting_age


def inflation_years_elapsed(year_index: int) -> int:
    """Inflation years elapsed by the *ending* balance of contribution year ``year_index``.

    Beginning-of-period timing: a full year of compounding (and inflation) has
    elapsed by the time the year-0 ending balance is measured, so n = year_index + 1.
    After N exclusive years (indices 0..N−1), the final point has n = N years of
    inflation — matching ``inflation_years_to_retirement``.
    """
    if year_index < 0:
        raise ValueError("year_index must be non-negative")
    return year_index + 1


def periodic_rate(annual_return: float, periods_per_year: int) -> float:
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    return (1.0 + annual_return) ** (1.0 / periods_per_year) - 1.0


def salary_at_year(starting_salary: float, merit_raise: float, year_index: int) -> float:
    return starting_salary * ((1.0 + merit_raise) ** year_index)


def contribution_allowed(
    req: CalculateRequest,
    *,
    year_index: int,
    age: int,
) -> bool:
    """True when the person would contribute this year (ignore earned-income cap)."""
    if year_index < req.contribution_delay_years:
        return False
    if req.early_stop_age is not None and age >= req.early_stop_age:
        return False
    if (
        req.contribution_gap_length > 0
        and req.contribution_gap_start_year is not None
        and req.contribution_gap_start_year
        <= year_index
        < req.contribution_gap_start_year + req.contribution_gap_length
    ):
        return False
    return True


def year_contribution_amount(
    req: CalculateRequest,
    *,
    year_index: int,
    age: int,
    limit: float,
    earned_income: float,
) -> float:
    """Contribution = min(statutory limit incl. catch-up, earned income) when allowed.

    IRC §219(b)(1): annual IRA contributions cannot exceed taxable compensation.
    """
    if not contribution_allowed(req, year_index=year_index, age=age):
        return 0.0
    return min(limit, max(0.0, earned_income))


def growth_multiple_for_period(
    *,
    period_index: int,
    total_periods: int,
    rate: float,
    timing: ContributionTiming,
) -> float:
    """Periods of growth until valuation at the horizon end.

    With exclusive horizon N = retirement − start (total_periods = N × ppy):
    - Beginning (annuity-due): remaining = total − index → first vintage (1+r)^N
    - End (annuity-immediate): remaining = total − index − 1 → first vintage (1+r)^(N−1)

    Periods remaining for a Beginning contribution at age a is exactly
    (retirement_age − a) — no extra +1.
    """
    if total_periods < 0 or period_index < 0:
        raise ValueError("period indices must be non-negative")
    if timing == ContributionTiming.BEGINNING:
        periods_remaining = total_periods - period_index
    else:
        periods_remaining = total_periods - period_index - 1
    if periods_remaining < 0:
        periods_remaining = 0
    return (1.0 + rate) ** periods_remaining


def seed_growth_multiple(total_periods: int, rate: float) -> float:
    return (1.0 + rate) ** total_periods


@dataclass(frozen=True)
class VintageResult:
    seed_growth_multiple: float
    seed_terminal_value: float
    year_growth_multiples: list[float]
    year_terminal_values: list[float]


def _limits_and_contribs(req: CalculateRequest, years: int) -> tuple[list[float], list[float]]:
    base_0 = req.ira_base_limit_0 if req.ira_base_limit_0 is not None else IRA_BASE_LIMIT_0
    catchup_0 = (
        req.ira_catchup_limit_0 if req.ira_catchup_limit_0 is not None else IRA_CATCHUP_LIMIT_0
    )
    salaries = build_salary_path(req, years)
    limits: list[float] = []
    contribs: list[float] = []
    for t in range(years):
        age = req.starting_age + t
        limit = ira_contribution_limit(
            age,
            req.annual_inflation,
            t,
            base_limit_0=base_0,
            catchup_limit_0=catchup_0,
        )
        limits.append(limit)
        contribs.append(
            year_contribution_amount(
                req,
                year_index=t,
                age=age,
                limit=limit,
                earned_income=salaries[t],
            )
        )
    return limits, contribs


def compute_vintages(req: CalculateRequest, years: int, ppy: int) -> VintageResult:
    total_periods = years * ppy
    r = periodic_rate(req.annual_return, ppy) if ppy > 0 and years > 0 else 0.0
    seed_gm = seed_growth_multiple(total_periods, r)
    seed_tv = req.current_ira_balance * seed_gm
    _, contribs = _limits_and_contribs(req, years)

    year_gms: list[float] = []
    year_tvs: list[float] = []
    for t in range(years):
        first_period = t * ppy
        year_gms.append(
            growth_multiple_for_period(
                period_index=first_period,
                total_periods=total_periods,
                rate=r,
                timing=req.contribution_timing,
            )
        )
        per_period = contribs[t] / ppy if ppy else 0.0
        year_tv = 0.0
        for p in range(ppy):
            gm = growth_multiple_for_period(
                period_index=first_period + p,
                total_periods=total_periods,
                rate=r,
                timing=req.contribution_timing,
            )
            year_tv += per_period * gm
        year_tvs.append(year_tv)

    return VintageResult(
        seed_growth_multiple=seed_gm,
        seed_terminal_value=seed_tv,
        year_growth_multiples=year_gms,
        year_terminal_values=year_tvs,
    )


def run_annual_engine(req: CalculateRequest, years: int) -> tuple[list[float], list[float], list[float]]:
    limits, contribs = _limits_and_contribs(req, years)
    balance = req.current_ira_balance
    ending: list[float] = []
    for t in range(years):
        contrib = contribs[t]
        if req.contribution_timing == ContributionTiming.BEGINNING:
            balance = (balance + contrib) * (1.0 + req.annual_return)
        else:
            balance = balance * (1.0 + req.annual_return) + contrib
        ending.append(balance)
    return ending, contribs, limits


def run_periodic_engine(
    req: CalculateRequest, years: int, ppy: int
) -> tuple[list[float], list[float], list[float], float]:
    limits, contribs = _limits_and_contribs(req, years)
    r = periodic_rate(req.annual_return, ppy)
    balance = req.current_ira_balance
    ending: list[float] = []
    for t in range(years):
        per_period = contribs[t] / ppy
        for _ in range(ppy):
            if req.contribution_timing == ContributionTiming.BEGINNING:
                balance = (balance + per_period) * (1.0 + r)
            else:
                balance = balance * (1.0 + r) + per_period
        ending.append(balance)
    return ending, contribs, limits, r


def run_projection_balances(req: CalculateRequest) -> tuple[float, float]:
    """Lightweight nominal/real finals for scenario shadow calcs."""
    years = projection_years(req)
    infl_years = inflation_years_to_retirement(req)
    ppy = req.periods_per_year()
    if years <= 0:
        return req.current_ira_balance, req.current_ira_balance
    ending, _, _, _ = run_periodic_engine(req, years, ppy)
    nom = ending[-1]
    real = nom / ((1.0 + req.annual_inflation) ** infl_years) if infl_years else nom
    return nom, real


def _first_crossing(
    *,
    starting_age: int,
    seed: float,
    year_ending_values: list[float],
    threshold: float,
) -> tuple[bool, int | None, int | None, float | None]:
    """Return (reached, age, year_index, value_at_crossing). year_index -1 = seed."""
    if seed >= threshold:
        return True, starting_age, -1, seed
    for t, value in enumerate(year_ending_values):
        if value >= threshold:
            return True, starting_age + t, t, value
    return False, None, None, None


def compute_balance_milestones(
    *,
    starting_age: int,
    seed: float,
    year_ending_balances: list[float],
    percentages: tuple[float, ...] = BALANCE_MILESTONE_PERCENTAGES,
) -> list[Milestone]:
    """Balance milestones at fixed % of this scenario's final nominal balance."""
    final = year_ending_balances[-1] if year_ending_balances else seed
    if final <= 0:
        return []

    milestones: list[Milestone] = []
    for pct in percentages:
        target = final * pct
        pct_label = f"{int(round(pct * 100))}%"
        reached, age, year_index, bal = _first_crossing(
            starting_age=starting_age,
            seed=seed,
            year_ending_values=year_ending_balances,
            threshold=target,
        )
        label = f"{pct_label} of final balance ({_fmt_dollars(target)})"
        if reached:
            milestones.append(
                Milestone(
                    label=label,
                    threshold=target,
                    reached=True,
                    age=age,
                    year_index=year_index,
                    balance_at_crossing=bal,
                )
            )
        else:
            # Should be rare (final always reaches 100%); keep a miss row for safety.
            milestones.append(Milestone(label=label, threshold=target, reached=False))
    return milestones


def compute_nominal_balance_milestones(
    *,
    starting_age: int,
    seed: float,
    year_ending_balances: list[float],
    thresholds: tuple[float, ...] = NOMINAL_BALANCE_MILESTONE_THRESHOLDS,
) -> list[Milestone]:
    """Round-dollar nominal balance crossings at or below final balance."""
    final = year_ending_balances[-1] if year_ending_balances else seed
    relevant = [t for t in thresholds if t <= final]
    milestones: list[Milestone] = []
    for threshold in relevant:
        reached, age, year_index, bal = _first_crossing(
            starting_age=starting_age,
            seed=seed,
            year_ending_values=year_ending_balances,
            threshold=threshold,
        )
        if not reached:
            continue
        milestones.append(
            Milestone(
                label=f"Nominal balance crosses {_fmt_dollars(threshold)}",
                threshold=threshold,
                reached=True,
                age=age,
                year_index=year_index,
                balance_at_crossing=bal,
            )
        )
    return milestones


def doubling_time_years(annual_return: float) -> float | None:
    """Exact years to double at continuous annual compounding: ln(2)/ln(1+r)."""
    if annual_return <= 0:
        return None
    return math.log(2.0) / math.log(1.0 + annual_return)


def cumulative_doublings_at_elapsed(annual_return: float, elapsed_years: float) -> int:
    """Whole-year cumulative doublings: floor(log2((1+r)^elapsed))."""
    if annual_return <= 0 or elapsed_years <= 0:
        return 0
    return int(math.floor(math.log2((1.0 + annual_return) ** elapsed_years)))


def compute_compounding_milestones(
    *,
    starting_age: int,
    retirement_age: int,
    annual_return: float,
) -> list[CompoundingMilestone]:
    """Fractional-age first-contribution doublings within [start, retirement]."""
    dt = doubling_time_years(annual_return)
    if dt is None:
        return []
    milestones: list[CompoundingMilestone] = []
    n = 1
    while n <= 64:
        age = starting_age + n * dt
        if age > retirement_age:
            break
        milestones.append(
            CompoundingMilestone(
                doubling_number=n,
                age=age,
                from_multiple=float(2 ** (n - 1)),
                to_multiple=float(2**n),
            )
        )
        n += 1
    return milestones


def compute_salary_milestones(
    *,
    starting_age: int,
    starting_salary: float,
    salaries: list[float],
    thresholds: tuple[float, ...] = SALARY_MILESTONE_THRESHOLDS,
) -> list[Milestone]:
    """Round-dollar salary crossings within (starting_salary, final_salary]."""
    if not salaries:
        return []
    final_salary = salaries[-1]
    relevant = [t for t in thresholds if starting_salary < t <= final_salary]
    milestones: list[Milestone] = []
    for threshold in relevant:
        # Salary path has no separate seed — year 0 is the starting salary (possibly
        # with Actuary Mode bonuses). Search the annual path only.
        hit_age: int | None = None
        hit_index: int | None = None
        hit_value: float | None = None
        for t, salary in enumerate(salaries):
            if salary >= threshold:
                hit_age = starting_age + t
                hit_index = t
                hit_value = salary
                break
        if hit_age is None:
            continue
        milestones.append(
            Milestone(
                label=f"Salary crosses {_fmt_dollars(threshold)}",
                threshold=threshold,
                reached=True,
                age=hit_age,
                year_index=hit_index,
                balance_at_crossing=hit_value,
            )
        )
    return milestones


def _req_from_engine_kwargs(
    *,
    seed: float,
    years: int,
    annual_return: float,
    timing: ContributionTiming,
    contribution_delay_years: int,
    starting_age: int,
    inflation: float,
    base_limit_0: float,
    catchup_limit_0: float,
    periods_per_year: int = 1,
) -> CalculateRequest:
    from .models import ContributionFrequency

    freq_map = {
        1: ContributionFrequency.ANNUAL,
        2: ContributionFrequency.SEMIANNUAL,
        4: ContributionFrequency.QUARTERLY,
        12: ContributionFrequency.MONTHLY,
        52: ContributionFrequency.WEEKLY,
    }
    common = dict(
        starting_age=starting_age,
        retirement_age=starting_age + years,
        current_ira_balance=seed,
        annual_return=annual_return,
        annual_inflation=inflation,
        contribution_timing=timing,
        contribution_delay_years=contribution_delay_years,
        # Engine-kw unit tests isolate limit/timing math; keep earned income above
        # the statutory limit so IRC §219(b)(1) does not distort those fixtures.
        starting_salary=1_000_000.0,
        annual_merit_raise=0.0,
        ira_base_limit_0=base_limit_0,
        ira_catchup_limit_0=catchup_limit_0,
    )
    if periods_per_year in freq_map:
        return CalculateRequest(contribution_frequency=freq_map[periods_per_year], **common)
    interval = 252 // periods_per_year
    return CalculateRequest(
        contribution_frequency=ContributionFrequency.ADVANCED,
        trading_day_interval=interval,
        **common,
    )


def run_annual_engine_kw(
    *,
    seed: float,
    years: int,
    annual_return: float,
    timing: ContributionTiming,
    contribution_delay_years: int,
    starting_age: int,
    inflation: float,
    base_limit_0: float,
    catchup_limit_0: float,
) -> tuple[list[float], list[float], list[float]]:
    req = _req_from_engine_kwargs(
        seed=seed,
        years=years,
        annual_return=annual_return,
        timing=timing,
        contribution_delay_years=contribution_delay_years,
        starting_age=starting_age,
        inflation=inflation,
        base_limit_0=base_limit_0,
        catchup_limit_0=catchup_limit_0,
        periods_per_year=1,
    )
    return run_annual_engine(req, years)


def run_periodic_engine_kw(
    *,
    seed: float,
    years: int,
    annual_return: float,
    periods_per_year: int,
    timing: ContributionTiming,
    contribution_delay_years: int,
    starting_age: int,
    inflation: float,
    base_limit_0: float,
    catchup_limit_0: float,
) -> tuple[list[float], list[float], list[float], float]:
    req = _req_from_engine_kwargs(
        seed=seed,
        years=years,
        annual_return=annual_return,
        timing=timing,
        contribution_delay_years=contribution_delay_years,
        starting_age=starting_age,
        inflation=inflation,
        base_limit_0=base_limit_0,
        catchup_limit_0=catchup_limit_0,
        periods_per_year=periods_per_year,
    )
    return run_periodic_engine(req, years, periods_per_year)


def calculate(req: CalculateRequest) -> CalculateResponse:
    years = projection_years(req)
    ppy = req.periods_per_year()

    annual_ending, contribs, limits = run_annual_engine(req, years)
    periodic_ending, contribs, limits, r = run_periodic_engine(req, years, ppy)
    vintages = compute_vintages(req, years, ppy)

    year_rows: list[YearProjection] = []
    total_fed = total_payroll = total_state = total_tax = 0.0
    total_gross = 0.0
    salaries = build_salary_path(req, years)
    milestones = compute_balance_milestones(
        starting_age=req.starting_age,
        seed=req.current_ira_balance,
        year_ending_balances=periodic_ending,
    )
    nominal_balance_milestones = compute_nominal_balance_milestones(
        starting_age=req.starting_age,
        seed=req.current_ira_balance,
        year_ending_balances=periodic_ending,
    )
    salary_milestones = compute_salary_milestones(
        starting_age=req.starting_age,
        starting_salary=req.starting_salary,
        salaries=salaries,
    )
    compounding_milestones = compute_compounding_milestones(
        starting_age=req.starting_age,
        retirement_age=req.retirement_age,
        annual_return=req.annual_return,
    )

    for t in range(years):
        # Age during this contribution year (limits, catch-up, charts, early-stop).
        # Exclusive horizon → ages run starting_age .. retirement_age - 1.
        age = req.starting_age + t
        tax = compute_year_tax(
            salary=salaries[t],
            status=req.filing_status_for_year(t),
            headline_inflation=req.annual_inflation,
            year_index=t,
            include_state_tax=req.include_state_tax,
            state_tax_rate=req.state_tax_rate,
        )
        total_gross += tax.salary
        total_fed += tax.federal_income_tax
        total_payroll += tax.oasdi_tax + tax.medicare_tax + tax.additional_medicare_tax
        total_state += tax.state_tax
        total_tax += tax.total_tax
        infl_n = inflation_years_elapsed(t)
        real_bal = periodic_ending[t] / ((1.0 + req.annual_inflation) ** infl_n)
        year_rows.append(
            YearProjection(
                year_index=t,
                age=age,
                ira_limit=limits[t],
                contribution=contribs[t],
                contribution_capped_by_income=(
                    contribution_allowed(req, year_index=t, age=age)
                    and contribs[t] + 1e-9 < limits[t]
                ),
                growth_multiple=vintages.year_growth_multiples[t],
                terminal_value=vintages.year_terminal_values[t],
                ending_balance_annual=annual_ending[t],
                ending_balance_periodic=periodic_ending[t],
                ending_balance_real_periodic=real_bal,
                cumulative_doublings=cumulative_doublings_at_elapsed(
                    req.annual_return, float(t)
                ),
                tax=YearTaxBreakdown(
                    year_index=t,
                    age=age,
                    filing_status=tax.filing_status,
                    salary=tax.salary,
                    federal_taxable_income=tax.federal_taxable_income,
                    federal_income_tax=tax.federal_income_tax,
                    oasdi_tax=tax.oasdi_tax,
                    medicare_tax=tax.medicare_tax,
                    additional_medicare_tax=tax.additional_medicare_tax,
                    state_tax=tax.state_tax,
                    total_tax=tax.total_tax,
                    oasdi_wage_base=tax.oasdi_wage_base,
                    standard_deduction=tax.standard_deduction,
                    contribution_method=tax.contribution_method,
                    magi_phase_out_lower=tax.magi_phase_out_lower,
                    magi_phase_out_upper=tax.magi_phase_out_upper,
                ),
            )
        )

    years_capped = sum(1 for y in year_rows if y.contribution_capped_by_income)

    final_periodic = periodic_ending[-1] if years else req.current_ira_balance
    final_annual = annual_ending[-1] if years else req.current_ira_balance
    infl_years = inflation_years_to_retirement(req)
    final_real = (
        final_periodic / ((1.0 + req.annual_inflation) ** infl_years)
        if infl_years
        else final_periodic
    )

    sum_year_tvs = sum(vintages.year_terminal_values)
    if years == 0:
        cross_ok = True
        seed_gm, seed_tv = 1.0, req.current_ira_balance
        sum_year_tvs = 0.0
    else:
        cross_ok = abs(vintages.seed_terminal_value + sum_year_tvs - final_periodic) <= VINTAGE_TOLERANCE
        seed_gm, seed_tv = vintages.seed_growth_multiple, vintages.seed_terminal_value

    scenarios = build_scenarios(req, final_periodic, final_real)

    return CalculateResponse(
        years_to_retirement=years,
        periods_per_year=ppy,
        periodic_rate=r if years else 0.0,
        final_balance_annual=final_annual,
        final_balance_periodic=final_periodic,
        final_balance_real_periodic=final_real,
        total_contributions=sum(contribs),
        seed_balance=req.current_ira_balance,
        seed_growth_multiple=seed_gm,
        seed_terminal_value=seed_tv,
        sum_contribution_terminal_values=sum_year_tvs,
        vintage_cross_check_ok=cross_ok,
        years_contribution_capped_by_income=years_capped,
        milestones=milestones,
        nominal_balance_milestones=nominal_balance_milestones,
        salary_milestones=salary_milestones,
        compounding_milestones=compounding_milestones,
        scenarios=scenarios,
        total_federal_income_tax=total_fed,
        total_payroll_tax=total_payroll,
        total_state_tax=total_state,
        total_tax=total_tax,
        total_gross_income=total_gross,
        years=year_rows,
        assumptions_notes=list(ASSUMPTIONS_NOTES),
    )
