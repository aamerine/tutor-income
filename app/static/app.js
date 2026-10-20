"use strict";

// Edits are validated immediately, saved after a short pause, and the save
// response carries a fresh projection that redraws the charts and totals.
const SAVE_DELAY_MS = 300;

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const money2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const pct = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 });
const shortDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const longDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

const $ = (id) => document.getElementById(id);

const state = {
  plan: null,
  projection: null,
  fieldErrors: new Map(), // input key -> message, for values that don't parse
  saveTimer: null,
  inflight: null,
  seq: 0,
  whatifTouched: false,
  charts: {},
};

// ---------- field specs & parsing ----------

const SETTINGS_FIELDS = {
  school_start: { type: "date", required: true, label: "School year start" },
  school_end: { type: "date", required: true, label: "School year end" },
  summer_start: { type: "date", required: true, label: "Summer start" },
  summer_end: { type: "date", required: true, label: "Summer end" },
  monthly_target: { type: "number", min: 0, max: 1000000, label: "Monthly target" },
};
const STUDENT_FIELDS = {
  included: { type: "bool" },
  name: { type: "text", required: true, max: 100, label: "Name" },
  rate: { type: "number", min: 0, max: 10000, label: "Rate" },
  school_hours: { type: "number", min: 0, max: 80, label: "School hrs/wk" },
  summer_hours: { type: "number", min: 0, max: 80, label: "Summer hrs/wk" },
  start: { type: "date", required: true, label: "Start" },
  end: { type: "date", required: false, label: "End" },
};
const BREAK_FIELDS = {
  name: { type: "text", required: true, max: 100, label: "Break name" },
  start: { type: "date", required: true, label: "Break start" },
  end: { type: "date", required: true, label: "Break end" },
  hours_factor: { type: "percent", min: 0, max: 100, label: "% of hours worked" },
};

function parseField(input, spec) {
  const raw = input.value.trim();
  switch (spec.type) {
    case "bool":
      return { ok: true, value: input.checked };
    case "text":
      if (spec.required && !raw) return { ok: false, msg: `${spec.label} is required` };
      if (raw.length > spec.max) return { ok: false, msg: `${spec.label} is too long` };
      return { ok: true, value: raw };
    case "number":
    case "percent": {
      const n = Number(raw);
      if (raw === "" || !Number.isFinite(n)) return { ok: false, msg: `${spec.label} must be a number` };
      if (n < spec.min || n > spec.max) return { ok: false, msg: `${spec.label} must be between ${spec.min} and ${spec.max}` };
      return { ok: true, value: spec.type === "percent" ? n / 100 : n };
    }
    case "date":
      if (!raw) return spec.required ? { ok: false, msg: `${spec.label} is required` } : { ok: true, value: null };
      if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return { ok: false, msg: `${spec.label} is not a valid date` };
      return { ok: true, value: raw };
  }
  throw new Error(`unknown field type ${spec.type}`);
}

function formatField(value, spec) {
  if (spec.type === "percent") return String(Math.round(value * 1000) / 10);
  return value == null ? "" : String(value);
}

const daysBetween = (a, b) => (Date.parse(b) - Date.parse(a)) / 86400000;
// ISO dates parse as UTC midnight, so this never shifts across time zones.
const addDays = (iso, n) => new Date(Date.parse(iso) + n * 86400000).toISOString().slice(0, 10);

// Summer starts the day after school ends; editing either side moves the other.
const LINKED_DATES = {
  school_end: ["summer_start", 1],
  summer_start: ["school_end", -1],
};

// Rules that span two fields. Returns input key -> message.
function crossErrors(plan) {
  const errs = new Map();
  const s = plan.settings;
  if (s.school_end <= s.school_start) errs.set("settings.school_end", "School year end must be after its start");
  if (s.summer_end < s.summer_start) errs.set("settings.summer_end", "Summer end must be on or after summer start");
  else if (daysBetween(s.school_start, s.summer_end) + 1 > 731) errs.set("settings.summer_end", "School year plus summer cannot be longer than two years");
  plan.students.forEach((st) => {
    if (st.end && st.end < st.start) errs.set(`student:${st.id}:end`, `${st.name}: end date is before start date`);
  });
  s.breaks.forEach((b, i) => {
    if (b.end < b.start) errs.set(`break:${i}:end`, `${b.name}: end date is before start date`);
  });
  return errs;
}

// ---------- editing ----------

