/* global Chart */

/* Dark-mode fintech chart palette */
const ACCENT = "#3B82F6";
const SERIES_SECONDARY = "#E5E7EB";
const SERIES_TERTIARY = "#9CA3AF";
const MUTED = "#9CA3AF";
const GRID = "rgba(255,255,255,0.08)";
const PIE = ["#3B82F6", "#60A5FA", "#FBBF24", "#F5F6F7", "#6B7280"];
const TAKEHOME_FED = "#6B7280";
const TAKEHOME_STATE = "#C9A227";
const TAKEHOME_PAYROLL = "#60A5FA";
const TAKEHOME_NET = "#3B82F6";

const $ = (sel) => document.querySelector(sel);
const form = $("#inputs");
const statusEl = $("#status");

let balanceChart;
let purchasingPowerChart;
let growthMultipleChart;
let contribChart;
let takeHomeChart;
let taxChart;
let allocationChart;
/** Persists across recalcs; only user toggle changes this. */
let balanceYScale = "linear";
/** Log-axis floor — keeps the chart in the informative $1k+ range. */
const LOG_AXIS_MIN = 1_000;
let debounceTimer;
let latestData = null;

function pctToDecimal(name) {
  return Number(form.elements[name].value) / 100;
}

function numOrNull(name) {
  const v = form.elements[name].value;
  if (v === "" || v == null) return null;
  return Number(v);
}

/**
 * Assign input.value only when it actually changes. Blind reassignment
 * resets caret/selection even when the displayed text is identical — which
 * races with click/select when a debounced recalc fires.
 */
function updateInputIfChanged(inputElement, newValue) {
  const next = String(newValue);
  if (inputElement.value === next) return;
  const selStart = inputElement.selectionStart;
  const selEnd = inputElement.selectionEnd;
  inputElement.value = next;
  if (document.activeElement === inputElement) {
    try {
      // type=number may not support selection APIs in every browser
      if (selStart != null && selEnd != null) {
        inputElement.setSelectionRange(selStart, selEnd);
      }
    } catch (_) {
      /* ignore */
    }
  }
}

/** Skip attribute writes on the focused control; otherwise only if changed. */
function updateAttrIfChanged(el, attr, newValue) {
  if (document.activeElement === el) return;
  const next = String(newValue);
  if (el.getAttribute(attr) === next) return;
  el.setAttribute(attr, next);
}

/** Skip class toggles on the focused control; otherwise only if changed. */
function updateClassFlag(el, className, shouldHave) {
  if (document.activeElement === el) return;
  if (el.classList.contains(className) === shouldHave) return;
  el.classList.toggle(className, shouldHave);
}

function toggleVisibility() {
  const freq = form.elements.contribution_frequency.value;
  document.querySelectorAll(".advanced-only").forEach((el) => {
    el.classList.toggle("hidden", freq !== "Advanced");
  });
  const change = form.elements.filing_status_change_enabled.checked;
  document.querySelectorAll(".status-change-only").forEach((el) => {
    el.classList.toggle("hidden", !change);
  });
  const state = form.elements.include_state_tax.checked;
  document.querySelectorAll(".state-only").forEach((el) => {
    el.classList.toggle("hidden", !state);
  });
  const actuary = form.elements.actuary_mode.checked;
  document.querySelectorAll(".actuary-only").forEach((el) => {
    el.classList.toggle("hidden", !actuary);
  });
  const cap = form.elements.cap_salary_growth.checked;
  document.querySelectorAll(".cap-only").forEach((el) => {
    el.classList.toggle("hidden", !cap);
  });
  validateSalaryCap();
}

/** Cap must be >= starting salary (equal allowed). Below is invalid. */
function validateSalaryCap() {
  const enabled = form.elements.cap_salary_growth.checked;
  const capInput = form.elements.salary_cap;
  const errEl = $("#salaryCapError");
  const start = Number(form.elements.starting_salary.value);
  if (Number.isFinite(start)) {
    updateAttrIfChanged(capInput, "min", start);
  }
  if (!enabled) {
    updateClassFlag(capInput, "input-invalid", false);
    if (errEl) errEl.classList.add("hidden");
    return true;
  }
  const cap = Number(capInput.value);
  const ok = Number.isFinite(cap) && Number.isFinite(start) && cap >= start;
  updateClassFlag(capInput, "input-invalid", !ok);
  if (errEl) errEl.classList.toggle("hidden", ok);
  return ok;
}

