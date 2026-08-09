"""Federal income tax, payroll tax, and indexing helpers (2026 baseline).

Indexing assumptions are illustrative — see ASSUMPTIONS_NOTES and handoff §6.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import ContributionMethod, FilingStatus

# ---------------------------------------------------------------------------
# 2026 IRS / SSA baselines (verify when the model year rolls forward)
# ---------------------------------------------------------------------------

IRA_BASE_LIMIT_0 = 7_500.0
IRA_CATCHUP_LIMIT_0 = 1_100.0

OASDI_RATE = 0.062
OASDI_WAGE_BASE_0 = 184_500.0
MEDICARE_RATE = 0.0145
ADDITIONAL_MEDICARE_RATE = 0.009

# Additional Medicare thresholds are statutory / not inflation-indexed.
ADDITIONAL_MEDICARE_THRESHOLDS: dict[FilingStatus, float] = {
    FilingStatus.SINGLE: 200_000.0,
    FilingStatus.JOINT: 250_000.0,
    FilingStatus.MFS: 125_000.0,
    FilingStatus.HOH: 200_000.0,
}

STANDARD_DEDUCTION_0: dict[FilingStatus, float] = {
    FilingStatus.SINGLE: 16_100.0,
    FilingStatus.JOINT: 32_200.0,
    FilingStatus.MFS: 16_100.0,
    FilingStatus.HOH: 24_150.0,
}

# Bracket upper bounds for each marginal rate (None = open-ended top bracket).
# Rates: 10%, 12%, 22%, 24%, 32%, 35%, 37%
BRACKETS_0: dict[FilingStatus, list[tuple[float | None, float]]] = {
    FilingStatus.SINGLE: [
        (12_400.0, 0.10),
        (50_400.0, 0.12),
        (105_700.0, 0.22),
        (201_775.0, 0.24),
        (256_225.0, 0.32),
        (640_600.0, 0.35),
        (None, 0.37),
    ],
    FilingStatus.JOINT: [
        (24_800.0, 0.10),
        (100_800.0, 0.12),
        (211_400.0, 0.22),
        (403_550.0, 0.24),
        (512_450.0, 0.32),
        (768_700.0, 0.35),
        (None, 0.37),
    ],
    FilingStatus.HOH: [
        (17_700.0, 0.10),
        (67_450.0, 0.12),
        (105_700.0, 0.22),
        (201_750.0, 0.24),
        (256_200.0, 0.32),
        (640_600.0, 0.35),
        (None, 0.37),
    ],
    FilingStatus.MFS: [
        (12_400.0, 0.10),
        (50_400.0, 0.12),
        (105_700.0, 0.22),
        (201_775.0, 0.24),
        (256_225.0, 0.32),
        (384_350.0, 0.35),
        (None, 0.37),
    ],
}

# Illustrative: C-CPI-U historically ~90% of headline CPI — not IRS methodology.
CHAINED_CPI_RATIO = 0.90

# 2026 Roth MAGI phase-out bands (salary used as MAGI proxy in this model).
# Flag only — does not reduce contribution amount.
ROTH_MAGI_PHASE_OUT_0: dict[FilingStatus, tuple[float, float]] = {
    FilingStatus.SINGLE: (153_000.0, 168_000.0),
    FilingStatus.HOH: (153_000.0, 168_000.0),
    FilingStatus.JOINT: (242_000.0, 252_000.0),
    FilingStatus.MFS: (0.0, 10_000.0),
}

ASSUMPTIONS_NOTES = [
    "IRA contributions are capped at the lesser of the statutory annual limit "
    "(including catch-up) and modeled earned income for that year (IRC §219(b)(1)).",
    "Federal brackets and standard deduction are indexed with an illustrative C-CPI-U proxy "
    f"(~{int(CHAINED_CPI_RATIO * 100)}% of modeled headline inflation), not official IRS methodology.",
    "OASDI wage base is indexed by modeled CPI (rounded to $100) as a simplified projection; "
    "real SSA indexing uses the National Average Wage Index.",
    "Additional Medicare Tax thresholds are statutory and not inflation-indexed.",
    "Flat state tax (when enabled) is applied to federal taxable income and is illustrative only.",
    "Roth MAGI Direct/Backdoor flag uses modeled salary as a MAGI proxy and does not change "
    "contribution amounts. Phase-out bands use fixed 2026 statutory baselines for the whole "
    "horizon (not CPI-indexed): Single/HoH $153k–$168k, Joint $242k–$252k, MFS $0–$10k.",
]


def floor_to_nearest(step: float, value: float) -> float:
    if step <= 0:
        raise ValueError("step must be positive")
    return (value // step) * step


def round_to_nearest(step: float, value: float) -> float:
    if step <= 0:
        raise ValueError("step must be positive")
    return round(value / step) * step


def inflation_index(rate: float, years: int) -> float:
    return (1.0 + rate) ** years


def chained_cpi_index(headline_inflation: float, years: int) -> float:
    return (1.0 + headline_inflation * CHAINED_CPI_RATIO) ** years


def _bracket_round_step(status: FilingStatus) -> float:
    # IRC §1(f)(7)/(8): MFS rounds to nearest $25; others to nearest $50.
    return 25.0 if status == FilingStatus.MFS else 50.0


def indexed_standard_deduction(
    status: FilingStatus,
    headline_inflation: float,
    year_index: int,
) -> float:
    base = STANDARD_DEDUCTION_0[status]
    indexed = base * chained_cpi_index(headline_inflation, year_index)
    return round_to_nearest(_bracket_round_step(status), indexed)


def indexed_brackets(
    status: FilingStatus,
    headline_inflation: float,
    year_index: int,
) -> list[tuple[float | None, float]]:
    factor = chained_cpi_index(headline_inflation, year_index)
    step = _bracket_round_step(status)
    out: list[tuple[float | None, float]] = []
    for upper, rate in BRACKETS_0[status]:
        if upper is None:
            out.append((None, rate))
        else:
            out.append((round_to_nearest(step, upper * factor), rate))
    return out


def federal_income_tax(
    taxable_income: float,
    status: FilingStatus,
    headline_inflation: float,
    year_index: int,
) -> float:
    if taxable_income <= 0:
        return 0.0
    brackets = indexed_brackets(status, headline_inflation, year_index)
    tax = 0.0
    prev = 0.0
    for upper, rate in brackets:
        if upper is None:
            tax += (taxable_income - prev) * rate
            break
        if taxable_income <= upper:
            tax += (taxable_income - prev) * rate
            break
        tax += (upper - prev) * rate
        prev = upper
    return tax


def indexed_oasdi_wage_base(headline_inflation: float, year_index: int) -> float:
    raw = OASDI_WAGE_BASE_0 * inflation_index(headline_inflation, year_index)
    return round_to_nearest(100.0, raw)


def payroll_taxes(
    wages: float,
    status: FilingStatus,
    headline_inflation: float,
    year_index: int,
) -> tuple[float, float, float, float]:
    """Return (oasdi, medicare, additional_medicare, wage_base)."""
    if wages <= 0:
        base = indexed_oasdi_wage_base(headline_inflation, year_index)
        return 0.0, 0.0, 0.0, base

    wage_base = indexed_oasdi_wage_base(headline_inflation, year_index)
    oasdi = OASDI_RATE * min(wages, wage_base)
    medicare = MEDICARE_RATE * wages
    threshold = ADDITIONAL_MEDICARE_THRESHOLDS[status]
    additional = ADDITIONAL_MEDICARE_RATE * max(0.0, wages - threshold)
    return oasdi, medicare, additional, wage_base


def ira_contribution_limit(
    age: int,
    headline_inflation: float,
    year_index: int,
    base_limit_0: float = IRA_BASE_LIMIT_0,
    catchup_limit_0: float = IRA_CATCHUP_LIMIT_0,
) -> float:
    base = floor_to_nearest(500.0, base_limit_0 * inflation_index(headline_inflation, year_index))
    catchup = floor_to_nearest(
        100.0, catchup_limit_0 * inflation_index(headline_inflation, year_index)
    )
    return base + (catchup if age >= 50 else 0.0)


def indexed_roth_magi_band(
    status: FilingStatus,
    headline_inflation: float,
    year_index: int,
) -> tuple[float, float]:
    """Return the model-year MAGI phase-out band for ``status``.

    Bands are held at the year-0 statutory / baseline levels for the whole
    horizon (not CPI-indexed). Indexing the floors caused Backdoor to never
    appear in realistic salary paths — salary grew with merit while thresholds
    compounded with inflation and permanently outran income.
    ``headline_inflation`` / ``year_index`` are unused but kept for call-site
    compatibility with other indexed tax helpers.
    """
    del headline_inflation, year_index
    return ROTH_MAGI_PHASE_OUT_0[status]


def roth_contribution_method(
    salary: float,
    status: FilingStatus,
    headline_inflation: float,
    year_index: int,
) -> tuple[ContributionMethod, float, float]:
    """Return (method, phase_out_lower, phase_out_upper). Does not alter contribution $.

    Direct when salary (MAGI proxy) is strictly below the phase-out lower bound;
    Backdoor when salary is within or above the band (Excel labeling convention).
    """
    lower, upper = indexed_roth_magi_band(status, headline_inflation, year_index)
    method = (
        ContributionMethod.DIRECT
        if salary < lower
        else ContributionMethod.BACKDOOR
    )
    return method, lower, upper


@dataclass(frozen=True)
class YearTaxResult:
    filing_status: FilingStatus
    salary: float
    federal_taxable_income: float
    federal_income_tax: float
    oasdi_tax: float
    medicare_tax: float
    additional_medicare_tax: float
    state_tax: float
    total_tax: float
    oasdi_wage_base: float
    standard_deduction: float
    contribution_method: ContributionMethod
    magi_phase_out_lower: float
    magi_phase_out_upper: float


def compute_year_tax(
    *,
    salary: float,
    status: FilingStatus,
    headline_inflation: float,
    year_index: int,
    include_state_tax: bool,
    state_tax_rate: float,
) -> YearTaxResult:
    # Bracket / std-deduction lookups must use the same FilingStatus enum values as inputs.
    std = indexed_standard_deduction(status, headline_inflation, year_index)
    taxable = max(0.0, salary - std)
    federal = federal_income_tax(taxable, status, headline_inflation, year_index)
    oasdi, medicare, addl, wage_base = payroll_taxes(
        salary, status, headline_inflation, year_index
    )
    state = (state_tax_rate * taxable) if include_state_tax else 0.0
    total = federal + oasdi + medicare + addl + state
    method, magi_lo, magi_hi = roth_contribution_method(
        salary, status, headline_inflation, year_index
    )
    return YearTaxResult(
        filing_status=status,
        salary=salary,
        federal_taxable_income=taxable,
        federal_income_tax=federal,
        oasdi_tax=oasdi,
        medicare_tax=medicare,
        additional_medicare_tax=addl,
        state_tax=state,
        total_tax=total,
        oasdi_wage_base=wage_base,
        standard_deduction=std,
        contribution_method=method,
        magi_phase_out_lower=magi_lo,
        magi_phase_out_upper=magi_hi,
    )