function onFieldInput(event) {
  const input = event.target;
  const key = input.dataset.key;
  if (!key) return;
  const { kind, id, field } = input.dataset;
  const spec = kind === "settings" ? SETTINGS_FIELDS[field] : kind === "student" ? STUDENT_FIELDS[field] : BREAK_FIELDS[field];
  const result = parseField(input, spec);
  if (!result.ok) {
    state.fieldErrors.set(key, result.msg);
  } else {
    state.fieldErrors.delete(key);
    const target =
      kind === "settings" ? state.plan.settings
      : kind === "student" ? state.plan.students.find((s) => s.id === id)
      : state.plan.settings.breaks[Number(id)];
    target[field] = result.value;
    if (kind === "settings" && LINKED_DATES[field]) {
      const [other, offset] = LINKED_DATES[field];
      state.plan.settings[other] = addDays(result.value, offset);
      state.fieldErrors.delete(`settings.${other}`);
      document.querySelector(`[data-key="settings.${other}"]`).value = state.plan.settings[other];
    }
    if (kind === "student" && field === "included") input.closest("tr").classList.toggle("excluded", !result.value);
  }
  planChanged();
}

function planChanged() {
  const errors = new Map([...crossErrors(state.plan), ...state.fieldErrors]);
  document.querySelectorAll("[data-key]").forEach((el) => {
    if (errors.has(el.dataset.key)) {
      el.setAttribute("aria-invalid", "true");
      el.title = errors.get(el.dataset.key);
    } else {
      el.removeAttribute("aria-invalid");
      el.removeAttribute("title");
    }
  });
  if (errors.size) {
    clearTimeout(state.saveTimer);
    state.saveTimer = null;
    showError([...errors.values()].join(" · "));
    setStatus("Not saved — fix highlighted fields", true);
    return;
  }
  showError(null);
  setStatus("Saving…");
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(save, SAVE_DELAY_MS);
}

async function save() {
  state.saveTimer = null;
  const seq = ++state.seq;
  if (state.inflight) state.inflight.abort();
  const controller = new AbortController();
  state.inflight = controller;
  try {
    const res = await fetch("/api/plan", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.plan),
      signal: controller.signal,
    });
    const body = await res.json();
    if (seq !== state.seq) return; // a newer save superseded this one
    if (!res.ok) {
      showError(describeServerError(body));
      setStatus("Not saved", true);
      return;
    }
    state.projection = body.projection;
    renderProjection();
    setStatus(`Saved ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`);
  } catch (err) {
    if (err.name === "AbortError") return;
    setStatus("Save failed — is the server running?", true);
  } finally {
    if (state.inflight === controller) state.inflight = null;
  }
}

async function flushSave() {
  if (state.saveTimer) {
    clearTimeout(state.saveTimer);
    await save();
  }
}

function describeServerError(body) {
  if (Array.isArray(body?.detail)) {
    return body.detail.map((d) => String(d.msg).replace(/^Value error, /, "")).join(" · ");
  }
  return body?.detail ? String(body.detail) : "The server rejected the change";
}

function setStatus(text, isError = false) {
  const el = $("save-status");
  el.textContent = text;
  el.classList.toggle("error", isError);
  el.classList.toggle("saving", !isError && text.endsWith("…"));
}

function showError(text) {
  const el = $("form-error");
  el.hidden = !text;
  el.textContent = text || "";
}

function newId() {
  if (window.crypto?.randomUUID) return crypto.randomUUID(); // only on https/localhost
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}

function addStudent() {
  const students = state.plan.students;
  const last = students[students.length - 1];
  const student = {
    id: newId(),
    name: `Student ${students.length + 1}`,
    rate: last ? last.rate : 50,
    school_hours: 1,
    summer_hours: 1,
    start: state.plan.settings.school_start,
    end: null,
    included: true,
  };
  students.push(student);
  renderStudents();
  const nameInput = document.querySelector(`[data-key="student:${student.id}:name"]`);
  nameInput.focus();
  nameInput.select();
  planChanged();
}

function addBreak() {
  const start = state.plan.settings.school_start;
  state.plan.settings.breaks.push({ name: "Time off", start, end: start, hours_factor: 0 });
  renderBreaks();
  planChanged();
}

