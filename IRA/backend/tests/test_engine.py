"""Phase-1/2 engine and tax edge-case tests (Excel regression fixtures TBD)."""

from __future__ import annotations

import math

import pytest

from backend.engine import calculate, periodic_rate, run_annual_engine_kw as run_annual_engine, run_periodic_engine_kw as run_periodic_engine
from backend.models import (
    CalculateRequest,
    ContributionFrequency,
    ContributionMethod,
    ContributionTiming,
    FilingStatus,
)
from backend.tax import (
    ADDITIONAL_MEDICARE_THRESHOLDS,
    BRACKETS_0,
    IRA_BASE_LIMIT_0,
    IRA_CATCHUP_LIMIT_0,
    ROTH_MAGI_PHASE_OUT_0,
    STANDARD_DEDUCTION_0,
    _bracket_round_step,
    compute_year_tax,
    federal_income_tax,
    indexed_standard_deduction,
    ira_contribution_limit,
    payroll_taxes,
)


def _base_req(**overrides) -> CalculateRequest:
    data = dict(
        starting_age=30,
        retirement_age=35,
        current_ira_balance=10_000.0,
        contribution_frequency=ContributionFrequency.ANNUAL,
        annual_return=0.07,
        annual_inflation=0.02,
        contribution_timing=ContributionTiming.BEGINNING,
        contribution_delay_years=0,
        filing_status=FilingStatus.SINGLE,
        starting_salary=80_000.0,
        annual_merit_raise=0.03,
    )
    data.update(overrides)
    return CalculateRequest(**data)


def test_zero_return_balance_equals_seed_plus_contributions():
    years = 5
    ending, contribs, _, _ = run_periodic_engine(
        seed=5_000.0,
        years=years,
        annual_return=0.0,
        periods_per_year=12,
        timing=ContributionTiming.BEGINNING,
        contribution_delay_years=0,
        starting_age=40,
        inflation=0.0,
        base_limit_0=IRA_BASE_LIMIT_0,
        catchup_limit_0=IRA_CATCHUP_LIMIT_0,
    )
    assert ending[-1] == pytest.approx(5_000.0 + sum(contribs), abs=1e-6)


def test_zero_inflation_real_equals_nominal():
    resp = calculate(
        _base_req(annual_inflation=0.0, retirement_age=40, starting_age=30)
    )
    for row in resp.years:
        assert row.ending_balance_real_periodic == pytest.approx(
            row.ending_balance_periodic, abs=1e-6
        )


def test_first_year_real_balance_deflates_one_year():
    """End of first Beginning-timed year has one full year of inflation elapsed."""
    resp = calculate(
        _base_req(
            starting_age=25,
            retirement_age=65,
            current_ira_balance=0.0,
            annual_return=0.07,
            annual_inflation=0.03,
            contribution_frequency=ContributionFrequency.ANNUAL,
            contribution_timing=ContributionTiming.BEGINNING,
            contribution_delay_years=0,
            starting_salary=100_000.0,
            annual_merit_raise=0.0,
        )
    )
    y0 = resp.years[0]
    assert y0.ending_balance_periodic == pytest.approx(8_025.0, abs=0.5)
    assert y0.ending_balance_real_periodic == pytest.approx(8_025.0 / 1.03, abs=0.5)
    # Later years keep compounding the inflation exponent (t+1).
    y10 = resp.years[10]
    assert y10.ending_balance_real_periodic == pytest.approx(
        y10.ending_balance_periodic / (1.03**11), rel=1e-9
    )
    y20 = resp.years[20]
    assert y20.ending_balance_real_periodic == pytest.approx(
        y20.ending_balance_periodic / (1.03**21), rel=1e-9
    )
    # Summary final real stays on Excel's exclusive N (not series t+1).
    assert resp.final_balance_real_periodic == pytest.approx(
        resp.final_balance_periodic / (1.03 ** (65 - 25)), rel=1e-9
    )


def test_contribution_delay_zeros_early_years():
    delay = 2
    ending, contribs, limits = run_annual_engine(
        seed=0.0,
        years=5,
        annual_return=0.05,
        timing=ContributionTiming.END,
        contribution_delay_years=delay,
        starting_age=30,
        inflation=0.0,
        base_limit_0=IRA_BASE_LIMIT_0,
        catchup_limit_0=IRA_CATCHUP_LIMIT_0,
    )
    assert contribs[:delay] == [0.0, 0.0]
    assert contribs[delay:] == limits[delay:]
    assert ending[0] == 0.0


def test_beginning_vs_end_differs_by_one_period_interest_on_contrib():
    kwargs = dict(
        seed=0.0,
        years=1,
        annual_return=0.12,
        contribution_delay_years=0,
        starting_age=30,
        inflation=0.0,
        base_limit_0=IRA_BASE_LIMIT_0,
        catchup_limit_0=IRA_CATCHUP_LIMIT_0,
    )
    beg, c_beg, _ = run_annual_engine(timing=ContributionTiming.BEGINNING, **kwargs)
    end, c_end, _ = run_annual_engine(timing=ContributionTiming.END, **kwargs)
    assert c_beg == c_end
    contrib = c_beg[0]
    # Annual engine: Beginning earns one full year's interest on the contribution.
    assert beg[0] == pytest.approx(end[0] + contrib * 0.12, abs=1e-6)


def test_catchup_starts_at_age_50():
    lim_49 = ira_contribution_limit(49, headline_inflation=0.0, year_index=0)
    lim_50 = ira_contribution_limit(50, headline_inflation=0.0, year_index=0)
    assert lim_49 == IRA_BASE_LIMIT_0
    assert lim_50 == IRA_BASE_LIMIT_0 + IRA_CATCHUP_LIMIT_0


