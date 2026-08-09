# Project Handoff: Roth IRA / TVM Retirement Model — Web App Rebuild

**For:** Cursor coding agent (no prior context — this doc is the full spec)
**Goal:** Rebuild an existing Excel actuarial/finance model as a web app — HTML/CSS/JS frontend, Python backend. This is a recruiting portfolio piece (actuarial exam FM material — time value of money, progressive taxation, Roth IRA mechanics) with a hard deadline; prioritize a working, correct core over exhaustive feature parity if time runs short.

---

## 1. What this project is

A Roth IRA retirement projection tool. The user enters personal assumptions (age, salary, contribution behavior, return/inflation assumptions, tax situation, optional actuarial-career salary progression) and the app projects account balance to retirement, computes lifetime tax burden, and offers several analytical/what-if views. Originally built in Excel; this is a full rebuild, not a port of Excel formulas — reimplement the *logic* cleanly in Python, don't try to replicate spreadsheet cell mechanics.

## 2. Recommended architecture

**Backend: Python, FastAPI.** Reasons: automatic request/response validation via Pydantic models maps naturally onto the many typed numeric/enum inputs below; trivial to expose a single `/api/calculate` POST endpoint that takes the full input set and returns the full computed result set as JSON; no templating needed since the frontend is a separate SPA-style vanilla JS app.

**Frontend: vanilla HTML/CSS/JS**, no build step. Use **Chart.js** (via CDN `<script>` tag, no bundler needed) for all charts — it's the easiest charting library to drop into a no-build-step vanilla JS project and covers every chart type needed here (line, bar, pie).

**Data flow:** frontend form → on any input change (debounce ~300ms) → `fetch()` POST to `/api/calculate` with the full input payload → backend recomputes everything from scratch and returns full results JSON → frontend re-renders all charts/tables from the fresh response.

**Important simplification vs. the Excel version:** the Excel build spent enormous effort on "dynamic named ranges" and chart auto-rebinding because Excel charts can silently freeze to stale cell addresses. **This entire class of problem does not exist in a web app** — every chart re-renders from a fresh data array on every recalculation, so there's no equivalent failure mode. Don't over-engineer around a problem that doesn't exist in this stack.

## 3. Suggested project structure

```
backend/
  app.py              # FastAPI app, single /api/calculate endpoint
  models.py           # Pydantic input schema + output schema
  engine.py           # annual + periodic accumulation engines
  tax.py              # federal/state/payroll tax logic
  actuary.py          # salary progression + credential-status gating
  scenarios.py        # what-if shadow calcs + required-return solver
  tests/
    test_engine.py    # regression tests (see section 9)
frontend/
  index.html
  style.css
  app.js              # form handling, fetch calls, Chart.js rendering
```

## 4. Inputs (full list)

| Input | Type | Notes |
|---|---|---|
| Starting age | int | |
| Retirement age | int | must be > starting age |
| Current IRA balance (seed) | float | |
| Contribution frequency | enum | Annual / Semiannual / Quarterly / Monthly / Weekly, or "Advanced" mode with a trading-day interval (periods/year = 252 / interval, interval must divide 252 evenly, e.g. 18 → 14 periods/year) |
| Annual investment return (nominal) | float (%) | |
| Annual inflation rate | float (%) | |
| Contribution timing | enum | Beginning / End of period |
| Contribution delay | int (years) | years before contributions start; 0 = start immediately |
| Filing status | enum | Single / Joint / Married Filing Separately / Head of Household |
| Include flat state income tax | bool | |
| Flat state tax rate | float (%) | applied to federal taxable income, illustrative only |
| Filing status change toggle | bool | |
| Target filing status after change | enum | |
| Years until filing status changes | int | 0 = applies starting immediately |
| Actuary Mode on | bool | |
| Credential status | enum | Not yet credentialed / ASA-ACAS / FSA-FCAS |
| Exams remaining | int | replaces old "passed so far / total expected" — single source of truth |
| Salary raise per exam passed | float ($) | |
| Salary raise at Associate | float ($) | one-time |
| Years until Associate | int | only relevant if Not yet credentialed |
| Salary raise at Fellowship | float ($) | one-time |
| Years until Fellowship | int | years from today, NOT "years after Associate" — must be ≥ years until Associate when status = Not yet credentialed |
| Years until exams finish | int | pace derived as `exams_remaining / years_until_exams_finish` |
| Cap salary growth | bool | |
| Salary cap | float ($) | must be > starting salary |
| Starting salary | float ($) | |
| Annual merit raise | float (%) | applies regardless of Actuary Mode |

