# Actuarial IRA Projection Model

## Table of Contents

- [Overview](#overview)
- [Project Highlights](#project-highlights)
- [Screenshots](#screenshots)
- [Workbook Structure](#workbook-structure)
- [How to Use](#how-to-use)
- [Methodology](#methodology)
- [Assumptions and Limitations](#assumptions-and-limitations)
- [Quality Assurance](#quality-assurance)
- [Future Improvements](#future-improvements)
- [Author](#author)

## Overview

This project is an Excel-based Roth IRA projection model that applies Actuarial Exam Financial Mathematics (FM) concepts to a realistic personal finance and actuarial career scenario. I built the model to show how contribution timing, investment returns, inflation, IRA contribution limits, salary growth, taxes, and career progression can affect long-term retirement outcomes.

The workbook uses a transparent year-by-year calculation engine so users can follow how each assumption affects the results. It also supports periodic contributions, including monthly, weekly, and advanced trading-day contribution schedules.

In addition to projecting Roth IRA balances, the model estimates gross salary, federal income tax, payroll taxes, optional state income tax, disposable take-home pay, retirement milestones, and what-if scenarios.

This project is intended to demonstrate my understanding of time value of money, annuities, compound interest, spreadsheet modeling, assumption management, and actuarial-style quality control. It is an educational model and is not intended to provide tax, legal, investment, or financial advice.

## Project Highlights

## Screenshots

## Workbook Structure

## How to Use

## Methodology

The model uses a year-by-year time value of money framework. Roth IRA contributions are modeled as either annual or periodic contributions. For periodic contributions, the annual effective investment return is converted to an effective return per period:

```text
(1 + annual return)^(1 / periods per year) - 1
```

The annual modeled Roth IRA limit is indexed once per projection year and then divided across the selected contribution periods. It is not indexed separately during each month, week, or trading-day period.

The model uses an illustrative indexed IRA limit. Because the IRS does not publish the intermediate unrounded indexing value used to determine future contribution limits, the model treats the published 2026 regular limit and catch-up limit as the starting index values. Future unrounded values are projected using the user’s inflation assumption and rounded downward using the modeled statutory increments.

Future federal tax thresholds and standard deductions use the same simplified indexing framework. The user’s inflation assumption is treated as CPI inflation, and the model estimates C-CPI-U inflation as approximately 90.1% of that rate based on historical data since C-CPI-U became available. For example, a 3.0% CPI assumption produces a modeled C-CPI-U rate of approximately 2.7%.

Federal income tax is calculated progressively by applying each marginal rate only to the portion of taxable income within that bracket. The model also estimates Social Security, Medicare, optional flat state income tax, salary growth, and disposable take-home pay.

## Assumptions & Limitations

The IRA indexing results are illustrative rather than official IRS forecasts. The IRS publishes the final contribution limits, but it does not publish the intermediate unrounded index used to determine each future limit. If the actual 2026 underlying index differs from the published $7,500 regular limit or $1,100 catch-up limit used as the model’s starting index, future modeled step increases could occur earlier or later than the official limits.

The same limitation applies to the age-50 catch-up contribution model. The model assumes catch-up eligibility begins when the individual is age 50 or older and applies an illustrative indexed catch-up limit. It does not forecast future official IRS catch-up limits.

The largest assumption is that the federal tax regime remains unchanged throughout the projection period. If Congress changes marginal tax rates, bracket structures, standard deductions, filing rules, phase-outs, or other provisions, those changes are not automatically reflected.

The model uses a simplified C-CPI-U proxy for future tax-bracket and deduction adjustments. It does not recreate every official IRS calculation date, statutory lookback period, or rounding rule. Current-year values are based on published reference inputs, while future values are explicitly illustrative.

The model does not include every factor that affects a real tax return. Excluded items include tax credits, itemized deductions, employer-sponsored retirement plans, HSA contributions, local taxes, capital gains, investment fees, Roth conversion taxation, and detailed state tax codes. State income tax is represented as an optional flat-rate estimate applied to federal taxable income.

Salary growth and actuarial career progression are user-defined assumptions. Exam raises, credential raises, merit increases, and salary caps are not forecasts of any particular employer or actuarial career path.

Investment returns, inflation, salary growth, contribution growth, and tax assumptions are deterministic. The model does not randomly simulate market volatility, sequence-of-returns risk, unemployment, or changing household circumstances. However, the `WHAT-IF SCENARIOS` sheet includes a user-defined contribution gap or career-break scenario that allows the user to specify a gap start year and gap length. This scenario is deterministic and does not model the probability, salary impact, or timing uncertainty of an actual career interruption.

This project is for educational and portfolio purposes only. It is not tax, legal, actuarial, investment, or financial advice.

## Quality Assurance

## Files

## Future Improvements

## Author 