function readPayload() {
  return {
    starting_age: Number(form.elements.starting_age.value),
    retirement_age: Number(form.elements.retirement_age.value),
    current_ira_balance: Number(form.elements.current_ira_balance.value),
    contribution_frequency: form.elements.contribution_frequency.value,
    trading_day_interval:
      form.elements.contribution_frequency.value === "Advanced"
        ? Number(form.elements.trading_day_interval.value)
        : null,
    annual_return: pctToDecimal("annual_return_pct"),
    annual_inflation: pctToDecimal("annual_inflation_pct"),
    contribution_timing: form.elements.contribution_timing.value,
    contribution_delay_years: Number(form.elements.contribution_delay_years.value),
    filing_status: form.elements.filing_status.value,
    filing_status_change_enabled: form.elements.filing_status_change_enabled.checked,
    target_filing_status: form.elements.filing_status_change_enabled.checked
      ? form.elements.target_filing_status.value
      : null,
    years_until_filing_status_change: Number(
      form.elements.years_until_filing_status_change.value
    ),
    include_state_tax: form.elements.include_state_tax.checked,
    state_tax_rate: pctToDecimal("state_tax_rate_pct"),
    starting_salary: Number(form.elements.starting_salary.value),
    annual_merit_raise: pctToDecimal("annual_merit_raise_pct"),
    actuary_mode: form.elements.actuary_mode.checked,
    credential_status: form.elements.credential_status.value,
    exams_remaining: Number(form.elements.exams_remaining.value),
    salary_raise_per_exam: Number(form.elements.salary_raise_per_exam.value),
    salary_raise_associate: Number(form.elements.salary_raise_associate.value),
    years_until_associate: Number(form.elements.years_until_associate.value),
    salary_raise_fellowship: Number(form.elements.salary_raise_fellowship.value),
    years_until_fellowship: Number(form.elements.years_until_fellowship.value),
    years_until_exams_finish: Number(form.elements.years_until_exams_finish.value),
    cap_salary_growth: form.elements.cap_salary_growth.checked,
    salary_cap: form.elements.cap_salary_growth.checked
      ? Number(form.elements.salary_cap.value)
      : null,
    return_spread: pctToDecimal("return_spread_pct"),
    inflation_swing: pctToDecimal("inflation_swing_pct"),
    contribution_gap_start_year: numOrNull("contribution_gap_start_year"),
    contribution_gap_length: Number(form.elements.contribution_gap_length.value) || 0,
    early_stop_age: numOrNull("early_stop_age"),
    target_retirement_balance: numOrNull("target_retirement_balance"),
    target_balance_is_real: form.elements.target_balance_is_real.checked,
  };
}

/** Whole dollars for balances; cents for tax-detail lines (handoff §10). */
function money(n, decimals = 0) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function moneyTax(n) {
  return money(n, 2);
}

function pct(n, digits = 1) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

function setStatus(msg, kind) {
  statusEl.textContent = msg;
  statusEl.className = `status${kind ? ` ${kind}` : ""}`;
}

function humanizeFieldName(name) {
  return String(name || "input")
    .replace(/_pct$/, "")
    .replace(/_/g, " ");
}

/** Turn FastAPI/Pydantic error bodies into a short readable status line. */
function formatApiError(errBody, fallback = "Something went wrong. Please check your inputs.") {
  const detail = errBody?.detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((err) => {
      let msg = String(err.msg || "invalid value").replace(/^Value error,\s*/i, "");
      // Custom validators already return a complete sentence after the prefix strip.
      if (err.type === "value_error") return msg;
      const loc = Array.isArray(err.loc)
        ? err.loc.filter((p) => p !== "body" && typeof p === "string")
        : [];
      const field = humanizeFieldName(loc[loc.length - 1] || "input");
      return `${field}: ${msg}`;
    });
    return parts.join("; ") || fallback;
  }
  if (typeof detail === "string" && detail.trim()) return detail;
  return fallback;
}

/** Native min/max (and type) constraints — catch bad values before the API call. */
function formatConstraintErrors() {
  const invalids = [...form.querySelectorAll("input:invalid, select:invalid")];
  if (!invalids.length) return null;
  return invalids
    .map((el) => {
      const field = humanizeFieldName(el.name || el.getAttribute("aria-label") || "input");
      return `${field}: ${el.validationMessage || "invalid value"}`;
    })
    .join("; ");
}

function fmtMultiple(n, digits = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(digits)}x`;
}

function renderSummary(data) {
  const periodic = data.final_balance_periodic;
  const contribs = data.total_contributions;
  const firstGm = data.years.length ? data.years[0].growth_multiple : null;
  const lastGm = data.years.length ? data.years[data.years.length - 1].growth_multiple : null;
  const moneyMult = contribs > 0 ? periodic / contribs : null;
  const gross = data.total_gross_income || 0;
  const taxRate = gross > 0 ? data.total_tax / gross : null;

  const primary = [
    ["Final nominal balance", money(periodic)],
    ["Final real balance", money(data.final_balance_real_periodic)],
    ["Total contributions", money(contribs)],
    ["Lifetime tax", money(data.total_tax)],
  ];
  const secondary = [
    ["First contribution’s growth multiple", fmtMultiple(firstGm)],
    ["Final contribution’s growth multiple", fmtMultiple(lastGm)],
    ["Money multiplier", fmtMultiple(moneyMult)],
    ["Cumulative effective tax rate", taxRate == null ? "—" : pct(taxRate, 1)],
  ];

  const toCards = (cells, cls) =>
    cells
      .map(
        ([label, value]) =>
          `<div class="stat ${cls}"><div class="label">${label}</div><div class="value">${value}</div></div>`
      )
      .join("");

  $("#summaryPrimary").innerHTML = toCards(primary, "stat-primary");
  $("#summarySecondary").innerHTML = toCards(secondary, "stat-secondary");

  const caption = $("#summaryCaption");
  if (firstGm != null && lastGm != null) {
    caption.hidden = false;
    caption.textContent =
      `Your dollars didn’t grow equally: ${fmtMultiple(firstGm)} for your earliest contribution ` +
      `vs. ${fmtMultiple(lastGm)} for your last, because early money compounds longer.`;
  } else {
    caption.hidden = true;
    caption.textContent = "";
  }

  const earnedNote = $("#earnedIncomeCapNote");
  const cappedYears = data.years_contribution_capped_by_income || 0;
  if (cappedYears > 0) {
    earnedNote.hidden = false;
    earnedNote.textContent =
      cappedYears === 1
        ? "Contributions were limited by earned income in 1 year (IRC §219 — cannot exceed compensation)."
        : `Contributions were limited by earned income in ${cappedYears} years (IRC §219 — cannot exceed compensation).`;
  } else {
    earnedNote.hidden = true;
    earnedNote.textContent = "";
  }

  const badge = $("#vintageBadge");
  if (badge) {
    badge.hidden = false;
    badge.textContent = data.vintage_cross_check_ok ? "Vintage check passed" : "Vintage check failed";
    badge.className = `badge${data.vintage_cross_check_ok ? " badge-ok" : " badge-err"}`;
  }
}

function chartDefaults() {
  Chart.defaults.font.family = "'Open Sans', 'Segoe UI', system-ui, sans-serif";
  Chart.defaults.color = MUTED;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.plugins.legend.labels.color = MUTED;
  Chart.defaults.elements.line.borderWidth = 2;
  Chart.defaults.elements.point.radius = 0;
  Chart.defaults.scale.grid.color = GRID;
  Chart.defaults.scale.grid.drawBorder = false;
  Chart.defaults.scale.grid.drawTicks = false;
}

function formatMoneyAxisTick(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n >= 1e6) {
    const m = n / 1e6;
    return `$${Number.isInteger(m) || m >= 10 ? m.toFixed(0) : m.toFixed(1)}M`;
  }
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}k`;
  if (n === 0) return "$0";
  return `$${Math.round(n)}`;
}