## 5. Core accumulation logic

### 5a. IRA contribution limits
```
base_limit_t = floor_to_nearest(500, base_limit_0 * (1 + inflation)^t)
catchup_limit_t = floor_to_nearest(100, catchup_limit_0 * (1 + inflation)^t)   # applies at age 50+
annual_contribution_limit_t = base_limit_t + (catchup_limit_t if age_t >= 50 else 0)
```
Use current-year real IRS figures as `base_limit_0`/`catchup_limit_0` defaults (look these up — don't guess stale numbers).

### 5b. Two accumulation engines
- **Annual engine:** full year's contribution applied at t=0 of each year (or t=1 if "End" timing), compounds once per year at the nominal return rate. This engine and the periodic engine are *expected* to disagree slightly — periodic timing spreads contributions across the year and earns less interest than a lump sum at the start. Don't try to reconcile them to match; that's correct behavior.
- **Periodic engine:** `periods_per_year` from contribution frequency. `periodic_rate = (1 + annual_return)^(1/periods_per_year) - 1`. Contribution per period = annual limit / periods_per_year. Compound every period.

### 5c. Growth Multiple / Terminal Value by contribution vintage
For each contributing period `t`, in isolation from every other contribution:
```
growth_multiple_t = (1 + periodic_rate)^(periods_remaining_from_t_to_retirement)
```
This is a pure function of time-remaining, not of contribution amount — compute it this way directly, don't derive it by dividing dollar terminal value by dollar contribution (breaks on $0-contribution rows during a contribution delay).

**Include the seed/starting balance as its own vintage entry** — it compounds at `(1 + periodic_rate)^(total_periods_in_horizon)`, same formula family, just from t=0 with the full horizon remaining. Don't let this get lost — it was a real bug in the Excel version where the seed's growth was excluded from summary stats.

Terminal value of a year's contributions:
```
terminal_value_of_year_t = sum(contribution_in_period_p * growth_multiple_p for each period p in year t)
```

**Cross-check (build this as an actual unit test):** `seed's terminal value + sum(all years' terminal values)` should equal the final ending balance from the periodic engine, to the cent (floating point tolerance ~1e-6 is fine).

## 6. Tax engine

### 6a. Federal income tax
- Progressive bracket table (2026 figures — verify current year's actual IRS brackets, don't reuse a stale hardcoded table from memory).
- Standard deduction, indexed annually.
- **Indexing methodology:** brackets and standard deduction indexed using Chained CPI-U (C-CPI-U) as an inflation proxy — C-CPI-U has historically run somewhat below headline CPI (roughly ~90% of headline inflation is a reasonable illustrative approximation, but don't hardcode this as fact — label it clearly as a simplified illustrative assumption in any UI copy, not an authoritative IRS methodology).
- **Bracket/deduction rounding:** round to nearest $50 for Single / Joint / Head of Household. **Round to nearest $25 for Married Filing Separately** — this is a real IRC distinction (§1(f)(7)/(8)), not arbitrary; don't apply $50 rounding universally.

### 6b. Filing status transition
If enabled, the model switches from the original filing status to a target status at a specified year. **Critical bug to avoid (this broke the Excel version once):** whatever bracket-table lookup drives this must use *exactly matching label text* between the filing-status enum/dropdown and the bracket table's internal keys (e.g. don't let one say "Joint" and the other "Married Filing Jointly" — pick one canonical set of labels and use it everywhere, including in code, not just in the UI). Test the transition explicitly for every filing status target, not just the one that happens to already exist in whatever table you build first.

### 6c. Payroll taxes
- **Social Security (OASDI):** 6.2% up to the wage base. **Index the wage base by inflation** (round to nearest $100) — do NOT hardcode it flat across the whole horizon (that was a real, material bug in the Excel version — understated lifetime payroll tax by ~$350k in testing). Label this in the UI as a simplified illustrative projection using CPI as a proxy — real SSA wage-base indexing uses the National Average Wage Index, not CPI; state that distinction explicitly rather than implying authority you don't have.
- **Medicare:** 1.45% flat on all wages, plus an Additional Medicare Tax of 0.9% above a threshold that varies by filing status: Single $200,000, Joint $250,000, MFS $125,000, **Head of Household $200,000** (don't forget HoH — this was a real gap in the Excel version that broke silently the first time HoH was actually selected). These thresholds are **not** inflation-indexed (that's correct/intentional — the real IRS thresholds are fixed by statute, not indexed).

### 6d. Flat state tax (optional)
Simple flat rate applied to federal taxable income (post-standard-deduction). Explicitly illustrative — doesn't model real state tax codes, credits, or brackets. Say so in the UI.

### 6e. Roth MAGI eligibility (display/flag only, doesn't change contribution amount)
Track whether modeled salary crosses the Roth MAGI phase-out band for the active filing status (roughly $153,000–$168,000 for Single/HoH — verify current-year real figures, these shift annually). When salary is within or above the phase-out band, flag that year's contribution method as "Backdoor" rather than "Direct" — this documents the mechanism honestly (a backdoor Roth: non-deductible traditional IRA contribution + conversion) without zeroing out or reducing the modeled contribution amount, since that's what a real person at that income actually does.

## 7. Actuary Mode — salary progression

Base salary path: `salary_t = MIN(salary_(t-1) * (1 + merit_raise) + this_year's_actuary_bonuses, salary_cap if enabled else infinity)`. The `MIN()` wrapper is self-plateauing once salary hits the cap — no special-case branch needed for years after the cap is reached, the recursive formula naturally holds flat once `salary_(t-1) == cap`.

**Credential status gates which bonuses apply** — this prevents double-counting salary bumps that a person who's already credentialed presumably already has reflected in their entered starting salary:

| Bonus | Not yet credentialed | ASA/ACAS | FSA/FCAS |
|---|---|---|---|
| Per-exam raise × exams remaining | active | active | excluded |
| Associate raise (one-time) | active | excluded | excluded |
| Fellowship raise (one-time) | active | active | excluded |

Exam pacing is derived, not directly input: `exams_per_year = exams_remaining / years_until_exams_finish`. Guard against division by zero — if `years_until_exams_finish = 0` and `exams_remaining > 0`, either apply all remaining bonuses immediately or raise a validation error; don't let it silently produce `inf`/`NaN`.

**Validation:** when credential status = "Not yet credentialed," `years_until_fellowship` must be ≥ `years_until_associate`. This validation doesn't apply for ASA/ACAS or FSA/FCAS (Associate is either already achieved or irrelevant in those states).

## 8. What-If scenarios

Each of these is computed independently — **never mutate the base-case inputs to produce a scenario result.** Compute each scenario as a parallel calculation with one parameter varied, and always show the base case's own result alongside each scenario as a sanity-check reference (the base-case row in the scenario table should exactly match the main calculation's own output — if it doesn't, there's a bug in the scenario logic, not a legitimate difference).