def test_periodic_rate_monthly():
    r = periodic_rate(0.12, 12)
    assert (1.0 + r) ** 12 == pytest.approx(1.12, abs=1e-12)


def test_advanced_frequency_periods():
    req = _base_req(
        contribution_frequency=ContributionFrequency.ADVANCED,
        trading_day_interval=18,
    )
    assert req.periods_per_year() == 14


def test_advanced_interval_must_divide_252():
    with pytest.raises(ValueError):
        _base_req(
            contribution_frequency=ContributionFrequency.ADVANCED,
            trading_day_interval=17,
        )


def test_federal_tax_single_year0_10_percent_bracket():
    tax = federal_income_tax(10_000.0, FilingStatus.SINGLE, 0.0, 0)
    assert tax == pytest.approx(1_000.0, abs=1e-6)


def test_oasdi_capped_at_wage_base():
    oasdi, medicare, addl, base = payroll_taxes(
        wages=300_000.0,
        status=FilingStatus.SINGLE,
        headline_inflation=0.0,
        year_index=0,
    )
    assert base == 184_500.0
    assert oasdi == pytest.approx(0.062 * 184_500.0, abs=1e-6)
    assert medicare == pytest.approx(0.0145 * 300_000.0, abs=1e-6)
    assert addl == pytest.approx(
        0.009 * (300_000.0 - ADDITIONAL_MEDICARE_THRESHOLDS[FilingStatus.SINGLE]),
        abs=1e-6,
    )


def test_hoh_additional_medicare_threshold():
    assert ADDITIONAL_MEDICARE_THRESHOLDS[FilingStatus.HOH] == 200_000.0
    _, _, addl, _ = payroll_taxes(210_000.0, FilingStatus.HOH, 0.0, 0)
    assert addl == pytest.approx(0.009 * 10_000.0, abs=1e-6)


def test_oasdi_wage_base_indexes_with_inflation():
    _, _, _, base0 = payroll_taxes(1.0, FilingStatus.SINGLE, 0.03, 0)
    _, _, _, base5 = payroll_taxes(1.0, FilingStatus.SINGLE, 0.03, 5)
    assert base0 == 184_500.0
    assert base5 > base0


def test_calculate_endpoint_shape():
    req = _base_req()
    resp = calculate(req)
    assert resp.years_to_retirement == 6
    assert len(resp.years) == 6
    assert resp.final_balance_periodic > req.current_ira_balance
    assert resp.total_contributions > 0
    assert resp.assumptions_notes


# ---- Phase 2: filing status, transition, state tax, MAGI --------------------


def test_canonical_filing_status_labels_match_tax_tables():
    """Enum values must be the sole keys in every tax lookup table."""
    for status in FilingStatus:
        assert status in BRACKETS_0
        assert status in STANDARD_DEDUCTION_0
        assert status in ADDITIONAL_MEDICARE_THRESHOLDS
        assert status in ROTH_MAGI_PHASE_OUT_0


@pytest.mark.parametrize("status", list(FilingStatus))
def test_every_filing_status_computes_tax(status: FilingStatus):
    result = compute_year_tax(
        salary=100_000.0,
        status=status,
        headline_inflation=0.0,
        year_index=0,
        include_state_tax=False,
        state_tax_rate=0.0,
    )
    assert result.filing_status == status
    assert result.federal_income_tax > 0
    assert result.standard_deduction == STANDARD_DEDUCTION_0[status]


def test_mfs_uses_25_dollar_rounding_others_50():
    assert _bracket_round_step(FilingStatus.MFS) == 25.0
    for status in (FilingStatus.SINGLE, FilingStatus.JOINT, FilingStatus.HOH):
        assert _bracket_round_step(status) == 50.0
    # Indexed MFS deduction should land on a $25 multiple.
    mfs_std = indexed_standard_deduction(FilingStatus.MFS, 0.025, 3)
    assert mfs_std % 25 == 0


def test_flat_state_tax_on_federal_taxable_income():
    rate = 0.05
    with_state = compute_year_tax(
        salary=80_000.0,
        status=FilingStatus.SINGLE,
        headline_inflation=0.0,
        year_index=0,
        include_state_tax=True,
        state_tax_rate=rate,
    )
    without = compute_year_tax(
        salary=80_000.0,
        status=FilingStatus.SINGLE,
        headline_inflation=0.0,
        year_index=0,
        include_state_tax=False,
        state_tax_rate=rate,
    )
    assert without.state_tax == 0.0
    assert with_state.state_tax == pytest.approx(rate * with_state.federal_taxable_income)
    assert with_state.total_tax == pytest.approx(without.total_tax + with_state.state_tax)


def test_state_tax_off_even_if_rate_set():
    resp = calculate(_base_req(include_state_tax=False, state_tax_rate=0.06))
    assert resp.total_state_tax == 0.0


def test_filing_status_change_requires_target():
    with pytest.raises(ValueError):
        _base_req(filing_status_change_enabled=True, target_filing_status=None)


@pytest.mark.parametrize("target", list(FilingStatus))
def test_transition_to_every_target_status(target: FilingStatus):
    """Years before change keep source status; from switch year onward use target."""
    switch_year = 2
    resp = calculate(
        _base_req(
            filing_status=FilingStatus.SINGLE,
            filing_status_change_enabled=True,
            target_filing_status=target,
            years_until_filing_status_change=switch_year,
            starting_salary=120_000.0,
            annual_merit_raise=0.0,
            annual_inflation=0.0,
        )
    )
    for row in resp.years:
        expected = FilingStatus.SINGLE if row.year_index < switch_year else target
        assert row.tax.filing_status == expected
        assert row.tax.standard_deduction == STANDARD_DEDUCTION_0[expected]