// A delete needs a second click within 3 seconds.
function confirmingDelete(button, onConfirm) {
  button.addEventListener("click", () => {
    if (button.dataset.armed) {
      onConfirm();
      return;
    }
    button.dataset.armed = "1";
    button.textContent = "Delete?";
    setTimeout(() => {
      delete button.dataset.armed;
      button.textContent = "✕";
    }, 3000);
  });
}

// ---------- form rendering ----------

function makeInput(type, key, value, spec, extra = {}) {
  const input = document.createElement("input");
  input.type = type;
  input.dataset.key = key;
  // key is "<kind>:<id>:<field>"; ids may themselves contain ":".
  const first = key.indexOf(":");
  const last = key.lastIndexOf(":");
  input.dataset.kind = key.slice(0, first);
  input.dataset.id = key.slice(first + 1, last);
  input.dataset.field = key.slice(last + 1);
  if (type === "checkbox") input.checked = Boolean(value);
  else input.value = formatField(value, spec);
  Object.assign(input, extra);
  return input;
}

function cell(child, className) {
  const td = document.createElement("td");
  if (className) td.className = className;
  if (child) td.append(child);
  return td;
}

function renderSettings() {
  document.querySelectorAll("[data-path]").forEach((input) => {
    const field = input.dataset.path.split(".")[1];
    input.dataset.key = `settings.${field}`;
    input.dataset.kind = "settings";
    input.dataset.field = field;
    input.value = formatField(state.plan.settings[field], SETTINGS_FIELDS[field]);
  });
}

function renderStudents() {
  const body = $("students-body");
  body.replaceChildren();
  for (const st of state.plan.students) {
    const k = (f) => `student:${st.id}:${f}`;
    const tr = document.createElement("tr");
    tr.dataset.studentId = st.id;
    tr.classList.toggle("excluded", !st.included);
    const del = document.createElement("button");
    del.type = "button";
    del.className = "icon-btn";
    del.textContent = "✕";
    del.setAttribute("aria-label", `Delete ${st.name}`);
    confirmingDelete(del, () => {
      state.plan.students = state.plan.students.filter((s) => s.id !== st.id);
      for (const key of [...state.fieldErrors.keys()]) if (key.startsWith(`student:${st.id}:`)) state.fieldErrors.delete(key);
      renderStudents();
      planChanged();
    });
    tr.append(
      cell(makeInput("checkbox", k("included"), st.included, STUDENT_FIELDS.included, { ariaLabel: "Include in projection" })),
      cell(makeInput("text", k("name"), st.name, STUDENT_FIELDS.name, { ariaLabel: "Name" })),
      cell(makeInput("number", k("rate"), st.rate, STUDENT_FIELDS.rate, { min: 0, step: 5, ariaLabel: "Hourly rate" })),
      cell(makeInput("number", k("school_hours"), st.school_hours, STUDENT_FIELDS.school_hours, { min: 0, step: 0.5, ariaLabel: "School-year hours per week" })),
      cell(makeInput("number", k("summer_hours"), st.summer_hours, STUDENT_FIELDS.summer_hours, { min: 0, step: 0.5, ariaLabel: "Summer hours per week" })),
      cell(makeInput("date", k("start"), st.start, STUDENT_FIELDS.start, { ariaLabel: "Start date" })),
      cell(makeInput("date", k("end"), st.end, STUDENT_FIELDS.end, { ariaLabel: "End date" })),
      cell(null, "num out-hours"),
      cell(null, "num out-revenue"),
      cell(null, "num out-share"),
      cell(del),
    );
    body.append(tr);
  }
  $("students-empty").hidden = state.plan.students.length > 0;
  renderStudentOutputs();
}

function renderBreaks() {
  const body = $("breaks-body");
  body.replaceChildren();
  state.plan.settings.breaks.forEach((b, i) => {
    const k = (f) => `break:${i}:${f}`;
    const tr = document.createElement("tr");
    const del = document.createElement("button");
    del.type = "button";
    del.className = "icon-btn";
    del.textContent = "✕";
    del.setAttribute("aria-label", `Delete ${b.name}`);
    confirmingDelete(del, () => {
      state.plan.settings.breaks.splice(i, 1);
      // Break keys are positional, so drop them all and re-render from state.
      for (const key of [...state.fieldErrors.keys()]) if (key.startsWith("break:")) state.fieldErrors.delete(key);
      renderBreaks();
      planChanged();
    });
    tr.append(
      cell(makeInput("text", k("name"), b.name, BREAK_FIELDS.name, { ariaLabel: "Break name" })),
      cell(makeInput("date", k("start"), b.start, BREAK_FIELDS.start, { ariaLabel: "Break start" })),
      cell(makeInput("date", k("end"), b.end, BREAK_FIELDS.end, { ariaLabel: "Break end" })),
      cell(makeInput("number", k("hours_factor"), b.hours_factor, BREAK_FIELDS.hours_factor, { min: 0, max: 100, step: 5, ariaLabel: "Percent of hours worked" })),
      cell(del),
    );
    body.append(tr);
  });
}

