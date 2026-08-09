"""Actuary Mode salary progression + credential-status gating."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CalculateRequest, CredentialStatus


@dataclass(frozen=True)
class ActuaryBonusFlags:
    per_exam: bool
    associate: bool
    fellowship: bool


def bonus_flags(status: CredentialStatus) -> ActuaryBonusFlags:
    """Which bump sources still apply given current credential status.

    Already-credentialed raises are assumed reflected in starting_salary —
    re-applying them would double-count.
    """
    if status == CredentialStatus.NOT_YET:
        return ActuaryBonusFlags(per_exam=True, associate=True, fellowship=True)
    if status == CredentialStatus.ASSOCIATE:
        return ActuaryBonusFlags(per_exam=True, associate=False, fellowship=True)
    # FSA-FCAS
    return ActuaryBonusFlags(per_exam=False, associate=False, fellowship=False)


def actuary_bonuses_for_year(req: CalculateRequest, year_index: int) -> float:
    """Dollar bonuses added in year_index (before salary cap)."""
    if not req.actuary_mode:
        return 0.0

    flags = bonus_flags(req.credential_status)
    bonus = 0.0

    if flags.per_exam and req.exams_remaining > 0:
        if req.years_until_exams_finish == 0:
            # Apply the entire remaining exam bonus stack immediately in year 0.
            if year_index == 0:
                bonus += req.exams_remaining * req.salary_raise_per_exam
        elif year_index < req.years_until_exams_finish:
            exams_per_year = req.exams_remaining / req.years_until_exams_finish
            bonus += exams_per_year * req.salary_raise_per_exam

    if flags.associate and year_index == req.years_until_associate:
        bonus += req.salary_raise_associate

    if flags.fellowship and year_index == req.years_until_fellowship:
        bonus += req.salary_raise_fellowship

    return bonus


def build_salary_path(req: CalculateRequest, years: int) -> list[float]:
    """Return salary for each year_index in [0, years).

    Recurrence (handoff §7), with year 0 anchored at starting_salary:
        salary_0 = MIN(starting_salary + bonuses_0, cap)
        salary_t = MIN(salary_(t-1) * (1 + merit) + bonuses_t, cap)  for t >= 1

    When Actuary Mode is off this matches starting_salary * (1+merit)^t.
    Cap self-plateaus once salary hits the cap — no special post-cap branch.
    """
    if years <= 0:
        return []

    path: list[float] = []
    prev = req.starting_salary
    cap: float = req.salary_cap if req.cap_salary_growth and req.salary_cap is not None else float("inf")

    for t in range(years):
        bonuses = actuary_bonuses_for_year(req, t)
        if t == 0:
            uncapped = prev + bonuses
        else:
            uncapped = prev * (1.0 + req.annual_merit_raise) + bonuses
        salary_t = min(uncapped, cap)
        path.append(salary_t)
        prev = salary_t

    return path