@pytest.mark.parametrize("source", list(FilingStatus))
def test_transition_from_every_source_status(source: FilingStatus):
    target = FilingStatus.JOINT if source != FilingStatus.JOINT else FilingStatus.SINGLE
    resp = calculate(
        _base_req(
            filing_status=source,
            filing_status_change_enabled=True,
            target_filing_status=target,
            years_until_filing_status_change=1,
            annual_inflation=0.0,
            annual_merit_raise=0.0,
            starting_salary=90_000.0,
        )
    )
    assert resp.years[0].tax.filing_status == source
    assert resp.years[1].tax.filing_status == target


def test_transition_year_zero_applies_immediately():
    resp = calculate(
        _base_req(
            filing_status=FilingStatus.SINGLE,
            filing_status_change_enabled=True,
            target_filing_status=FilingStatus.JOINT,
            years_until_filing_status_change=0,
            annual_inflation=0.0,
        )
    )
    assert all(y.tax.filing_status == FilingStatus.JOINT for y in resp.years)


def test_transition_affects_federal_tax_vs_no_change():
    base = calculate(
        _base_req(
            filing_status=FilingStatus.SINGLE,
            starting_salary=150_000.0,
            annual_merit_raise=0.0,
            annual_inflation=0.0,
        )
    )
    switched = calculate(
        _base_req(
            filing_status=FilingStatus.SINGLE,
            filing_status_change_enabled=True,
            target_filing_status=FilingStatus.JOINT,
            years_until_filing_status_change=0,
            starting_salary=150_000.0,
            annual_merit_raise=0.0,
            annual_inflation=0.0,
        )
    )
    # Joint brackets/deduction should reduce federal tax at this salary.
    assert switched.total_federal_income_tax < base.total_federal_income_tax


def test_magi_direct_below_band_backdoor_inside_or_above():
    lo, hi = ROTH_MAGI_PHASE_OUT_0[FilingStatus.SINGLE]
    below = compute_year_tax(
        salary=lo - 1,
        status=FilingStatus.SINGLE,
        headline_inflation=0.0,
        year_index=0,
        include_state_tax=False,
        state_tax_rate=0.0,
    )
    inside = compute_year_tax(
        salary=(lo + hi) / 2,
        status=FilingStatus.SINGLE,
        headline_inflation=0.0,
        year_index=0,
        include_state_tax=False,
        state_tax_rate=0.0,
    )
    above = compute_year_tax(
        salary=hi + 50_000,
        status=FilingStatus.SINGLE,
        headline_inflation=0.0,
        year_index=0,
        include_state_tax=False,
        state_tax_rate=0.0,
    )
    assert below.contribution_method == ContributionMethod.DIRECT
    assert inside.contribution_method == ContributionMethod.BACKDOOR
    assert above.contribution_method == ContributionMethod.BACKDOOR
    # Contribution amount is independent of MAGI flag (engine still uses full limit).
    resp = calculate(_base_req(starting_salary=hi + 10_000, annual_inflation=0.0))
    assert resp.years[0].tax.contribution_method == ContributionMethod.BACKDOOR
    assert resp.years[0].contribution == IRA_BASE_LIMIT_0


def test_magi_bands_not_cpi_indexed_over_horizon():
    """Fixed 2026 statutory floors — $253k Single at late ages must be Backdoor."""
    resp = calculate(
        _base_req(
            starting_age=25,
            retirement_age=65,
            starting_salary=75_000.0,
            annual_merit_raise=0.03,
            annual_inflation=0.025,
            filing_status=FilingStatus.SINGLE,
        )
    )
    lo, hi = ROTH_MAGI_PHASE_OUT_0[FilingStatus.SINGLE]
    assert resp.years[0].tax.contribution_method == ContributionMethod.DIRECT
    assert resp.years[0].tax.salary < lo
    last = resp.years[-1]
    assert last.tax.salary > hi
    assert last.tax.contribution_method == ContributionMethod.BACKDOOR
    # Bands reported on the row stay at year-0 statutory levels.
    assert last.tax.magi_phase_out_lower == pytest.approx(lo)
    assert last.tax.magi_phase_out_upper == pytest.approx(hi)
    # Transition year: first Backdoor after Direct.
    methods = [y.tax.contribution_method for y in resp.years]
    first_backdoor = methods.index(ContributionMethod.BACKDOOR)
    assert first_backdoor > 0
    assert methods[first_backdoor - 1] == ContributionMethod.DIRECT
    assert resp.years[first_backdoor].tax.salary >= lo
    # Flag does not change contribution dollars vs statutory limit when income allows.
    assert all(
        (y.contribution == y.ira_limit) or y.contribution_capped_by_income for y in resp.years
    )


@pytest.mark.parametrize(
    "status,salary,expected",
    [
        (FilingStatus.SINGLE, 152_999.0, ContributionMethod.DIRECT),
        (FilingStatus.SINGLE, 153_000.0, ContributionMethod.BACKDOOR),
        (FilingStatus.HOH, 152_999.0, ContributionMethod.DIRECT),
        (FilingStatus.HOH, 168_000.0, ContributionMethod.BACKDOOR),
        (FilingStatus.JOINT, 241_999.0, ContributionMethod.DIRECT),
        (FilingStatus.JOINT, 242_000.0, ContributionMethod.BACKDOOR),
        (FilingStatus.MFS, 0.0, ContributionMethod.BACKDOOR),  # MFS floor is $0
        (FilingStatus.MFS, 5_000.0, ContributionMethod.BACKDOOR),
        (FilingStatus.MFS, 10_000.0, ContributionMethod.BACKDOOR),
    ],
)
def test_magi_boundaries_all_filing_statuses(status, salary, expected):
    result = compute_year_tax(
        salary=salary,
        status=status,
        headline_inflation=0.03,
        year_index=20,  # indexing must not move the fixed statutory band
        include_state_tax=False,
        state_tax_rate=0.0,
    )
    assert result.contribution_method == expected
    lo, hi = ROTH_MAGI_PHASE_OUT_0[status]
    assert result.magi_phase_out_lower == pytest.approx(lo)
    assert result.magi_phase_out_upper == pytest.approx(hi)