function renderForms() {
  state.fieldErrors.clear();
  renderSettings();
  renderStudents();
  renderBreaks();
}

// ---------- projection rendering ----------

function setTile(id, text) {
  $(id).textContent = text;
}

function setDelta(el, prefix, amount) {
  el.replaceChildren(document.createTextNode(prefix));
  const span = document.createElement("span");
  span.className = amount >= 0 ? "good" : "bad";
  span.textContent = `${amount >= 0 ? "▲" : "▼"} ${money.format(Math.abs(amount))} ${amount >= 0 ? "over" : "under"}`;
  el.append(span);
}

function renderStudentOutputs() {
  const rows = new Map((state.projection?.students || []).map((s) => [s.id, s]));
  document.querySelectorAll("#students-body tr").forEach((tr) => {
    const out = rows.get(tr.dataset.studentId);
    tr.querySelector(".out-hours").textContent = out ? num1.format(out.hours) : "…";
    tr.querySelector(".out-revenue").textContent = out ? money.format(out.revenue) : "…";
    tr.querySelector(".out-share").textContent = out ? pct.format(out.share) : "…";
  });
}

function renderProjection() {
  const p = state.projection;
  const t = p.totals;
  const target = state.plan.settings.monthly_target;

  setTile("t-revenue", money.format(t.revenue));
  setDelta($("t-revenue-sub"), `Target ${money.format(t.target)} · `, t.gap);
  setTile("t-monthly", money.format(t.avg_monthly_revenue));
  setDelta($("t-monthly-sub"), `Target ${money.format(target)} · `, t.avg_monthly_revenue - target);
  setTile("t-hours", num1.format(p.seasons.school.regular_weekly_hours));
  $("t-hours-sub").textContent =
    `Regular summer week ${num1.format(p.seasons.summer.regular_weekly_hours)} · Whole-year average ${num1.format(t.avg_weekly_hours)}`;
  setTile("t-rate", t.effective_rate == null ? "—" : money2.format(t.effective_rate));
  const sr = (r) => (r == null ? "—" : money2.format(r));
  $("t-rate-sub").textContent = `School year ${sr(p.seasons.school.effective_rate)} · Summer ${sr(p.seasons.summer.effective_rate)}`;

  renderJar();
  renderGap();
  renderStudentOutputs();
  renderCharts();
}

function renderJar() {
  const t = state.projection.totals;
  const pctOfTarget = t.target > 0 ? t.revenue / t.target : 0;
  const fill = $("jar-fill");
  fill.style.width = `${Math.min(pctOfTarget, 1) * 100}%`;
  fill.classList.toggle("full", pctOfTarget >= 1);
  $("jar").setAttribute("aria-valuenow", String(Math.round(Math.min(pctOfTarget, 1) * 100)));
  const text = $("jar-text");
  text.replaceChildren();
  const strong = document.createElement("strong");
  strong.textContent = money.format(t.revenue);
  text.append(strong, ` of ${money.format(t.target)} for the year`);
  $("jar-pct").textContent = pctOfTarget >= 1 ? "Target reached! ✿" : `${Math.round(pctOfTarget * 100)}% of the way there`;
}

function greet() {
  const hour = new Date().getHours();
  const part = hour < 5 ? "Hello" : hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  $("greeting").textContent = `${part}, Jessica — here's how your year is growing.`;
}

