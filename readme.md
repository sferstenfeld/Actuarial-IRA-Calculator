# Actuarial IRA Projection Model

A Roth IRA retirement calculator with progressive federal tax modeling, real IRS eligibility rules, and actuarial career projections. 

## Table of Contents

- [Overview](#overview)
- [Why I Built This](#why-i-built-this)
- [Live Demo](#live-demo)
- [Screenshots](#screenshots)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Setup](#setup)
- [Methodology](#methodology)
- [Assumptions and Limitations](#assumptions-and-limitations)
- [Quality Assurance](#quality-assurance)
- [Future Improvements](#future-improvements)
- [About Me](#about-me)
- [Suggestions](#suggestions)



## Overview

This project is a Roth IRA projection model that applies Actuarial Exam Financial Mathematics (FM) concepts to a realistic personal finance and actuarial career scenario. Originally built in Excel and rebuilt as a FastAPI web app, it shows how contribution timing, investment returns, inflation, IRA contribution limits, salary growth, taxes, and career progression can affect long-term retirement outcomes.

The app uses a transparent year-by-year calculation engine so users can follow how each assumption affects the results. It also supports periodic contributions, including monthly, weekly, and advanced trading-day contribution schedules.

In addition to projecting Roth IRA balances, the model estimates gross salary, federal income tax, payroll taxes, optional state income tax, disposable take-home pay, retirement milestones, and what-if scenarios.

This project is intended to demonstrate my understanding of time value of money, annuities, compound interest, financial modeling, assumption management, and actuarial-style quality control. It is an educational model and is not intended to provide tax, legal, investment, or financial advice.

## Why I Built This

I built this project because most popular online Roth IRA calculators are too simplified for long-horizon planning. Tools like [NerdWallet](https://www.nerdwallet.com/investing/calculators/roth-ira-calculator) or [Calculator.net](https://www.calculator.net/ira-calculator.html) are useful for a quick estimate, but they treat annual contributions as a flat input held constant for decades. In reality, IRS IRA contribution limits (and catch-up amounts) are inflation-indexed over time, so a multi-decade projection that never lifts that ceiling understates how much a disciplined saver can put away.

Those calculators also leave out much of the surrounding tax and eligibility mechanics that shape Roth outcomes over a career. NerdWallet applies current-year income limits to size this year's contribution, but neither tool projects inflation-indexed contribution ceilings forward, and neither models year-by-year progressive federal brackets, payroll taxes, evolving MAGI phase-outs (including Direct vs Backdoor paths), or contribution caps tied to earned income. Few of them model an actuarial-style career path with exam and credential raises.

I first built the model in Excel. That workbook was the right place to get the math right: a transparent year-by-year engine for Exam FM time-value-of-money logic, progressive taxes, IRA limits, and career assumptions. It became a separate audited reference model and the foundational building block for this app's engine logic. I used it for independent verification while rebuilding the calculations in Python, not as a downloadable deliverable in this repository.

The limitation was the product experience. Spreadsheet tabs multiplied as the model grew, and there was no cohesive dashboard. With as many inputs and paths as the scenario allows (visible in the live app), I could not keep the variable inputs on one usable surface alongside the outputs, charts, and what-if comparisons. That friction is what pushed the next step: the same verified engine, rebuilt as a FastAPI web app with a single interactive interface.

## Live Demo

Try the app here: [https://actuarial-ira-calculator.onrender.com/](https://actuarial-ira-calculator.onrender.com/)

## Screenshots

### Calculator Overview

![Calculator Overview](Screenshots/calculator-overview.png)

### What-If Scenarios

![What-If Scenarios](Screenshots/what-if-scenario.png)

## Features



## Tech Stack

The backend is a Python FastAPI service with Pydantic-validated inputs and a single `POST /api/calculate` endpoint that returns the full projection as JSON. The frontend is vanilla HTML, CSS, and JavaScript with no build step, and Chart.js (via CDN) for the charts. The UI is a dark, fintech-style layout with two tabs: Calculator Overview for the main projection, and What-If Scenarios for isolated shadow calculations.

## Setup



## Methodology



#### Compound Interest

The model uses a year-by-year time value of money framework. Account balances grow based on the selected effective annual investment return.

#### Annuities

Roth IRA contributions are modeled as recurring annuity contributions. The model supports both beginning-of-period and end-of-period contribution timing.

#### Periodic Effective Returns

For periodic contributions, the annual effective investment return is converted to an effective return per period:

$$
i_p = (1+i)^{1/m}-1
$$

where $i$ is the annual effective investment return and $m$ is the number of contribution periods per year.

In this equation:

- $i_p$: effective investment return per contribution period.
- $i$: nominal effective annual investment return.
- $m$: number of contribution periods per year.

The annual modeled Roth IRA limit is indexed once per projection year and then divided across the selected contribution periods. It is not indexed separately during each month, week, or trading-day period.

#### IRA-Limit Indexing

The model uses an illustrative indexed IRA limit. Because the IRS does not publish the intermediate unrounded indexing value used to determine future contribution limits, the model treats the published 2026 regular limit and catch-up limit as the starting index values. Future unrounded values are projected using the user’s inflation assumption and rounded downward using the modeled statutory increments.

#### Real-Dollar Conversion

The Fisher equation describes the relationship between nominal returns, real returns, and inflation:

$$
1+i = (1+r)(1+\pi)
$$

Solving for the real return:

$$
r = \frac{1+i}{1+\pi}-1
$$

In these equations:

- $r$: real effective annual investment return after adjusting for inflation.
- $\pi$: effective annual inflation rate.

For future balances, the model applies the cumulative form of this relationship. A nominal balance is divided by the cumulative inflation index to estimate its purchasing power in today’s dollars:

$$
\text{Real Balance}_t = \frac{\text{Nominal Balance}_t}{\text{Cumulative Inflation Index}_t}
$$

If inflation is constant:

$$
\text{Cumulative Inflation Index}_t = (1+\pi)^t
$$

Here, $t$ represents the number of years in the projection period.

#### Progressive Taxation

Federal income tax is calculated progressively by applying each marginal rate only to the portion of taxable income within that bracket. The model also estimates Social Security, Medicare, optional flat state income tax, salary growth, and disposable take-home pay.

#### C-CPI-U Proxy for Future Tax Thresholds

Future federal tax thresholds and standard deductions use the same simplified indexing framework. The user’s inflation assumption is treated as CPI inflation, and the model estimates C-CPI-U inflation as approximately 90.1% of that rate based on historical data since C-CPI-U became available. For example, a 3.0% CPI assumption produces a modeled C-CPI-U rate of approximately 2.7%.

#### Required Return Solver

The What-If Scenarios tab can solve for the constant annual effective return needed to reach a user-specified retirement balance, given the same contribution schedule, timing, and other base-case assumptions. This is an Exam FM-style unknown-rate problem: find $r$ such that the projected ending balance equals a target.

If the user enters a real (inflation-adjusted) target, the solver first converts it to a nominal target using the model’s inflation path:

$$
T_{\text{nominal}} = T_{\text{real}} \cdot (1+\pi)^{N_{\pi}}
$$

where $\pi$ is the assumed annual inflation rate and $N_{\pi}$ is the number of inflation years used elsewhere in the projection. The solve itself is always performed against this nominal target.

Let $B(r)$ be the final nominal balance from the periodic accumulation engine when the annual return equals $r$, holding every other input fixed. The solver searches for a root of the gap function

$$
g(r) = B(r) - T_{\text{nominal}}
$$

Conceptually, $B(r)$ is the future value of the starting balance plus each contribution grown at rate $r$ for the remaining investment periods (with Beginning vs End timing already embedded in the engine). Because a higher return produces a higher ending balance, $g(r)$ is smooth and monotonically increasing in $r$, so a single root is well-defined when the target is reachable.

The implementation does not rely on a spreadsheet Goal-Seek workaround. It brackets the root on $[0, 0.05]$ and doubles the upper bound until $g$ changes sign (or reports that the target is unreachable within a 1000% annual return search limit). It then applies numerical bisection until the gap or interval width falls below a tight tolerance. If the target is already reachable at a 0% return, the solver reports 0%.

The solve runs as an isolated shadow calculation: it does not overwrite the main model’s assumed return or regenerate the base-case charts.

## Assumptions and Limitations

#### Indexing

The IRA indexing results are illustrative rather than official IRS forecasts. The IRS publishes the final contribution limits, but it does not publish the intermediate unrounded index used to determine each future limit. If the actual 2026 underlying index differs from the published $7,500 regular limit or $1,100 catch-up limit used as the model’s starting index, future modeled step increases could occur earlier or later than the official limits.

The same limitation applies to the age-50 catch-up contribution model. The model assumes catch-up eligibility begins when the individual is age 50 or older and applies an illustrative indexed catch-up limit. It does not forecast future official IRS catch-up limits.

The model uses a simplified C-CPI-U proxy for future tax-bracket and deduction adjustments. It does not recreate every official IRS calculation date, statutory lookback period, or rounding rule. Current-year values are based on published reference inputs, while future values are explicitly illustrative.

#### Tax Policy

The largest assumption is that the federal tax regime remains unchanged throughout the projection period. If Congress changes marginal tax rates, bracket structures, standard deductions, filing rules, phase-outs, or other provisions, those changes are not automatically reflected.

#### Tax Scope

The model does not include every factor that affects a real tax return. Excluded items include tax credits, itemized deductions, employer-sponsored retirement plans, HSA contributions, local taxes, capital gains, investment fees, Roth conversion taxation, and detailed state tax codes. State income tax is represented as an optional flat-rate estimate applied to federal taxable income.

#### Career Assumptions

Salary growth and actuarial career progression are user-defined assumptions. Exam raises, credential raises, merit increases, and salary caps are not forecasts of any particular employer or actuarial career path.

#### Deterministic Assumptions

Investment returns, inflation, salary growth, contribution growth, and tax assumptions are deterministic. The model does not randomly simulate market volatility, sequence-of-returns risk, unemployment, or changing household circumstances. However, the What-If Scenarios tab includes a user-defined contribution gap or career-break scenario that allows the user to specify a gap start year and gap length. These scenarios run as isolated shadow calculations and do not change the base model. The gap scenario is deterministic and does not model the probability, salary impact, or timing uncertainty of an actual career interruption.

This project is for educational and portfolio purposes only. It is not tax, legal, actuarial, investment, or financial advice.

## Quality Assurance



## Future Improvements

One direction I may add is optional Traditional IRA contributions alongside the current Roth path, including a comparison analysis for when each account type is more advantageous. That could include scenarios where it makes sense to prefer Traditional early, Roth later, or the reverse, depending on projected tax brackets, take-home pay, and retirement tax assumptions.

Another direction is to move beyond fixed expected return and inflation assumptions. I am considering stochastic processes and Monte Carlo simulation driven by historical market returns, or by return distributions for selected investment classes, so outcomes can be shown as a range of paths rather than a single deterministic projection.

## About Me

I am an Actuarial Science and Economics student entering my senior year and preparing for a career in actuarial analysis and risk management. I built this project to strengthen and apply my understanding of Exam FM concepts while exploring how actuarial modeling can be applied to personal finance and career planning.

I am especially interested in combining financial mathematics, Excel and Python modeling, and clear communication to build models that are both technically sound and easy to understand.

[LinkedIn](https://www.linkedin.com/in/sferst/) | [GitHub](https://github.com/sferstenfeld)

## Suggestions

If you have any suggestions to make or find any quality assurance issues (bugs), please email me at [sferstenfeld@gmail.com](mailto:sferstenfeld@gmail.com).