def test_mfs_magi_band_is_tight():
    result = compute_year_tax(
        salary=5_000.0,
        status=FilingStatus.MFS,
        headline_inflation=0.0,
        year_index=0,
        include_state_tax=False,
        state_tax_rate=0.0,
    )
    assert result.contribution_method == ContributionMethod.BACKDOOR


# ---- Phase 3: Actuary Mode + salary cap -------------------------------------


from backend.actuary import actuary_bonuses_for_year, bonus_flags, build_salary_path
from backend.models import CredentialStatus


def test_bonus_flags_by_credential():
    f_not = bonus_flags(CredentialStatus.NOT_YET)
    assert (f_not.per_exam, f_not.associate, f_not.fellowship) == (True, True, True)
    f_asa = bonus_flags(CredentialStatus.ASSOCIATE)
    assert (f_asa.per_exam, f_asa.associate, f_asa.fellowship) == (True, False, True)
    f_fsa = bonus_flags(CredentialStatus.FELLOW)
    assert (f_fsa.per_exam, f_fsa.associate, f_fsa.fellowship) == (False, False, False)


def test_merit_only_path_matches_closed_form():
    req = _base_req(
        starting_salary=100_000.0,
        annual_merit_raise=0.05,
        actuary_mode=False,
        retirement_age=35,
    )
    path = build_salary_path(req, 5)
    for t, sal in enumerate(path):
        assert sal == pytest.approx(100_000.0 * (1.05**t), abs=1e-6)


def test_fellowship_must_be_after_associate_when_not_credentialed():
    with pytest.raises(ValueError, match="years_until_fellowship"):
        _base_req(
            actuary_mode=True,
            credential_status=CredentialStatus.NOT_YET,
            years_until_associate=5,
            years_until_fellowship=3,
        )


def test_fellowship_before_associate_ok_when_already_associate():
    # Validation only applies to Not yet credentialed.
    req = _base_req(
        actuary_mode=True,
        credential_status=CredentialStatus.ASSOCIATE,
        years_until_associate=5,
        years_until_fellowship=2,
        exams_remaining=0,
        years_until_exams_finish=0,
    )
    assert req.years_until_fellowship == 2


@pytest.mark.parametrize(
    "status, expect_assoc, expect_fellow",
    [
        (CredentialStatus.NOT_YET, True, True),
        (CredentialStatus.ASSOCIATE, False, True),
        (CredentialStatus.FELLOW, False, False),
    ],
)
def test_credential_gates_one_time_raises(status, expect_assoc, expect_fellow):
    req = _base_req(
        starting_salary=80_000.0,
        annual_merit_raise=0.0,
        actuary_mode=True,
        credential_status=status,
        exams_remaining=0,
        years_until_exams_finish=0,
        salary_raise_associate=5_000.0,
        years_until_associate=1,
        salary_raise_fellowship=10_000.0,
        years_until_fellowship=2,
        retirement_age=35,
    )
    path = build_salary_path(req, 5)
    assert path[0] == 80_000.0
    assert path[1] == pytest.approx(80_000.0 + (5_000.0 if expect_assoc else 0.0))
    # Year 2: prior + fellowship if gated on
    expected_y2 = path[1] + (10_000.0 if expect_fellow else 0.0)
    assert path[2] == pytest.approx(expected_y2)


def test_exam_bonuses_paced_across_years():
    req = _base_req(
        starting_salary=70_000.0,
        annual_merit_raise=0.0,
        actuary_mode=True,
        credential_status=CredentialStatus.NOT_YET,
        exams_remaining=4,
        years_until_exams_finish=4,
        salary_raise_per_exam=2_000.0,
        salary_raise_associate=0.0,
        salary_raise_fellowship=0.0,
        years_until_associate=99,
        years_until_fellowship=99,
        retirement_age=40,
    )
    # 4 exams / 4 years => $2,000 each of years 0..3
    assert actuary_bonuses_for_year(req, 0) == pytest.approx(2_000.0)
    assert actuary_bonuses_for_year(req, 3) == pytest.approx(2_000.0)
    assert actuary_bonuses_for_year(req, 4) == 0.0
    path = build_salary_path(req, 6)
    assert path[0] == pytest.approx(72_000.0)
    assert path[3] == pytest.approx(78_000.0)
    assert path[4] == pytest.approx(78_000.0)


def test_exams_finish_zero_applies_all_immediately():
    req = _base_req(
        starting_salary=70_000.0,
        annual_merit_raise=0.0,
        actuary_mode=True,
        credential_status=CredentialStatus.ASSOCIATE,
        exams_remaining=3,
        years_until_exams_finish=0,
        salary_raise_per_exam=1_000.0,
        salary_raise_associate=0.0,
        salary_raise_fellowship=0.0,
        years_until_associate=0,
        years_until_fellowship=99,
        retirement_age=35,
    )
    assert actuary_bonuses_for_year(req, 0) == pytest.approx(3_000.0)
    assert actuary_bonuses_for_year(req, 1) == 0.0
    path = build_salary_path(req, 2)
    assert path[0] == pytest.approx(73_000.0)
    assert path[1] == pytest.approx(73_000.0)


def test_salary_cap_equals_starting_produces_zero_growth():
    req = _base_req(
        starting_salary=90_000.0,
        annual_merit_raise=0.10,
        cap_salary_growth=True,
        salary_cap=90_000.0,
        actuary_mode=False,
        retirement_age=40,
    )
    path = build_salary_path(req, 5)
    assert path == [90_000.0] * 5