function renderGap() {
  const p = state.projection;
  const t = p.totals;
  const g = p.gap_analysis;
  const school = p.seasons.school;
  const summer = p.seasons.summer;
  const target = money.format(state.plan.settings.monthly_target);
  const el = $("gap-summary");
  if (!t.hours) {
    el.textContent = "Add your students to see how your year compares to the target.";
  } else {
    // Hours are stated per regular (non-break) week of each season, never averaged
    // over the whole year, because that is how she experiences her workload.
    const needed = [
      [school, "school"],
      [summer, "summer"],
    ]
      .filter(([s]) => s.regular_weekly_hours > 0)
      .map(([s, name]) => `about ${num1.format(s.required_regular_weekly_hours)} hrs in a regular ${name} week (now ${num1.format(s.regular_weekly_hours)})`)
      .join(" and ");
    const rate = money2.format(t.effective_rate);
    const months = `${t.months_below_target} of ${p.months.length} months fall below ${target}.`;
    if (t.gap >= 0) {
      el.textContent =
        `You clear the target by ${money.format(t.gap)} over the year. At your current average rate (${rate}/hr) ` +
        `you could cut back to ${needed} and still average ${target}/month. ${months}`;
    } else {
      el.textContent =
        `You are ${money.format(-t.gap)} short of the target over the year. At your current average rate (${rate}/hr) ` +
        `you would need ${needed}, or an average of ${money2.format(g.required_rate_at_current_hours)}/hr ` +
        `at your current hours. ${months}`;
    }
  }
  if (!state.whatifTouched && school.regular_weekly_hours > 0) {
    $("whatif-hours").value = String(Math.round(school.regular_weekly_hours * 2) / 2);
  }
  renderWhatif();
}

// Rate needed if regular school weeks had `hours`, with breaks and summer as planned.
function requiredRate(projection, hours) {
  const { school, summer } = projection.seasons;
  const totalHours = hours * school.working_weeks + summer.hours;
  return totalHours > 0 ? projection.totals.target / totalHours : null;
}

function renderWhatif() {
  const p = state.projection;
  const hours = Number($("whatif-hours").value);
  $("whatif-hours-out").textContent = num1.format(hours);
  if (!p) return;
  const needed = requiredRate(p, hours);
  const summer = num1.format(p.seasons.summer.regular_weekly_hours);
  const current = p.totals.effective_rate == null ? "" : ` (your current average is ${money2.format(p.totals.effective_rate)}/hr)`;
  $("whatif-result").textContent = needed == null
    ? "…add hours to see the rate you would need."
    : `…with breaks and summer as planned (${summer} hrs/week in summer), you would need to average ` +
      `${money2.format(needed)}/hr to hit ${money.format(state.plan.settings.monthly_target)}/month${current}.`;
}

// ---------- charts ----------

function theme() {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  return {
    school: v("--school"), summer: v("--summer"), text: v("--text"), text2: v("--text-2"), muted: v("--muted"),
    grid: v("--grid"), surface: v("--surface"), border: v("--border"), sans: v("--sans"), serif: v("--serif"),
  };
}

const moneyTick = (v) => (Math.abs(v) >= 1000 ? `$${num1.format(v / 1000)}k` : `$${v}`);

function baseOptions(th) {
  return {
    maintainAspectRatio: false,
    animation: { duration: 250 },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: th.surface, borderColor: th.border, borderWidth: 1, cornerRadius: 12, padding: 12,
        titleColor: th.text, bodyColor: th.text2, footerColor: th.text2,
        titleFont: { family: th.serif, size: 14, weight: "600" }, footerFont: { weight: "normal" },
        boxPadding: 4, usePointStyle: true,
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: th.muted, autoSkip: true, maxRotation: 0 } },
      y: { beginAtZero: true, grid: { color: th.grid }, border: { display: false }, ticks: { color: th.muted } },
    },
  };
}