function axisMoneyTicks() {
  return {
    callback: formatMoneyAxisTick,
  };
}

/**
 * Replace Chart.js's default log major+minor tick set with a single decade list.
 * Filtering via callback alone still left competing tick slots and clipped labels.
 */
function buildLogDecadeTicks(axis) {
  const floor = Math.max(Number(axis.options.min) || LOG_AXIS_MIN, LOG_AXIS_MIN);
  const ceiling = Math.max(Number(axis.max) || floor, floor);
  const startExp = Math.ceil(Math.log10(floor) - 1e-12);
  const endExp = Math.floor(Math.log10(ceiling) + 1e-12);
  const ticks = [];
  for (let e = startExp; e <= endExp; e++) {
    ticks.push({ value: 10 ** e });
  }
  if (!ticks.length) {
    ticks.push({ value: 10 ** Math.max(0, Math.round(Math.log10(ceiling))) });
  }
  axis.ticks = ticks;
}

/** Drop values below the log floor (incl. $0 delay years) so they sit off-chart. */
function seriesForBalanceScale(values, useLog) {
  if (!useLog) return values;
  return values.map((v) => (v == null || v < LOG_AXIS_MIN ? null : v));
}

function syncBalanceScaleToggle() {
  document.querySelectorAll("[data-balance-scale]").forEach((btn) => {
    const active = btn.dataset.balanceScale === balanceYScale;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

/** Destroy any Chart.js instance on this canvas and create a fresh one.
 *  Avoids DPI / buffer drift from repeated .resize() or in-place .update().
 */
function mountChart(canvas, config) {
  const existing = typeof Chart.getChart === "function" ? Chart.getChart(canvas) : null;
  if (existing) existing.destroy();
  canvas.removeAttribute("width");
  canvas.removeAttribute("height");
  canvas.style.width = "";
  canvas.style.height = "";
  return new Chart(canvas, config);
}

function chartFillOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    ...extra,
  };
}

function moneyAxisOptions() {
  return chartFillOptions({
    plugins: {
      legend: { position: "top", labels: { color: MUTED } },
    },
    scales: {
      x: {
        title: { display: true, text: "Age", color: MUTED },
        ticks: { color: MUTED },
        grid: { display: false, drawBorder: false },
        border: { display: false },
      },
      y: {
        ticks: { ...axisMoneyTicks(), color: MUTED },
        grid: { color: GRID, drawBorder: false },
        border: { display: false },
      },
    },
  });
}

/** Primary TVM charts — Balance, Purchasing Power, Growth Multiple, Contributions. */
function renderPrimaryCharts(data) {
  const ages = data.years.map((y) => y.age);
  const nominalPeriodic = data.years.map((y) => y.ending_balance_periodic);
  const real = data.years.map((y) => y.ending_balance_real_periodic);
  const purchasingPowerPct = data.years.map((y) => {
    const nom = y.ending_balance_periodic;
    if (!nom) return null;
    return (y.ending_balance_real_periodic / nom) * 100;
  });
  const contribs = data.years.map((y) => y.contribution);
  const tvs = data.years.map((y) => y.terminal_value);
  let runningContrib = 0;
  const cumulativeContributions = data.years.map((y) => {
    runningContrib += y.contribution;
    return runningContrib;
  });
  const commonOpts = moneyAxisOptions();
  const useLog = balanceYScale === "log";
  syncBalanceScaleToggle();

  balanceChart = mountChart($("#balanceChart"), {
    type: "line",
    data: {
      labels: ages,
      datasets: [
        {
          label: "Periodic nominal",
          data: seriesForBalanceScale(nominalPeriodic, useLog),
          borderColor: ACCENT,
          backgroundColor: ACCENT,
          borderWidth: 2.5,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointStyle: "rect",
          spanGaps: useLog,
        },
        {
          label: "Periodic real",
          data: seriesForBalanceScale(real, useLog),
          borderColor: SERIES_TERTIARY,
          backgroundColor: SERIES_TERTIARY,
          borderDash: [2, 2],
          pointRadius: 0,
          pointHoverRadius: 4,
          pointStyle: "rect",
          spanGaps: useLog,
        },
        {
          label: "Total contributions",
          data: seriesForBalanceScale(cumulativeContributions, useLog),
          borderColor: TAKEHOME_STATE,
          backgroundColor: TAKEHOME_STATE,
          borderWidth: 2,
          borderDash: [6, 4],
          pointRadius: 0,
          pointHoverRadius: 4,
          pointStyle: "rect",
          spanGaps: useLog,
        },
      ],
    },
    options: chartFillOptions({
      plugins: {
        legend: {
          position: "top",
          labels: {
            color: MUTED,
            // Solid legend swatches for all series (including dashed lines on the plot).
            usePointStyle: true,
            pointStyle: "rect",
            boxWidth: 12,
            boxHeight: 12,
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const i = ctx.dataIndex;
              const raw =
                ctx.datasetIndex === 0
                  ? nominalPeriodic[i]
                  : ctx.datasetIndex === 1
                    ? real[i]
                    : cumulativeContributions[i];
              return `${ctx.dataset.label}: ${money(raw)}`;
            },
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: "Age", color: MUTED },
          ticks: { color: MUTED },
          grid: { display: false, drawBorder: false },
          border: { display: false },
        },
        y: useLog
          ? {
              type: "logarithmic",
              min: LOG_AXIS_MIN,
              ticks: {
                color: MUTED,
                // Single formatter only — decade list comes from afterBuildTicks.
                callback: formatMoneyAxisTick,
                padding: 6,
              },
              afterBuildTicks: buildLogDecadeTicks,
              grid: { color: GRID, drawBorder: false },
              border: { display: false },
            }
          : {
              type: "linear",
              ticks: { ...axisMoneyTicks(), color: MUTED },
              grid: { color: GRID, drawBorder: false },
              border: { display: false },
            },
      },
    }),
  });

  purchasingPowerChart = mountChart($("#purchasingPowerChart"), {
    type: "line",
    data: {
      labels: ages,
      datasets: [
        {
          label: "Purchasing power retained",
          data: purchasingPowerPct,
          borderColor: ACCENT,
          backgroundColor: ACCENT,
          borderWidth: 2.5,
          spanGaps: true,
        },
      ],
    },
    options: chartFillOptions({
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) =>
              ctx.parsed.y == null ? "—" : `${ctx.parsed.y.toFixed(1)}% of nominal`,
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: "Age", color: MUTED },
          ticks: { color: MUTED },
          grid: { display: false, drawBorder: false },
          border: { display: false },
        },
        y: {
          min: 0,
          max: 100,
          title: { display: true, text: "% of nominal", color: MUTED },
          ticks: {
            color: MUTED,
            callback: (v) => `${v}%`,
          },
          grid: { color: GRID, drawBorder: false },
          border: { display: false },
        },
      },
    }),
  });

  // Growth multiple by vintage — pure time-remaining TVM factor from the engine
  // (periodic rate + Beginning/End). Not TV/contribution, so delay years still plot.
  const growthMultiples = data.years.map((y) => y.growth_multiple);
  growthMultipleChart = mountChart($("#growthMultipleChart"), {
    type: "line",
    data: {
      labels: ages,
      datasets: [
        {
          label: "Growth multiple (×)",
          data: growthMultiples,
          borderColor: ACCENT,
          backgroundColor: ACCENT,
          tension: 0.15,
        },
      ],
    },
    options: chartFillOptions({
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const y = data.years[ctx.dataIndex];
              const gm = ctx.parsed.y;
              const parts = [`${gm.toFixed(2)}× by retirement`];
              if (y.contribution > 0) {
                parts.push(
                  `TV ${money(y.terminal_value)} on ${money(y.contribution)} contrib`
                );
              }
              return parts;
            },
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: "Age", color: MUTED },
          ticks: { color: MUTED },
          grid: { display: false, drawBorder: false },
          border: { display: false },
        },
        y: {
          title: { display: true, text: "Growth multiple (×)", color: MUTED },
          ticks: {
            color: MUTED,
            callback: (v) => `${Number(v).toFixed(v >= 10 ? 0 : 1)}×`,
          },
          grid: { color: GRID, drawBorder: false },
          border: { display: false },
        },
      },
    }),
  });

  contribChart = mountChart($("#contribChart"), {
    type: "bar",
    data: {
      labels: ages,
      datasets: [
        {
          label: "Contribution",
          data: contribs,
          backgroundColor: ACCENT,
          borderWidth: 0,
          borderRadius: 4,
        },
        {
          label: "Terminal value (vintage)",
          data: tvs,
          backgroundColor: SERIES_TERTIARY,
          borderWidth: 0,
          borderRadius: 4,
        },
      ],
    },
    options: commonOpts,
  });
}