- **Return-rate Bear/Base/Bull:** `bear_rate = max(0, base_rate - spread)`, `bull_rate = base_rate + spread`. Spread is itself a user-adjustable input (default ±3 percentage points), not hardcoded absolute rates — a fixed "Bear = 8%" is meaningless if the user's actual base rate is 6% or 12%.
- **Inflation swing:** same relative-offset pattern, `low = max(0, base_inflation - swing)`, `high = base_inflation + swing`, default swing ±1.5 points. Only affects the *real* (inflation-adjusted) balance figure — nominal balance is unaffected by inflation assumptions.
- **Contribution gap / career break:** user specifies a start year and length; zero out contributions for periods inside that window only, everything else (including growth on the balance already accumulated) proceeds normally.
- **Early stop contributing:** user specifies a stop age; contributions become zero from that age onward, but the balance continues compounding through retirement (different from the gap — contributions never resume here).
- **Required-return solver:** given a target retirement balance (nominal or real — if real, convert to nominal by multiplying by `(1+inflation)^years` before solving) and the actual contribution schedule, solve for the constant annual return rate `r` such that `seed's FV + sum(contribution_t * (1+r)^(periods_remaining_from_t)) = target`. **This is a real numerical root-finding problem** — the function is smooth and monotonically increasing in `r`, so a simple bisection or Newton's method converges reliably in a handful of iterations. (The Excel version needed an awkward Goal-Seek workaround for this; in Python this is trivial — use `scipy.optimize.brentq` or hand-roll bisection, no special handling needed.)

## 9. Testing / regression approach

Before writing any UI polish, get the model's core numbers right and verifiable. Ask the user (Steven) for 2–3 known input/output pairs from the existing Excel file — specific input combinations and their resulting final balances/tax figures — and use those as regression test fixtures in `tests/test_engine.py`. Don't guess at expected values; get them from the source of truth (the Excel file) directly.