function buildCharts() {
  Object.values(state.charts).forEach((c) => c.destroy());
  const th = theme();
  Chart.defaults.font.family = th.sans;
  Chart.defaults.font.size = 12;
  const seasonColor = (s) => (s === "school" ? th.school : th.summer);
  const weeks = () => state.projection?.weeks || [];
  const months = () => state.projection?.months || [];

  const monthly = baseOptions(th);
  monthly.scales.x.stacked = true;
  monthly.scales.y.stacked = true;
  monthly.scales.y.ticks.callback = moneyTick;
  monthly.plugins.legend = { display: true, position: "top", align: "start", labels: { color: th.text2, boxWidth: 14, boxHeight: 8, useBorderRadius: true, borderRadius: 4 } };
  monthly.plugins.tooltip.callbacks = {
    label: (ctx) => (ctx.parsed.y ? `${ctx.dataset.label}: ${money.format(ctx.parsed.y)}` : null),
    footer: (items) => {
      const m = months()[items[0].dataIndex];
      if (!m) return "";
      const rate = m.effective_rate == null ? "—" : money2.format(m.effective_rate);
      return [`Total ${money.format(m.revenue)} (${m.gap >= 0 ? "+" : "−"}${money.format(Math.abs(m.gap))} vs target)`, `${num1.format(m.hours)} hrs · ${rate}/hr`];
    },
  };
  state.charts.monthly = new Chart($("chart-monthly"), {
    type: "bar",
    data: {
      labels: [],
      datasets: [
        { label: "School year", data: [], backgroundColor: th.school, stack: "revenue", borderRadius: 6, borderColor: th.surface, borderWidth: { top: 2 }, maxBarThickness: 44 },
        { label: "Summer", data: [], backgroundColor: th.summer, stack: "revenue", borderRadius: 6, borderColor: th.surface, borderWidth: { top: 2 }, maxBarThickness: 44 },
        { type: "line", label: "Target", data: [], stack: "target", borderColor: th.text2, borderDash: [6, 4], borderWidth: 2, pointRadius: 0, stepped: "middle" },
      ],
    },
    options: monthly,
  });

  const weekTooltip = (valueLabel) => ({
    title: (items) => {
      const w = weeks()[items[0].dataIndex];
      return w ? `Week of ${longDate.format(new Date(w.week_start))}` : "";
    },
    label: valueLabel,
    footer: (items) => {
      const w = weeks()[items[0].dataIndex];
      if (!w) return "";
      const lines = [w.season === "school" ? "School year" : "Summer"];
      if (w.breaks.length) lines.push(`Break: ${w.breaks.join(", ")}`);
      if (w.days < 7) lines.push(`Partial week (${w.days} days in plan)`);
      return lines;
    },
  });
  const seasonLine = (key) => ({
    label: key,
    data: [],
    borderWidth: 2.5,
    cubicInterpolationMode: "monotone", // softened curve that never overshoots the data
    fill: "origin",
    pointRadius: 0,
    pointHoverRadius: 6,
    pointHoverBorderColor: th.surface,
    pointHoverBorderWidth: 2,
    pointHoverBackgroundColor: (ctx) => seasonColor(weeks()[ctx.dataIndex]?.season),
    segment: {
      borderColor: (ctx) => seasonColor(weeks()[ctx.p1DataIndex]?.season),
      backgroundColor: (ctx) => `${seasonColor(weeks()[ctx.p1DataIndex]?.season)}26`, // ~15% wash
    },
  });

  const weeklyRev = baseOptions(th);
  weeklyRev.scales.y.ticks.callback = moneyTick;
  weeklyRev.scales.x.ticks.maxTicksLimit = 12;
  weeklyRev.plugins.tooltip.callbacks = weekTooltip((ctx) =>
    ctx.dataset.label === "Target" ? `Target pace: ${money.format(ctx.parsed.y)}` : `Revenue: ${money.format(ctx.parsed.y)}`);
  state.charts.weeklyRevenue = new Chart($("chart-weekly-revenue"), {
    type: "line",
    data: {
      labels: [],
      datasets: [
        seasonLine("Revenue"),
        { label: "Target", data: [], borderColor: th.text2, borderDash: [6, 4], borderWidth: 2, pointRadius: 0, pointHoverRadius: 0 },
      ],
    },
    options: weeklyRev,
  });

  const weeklyHours = baseOptions(th);
  weeklyHours.scales.x.ticks.maxTicksLimit = 12;
  weeklyHours.plugins.tooltip.callbacks = weekTooltip((ctx) => `Hours: ${num1.format(ctx.parsed.y)}`);
  state.charts.weeklyHours = new Chart($("chart-weekly-hours"), {
    type: "line",
    data: { labels: [], datasets: [seasonLine("Hours")] },
    options: weeklyHours,
  });

  const rates = baseOptions(th);
  rates.indexAxis = "y";
  rates.interaction = { mode: "nearest", axis: "y", intersect: false };
  rates.scales = {
    x: { beginAtZero: true, grid: { color: th.grid }, border: { display: false }, ticks: { color: th.muted, callback: moneyTick } },
    y: { grid: { display: false }, ticks: { color: th.text2 } },
  };
  rates.plugins.tooltip.callbacks = {
    label: (ctx) => {
      const r = state.projection.rates[ctx.dataIndex];
      return [
        `Revenue: ${money.format(r.revenue)} (${pct.format(r.share)})`,
        `Hours: ${num1.format(r.hours)}`,
        `${r.students} student${r.students === 1 ? "" : "s"}`,
      ];
    },
  };
  state.charts.rates = new Chart($("chart-rates"), {
    type: "bar",
    data: { labels: [], datasets: [{ label: "Revenue", data: [], backgroundColor: th.school, borderRadius: 999, borderSkipped: false, maxBarThickness: 22 }] },
    options: rates,
  });
}