def test_salary_cap_plateaus_after_hit():
    req = _base_req(
        starting_salary=100_000.0,
        annual_merit_raise=0.10,
        cap_salary_growth=True,
        salary_cap=115_000.0,
        actuary_mode=False,
        retirement_age=40,
    )
    path = build_salary_path(req, 5)
    assert path[0] == 100_000.0
    assert path[1] == pytest.approx(110_000.0)
    assert path[2] == pytest.approx(115_000.0)
    assert path[3] == pytest.approx(115_000.0)


def test_salary_cap_below_starting_rejected():
    with pytest.raises(ValueError, match="salary_cap"):
        _base_req(cap_salary_growth=True, salary_cap=50_000.0, starting_salary=80_000.0)


def test_salary_cap_clips_actuary_bonus_in_same_year():
    """Bonus that would push salary over the cap is clipped — cap still wins."""
    req = _base_req(
        starting_salary=100_000.0,
        annual_merit_raise=0.0,
        cap_salary_growth=True,
        salary_cap=105_000.0,
        actuary_mode=True,
        credential_status=CredentialStatus.NOT_YET,
        exams_remaining=0,
        years_until_exams_finish=0,
        salary_raise_per_exam=0.0,
        salary_raise_associate=20_000.0,
        years_until_associate=0,  # associate bonus in year 0
        salary_raise_fellowship=0.0,
        years_until_fellowship=10,
        retirement_age=35,
    )
    path = build_salary_path(req, 3)
    # Year 0: 100k + 20k bonus → clipped to 105k
    assert path[0] == pytest.approx(105_000.0)
    assert path[1] == pytest.approx(105_000.0)
    assert path[2] == pytest.approx(105_000.0)


def test_fellow_gets_no_actuary_bonuses():
    req = _base_req(
        starting_salary=200_000.0,
        annual_merit_raise=0.0,
        actuary_mode=True,
        credential_status=CredentialStatus.FELLOW,
        exams_remaining=10,
        years_until_exams_finish=5,
        salary_raise_per_exam=5_000.0,
        salary_raise_associate=20_000.0,
        years_until_associate=0,
        salary_raise_fellowship=30_000.0,
        years_until_fellowship=0,
        retirement_age=35,
    )
    path = build_salary_path(req, 5)
    assert path == [200_000.0] * 5


def test_calculate_uses_actuary_salary_in_tax():
    resp = calculate(
        _base_req(
            starting_salary=80_000.0,
            annual_merit_raise=0.0,
            annual_inflation=0.0,
            actuary_mode=True,
            credential_status=CredentialStatus.NOT_YET,
            exams_remaining=0,
            years_until_exams_finish=0,
            salary_raise_associate=20_000.0,
            years_until_associate=0,
            salary_raise_fellowship=0.0,
            years_until_fellowship=0,
        )
    )
    # Associate bump lands in year 0.
    assert resp.years[0].tax.salary == pytest.approx(100_000.0)


# ---- Phase 4: Growth Multiple / Terminal Value by vintage -------------------


from backend.engine import growth_multiple_for_period


@pytest.mark.parametrize(
    "frequency,timing",
    [
        (ContributionFrequency.ANNUAL, ContributionTiming.BEGINNING),
        (ContributionFrequency.ANNUAL, ContributionTiming.END),
        (ContributionFrequency.MONTHLY, ContributionTiming.BEGINNING),
        (ContributionFrequency.MONTHLY, ContributionTiming.END),
        (ContributionFrequency.WEEKLY, ContributionTiming.BEGINNING),
        (ContributionFrequency.SEMIANNUAL, ContributionTiming.END),
        (ContributionFrequency.QUARTERLY, ContributionTiming.BEGINNING),
    ],
)
def test_vintage_cross_check_matches_periodic_ending(frequency, timing):
    resp = calculate(
        _base_req(
            contribution_frequency=frequency,
            contribution_timing=timing,
            current_ira_balance=12_345.67,
            starting_age=28,
            retirement_age=45,
            annual_return=0.08,
            annual_inflation=0.025,
            contribution_delay_years=0,
        )
    )
    reconstructed = resp.seed_terminal_value + resp.sum_contribution_terminal_values
    assert reconstructed == pytest.approx(resp.final_balance_periodic, abs=1e-6)
    assert resp.vintage_cross_check_ok is True


def test_vintage_cross_check_with_contribution_delay():
    resp = calculate(
        _base_req(
            contribution_frequency=ContributionFrequency.MONTHLY,
            contribution_timing=ContributionTiming.BEGINNING,
            current_ira_balance=5_000.0,
            contribution_delay_years=3,
            starting_age=30,
            retirement_age=50,
            annual_return=0.06,
        )
    )
    # Delay years still have a time-based growth_multiple (not TV/contrib).
    for row in resp.years[:3]:
        assert row.contribution == 0.0
        assert row.terminal_value == 0.0
        assert row.growth_multiple > 0.0
    assert resp.vintage_cross_check_ok is True
    assert resp.seed_terminal_value + resp.sum_contribution_terminal_values == pytest.approx(
        resp.final_balance_periodic, abs=1e-6
    )


def test_seed_vintage_not_lost():
    """Seed TV must be present and equals seed * (1+r)^N even with zero contributions."""
    resp = calculate(
        _base_req(
            current_ira_balance=10_000.0,
            contribution_delay_years=99,  # no contributions in inclusive horizon
            contribution_frequency=ContributionFrequency.ANNUAL,
            contribution_timing=ContributionTiming.BEGINNING,
            annual_return=0.10,
            annual_inflation=0.0,
            starting_age=40,
            retirement_age=45,
            ira_base_limit_0=0.0,
            ira_catchup_limit_0=0.0,
        )
    )
    assert resp.seed_growth_multiple == pytest.approx(1.10**6, abs=1e-12)
    assert resp.seed_terminal_value == pytest.approx(10_000.0 * 1.10**6, abs=1e-6)
    assert resp.sum_contribution_terminal_values == pytest.approx(0.0, abs=1e-9)
    assert resp.final_balance_periodic == pytest.approx(resp.seed_terminal_value, abs=1e-6)


