"""Pydantic request/response schemas for the Roth IRA calculator."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FilingStatus(str, Enum):
    """Canonical filing-status labels — use these keys everywhere (UI + tax tables)."""

    SINGLE = "Single"
    JOINT = "Joint"
    MFS = "Married Filing Separately"
    HOH = "Head of Household"


class ContributionFrequency(str, Enum):
    ANNUAL = "Annual"
    SEMIANNUAL = "Semiannual"
    QUARTERLY = "Quarterly"
    MONTHLY = "Monthly"
    WEEKLY = "Weekly"
    ADVANCED = "Advanced"


class ContributionTiming(str, Enum):
    BEGINNING = "Beginning"
    END = "End"


class CredentialStatus(str, Enum):
    NOT_YET = "Not yet credentialed"
    ASSOCIATE = "ASA-ACAS"
    FELLOW = "FSA-FCAS"


class ContributionMethod(str, Enum):
    """Roth contribution mechanism flag — does not change modeled contribution amount."""

    DIRECT = "Direct"
    BACKDOOR = "Backdoor"


FREQUENCY_PERIODS: dict[ContributionFrequency, int] = {
    ContributionFrequency.ANNUAL: 1,
    ContributionFrequency.SEMIANNUAL: 2,
    ContributionFrequency.QUARTERLY: 4,
    ContributionFrequency.MONTHLY: 12,
    ContributionFrequency.WEEKLY: 52,
}


class CalculateRequest(BaseModel):
    starting_age: int = Field(ge=0, le=120)
    retirement_age: int = Field(ge=1, le=120)
    current_ira_balance: float = Field(ge=0, default=0.0)
    contribution_frequency: ContributionFrequency = ContributionFrequency.MONTHLY
    trading_day_interval: int | None = Field(default=None, ge=1, le=252)
    annual_return: float = Field(ge=0, description="Nominal annual return as decimal")
    annual_inflation: float = Field(ge=0, description="Annual inflation as decimal")
    contribution_timing: ContributionTiming = ContributionTiming.BEGINNING
    contribution_delay_years: int = Field(ge=0, default=0)
    filing_status: FilingStatus = FilingStatus.SINGLE
    filing_status_change_enabled: bool = False
    target_filing_status: FilingStatus | None = None
    years_until_filing_status_change: int = Field(ge=0, default=0)
    include_state_tax: bool = False
    state_tax_rate: float = Field(ge=0, default=0.0)
    starting_salary: float = Field(ge=0, default=0.0)
    annual_merit_raise: float = Field(ge=0, default=0.0)
    actuary_mode: bool = False
    credential_status: CredentialStatus = CredentialStatus.NOT_YET
    exams_remaining: int = Field(ge=0, default=0)
    salary_raise_per_exam: float = Field(ge=0, default=0.0)
    salary_raise_associate: float = Field(ge=0, default=0.0)
    years_until_associate: int = Field(ge=0, default=0)
    salary_raise_fellowship: float = Field(ge=0, default=0.0)
    years_until_fellowship: int = Field(ge=0, default=0)
    years_until_exams_finish: int = Field(ge=0, default=0)
    cap_salary_growth: bool = False
    salary_cap: float | None = Field(default=None, ge=0)
    # --- What-If scenario inputs (Phase 6) ---
    return_spread: float = Field(
        ge=0, default=0.03, description="Bear/Bull return offset in decimal points"
    )
    inflation_swing: float = Field(
        ge=0, default=0.015, description="Low/High inflation offset in decimal points"
    )
    contribution_gap_start_year: int | None = Field(default=None, ge=0)
    contribution_gap_length: int = Field(ge=0, default=0)
    early_stop_age: int | None = Field(default=None, ge=0)
    target_retirement_balance: float | None = Field(default=None, ge=0)
    target_balance_is_real: bool = False
    ira_base_limit_0: float | None = Field(default=None, ge=0)
    ira_catchup_limit_0: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate(self) -> CalculateRequest:
        if self.retirement_age <= self.starting_age:
            raise ValueError("retirement_age must be greater than starting_age")
        if self.contribution_frequency == ContributionFrequency.ADVANCED:
            if self.trading_day_interval is None:
                raise ValueError("trading_day_interval is required when frequency is Advanced")
            if 252 % self.trading_day_interval != 0:
                raise ValueError("trading_day_interval must divide 252 evenly")
        if self.filing_status_change_enabled and self.target_filing_status is None:
            raise ValueError(
                "target_filing_status is required when filing_status_change_enabled is true"
            )
        if (
            self.actuary_mode
            and self.credential_status == CredentialStatus.NOT_YET
            and self.years_until_fellowship < self.years_until_associate
        ):
            raise ValueError(
                "years_until_fellowship must be >= years_until_associate "
                "when credential status is Not yet credentialed"
            )
        if self.cap_salary_growth:
            if self.salary_cap is None:
                raise ValueError("salary_cap is required when cap_salary_growth is true")
            if self.salary_cap < self.starting_salary:
                raise ValueError("salary_cap must be >= starting_salary")
        if self.contribution_gap_length > 0 and self.contribution_gap_start_year is None:
            raise ValueError(
                "contribution_gap_start_year is required when contribution_gap_length > 0"
            )
        if self.early_stop_age is not None and self.early_stop_age > self.retirement_age:
            raise ValueError("early_stop_age cannot exceed retirement_age")
        return self

    def periods_per_year(self) -> int:
        if self.contribution_frequency == ContributionFrequency.ADVANCED:
            assert self.trading_day_interval is not None
            return 252 // self.trading_day_interval
        return FREQUENCY_PERIODS[self.contribution_frequency]

    def filing_status_for_year(self, year_index: int) -> FilingStatus:
        if not self.filing_status_change_enabled:
            return self.filing_status
        assert self.target_filing_status is not None
        if year_index >= self.years_until_filing_status_change:
            return self.target_filing_status
        return self.filing_status


class YearTaxBreakdown(BaseModel):
    year_index: int
    age: int
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


class YearProjection(BaseModel):
    year_index: int
    age: int
    ira_limit: float
    contribution: float
    # True when IRC §219(b)(1) earned-income cap reduced the contribution below the
    # statutory limit (incl. catch-up) in a year the person would otherwise contribute.
    contribution_capped_by_income: bool = False
    growth_multiple: float
    terminal_value: float
    ending_balance_annual: float
    ending_balance_periodic: float
    ending_balance_real_periodic: float
    tax: YearTaxBreakdown


class Milestone(BaseModel):
    label: str
    threshold: float
    reached: bool
    age: int | None = None
    year_index: int | None = None
    balance_at_crossing: float | None = None


class ScenarioCase(BaseModel):
    label: str
    final_balance_nominal: float
    final_balance_real: float
    parameter_value: float | None = None


class RequiredReturnResult(BaseModel):
    solved: bool
    required_annual_return: float | None = None
    target_nominal: float
    message: str


class ScenarioResults(BaseModel):
    return_cases: list[ScenarioCase]
    inflation_cases: list[ScenarioCase]
    contribution_gap: ScenarioCase | None = None
    early_stop: ScenarioCase | None = None
    required_return: RequiredReturnResult | None = None


class CalculateResponse(BaseModel):
    years_to_retirement: int
    periods_per_year: int
    periodic_rate: float
    final_balance_annual: float
    final_balance_periodic: float
    final_balance_real_periodic: float
    total_contributions: float
    seed_balance: float
    seed_growth_multiple: float
    seed_terminal_value: float
    sum_contribution_terminal_values: float
    vintage_cross_check_ok: bool
    years_contribution_capped_by_income: int = 0
    milestones: list[Milestone]
    salary_milestones: list[Milestone] = []
    scenarios: ScenarioResults
    total_federal_income_tax: float
    total_payroll_tax: float
    total_state_tax: float
    total_tax: float
    # Sum of modeled salaries over the horizon (for allocation / effective rates).
    total_gross_income: float
    years: list[YearProjection]
    assumptions_notes: list[str]


class HealthResponse(BaseModel):
    status: Literal["ok"]
