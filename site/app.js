"use strict";

// Data locations: calls.json next to the page when deployed; ../data/calls.json
// when the repository root is served locally.
const DATA_URLS = ["calls.json", "../data/calls.json"];
const CHECK = "check portal";
const STALE_AFTER_DAYS = 3;

const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];
const ERC_DOMAIN_NAMES = { SH: "Social sciences and humanities", PE: "Physical sciences and engineering", LS: "Life sciences" };
const SCHEME_LABELS = {
  individual: "Individual application",
  consortium: "Consortium needed",
  either: "Alone or in a consortium",
};

// Answers to "What are you looking for?". The ids match the purposes that
// build_calls.py stores on each call.
const WANT_OPTIONS = [
  { id: "own-project", title: "A grant for my own project", desc: "Schemes where one researcher applies with a host institution." },
  { id: "consortium", title: "Joining or building an international consortium", desc: "Projects run by several organisations, usually from different countries." },
  { id: "training", title: "Funding for doctoral training or staff exchanges", desc: "MSCA doctoral networks, COFUND programmes and staff exchanges." },
  { id: "all", title: "Not sure, show me everything", desc: "Keep every type of call in the list." },
];
const FIT_LABELS = { likely: "Likely fits your career stage", check: "Check eligibility" };

const state = { data: null, calls: [], guide: { who: "", want: "", stage: "" }, profiles: {} };
const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function parseDate(iso) {
  // ISO dates are calendar dates; treat them as UTC to avoid time-zone shifts.
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function formatDate(iso) {
  if (!iso) return CHECK;
  return parseDate(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

function formatEuro(n) {
  return "€" + Number(n).toLocaleString("en-GB", { maximumFractionDigits: 0 });
}

function formatBudget(b) {
  if (!b || b.min == null || b.max == null) return CHECK;
  if (b.min === b.max) return formatEuro(b.max);
  if (!b.min) return `up to ${formatEuro(b.max)}`;
  return `${formatEuro(b.min)} to ${formatEuro(b.max)}`;
}

function todayUtc() {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

function daysBetween(a, b) {
  return Math.round((b - a) / 86400000);
}

// Deadlines a new applicant still has to meet. For two-stage calls that is
// the first-stage deadline; for others, every future cut-off.
function upcomingDeadlines(call) {
  const today = todayUtc();
  return call.deadlines.filter((d) => parseDate(d) >= today);
}

function nextDeadline(call) {
  const upcoming = upcomingDeadlines(call);
  if (call.stages === 2) return call.deadlines[0];
  return upcoming[0] || call.deadlines[0];
}

function isOpenNow(call) {
  if (!call.opening_date) return call.status === "open";
  return parseDate(call.opening_date) <= todayUtc();
}

// ------------------------------------------------------------ guided start

function optionHtml(name, value, title, desc) {
  return `<label class="option"><input type="radio" name="${name}" value="${escapeHtml(value)}">
    <span class="option-title">${escapeHtml(title)}</span>${desc ? `<span class="option-desc">${escapeHtml(desc)}</span>` : ""}</label>`;
}

function chipHtml(name, value, title) {
  return `<label class="chip"><input type="radio" name="${name}" value="${escapeHtml(value)}"><span>${escapeHtml(title)}</span></label>`;
}

function setupGuide() {
  const guide = state.data.guide || {};
  for (const d of guide.departments || []) state.profiles[`dept:${d.id}`] = d;
  for (const t of guide.topics || []) state.profiles[`topic:${t.id}`] = t;

  $("whoCards").innerHTML = (guide.departments || []).map((d) => optionHtml("who", `dept:${d.id}`, d.name, d.description)).join("")
    + optionHtml("who", "other", "Another faculty or unit", "Show calls from every field.");
  $("whoChips").innerHTML = (guide.topics || []).map((t) => chipHtml("who", `topic:${t.id}`, t.name)).join("");
  $("topicsLabel").hidden = !(guide.topics || []).length;
  $("wantCards").innerHTML = WANT_OPTIONS.map((o) => optionHtml("want", o.id, o.title, o.desc)).join("");

  const career = guide.career;
  if (career) {
    $("stageHint").textContent = career.question;
    $("stageCards").innerHTML = career.options.map((o) => optionHtml("stage", o.id, o.label, "")).join("");
  } else {
    $("stageCards").closest(".question").hidden = true;
  }

  readGuideFromUrl();
  const form = $("guideForm");
  // Clicking the selected card again clears the answer (each question can be skipped).
  form.addEventListener("mousedown", (e) => {
    const label = e.target.closest("label");
    const input = label && label.querySelector("input[type=radio]");
    if (input) input.dataset.wasChecked = input.checked ? "1" : "";
  });
  form.addEventListener("click", (e) => {
    const input = e.target.closest("input[type=radio]");
    if (!input) return;
    if (input.dataset.wasChecked === "1") input.checked = false;
    input.dataset.wasChecked = "";
    onGuideChange();
  });
  form.addEventListener("change", onGuideChange);
  form.addEventListener("submit", (e) => e.preventDefault());
  for (const button of form.querySelectorAll(".clear-q")) {
    button.addEventListener("click", () => {
      for (const input of form.querySelectorAll(`input[name="${button.dataset.clear}"]`)) input.checked = false;
      onGuideChange();
      const first = form.querySelector(`input[name="${button.dataset.clear}"]`);
      if (first) first.focus();
    });
  }
  $("startAgain").addEventListener("click", (e) => {
    e.preventDefault();
    form.reset();
    $("filters").reset();
    setTimeout(() => { refreshClusterOptions(); onGuideChange(); window.scrollTo({ top: 0 }); }, 0);
  });
  syncGuide();
}

function syncGuide() {
  const form = $("guideForm");
  for (const name of ["who", "want", "stage"]) {
    const checked = form.querySelector(`input[name="${name}"]:checked`);
    state.guide[name] = checked ? checked.value : "";
    form.querySelector(`.clear-q[data-clear="${name}"]`).hidden = !checked;
  }
  for (const label of form.querySelectorAll("label.option, label.chip")) {
    label.classList.toggle("selected", label.querySelector("input").checked);
  }
}

function onGuideChange() {
  syncGuide();
  onChange();
}

function readGuideFromUrl() {
  const params = new URLSearchParams(location.search);
  const form = $("guideForm");
  const values = {
    who: params.get("dept") === "other" ? "other"
      : params.get("dept") ? `dept:${params.get("dept")}`
      : params.get("topic") ? `topic:${params.get("topic")}` : "",
    want: params.get("want") || "",
    stage: params.get("stage") || "",
  };
  for (const [name, value] of Object.entries(values)) {
    if (!value) continue;
    const input = form.querySelector(`input[name="${name}"][value="${CSS.escape(value)}"]`);
    if (input) input.checked = true;
  }
}

function guideParams() {
  const g = state.guide;
  const params = {};
  if (g.who === "other") params.dept = "other";
  else if (g.who.startsWith("dept:")) params.dept = g.who.slice(5);
  else if (g.who.startsWith("topic:")) params.topic = g.who.slice(6);
  if (g.want) params.want = g.want;
  if (g.stage) params.stage = g.stage;
  return params;
}

function profileId() {
  const who = state.guide.who;
  return who && who !== "other" ? who.split(":")[1] : "";
}

function careerScheme(call) {
  const career = state.data.guide && state.data.guide.career;
  if (!career) return null;
  return career.schemes.find((s) => new RegExp(s.pattern, "i").test(call.identifier)) || null;
}

// ------------------------------------------------------------ filters

function fillSelect(select, values, labelFn = (v) => v) {
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labelFn(value);
    select.appendChild(option);
  }
}

function setupFilters() {
  const calls = state.calls;
  fillSelect($("programme"), state.data.programmes || [...new Set(calls.map((c) => c.programme))].sort());
  refreshClusterOptions();

  const panels = [...new Set(calls.flatMap((c) => c.erc_panels || []))];
  const panelOrder = (p) => ["SH", "PE", "LS"].indexOf(p.slice(0, 2)) * 100 + Number(p.slice(2));
  panels.sort((a, b) => panelOrder(a) - panelOrder(b));
  // Offer all panels of any domain that appears, so a domain-wide call can be
  // found from a panel the user knows.
  const domainsPresent = new Set(calls.flatMap((c) => c.erc_domains || []));
  const allPanels = [];
  const counts = { SH: 8, PE: 11, LS: 9 };
  for (const domain of ["SH", "PE", "LS"]) {
    if (!domainsPresent.has(domain)) continue;
    for (let i = 1; i <= counts[domain]; i++) allPanels.push(domain + i);
  }
  fillSelect($("panel"), allPanels.length ? allPanels : panels);
  // Panels are not shown until tags.csv gives calls their panels.
  $("panelField").hidden = panels.length === 0;

  const months = new Set();
  for (const call of calls) {
    for (const d of call.deadlines) {
      if (d.startsWith(String(state.data.target_year))) months.add(Number(d.slice(5, 7)));
    }
  }
  fillSelect($("month"), [...months].sort((a, b) => a - b).map(String),
    (m) => `${MONTHS[m - 1]} ${state.data.target_year}`);

  readFiltersFromUrl();
  const form = $("filters");
  if (Object.values(getFilters()).some(Boolean)) $("filterBox").open = true;
  form.addEventListener("input", onChange);
  form.addEventListener("change", onChange);
  form.addEventListener("submit", (e) => e.preventDefault());
  form.addEventListener("reset", () => setTimeout(() => { refreshClusterOptions(); onChange(); }, 0));
}

function refreshClusterOptions() {
  const select = $("cluster");
  const current = select.value;
  const programme = $("programme").value;
  const clusters = [...new Set(state.calls
    .filter((c) => !programme || c.programme === programme)
    .map((c) => c.pillar_or_cluster)
    .filter(Boolean))].sort();
  select.length = 1;
  fillSelect(select, clusters);
  select.disabled = clusters.length === 0;
  select.value = clusters.includes(current) ? current : "";
}

function getFilters() {
  const form = $("filters");
  return {
    q: form.q.value.trim().toLowerCase(),
    programme: form.programme.value,
    cluster: form.cluster.value,
    discipline: form.discipline.value,
    panel: form.panel.value,
    scheme: form.scheme.value,
    month: form.month.value,
    openOnly: form.openOnly.checked,
  };
}

function readFiltersFromUrl() {
  const params = new URLSearchParams(location.search);
  const form = $("filters");
  if (params.has("q")) form.q.value = params.get("q");
  for (const name of ["programme", "panel", "month"]) {
    const v = params.get(name);
    if (v && [...form[name].options].some((o) => o.value === v)) form[name].value = v;
  }
  refreshClusterOptions();
  const cluster = params.get("cluster");
  if (cluster && [...form.cluster.options].some((o) => o.value === cluster)) form.cluster.value = cluster;
  for (const name of ["discipline", "scheme"]) {
    const v = params.get(name);
    const radio = form.querySelector(`input[name="${name}"][value="${CSS.escape(v || "")}"]`);
    if (radio) radio.checked = true;
  }
  form.openOnly.checked = params.get("open") === "1";
}

function writeFiltersToUrl(f) {
  const params = new URLSearchParams(guideParams());
  for (const key of ["q", "programme", "cluster", "discipline", "panel", "scheme", "month"]) {
    if (f[key]) params.set(key, f[key]);
  }
  if (f.openOnly) params.set("open", "1");
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

function matches(call, f) {
  if (f.programme && call.programme !== f.programme) return false;
  if (f.cluster && call.pillar_or_cluster !== f.cluster) return false;
  if (f.q) {
    const hay = `${call.title || ""} ${call.identifier} ${call.call_identifier || ""}`.toLowerCase();
    if (!f.q.split(/\s+/).every((word) => hay.includes(word))) return false;
  }
  const domains = call.erc_domains || [];
  if (f.discipline === "ssh" && !(call.ssh_flag === true || domains.includes("SH"))) return false;
  if ((f.discipline === "PE" || f.discipline === "LS") && !domains.includes(f.discipline)) return false;
  if (f.panel) {
    const panels = call.erc_panels || [];
    const domain = f.panel.slice(0, 2);
    const domainWide = panels.length === 0 && domains.includes(domain);
    if (!panels.includes(f.panel) && !domainWide) return false;
  }
  if (f.scheme === "alone" && !(call.scheme === "individual" || call.scheme === "either")) return false;
  if (f.scheme === "consortium" && call.scheme !== "consortium") return false;
  if (f.month) {
    const prefix = `${state.data.target_year}-${f.month.padStart(2, "0")}`;
    const relevant = call.stages === 2 ? [call.deadlines[0]] : call.deadlines;
    if (!relevant.some((d) => d.startsWith(prefix))) return false;
  }
  if (f.openOnly && !isOpenNow(call)) return false;

  // Guided start.
  const pid = profileId();
  if (pid && !call.open_to_all_fields && !(call.fits && call.fits[pid])) return false;
  const want = state.guide.want;
  if (want && want !== "all" && !(call.purposes || []).includes(want)) return false;
  return true;
}

function onChange(event) {
  if (event && event.target && event.target.id === "programme") refreshClusterOptions();
  const f = getFilters();
  writeFiltersToUrl(f);
  const active = Object.values(f).filter(Boolean).length;
  document.querySelector("#filterBox > summary").textContent = active ? `Advanced filters (${active} active)` : "Advanced filters";
  render(state.calls.filter((c) => matches(c, f)));
}

// ------------------------------------------------------------ rendering

function deadlineHtml(call) {
  if (!call.deadlines.length) return CHECK;
  if (call.stages === 2 && call.deadlines.length >= 2) {
    return `Stage 1: ${formatDate(call.deadlines[0])}<br>Stage 2: ${formatDate(call.deadlines[1])}`;
  }
  const upcoming = upcomingDeadlines(call);
  if (upcoming.length > 1) {
    return `${upcoming.length} cut-off dates: ` + upcoming.map(formatDate).join(", ");
  }
  return formatDate(nextDeadline(call));
}

function schemeHtml(call) {
  if (!call.scheme) return CHECK;
  const basis = call.scheme_basis ? `<span class="sub">${escapeHtml(call.scheme_basis)}</span>` : "";
  return escapeHtml(SCHEME_LABELS[call.scheme] || call.scheme) + basis;
}

function disciplineHtml(call) {
  const parts = [];
  if (call.erc_panels && call.erc_panels.length) parts.push("ERC panels " + call.erc_panels.join(", "));
  else if (call.erc_domains && call.erc_domains.length) {
    parts.push(call.erc_domains.length === 3 ? "All ERC domains" : call.erc_domains.map((d) => ERC_DOMAIN_NAMES[d] || d).join(", "));
  }
  if (call.ssh_flag === true && !(call.erc_domains || []).includes("SH")) parts.push("open to social sciences and humanities");
  if (call.ssh_flag === false) parts.push("not aimed at social sciences and humanities");
  if (!parts.length) return "Not tagged yet";
  let text = escapeHtml(parts.join("; "));
  const label = call.tag_status === "reviewed" ? "checked" : "suggested";
  text += ` <span class="tag tag-${escapeHtml(call.tag_status)}">${label}</span>`;
  if (call.tag_note) text += `<span class="sub">${escapeHtml(call.tag_note)}</span>`;
  return text;
}

function statusHtml(call) {
  if (isOpenNow(call)) return '<span class="badge badge-open">Open</span>';
  const opens = call.opening_date ? ` – opens ${formatDate(call.opening_date)}` : "";
  return `<span class="badge badge-forthcoming">Forthcoming${escapeHtml(opens)}</span>`;
}

function careerHtml(call) {
  const stage = state.guide.stage;
  const scheme = stage && careerScheme(call);
  const label = scheme && scheme.labels[stage];
  if (!label) return "";
  const verdict = FIT_LABELS[label.fit]
    ? `<span class="fit fit-${label.fit}">${FIT_LABELS[label.fit]}</span> ` : "";
  return `<div class="career">${verdict}${escapeHtml(label.text)}
    <span class="sub">Rule: ${escapeHtml(scheme.rule)} <a href="${escapeHtml(scheme.source_url)}" rel="noopener">${escapeHtml(scheme.source_label)}</a></span></div>`;
}

function row(label, html) {
  return `<div class="row"><dt>${label}</dt><dd>${html}</dd></div>`;
}

function callHtml(call) {
  const where = [call.programme, call.pillar_or_cluster].filter(Boolean).map(escapeHtml).join(" · ");
  const days = daysBetween(todayUtc(), parseDate(nextDeadline(call)));
  const soon = days >= 0 && days <= 30 ? ` <span class="soon">in ${days} day${days === 1 ? "" : "s"}</span>` : "";
  return `<li class="call">
    <div class="call-head">
      <p class="where">${where}</p>
      ${statusHtml(call)}
    </div>
    <h2><a href="${escapeHtml(call.portal_url)}" rel="noopener">${escapeHtml(call.title || call.identifier)}</a></h2>
    <p class="ident">${escapeHtml(call.identifier)}</p>
    ${careerHtml(call)}
    <dl>
      ${row("Deadline", deadlineHtml(call) + soon)}
      ${row("Who applies", schemeHtml(call))}
      ${row("Budget per project", escapeHtml(formatBudget(call.budget_per_project_eur)))}
      ${row("Type of action", call.type_of_action ? escapeHtml(call.type_of_action) : CHECK)}
      ${row("Disciplines", disciplineHtml(call))}
    </dl>
    <p class="portal"><a href="${escapeHtml(call.portal_url)}" rel="noopener">Topic page on the Funding &amp; Tenders Portal</a>
      <span class="checked">Last checked ${escapeHtml(formatDate(call.last_checked))}</span></p>
  </li>`;
}

function render(calls) {
  const pid = profileId();
  const fitScore = (c) => (c.fits && c.fits[pid] ? c.fits[pid].score : 0);
  const sorted = calls.slice().sort((a, b) => {
    if (pid) {
      const open = Number(!a.open_to_all_fields) - Number(!b.open_to_all_fields);
      if (open) return open;
      const score = fitScore(b) - fitScore(a);
      if (score) return score;
    }
    return nextDeadline(a).localeCompare(nextDeadline(b));
  });
  $("calls").innerHTML = sorted.map(callHtml).join("");
  $("empty").hidden = sorted.length > 0;
  const total = state.calls.length;
  const order = pid ? "calls open to all fields first, then best match" : "soonest deadline first";
  $("jumpLink").textContent = `See the ${sorted.length} matching call${sorted.length === 1 ? "" : "s"}`;
  $("count").textContent = sorted.length === total
    ? `${total} call${total === 1 ? "" : "s"}, ${order}`
    : `${sorted.length} of ${total} calls match, ${order}`;
}

function showRefreshed() {
  const iso = state.data.data_refreshed || state.data.generated_at;
  const el = $("refreshed");
  if (!iso) { el.textContent = "Date of last refresh unknown."; return; }
  const refreshed = parseDate(iso);
  el.textContent = `Data last refreshed: ${formatDate(iso)}.`;
  const age = daysBetween(refreshed, todayUtc());
  if (age > STALE_AFTER_DAYS) {
    el.textContent += ` That was ${age} days ago, so some details may be out of date.`;
    el.classList.add("stale");
  }
}

async function load() {
  for (const url of DATA_URLS) {
    try {
      const resp = await fetch(url, { cache: "no-cache" });
      if (resp.ok) return await resp.json();
    } catch (_) { /* try the next location */ }
  }
  throw new Error("calls.json not found");
}

load().then((data) => {
  state.data = data;
  state.calls = (data.calls || []).filter((c) => c.deadlines && c.deadlines.length);
  showRefreshed();
  setupFilters();
  setupGuide();
  onChange();
}).catch(() => {
  $("refreshed").textContent = "The call data could not be loaded. Please try again later, or search the Funding & Tenders Portal directly.";
  $("refreshed").classList.add("stale");
});