def test_growth_multiple_is_time_based_not_tv_over_contrib():
    # With zero contribution, GM must still be computable (no division by zero).
    gm = growth_multiple_for_period(
        period_index=0,
        total_periods=24,
        rate=0.005,
        timing=ContributionTiming.BEGINNING,
    )
    assert gm == pytest.approx((1.005) ** 24, abs=1e-12)


def test_beginning_vs_end_growth_multiple_differs_by_one_period():
    total = 12
    rate = 0.01
    beg = growth_multiple_for_period(
        period_index=0, total_periods=total, rate=rate, timing=ContributionTiming.BEGINNING
    )
    end = growth_multiple_for_period(
        period_index=0, total_periods=total, rate=rate, timing=ContributionTiming.END
    )
    assert beg == pytest.approx(end * (1.0 + rate), abs=1e-12)


def test_advanced_frequency_vintage_cross_check():
    resp = calculate(
        _base_req(
            contribution_frequency=ContributionFrequency.ADVANCED,
            trading_day_interval=18,
            contribution_timing=ContributionTiming.BEGINNING,
            current_ira_balance=8_000.0,
            starting_age=32,
            retirement_age=42,
            annual_return=0.07,
        )
    )
    assert resp.periods_per_year == 14
    assert resp.vintage_cross_check_ok is True


# ---- Phase 5–8: milestones, scenarios, QA edges -----------------------------


def test_year_ages_span_to_retirement_age():
    """Inclusive horizon: ages run starting_age .. retirement_age inclusive."""
    resp = calculate(_base_req(starting_age=28, retirement_age=65))
    ages = [y.age for y in resp.years]
    assert ages[0] == 28
    assert ages[-1] == 65
    assert len(ages) == 65 - 28 + 1


def test_contribution_capped_at_earned_income():
    resp = calculate(
        _base_req(
            starting_age=25,
            retirement_age=30,
            current_ira_balance=0.0,
            starting_salary=5_000.0,
            annual_merit_raise=0.0,
            annual_inflation=0.0,
            contribution_frequency=ContributionFrequency.ANNUAL,
        )
    )
    y0 = resp.years[0]
    assert y0.ira_limit == pytest.approx(7_500.0)
    assert y0.contribution == pytest.approx(5_000.0)
    assert y0.contribution_capped_by_income is True
    assert resp.years_contribution_capped_by_income == len(resp.years)
    assert all(y.contribution <= y.tax.salary + 1e-9 for y in resp.years)
    assert resp.vintage_cross_check_ok is True


def test_high_inflation_contrib_never_exceeds_salary():
    resp = calculate(
        _base_req(
            starting_age=25,
            retirement_age=65,
            current_ira_balance=0.0,
            starting_salary=85_000.0,
            annual_merit_raise=0.02,
            annual_inflation=0.20,
            contribution_frequency=ContributionFrequency.ANNUAL,
        )
    )
    assert resp.years_contribution_capped_by_income > 0
    for y in resp.years:
        assert y.contribution <= y.tax.salary + 1e-9
        if y.contribution_capped_by_income:
            assert y.contribution == pytest.approx(y.tax.salary, abs=1e-6)
            assert y.contribution < y.ira_limit
    assert resp.vintage_cross_check_ok is True


def test_realistic_scenario_earned_income_cap_does_not_bind():
    resp = calculate(
        _base_req(
            starting_age=25,
            retirement_age=65,
            current_ira_balance=0.0,
            starting_salary=85_000.0,
            annual_merit_raise=0.03,
            annual_return=0.07,
            annual_inflation=0.025,
            contribution_frequency=ContributionFrequency.MONTHLY,
        )
    )
    assert resp.years_contribution_capped_by_income == 0
    assert all(not y.contribution_capped_by_income for y in resp.years)
    assert all(y.contribution == pytest.approx(y.ira_limit) for y in resp.years)


def test_excel_regression_age22_to_65_annual_beginning():
    """Standing regression vs Excel source model (handoff §9).

    Inputs: age 22→65, $0 seed, 7%/3%, Annual/Beginning, 0 delay,
    $85k salary, 3% merit, Single, no state tax, Actuary Mode off.
    """
    resp = calculate(
        _base_req(
            starting_age=22,
            retirement_age=65,
            current_ira_balance=0.0,
            annual_return=0.07,
            annual_inflation=0.03,
            contribution_frequency=ContributionFrequency.ANNUAL,
            contribution_timing=ContributionTiming.BEGINNING,
            contribution_delay_years=0,
            starting_salary=85_000.0,
            annual_merit_raise=0.03,
            filing_status=FilingStatus.SINGLE,
            include_state_tax=False,
            actuary_mode=False,
        )
    )
    assert resp.years_to_retirement == 44
    assert resp.years[0].age == 22
    assert resp.years[-1].age == 65
    assert resp.total_contributions == pytest.approx(706_800.0, abs=0.5)
    assert resp.years[0].growth_multiple == pytest.approx(1.07**44, rel=1e-9)
    assert resp.years[-1].growth_multiple == pytest.approx(1.07, rel=1e-9)
    assert resp.final_balance_periodic == pytest.approx(3_223_138.0, abs=1.0)
    assert resp.final_balance_real_periodic == pytest.approx(904_229.0, abs=1.0)
    multiplier = resp.final_balance_periodic / resp.total_contributions
    assert multiplier == pytest.approx(4.56, abs=0.01)
    assert resp.years_contribution_capped_by_income == 0