function renderCharts() {
  const p = state.projection;
  if (!p) return;
  const c = state.charts;

  c.monthly.data.labels = p.months.map((m) => m.label);
  c.monthly.data.datasets[0].data = p.months.map((m) => m.school_revenue);
  c.monthly.data.datasets[1].data = p.months.map((m) => m.summer_revenue);
  c.monthly.data.datasets[2].data = p.months.map((m) => m.target);
  c.monthly.update();

  const weekLabels = p.weeks.map((w) => shortDate.format(new Date(w.week_start)));
  c.weeklyRevenue.data.labels = weekLabels;
  c.weeklyRevenue.data.datasets[0].data = p.weeks.map((w) => w.revenue);
  c.weeklyRevenue.data.datasets[1].data = p.weeks.map((w) => w.target);
  c.weeklyRevenue.update();
  c.weeklyHours.data.labels = weekLabels;
  c.weeklyHours.data.datasets[0].data = p.weeks.map((w) => w.hours);
  c.weeklyHours.update();

  const ratesHeight = `${Math.max(120, p.rates.length * 40 + 50)}px`;
  if ($("rates-box").style.height !== ratesHeight) {
    $("rates-box").style.height = ratesHeight;
    c.rates.resize(); // otherwise the canvas keeps its old size until the next frame
  }
  c.rates.data.labels = p.rates.map((r) => `${money2.format(r.rate).replace(/\.00$/, "")}/hr`);
  c.rates.data.datasets[0].data = p.rates.map((r) => r.revenue);
  c.rates.update();
}

// ---------- backup / restore ----------

async function exportPlan(event) {
  if (!state.saveTimer) return; // nothing pending; let the link download
  event.preventDefault();
  await flushSave();
  window.location.href = "/api/export";
}

async function importPlan(event) {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  let plan;
  try {
    plan = JSON.parse(await file.text());
  } catch {
    showError("That file is not valid JSON.");
    return;
  }
  if (plan && plan.plan) plan = plan.plan; // accept the GET /api/plan shape too
  const res = await fetch("/api/plan", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(plan) });
  const body = await res.json();
  if (!res.ok) {
    showError(`Backup not restored: ${describeServerError(body)}`);
    return;
  }
  state.seq++; // discard any in-flight save of the old plan
  state.plan = body.plan;
  state.projection = body.projection;
  state.whatifTouched = false;
  renderForms();
  showError(null);
  renderProjection();
  setStatus("Backup restored");
}

// ---------- startup ----------

async function init() {
  greet();
  buildCharts();
  // Canvas text doesn't reflow when web fonts arrive, so redraw once they have.
  document.fonts?.ready.then(() => {
    buildCharts();
    renderCharts();
  });
  document.querySelector("main").addEventListener("input", (e) => {
    if (e.target.id === "whatif-hours") {
      state.whatifTouched = true;
      renderWhatif();
    } else {
      onFieldInput(e);
    }
  });
  // Checkboxes and date pickers fire "change" in some browsers without "input".
  document.querySelector("main").addEventListener("change", (e) => {
    if (e.target.type === "checkbox" || e.target.type === "date") onFieldInput(e);
  });
  $("add-student").addEventListener("click", addStudent);
  $("add-break").addEventListener("click", addBreak);
  $("export-btn").addEventListener("click", exportPlan);
  $("import-file").addEventListener("change", importPlan);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    buildCharts();
    renderCharts();
  });
  // Don't lose an edit made just before closing the tab.
  window.addEventListener("pagehide", () => {
    if (!state.saveTimer) return;
    fetch("/api/plan", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.plan), keepalive: true });
  });

  try {
    const res = await fetch("/api/plan");
    const body = await res.json();
    state.plan = body.plan;
    renderForms();
    const proj = await fetch("/api/projection", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.plan) });
    state.projection = await proj.json();
    renderProjection();
    setStatus(body.saved_at ? "All changes saved" : "Defaults — edit to start");
  } catch (err) {
    setStatus("Could not reach the server", true);
    console.error(err);
  }
}

init();