Edge cases worth explicit unit tests, based on issues found during the Excel build's QA process:
- Zero return rate (balance should equal seed + cumulative contributions exactly, no growth)
- Zero inflation (real balance = nominal balance every year)
- Contribution delay > 0 (contributions correctly $0 during delay, resume correctly after)
- Beginning vs. End timing (should differ by exactly one period's interest on contributions)
- Age 49 vs. 50 catch-up boundary (catch-up should apply starting exactly at 50, not 49 or 51)
- Every filing status × the filing-status-transition toggle, including transitioning *to* each possible target status (the earlier Excel bug only showed up for one specific status combination — test all of them, not just the default)
- Salary cap boundary: cap set exactly equal to starting salary (should produce zero salary growth, not an error)
- Every credential status value, confirming the correct bonuses are included/excluded
- Contribution gap and early-stop scenarios at boundary values (e.g. stop age = retirement age should produce ~$0 difference vs. base case)
- Monthly/Weekly/custom-trading-day-interval periodic modes, confirming periods-per-year and periodic rate compute correctly for each

## 10. Design system (carry over from the Excel visual redesign)

| Element | Value |
|---|---|
| Primary header fill | `#1B2A4A` (steel-navy) |
| Secondary header fill | `#3D4C6C` (navy-slate) |
| Accent (charts, highlights) | `#17A398` (teal) |
| Input field border/accent | `#7B93A8` (blue-grey) |
| Page/card background | `#FAF7F0` (warm ivory) |
| Body text | `#1A1A1A` (near-black) |
| Validation pass | `#6B9E78` (sage green) |
| Validation fail | `#C1666B` (muted rust) |
| Font | Open Sans (or system-ui fallback stack: `'Open Sans', 'Segoe UI', system-ui, sans-serif`) |

Formatting conventions:
- Currency: no decimals except tax-detail line items (`$#,##0` vs `$#,##0.00`).
- Percentages: one decimal for rate inputs (`10.0%`), two decimals for computed effective rates (`12.31%`).
- Charts: one consistent color mapping across every chart — teal = nominal values, slate = real/inflation-adjusted values, muted amber (`#C9A227`) reserved for threshold/reference lines only. A color should mean the same thing on every chart it appears in.
- No default Chart.js styling left in place — remove default borders/shadows, minimal or no gridlines, clean typography matching the rest of the page.

## 11. Suggested build order

1. **Backend core:** annual + periodic engines, IRA limits, basic federal/payroll tax — get this numerically correct and unit-tested against real Excel output before anything else.
2. **Filing status + state tax + filing-status transition.**
3. **Actuary Mode + salary cap.**
4. **Growth Multiple / Terminal Value by vintage**, including the seed balance.
5. **Milestones** (age balance crosses $500k/$1M/$2M).
6. **What-If scenarios + required-return solver.**
7. **Frontend:** form, live recalculation on input change, Chart.js visualizations, design system application.
8. **QA pass** against the edge-case list in section 9.

Don't front-load frontend polish before the backend math is verified correct — this project's Excel version repeatedly found real calculation bugs (filing-status lookup mismatches, wage-base indexing, MAGI eligibility, double-counted growth timing) well after the model "looked" done, so budget real time for verification, not just feature-building.

## 12. Session start behavior

When the user types **`init`** into the Cursor chat prompt, respond with a short status greeting instead of silently starting to code. This confirms context was actually read before any work begins. The greeting should:

- Confirm this handoff doc has been read and understood.
- State in 1-2 sentences what this project is (Roth IRA/TVM retirement model, HTML/CSS/JS frontend + Python/FastAPI backend, rebuilt from an existing Excel model).
- List the build order from Section 11 as a short checklist, marking nothing as started yet.
- Ask which phase to begin with, or confirm starting at Phase 1 (backend core engine) by default.
- Ask for the 2-3 known input/output pairs from the Excel file mentioned in Section 9, if not already provided, since those are needed before writing regression tests.

Example tone/shape (don't copy verbatim, adapt naturally):

> Read the handoff — this is the Roth IRA/TVM retirement model rebuild (Excel → FastAPI backend + vanilla HTML/CSS/JS frontend). Build order ahead:
> 1. Backend core engine (annual + periodic, IRA limits, base tax) — not started
> 2. Filing status + state tax + transition logic — not started
> 3. Actuary Mode + salary cap — not started
> 4. Growth Multiple / Terminal Value by vintage — not started
> 5. Milestones — not started
> 6. What-If scenarios + required-return solver — not started
> 7. Frontend + Chart.js — not started
> 8. QA pass — not started
>
> Before starting Phase 1: can you share 2-3 known input/output pairs from the Excel file so I have real regression fixtures? Otherwise I'll start on the core engine now and we verify against Excel once you have those handy.

This should only trigger on the literal `init` command, not on every message — normal requests get normal direct responses without repeating this checklist.