def test_balance_milestones_are_percent_of_final():
    resp = calculate(
        _base_req(
            starting_age=25,
            retirement_age=65,
            current_ira_balance=10_000.0,
            annual_return=0.07,
            annual_inflation=0.02,
            contribution_frequency=ContributionFrequency.MONTHLY,
        )
    )
    assert len(resp.milestones) == 3
    assert all(m.reached for m in resp.milestones)
    final = resp.final_balance_periodic
    for m, pct in zip(resp.milestones, (0.25, 0.50, 0.75), strict=True):
        assert m.threshold == pytest.approx(final * pct, rel=1e-9)
        assert f"{int(pct * 100)}% of final balance" in m.label
        assert m.age is not None
        assert m.balance_at_crossing is not None
        assert m.balance_at_crossing >= m.threshold
    ages = [m.age for m in resp.milestones]
    assert ages == sorted(ages)


def test_balance_milestones_scale_with_final():
    low = calculate(
        _base_req(
            starting_age=40,
            retirement_age=50,
            current_ira_balance=0.0,
            annual_return=0.04,
            contribution_frequency=ContributionFrequency.ANNUAL,
        )
    )
    high = calculate(
        _base_req(
            starting_age=25,
            retirement_age=65,
            current_ira_balance=50_000.0,
            annual_return=0.09,
            contribution_frequency=ContributionFrequency.MONTHLY,
        )
    )
    assert low.final_balance_periodic < high.final_balance_periodic
    assert low.milestones[0].threshold < high.milestones[0].threshold
    assert low.milestones[0].threshold == pytest.approx(
        low.final_balance_periodic * 0.25, rel=1e-9
    )
    assert high.milestones[0].threshold == pytest.approx(
        high.final_balance_periodic * 0.25, rel=1e-9
    )


def test_salary_milestones_only_within_range():
    resp = calculate(
        _base_req(
            starting_age=25,
            retirement_age=65,
            starting_salary=60_000.0,
            annual_merit_raise=0.03,
            actuary_mode=False,
        )
    )
    start = 60_000.0
    final = resp.years[-1].tax.salary
    assert all(start < m.threshold <= final for m in resp.salary_milestones)
    assert all(m.reached for m in resp.salary_milestones)
    assert all("Salary crosses" in m.label for m in resp.salary_milestones)


def test_salary_milestones_empty_when_flat():
    resp = calculate(
        _base_req(
            starting_age=30,
            retirement_age=35,
            starting_salary=80_000.0,
            annual_merit_raise=0.0,
            actuary_mode=False,
        )
    )
    assert resp.salary_milestones == []


def test_nominal_balance_milestones_scale_with_final():
    low = calculate(
        _base_req(
            starting_age=40,
            retirement_age=50,
            current_ira_balance=0.0,
            annual_return=0.04,
            contribution_frequency=ContributionFrequency.ANNUAL,
            starting_salary=60_000.0,
            annual_merit_raise=0.02,
        )
    )
    high = calculate(
        _base_req(
            starting_age=22,
            retirement_age=65,
            current_ira_balance=100_000.0,
            annual_return=0.10,
            contribution_frequency=ContributionFrequency.MONTHLY,
            contribution_timing=ContributionTiming.BEGINNING,
            starting_salary=150_000.0,
            annual_merit_raise=0.04,
        )
    )
    assert low.final_balance_periodic < 500_000
    assert low.nominal_balance_milestones == []
    assert high.final_balance_periodic >= 5_000_000
    expected = [
        t
        for t in (
            500_000,
            1_000_000,
            2_000_000,
            5_000_000,
            10_000_000,
            20_000_000,
            50_000_000,
        )
        if t <= high.final_balance_periodic
    ]
    assert [m.threshold for m in high.nominal_balance_milestones] == expected
    assert len(expected) >= 4
    assert all(m.reached for m in high.nominal_balance_milestones)
    assert all("Nominal balance crosses" in m.label for m in high.nominal_balance_milestones)
    ages = [m.age for m in high.nominal_balance_milestones]
    assert ages == sorted(ages)
    for m in high.nominal_balance_milestones:
        assert m.balance_at_crossing >= m.threshold
        assert m.age is not None
        # Spot-check vs year path when crossing happens after seed.
        if m.year_index is not None and m.year_index >= 0:
            assert high.years[m.year_index].ending_balance_periodic >= m.threshold
            if m.year_index > 0:
                assert high.years[m.year_index - 1].ending_balance_periodic < m.threshold


def test_compounding_doubling_time_at_7_percent():
    from backend.engine import doubling_time_years

    dt = doubling_time_years(0.07)
    assert dt == pytest.approx(math.log(2) / math.log(1.07), rel=1e-12)
    assert dt == pytest.approx(10.244768, abs=1e-5)
    # Rule of 72 approximation is nearby but not exact.
    assert abs(dt - (72 / 7)) < 0.1


def test_compounding_milestones_list_and_year_column():
    import math as _math

    resp = calculate(
        _base_req(
            starting_age=25,
            retirement_age=65,
            annual_return=0.07,
            annual_inflation=0.02,
            starting_salary=80_000.0,
        )
    )
    dt = _math.log(2) / _math.log(1.07)
    assert len(resp.compounding_milestones) >= 3
    assert resp.compounding_milestones[0].age == pytest.approx(25 + dt, abs=1e-9)
    assert resp.compounding_milestones[0].from_multiple == 1
    assert resp.compounding_milestones[0].to_multiple == 2
    assert resp.compounding_milestones[-1].age <= 65
    # Next doubling would exceed retirement.
    assert 25 + (len(resp.compounding_milestones) + 1) * dt > 65
    # Year column independent of contrib amount / frequency.
    assert resp.years[0].cumulative_doublings == 0
    for y in resp.years:
        expected = (
            0
            if y.year_index <= 0
            else int(_math.floor(_math.log2((1.07) ** y.year_index)))
        )
        assert y.cumulative_doublings == expected