/** Tax line chart + Annual Take-Home Pay stacked bar. */
function renderTaxDetailCharts(data) {
  const ages = data.years.map((y) => y.age);
  const fed = data.years.map((y) => y.tax.federal_income_tax);
  const state = data.years.map((y) => y.tax.state_tax);
  const payroll = data.years.map(
    (y) => y.tax.oasdi_tax + y.tax.medicare_tax + y.tax.additional_medicare_tax
  );
  const takeHome = data.years.map((y) => {
    const taxes =
      y.tax.federal_income_tax +
      y.tax.state_tax +
      y.tax.oasdi_tax +
      y.tax.medicare_tax +
      y.tax.additional_medicare_tax;
    return Math.max(0, y.tax.salary - taxes);
  });
  const includeState = state.some((v) => v > 0.005);

  const stackedDatasets = [
    {
      label: "Federal Income Tax",
      data: fed,
      backgroundColor: TAKEHOME_FED,
      borderWidth: 0,
      borderRadius: 0,
      stack: "cashflow",
    },
  ];
  if (includeState) {
    stackedDatasets.push({
      label: "Flat State Income Tax",
      data: state,
      backgroundColor: TAKEHOME_STATE,
      borderWidth: 0,
      borderRadius: 0,
      stack: "cashflow",
    });
  }
  stackedDatasets.push(
    {
      label: "Payroll Taxes",
      data: payroll,
      backgroundColor: TAKEHOME_PAYROLL,
      borderWidth: 0,
      borderRadius: 0,
      stack: "cashflow",
    },
    {
      label: "Take-Home Pay After Taxes",
      data: takeHome,
      backgroundColor: TAKEHOME_NET,
      borderWidth: 0,
      borderRadius: 0,
      stack: "cashflow",
    }
  );

  takeHomeChart = mountChart($("#takeHomeChart"), {
    type: "bar",
    data: {
      labels: ages,
      datasets: stackedDatasets,
    },
    options: chartFillOptions({
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: MUTED, boxWidth: 12, padding: 14 },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${money(ctx.parsed.y)}`,
            footer: (items) => {
              const total = items.reduce((s, i) => s + (i.parsed.y || 0), 0);
              return `Gross: ${money(total)}`;
            },
          },
        },
      },
      scales: {
        x: {
          stacked: true,
          title: { display: true, text: "Age", color: MUTED },
          ticks: { color: MUTED },
          grid: { display: false, drawBorder: false },
          border: { display: false },
        },
        y: {
          stacked: true,
          title: { display: true, text: "Annual Cash Flow ($)", color: MUTED },
          ticks: { ...axisMoneyTicks(), color: MUTED },
          grid: { color: GRID, drawBorder: false },
          border: { display: false },
        },
      },
    }),
  });

  taxChart = mountChart($("#taxChart"), {
    type: "line",
    data: {
      labels: ages,
      datasets: [
        {
          label: "Federal income tax",
          data: fed,
          borderColor: ACCENT,
          borderWidth: 2,
        },
        {
          label: "Payroll tax",
          data: payroll,
          borderColor: SERIES_SECONDARY,
          borderDash: [4, 3],
        },
      ],
    },
    options: moneyAxisOptions(),
  });
}

function renderCharts(data) {
  renderPrimaryCharts(data);
  renderTaxDetailCharts(data);
}

function renderTaxSummaryAndAllocation(data) {
  const gross = data.total_gross_income || 0;
  const fed = data.total_federal_income_tax;
  const state = data.total_state_tax;
  const payroll = data.total_payroll_tax;
  const totalTax = data.total_tax;
  const ira = data.total_contributions;
  const remaining = Math.max(0, gross - totalTax - ira);
  const taxRate = gross > 0 ? totalTax / gross : 0;
  const takeHomeRate = gross > 0 ? (gross - totalTax) / gross : 0;

  const rows = [
    ["Federal income tax", moneyTax(fed)],
    ["Flat state income tax", moneyTax(state)],
    ["Payroll taxes", moneyTax(payroll)],
    ["Total taxes paid", moneyTax(totalTax), true],
    ["Total gross income earned", money(gross)],
    ["Cumulative total tax rate", pct(taxRate, 1)],
    ["Cumulative effective take-home rate", pct(takeHomeRate, 1)],
  ];
  $("#taxSummaryTable").innerHTML = rows
    .map(
      ([label, value, emph]) =>
        `<tr class="${emph ? "row-emph" : ""}"><td>${label}</td><td>${value}</td></tr>`
    )
    .join("");

  const slices = [
    {
      label: "Remaining income\n(after tax & Roth)",
      value: remaining,
      color: PIE[0],
    },
    {
      label: "IRA contributions",
      value: ira,
      color: PIE[1],
    },
    {
      label: "Payroll taxes",
      value: payroll,
      color: PIE[2],
    },
    {
      label: "Federal income tax",
      value: fed,
      color: PIE[3],
    },
    {
      label: "Flat state income tax",
      value: state,
      color: PIE[4],
    },
  ].filter((s) => s.value > 0.005);

  if (allocationChart) {
    allocationChart.destroy();
    allocationChart = null;
  }
  const canvas = $("#allocationChart");
  if (!slices.length || gross <= 0) {
    return;
  }

  allocationChart = mountChart(canvas, {
    type: "pie",
    data: {
      labels: slices.map((s) => s.label),
      datasets: [
        {
          data: slices.map((s) => s.value),
          backgroundColor: slices.map((s) => s.color),
          borderWidth: 0,
        },
      ],
    },
    options: chartFillOptions({
      layout: {
        padding: { top: 4, bottom: 4, left: 4, right: 4 },
      },
      plugins: {
        legend: {
          position: "bottom",
          align: "center",
          labels: {
            boxWidth: 12,
            padding: 14,
            color: MUTED,
            textAlign: "left",
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const v = ctx.parsed;
              const share = gross > 0 ? (v / gross) * 100 : 0;
              const name = String(ctx.label || "").replace(/\n/g, " ");
              return `${name}: ${money(v)} (${share.toFixed(1)}%)`;
            },
          },
        },
      },
    }),
  });
}

function renderMilestones(data) {
  $("#milestones").innerHTML = (data.milestones || [])
    .map((m) => {
      if (m.reached) {
        return `<li class="hit">${m.label} crossed at age ${m.age} (${money(
          m.balance_at_crossing
        )})</li>`;
      }
      return `<li class="miss">${m.label} not reached by retirement</li>`;
    })
    .join("");

  const nominalList = data.nominal_balance_milestones || [];
  const nominalGroup = $("#nominalMilestonesGroup");
  const nominalUl = $("#nominalMilestones");
  if (!nominalList.length) {
    nominalGroup.hidden = true;
    nominalUl.innerHTML = "";
  } else {
    nominalGroup.hidden = false;
    nominalUl.innerHTML = nominalList
      .map((m) => `<li class="hit">${m.label} at age ${m.age}</li>`)
      .join("");
  }

  const salaryList = data.salary_milestones || [];
  const salaryGroup = $("#salaryMilestonesGroup");
  const salaryUl = $("#salaryMilestones");
  if (!salaryList.length) {
    salaryGroup.hidden = true;
    salaryUl.innerHTML = "";
  } else {
    salaryGroup.hidden = false;
    salaryUl.innerHTML = salaryList
      .map((m) => `<li class="hit">${m.label} at age ${m.age}</li>`)
      .join("");
  }

  const compoundingList = data.compounding_milestones || [];
  const compoundingUl = $("#compoundingMilestones");
  const compoundingEmpty = $("#compoundingMilestonesEmpty");
  if (!compoundingList.length) {
    compoundingUl.innerHTML = "";
    compoundingEmpty.hidden = false;
  } else {
    compoundingEmpty.hidden = true;
    compoundingUl.innerHTML = compoundingList
      .map((m, i) => {
        const from = Number(m.from_multiple).toFixed(0);
        const to = Number(m.to_multiple).toFixed(0);
        const age = Number(m.age).toFixed(1);
        const lead =
          i === 0
            ? `Money doubles (${from}x → ${to}x)`
            : `Doubles again (${from}x → ${to}x)`;
        return `<li class="hit">${lead} by age ${age}</li>`;
      })
      .join("");
  }
}

function deltaCell(value, base) {
  const d = value - base;
  const cls = d > 0 ? "delta-pos" : d < 0 ? "delta-neg" : "delta-zero";
  const sign = d > 0 ? "+" : "";
  return `<td class="${cls}">${sign}${money(d)}</td>`;
}

function scenarioTableWithDeltas(title, rows, baseValue, { deltaField = "nominal" } = {}) {
  if (!rows || !rows.length) return "";
  const valueOf = (r) =>
    deltaField === "real" ? r.final_balance_real : r.final_balance_nominal;
  const deltaHeader = deltaField === "real" ? "Δ real vs base" : "Δ vs base";
  const body = rows
    .map((r) => {
      const isBase = r.label === "Base";
      return (
        `<tr class="${isBase ? "row-base" : ""}">` +
        `<td>${r.label}</td>` +
        `<td>${r.parameter_value != null ? pct(r.parameter_value, 1) : "—"}</td>` +
        `<td>${money(r.final_balance_nominal)}</td>` +
        `<td>${money(r.final_balance_real)}</td>` +
        (isBase
          ? `<td class="delta-zero">—</td>`
          : deltaCell(valueOf(r), baseValue)) +
        `</tr>`
      );
    })
    .join("");
  return (
    `<h3 class="scenario-title">${title}</h3>` +
    `<table><thead><tr><th>Case</th><th>Param</th><th>Nominal</th><th>Real</th><th>${deltaHeader}</th></tr></thead>` +
    `<tbody>${body}</tbody></table>`
  );
}

function renderRequiredReturn(data) {
  const rateEl = $("#requiredReturnRate");
  const targetEl = $("#requiredReturnTarget");
  const noteEl = $("#requiredReturnNote");
  if (!rateEl || !targetEl || !noteEl) return;

  const rr = data?.scenarios?.required_return ?? null;
  rateEl.classList.remove("solver-placeholder", "solver-fail");

  if (!rr) {
    rateEl.textContent = "—";
    rateEl.classList.add("solver-placeholder");
    targetEl.textContent = "—";
    noteEl.textContent = "Enter a target balance to solve.";
    return;
  }

  targetEl.textContent = money(rr.target_nominal);
  if (rr.solved && rr.required_annual_return != null) {
    rateEl.textContent = pct(rr.required_annual_return, 2);
    noteEl.textContent = rr.message;
  } else {
    rateEl.textContent = "n/a";
    rateEl.classList.add("solver-fail");
    noteEl.textContent = rr.message || "Could not solve for a required return.";
  }
}

function renderScenarios(data) {
  const s = data.scenarios;
  const baseNom = data.final_balance_periodic;
  const baseReal = data.final_balance_real_periodic;
  let html = scenarioTableWithDeltas("Return Bear / Base / Bull", s.return_cases, baseNom, {
    deltaField: "nominal",
  });
  html += scenarioTableWithDeltas(
    "Inflation swing (nominal held fixed)",
    s.inflation_cases,
    baseReal,
    { deltaField: "real" }
  );

  if (s.contribution_gap) {
    const g = s.contribution_gap;
    html +=
      `<h3 class="scenario-title">Contribution gap</h3>` +
      `<table><thead><tr><th>Case</th><th>Nominal</th><th>Real</th></tr></thead><tbody>` +
      `<tr class="row-base"><td>Base (with gap)</td><td>${money(g.final_balance_nominal)}</td>` +
      `<td>${money(g.final_balance_real)}</td></tr>` +
      `<tr><td colspan="3" class="scenario-note">${g.label}</td></tr>` +
      `</tbody></table>`;
  }
  if (s.early_stop) {
    const e = s.early_stop;
    html +=
      `<h3 class="scenario-title">Early stop contributing</h3>` +
      `<table><thead><tr><th>Case</th><th>Nominal</th><th>Real</th></tr></thead><tbody>` +
      `<tr class="row-base"><td>Base (with early stop)</td><td>${money(e.final_balance_nominal)}</td>` +
      `<td>${money(e.final_balance_real)}</td></tr>` +
      `<tr><td colspan="3" class="scenario-note">${e.label}</td></tr>` +
      `</tbody></table>`;
  }
  // Required return lives in its own always-visible solver card.
  $("#scenarios").innerHTML = html;
  renderRequiredReturn(data);
}

const SERIES_COLS = [
  { key: "year_index", label: "Year", fmt: (y) => y.year_index },
  { key: "age", label: "Age", fmt: (y) => y.age },
  { key: "salary", label: "Salary", fmt: (y) => money(y.tax.salary) },
  { key: "filing_status", label: "Filing", fmt: (y) => y.tax.filing_status },
  { key: "method", label: "Roth method", fmt: (y) => y.tax.contribution_method },
  { key: "ira_limit", label: "IRA limit", fmt: (y) => money(y.ira_limit) },
  { key: "contribution", label: "Contribution", fmt: (y) => money(y.contribution) },
  { key: "bal_annual", label: "Bal. annual", fmt: (y) => money(y.ending_balance_annual) },
  { key: "bal_periodic", label: "Bal. periodic", fmt: (y) => money(y.ending_balance_periodic) },
  { key: "bal_real", label: "Bal. real", fmt: (y) => money(y.ending_balance_real_periodic) },
  { key: "gm", label: "Growth mult.", fmt: (y) => y.growth_multiple.toFixed(4) },
  { key: "doublings", label: "Cumul. doublings", fmt: (y) => y.cumulative_doublings ?? 0 },
  { key: "tv", label: "Terminal value", fmt: (y) => money(y.terminal_value) },
  { key: "fed", label: "Federal tax", fmt: (y) => moneyTax(y.tax.federal_income_tax) },
  { key: "oasdi", label: "OASDI", fmt: (y) => moneyTax(y.tax.oasdi_tax) },
  { key: "medicare", label: "Medicare", fmt: (y) => moneyTax(y.tax.medicare_tax + y.tax.additional_medicare_tax) },
  { key: "state", label: "State tax", fmt: (y) => moneyTax(y.tax.state_tax) },
  { key: "total_tax", label: "Total tax", fmt: (y) => moneyTax(y.tax.total_tax) },
];

function renderSeriesTable(data) {
  const thead = $("#seriesTable thead");
  const tbody = $("#seriesTable tbody");
  thead.innerHTML =
    `<tr>${SERIES_COLS.map((c) => `<th>${c.label}</th>`).join("")}</tr>`;
  tbody.innerHTML = data.years
    .map((y) => {
      const methodClass =
        y.tax.contribution_method === "Backdoor" ? "method-backdoor" : "method-direct";
      return (
        `<tr>` +
        SERIES_COLS.map((c) => {
          const val = c.fmt(y);
          if (c.key === "method") {
            return `<td class="${methodClass}">${val}</td>`;
          }
          if (c.key === "contribution" && y.contribution_capped_by_income) {
            return `<td class="contrib-capped" title="Limited by earned income (IRC §219)">${val} <span class="capped-flag">income cap</span></td>`;
          }
          return `<td>${val}</td>`;
        }).join("") +
        `</tr>`
      );
    })
    .join("");
}

function csvEscape(v) {
  const s = String(v);
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function exportCsv() {
  if (!latestData) return;
  const headers = [
    "year_index",
    "age",
    "salary",
    "filing_status",
    "contribution_method",
    "ira_limit",
    "contribution",
    "contribution_capped_by_income",
    "ending_balance_annual",
    "ending_balance_periodic",
    "ending_balance_real_periodic",
    "growth_multiple",
    "cumulative_doublings",
    "terminal_value",
    "federal_income_tax",
    "oasdi_tax",
    "medicare_tax",
    "additional_medicare_tax",
    "state_tax",
    "total_tax",
  ];
  const lines = [headers.join(",")];
  for (const y of latestData.years) {
    lines.push(
      [
        y.year_index,
        y.age,
        y.tax.salary,
        y.tax.filing_status,
        y.tax.contribution_method,
        y.ira_limit,
        y.contribution,
        y.contribution_capped_by_income ? "true" : "false",
        y.ending_balance_annual,
        y.ending_balance_periodic,
        y.ending_balance_real_periodic,
        y.growth_multiple,
        y.cumulative_doublings ?? 0,
        y.terminal_value,
        y.tax.federal_income_tax,
        y.tax.oasdi_tax,
        y.tax.medicare_tax,
        y.tax.additional_medicare_tax,
        y.tax.state_tax,
        y.tax.total_tax,
      ]
        .map(csvEscape)
        .join(",")
    );
  }
  // Summary footer rows for Excel side-by-side checks
  lines.push("");
  lines.push(`seed_balance,${latestData.seed_balance}`);
  lines.push(`seed_terminal_value,${latestData.seed_terminal_value}`);
  lines.push(`final_balance_periodic,${latestData.final_balance_periodic}`);
  lines.push(`final_balance_annual,${latestData.final_balance_annual}`);
  lines.push(`final_balance_real_periodic,${latestData.final_balance_real_periodic}`);
  lines.push(`total_contributions,${latestData.total_contributions}`);
  lines.push(`total_tax,${latestData.total_tax}`);

  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "roth_ira_timeseries.csv";
  a.click();
  URL.revokeObjectURL(url);
}

function renderAssumptions(data) {
  $("#assumptions").innerHTML = data.assumptions_notes.map((n) => `<li>${n}</li>`).join("");
}

async function recalculate() {
  toggleVisibility();
  if (!validateSalaryCap()) {
    setStatus("Error: salary cap must be ≥ starting salary", "err");
    return;
  }
  const constraintErr = formatConstraintErrors();
  if (constraintErr) {
    setStatus(`Error: ${constraintErr}`, "err");
    return;
  }
  setStatus("Calculating…");
  try {
    const payload = readPayload();
    const res = await fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatApiError(err, res.statusText || undefined));
    }
    const data = await res.json();
    latestData = data;
    renderSummary(data);
    renderCharts(data);
    renderMilestones(data);
    renderScenarios(data);
    renderTaxSummaryAndAllocation(data);
    renderSeriesTable(data);
    renderAssumptions(data);
    setStatus(
      data.vintage_cross_check_ok
        ? "Updated · vintage check passed"
        : "Updated · vintage check failed",
      data.vintage_cross_check_ok ? "ok" : "err"
    );
  } catch (e) {
    setStatus(`Error: ${e.message}`, "err");
  }
}

function scheduleRecalc() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(recalculate, 300);
}

/** Remount charts after a previously-hidden layout becomes visible.
 *  Destroy/recreate only the charts that need a fresh size read —
 *  never .resize(), and never remount unrelated siblings. */
function remountChartsForVisibility(scope = "all") {
  if (!latestData) return;
  if (scope === "all" || scope === "primary") {
    renderPrimaryCharts(latestData);
  }
  if (scope === "all" || scope === "tax") {
    renderTaxDetailCharts(latestData);
    renderTaxSummaryAndAllocation(latestData);
  }
}

function setPanelVisible(panel, show) {
  panel.classList.toggle("hidden", !show);
  if (show) panel.removeAttribute("hidden");
  else panel.setAttribute("hidden", "");
}

function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    const active = btn.dataset.tab === tabId;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".input-panel, .output-panel").forEach((panel) => {
    setPanelVisible(panel, panel.dataset.tab === tabId);
  });
  if (tabId === "main") {
    // Tab was display:none — remount visible chart sections only after layout.
    requestAnimationFrame(() => remountChartsForVisibility("all"));
  }
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// Native <details> already keeps open/closed state local per section.
// Only remount charts when THAT section (and it contains charts) opens.
document.querySelectorAll(".extra-detail").forEach((section) => {
  section.addEventListener("toggle", () => {
    if (!section.open) return;
    const scope = section.dataset.chartSection;
    if (!scope) return; // milestones / series / scenarios / solver — no charts
    requestAnimationFrame(() => remountChartsForVisibility(scope));
  });
});

function whenLayoutReady() {
  const fontsReady =
    document.fonts && document.fonts.ready
      ? document.fonts.ready.catch(() => undefined)
      : Promise.resolve();
  const nextPaint = new Promise((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(resolve))
  );
  return Promise.all([fontsReady, nextPaint]);
}

async function boot() {
  chartDefaults();
  form.addEventListener("input", scheduleRecalc);
  form.addEventListener("change", scheduleRecalc);
  // Apply deferred min/invalid styling after the user leaves the field —
  // recalc deliberately skips mutating the focused control.
  form.addEventListener("blur", (e) => {
    if (!(e.target instanceof HTMLInputElement)) return;
    if (e.target.name === "salary_cap" || e.target.name === "starting_salary") {
      validateSalaryCap();
    }
  }, true);
  $("#exportCsv").addEventListener("click", exportCsv);
  document.querySelectorAll("[data-balance-scale]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = btn.dataset.balanceScale;
      if (!next || next === balanceYScale) return;
      balanceYScale = next;
      syncBalanceScaleToggle();
      if (latestData) requestAnimationFrame(() => renderPrimaryCharts(latestData));
    });
  });
  syncBalanceScaleToggle();
  toggleVisibility();
  // Wait for fonts + a settled layout/paint before the first chart create.
  await whenLayoutReady();
  await recalculate();
}

boot();