def test_compounding_milestones_empty_when_no_doubling_fits():
    resp = calculate(
        _base_req(
            starting_age=60,
            retirement_age=65,
            annual_return=0.01,
        )
    )
    assert resp.compounding_milestones == []
    assert all(y.cumulative_doublings == 0 for y in resp.years)


def test_short_horizon_balance_milestones_still_compute():
    resp = calculate(
        _base_req(
            starting_age=60,
            retirement_age=62,
            current_ira_balance=1_000.0,
            annual_return=0.01,
            contribution_frequency=ContributionFrequency.ANNUAL,
        )
    )
    assert len(resp.milestones) == 3
    assert all(m.reached for m in resp.milestones)
    assert resp.milestones[0].threshold == pytest.approx(
        resp.final_balance_periodic * 0.25, rel=1e-9
    )

def test_scenario_base_matches_main():
    resp = calculate(_base_req(annual_return=0.07, return_spread=0.03))
    base = next(c for c in resp.scenarios.return_cases if c.label == "Base")
    assert base.final_balance_nominal == pytest.approx(resp.final_balance_periodic, abs=1e-6)
    assert base.final_balance_real == pytest.approx(resp.final_balance_real_periodic, abs=1e-6)


def test_bear_bull_spread():
    resp = calculate(_base_req(annual_return=0.07, return_spread=0.03))
    bear = next(c for c in resp.scenarios.return_cases if c.label == "Bear")
    bull = next(c for c in resp.scenarios.return_cases if c.label == "Bull")
    assert bear.parameter_value == pytest.approx(0.04)
    assert bull.parameter_value == pytest.approx(0.10)
    assert bear.final_balance_nominal < resp.final_balance_periodic < bull.final_balance_nominal


def test_inflation_swing_preserves_nominal():
    resp = calculate(_base_req(annual_inflation=0.02, inflation_swing=0.015))
    for case in resp.scenarios.inflation_cases:
        assert case.final_balance_nominal == pytest.approx(resp.final_balance_periodic, abs=1e-6)
    low = next(c for c in resp.scenarios.inflation_cases if c.label == "Low inflation")
    high = next(c for c in resp.scenarios.inflation_cases if c.label == "High inflation")
    assert low.final_balance_real > high.final_balance_real


def test_contribution_gap_reduces_balance():
    base = calculate(_base_req(starting_age=30, retirement_age=50, annual_return=0.06))
    gapped = calculate(
        _base_req(
            starting_age=30,
            retirement_age=50,
            annual_return=0.06,
            contribution_gap_start_year=5,
            contribution_gap_length=3,
        )
    )
    assert gapped.final_balance_periodic < base.final_balance_periodic
    assert gapped.scenarios.contribution_gap is not None
    # Zero contributions inside gap window
    for row in gapped.years[5:8]:
        assert row.contribution == 0.0


def test_early_stop_at_retirement_zeros_final_year_only():
    """Stop age == retirement age zeros the inclusive final year (handoff: from that age onward)."""
    base = calculate(_base_req(starting_age=30, retirement_age=50))
    stopped = calculate(
        _base_req(starting_age=30, retirement_age=50, early_stop_age=50)
    )
    assert stopped.years[-1].contribution == 0.0
    assert base.years[-1].contribution > 0.0
    assert stopped.total_contributions == pytest.approx(
        base.total_contributions - base.years[-1].contribution, abs=0.5
    )
    assert stopped.final_balance_periodic < base.final_balance_periodic


def test_early_stop_reduces_contributions():
    base = calculate(_base_req(starting_age=30, retirement_age=55, annual_return=0.05))
    early = calculate(
        _base_req(starting_age=30, retirement_age=55, annual_return=0.05, early_stop_age=40)
    )
    assert early.total_contributions < base.total_contributions
    assert early.final_balance_periodic < base.final_balance_periodic


def test_required_return_solver_hits_target():
    # First get a known final, then solve back for the same return.
    known = calculate(
        _base_req(
            starting_age=30,
            retirement_age=50,
            annual_return=0.08,
            annual_inflation=0.0,
            current_ira_balance=20_000.0,
        )
    )
    solved = calculate(
        _base_req(
            starting_age=30,
            retirement_age=50,
            annual_return=0.05,  # decoy — solver ignores this for the solve itself
            annual_inflation=0.0,
            current_ira_balance=20_000.0,
            target_retirement_balance=known.final_balance_periodic,
            target_balance_is_real=False,
        )
    )
    rr = solved.scenarios.required_return
    assert rr is not None and rr.solved
    assert rr.required_annual_return == pytest.approx(0.08, abs=1e-4)


def test_required_return_real_target_converts():
    resp = calculate(
        _base_req(
            starting_age=30,
            retirement_age=40,
            annual_return=0.07,
            annual_inflation=0.02,
            target_retirement_balance=100_000.0,
            target_balance_is_real=True,
        )
    )
    rr = resp.scenarios.required_return
    assert rr is not None
    assert rr.target_nominal == pytest.approx(100_000.0 * (1.02**10), abs=1e-6)


def test_monthly_weekly_frequencies():
    for freq in (
        ContributionFrequency.MONTHLY,
        ContributionFrequency.WEEKLY,
        ContributionFrequency.QUARTERLY,
    ):
        resp = calculate(_base_req(contribution_frequency=freq, starting_age=30, retirement_age=40))
        assert resp.vintage_cross_check_ok
        assert resp.periods_per_year == {
            ContributionFrequency.MONTHLY: 12,
            ContributionFrequency.WEEKLY: 52,
            ContributionFrequency.QUARTERLY: 4,
        }[freq]

