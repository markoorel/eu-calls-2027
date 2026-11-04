"use strict";

// Data locations: calls.json next to the page when deployed; ../data/calls.json
// when the repository root is served locally.
const DATA_URLS = ["calls.json", "../data/calls.json"];
const CHECK = "check portal";
const STALE_AFTER_DAYS = 3;
const SHORTLIST_KEY = "eu-calls-2027-shortlist";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];
const ERC_DOMAIN_NAMES = { SH: "Social sciences and humanities", PE: "Physical sciences and engineering", LS: "Life sciences" };
const SCHEME_BADGES = {
  individual: "You can apply alone",
  consortium: "Consortium needed",
  either: "One organisation or a consortium",
};
const SCHEME_LABELS = {
  individual: "Individual application",
  consortium: "Consortium needed",
  either: "One organisation alone, or a consortium",
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

const state = {
  data: null,
  calls: [],
  byId: {},
  guide: { who: "", want: "", stage: "" },
  profiles: {},
  shortlist: [],
};
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------ helpers

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

// Deadlines a new applicant has to meet: the first-stage deadline for
// two-stage calls, every cut-off otherwise.
function relevantDeadlines(call) {
  return call.stages === 2 ? [call.deadlines[0]] : call.deadlines;
}

function upcomingDeadlines(call) {
  const today = todayUtc();
  return call.deadlines.filter((d) => parseDate(d) >= today);
}

function nextDeadline(call) {
  if (call.stages === 2) return call.deadlines[0];
  return upcomingDeadlines(call)[0] || call.deadlines[0];
}

function isOpenNow(call) {
  if (!call.opening_date) return call.status === "open";
  return parseDate(call.opening_date) <= todayUtc();
}

function fillSelect(select, values, labelFn = (v) => v) {
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labelFn(value);
    select.appendChild(option);
  }
}

// ------------------------------------------------------------ shortlist (this browser only)

function loadShortlist() {
  try {
    const stored = JSON.parse(localStorage.getItem(SHORTLIST_KEY) || "[]");
    return Array.isArray(stored) ? stored.filter((x) => typeof x === "string") : [];
  } catch (_) {
    return [];
  }
}

function saveShortlist() {
  try {
    localStorage.setItem(SHORTLIST_KEY, JSON.stringify(state.shortlist));
    return true;
  } catch (_) {
    return false;
  }
}

function isStarred(id) {
  return state.shortlist.includes(id);
}

function toggleStar(id) {
  state.shortlist = isStarred(id) ? state.shortlist.filter((x) => x !== id) : [...state.shortlist, id];
  const saved = saveShortlist();
  renderShortlist(saved ? "" : "Your browser is not saving data, so the shortlist will be lost when you close this page.");
  for (const button of document.querySelectorAll(`.star[data-id="${CSS.escape(id)}"]`)) updateStarButton(button);
}

function updateStarButton(button) {
  const on = isStarred(button.dataset.id);
  button.setAttribute("aria-pressed", on ? "true" : "false");
  button.querySelector(".star-icon").textContent = on ? "★" : "☆";
  button.querySelector(".star-text").textContent = on ? "On shortlist" : "Add to shortlist";
}

function shortlistCalls() {
  return state.shortlist.map((id) => state.byId[id] || { identifier: id, missing: true });
}

function renderShortlist(message = "") {
  const items = shortlistCalls();
  $("shortlistSummary").textContent = `Your shortlist (${items.length})`;
  $("shortlistEmpty").hidden = items.length > 0;
  $("shortlistActions").hidden = items.length === 0;
  $("shortlistItems").innerHTML = items.map((c) => c.missing
    ? `<li>${escapeHtml(c.identifier)} <span class="hint">(no longer listed; it may have closed)</span>
        <button type="button" class="link-button" data-remove="${escapeHtml(c.identifier)}">Remove</button></li>`
    : `<li><a href="${escapeHtml(c.portal_url)}" rel="noopener">${escapeHtml(c.title || c.identifier)}</a>
        <span class="hint">${escapeHtml(c.identifier)} · deadline ${escapeHtml(formatDate(nextDeadline(c)))}</span>
        <button type="button" class="link-button" data-remove="${escapeHtml(c.identifier)}">Remove</button></li>`).join("");
  $("shortlistStatus").textContent = message;
}

function shortlistText() {
  return shortlistCalls().filter((c) => !c.missing).map((c) =>
    `${c.title || c.identifier}\n${c.identifier} | deadline ${formatDate(nextDeadline(c))} | ${SCHEME_LABELS[c.scheme] || "who applies: check portal"}\n${c.portal_url}`
  ).join("\n\n");
}

function csvCell(value) {
  const text = value == null ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function shortlistCsv() {
  const header = ["identifier", "title", "programme", "part_of_programme", "deadlines", "two_stage",
    "who_applies", "budget_min_eur", "budget_max_eur", "portal_url"];
  const rows = shortlistCalls().filter((c) => !c.missing).map((c) => [
    c.identifier, c.title, c.programme, c.pillar_or_cluster, c.deadlines.join("; "), c.stages === 2 ? "yes" : "no",
    c.scheme || CHECK, c.budget_per_project_eur ? c.budget_per_project_eur.min : "",
    c.budget_per_project_eur ? c.budget_per_project_eur.max : "", c.portal_url,
  ]);
  return "﻿" + [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

async function copyShortlist() {
  const text = shortlistText();
  try {
    await navigator.clipboard.writeText(text);
    $("shortlistStatus").textContent = "Copied. Paste it into an email or a document.";
  } catch (_) {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
    area.remove();
    $("shortlistStatus").textContent = ok ? "Copied. Paste it into an email or a document."
      : "Your browser blocked copying. Use “Download as CSV” instead.";
  }
}

function downloadShortlist() {
  const blob = new Blob([shortlistCsv()], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "eu-calls-2027-shortlist.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  $("shortlistStatus").textContent = "Downloaded eu-calls-2027-shortlist.csv.";
}

function setupShortlist() {
  state.shortlist = loadShortlist();
  renderShortlist();
  $("copyList").addEventListener("click", copyShortlist);
  $("downloadCsv").addEventListener("click", downloadShortlist);
  $("clearList").addEventListener("click", () => {
    state.shortlist = [];
    saveShortlist();
    renderShortlist("Shortlist cleared.");
    for (const button of document.querySelectorAll(".star")) updateStarButton(button);
  });
  $("shortlistItems").addEventListener("click", (e) => {
    const button = e.target.closest("[data-remove]");
    if (button) toggleStar(button.dataset.remove);
  });
  $("groups").addEventListener("click", (e) => {
    const button = e.target.closest(".star");
    if (button) toggleStar(button.dataset.id);
  });
}

// ------------------------------------------------------------ glossary

function openGlossary(targetId) {
  const drawer = $("glossary");
  drawer.open = true;
  const target = targetId ? $(targetId) : drawer.querySelector("summary");
  if (target) {
    target.scrollIntoView({ block: "center" });
    target.focus({ preventScroll: true });
  }
}

function setupGlossary() {
  document.addEventListener("click", (e) => {
    const link = e.target.closest("a.gloss");
    if (!link) return;
    e.preventDefault();
    openGlossary(link.getAttribute("href").slice(1));
  });
}

function glossaryLink(term, text) {
  return `<a class="gloss" href="#g-${term}">${text}</a>`;
}

function actionTerm(typeOfAction) {
  const t = typeOfAction || "";
  if (/Research and Innovation Action/i.test(t)) return "ria";
  if (/Coordination and Support Action/i.test(t)) return "csa";
  if (/Innovation Action/i.test(t)) return "ia";
  return null;
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
  for (const d of guide.departments || []) state.profiles[`dept:${d.id}`] = { ...d, kind: "department" };
  for (const t of guide.topics || []) state.profiles[`topic:${t.id}`] = { ...t, kind: "topic" };

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
    button.addEventListener("click", () => clearAnswer(button.dataset.clear, true));
  }
  $("startAgain").addEventListener("click", (e) => {
    e.preventDefault();
    form.reset();
    $("filters").reset();
    setTimeout(() => { refreshClusterOptions(); onGuideChange(); window.scrollTo({ top: 0 }); }, 0);
  });
  syncGuide();
}

function clearAnswer(name, focus) {
  const form = $("guideForm");
  for (const input of form.querySelectorAll(`input[name="${name}"]`)) input.checked = false;
  onGuideChange();
  if (focus) {
    const first = form.querySelector(`input[name="${name}"]`);
    if (first) first.focus();
  }
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

function currentProfile() {
  const who = state.guide.who;
  return who && who !== "other" ? state.profiles[who] : null;
}

function careerScheme(call) {
  const career = state.data.guide && state.data.guide.career;
  if (!career) return null;
  return career.schemes.find((s) => new RegExp(s.pattern, "i").test(call.identifier)) || null;
}

// ------------------------------------------------------------ advanced filters

function setupFilters() {
  const calls = state.calls;
  fillSelect($("programme"), state.data.programmes || [...new Set(calls.map((c) => c.programme))].sort());
  refreshClusterOptions();

  const panels = [...new Set(calls.flatMap((c) => c.erc_panels || []))];
  const domainsPresent = new Set(calls.flatMap((c) => c.erc_domains || []));
  const allPanels = [];
  const counts = { SH: 8, PE: 11, LS: 9 };
  for (const domain of ["SH", "PE", "LS"]) {
    if (!domainsPresent.has(domain)) continue;
    for (let i = 1; i <= counts[domain]; i++) allPanels.push(domain + i);
  }
  fillSelect($("panel"), allPanels);
  // Panels are not shown until tags.csv gives calls their panels.
  $("panelField").hidden = panels.length === 0;

  const months = new Set();
  for (const call of calls) {
    for (const d of relevantDeadlines(call)) {
      if (d.startsWith(String(state.data.target_year))) months.add(Number(d.slice(5, 7)));
    }
  }
  fillSelect($("month"), [...months].sort((a, b) => a - b).map(String),
    (m) => `${MONTHS[m - 1]} ${state.data.target_year}`);

  readFiltersFromUrl();
  const form = $("filters");
  if (advancedActiveCount(getFilters()) > 0) $("filterBox").open = true;
  form.addEventListener("input", onChange);
  form.addEventListener("change", onChange);
  form.addEventListener("submit", (e) => e.preventDefault());
  form.addEventListener("reset", () => setTimeout(() => { refreshClusterOptions(); onChange(); }, 0));
}

// The month also has its own strip above the results, so it is not counted
// as an "advanced" filter.
function advancedActiveCount(f) {
  return Object.entries(f).filter(([k, v]) => v && k !== "month").length;
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

function matches(call, f, ignoreMonth = false) {
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
    const domainWide = panels.length === 0 && domains.includes(f.panel.slice(0, 2));
    if (!panels.includes(f.panel) && !domainWide) return false;
  }
  if (f.scheme === "alone" && !(call.scheme === "individual" || call.scheme === "either")) return false;
  if (f.scheme === "consortium" && call.scheme !== "consortium") return false;
  if (f.month && !ignoreMonth) {
    const prefix = `${state.data.target_year}-${f.month.padStart(2, "0")}`;
    if (!relevantDeadlines(call).some((d) => d.startsWith(prefix))) return false;
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
  const active = advancedActiveCount(f);
  document.querySelector("#filterBox > summary").textContent = active ? `Advanced filters (${active} active)` : "Advanced filters";
  render(f);
}

// ------------------------------------------------------------ month strip

function renderMonths(f, callsWithoutMonth) {
  const year = String(state.data.target_year);
  const counts = new Array(12).fill(0);
  for (const call of callsWithoutMonth) {
    const months = new Set(relevantDeadlines(call).filter((d) => d.startsWith(year)).map((d) => Number(d.slice(5, 7))));
    for (const m of months) counts[m - 1] += 1;
  }
  const max = Math.max(1, ...counts);
  $("months").innerHTML = counts.map((n, i) => {
    const m = String(i + 1);
    const selected = f.month === m;
    const label = `${MONTHS[i]}: ${n} deadline${n === 1 ? "" : "s"}`;
    return `<button type="button" class="month${selected ? " selected" : ""}" data-month="${m}"
      aria-pressed="${selected}" aria-label="${label}" ${n === 0 ? "disabled" : ""}>
      <span class="month-bar" aria-hidden="true"><span style="height:${Math.round((n / max) * 100)}%"></span></span>
      <span class="month-name" aria-hidden="true">${MONTHS[i].slice(0, 3)}</span>
      <span class="month-count" aria-hidden="true">${n}</span></button>`;
  }).join("");
}

function setupMonths() {
  $("months").addEventListener("click", (e) => {
    const button = e.target.closest("button.month");
    if (!button || button.disabled) return;
    const select = $("month");
    const value = select.value === button.dataset.month ? "" : button.dataset.month;
    if (value && ![...select.options].some((o) => o.value === value)) return;
    select.value = value;
    onChange();
    const again = $("months").querySelector(`[data-month="${button.dataset.month}"]`);
    if (again) again.focus();
  });
}

// ------------------------------------------------------------ results

function badgesHtml(call) {
  const badges = [];
  badges.push(escapeHtml(call.scheme ? SCHEME_BADGES[call.scheme] : "Who applies: check portal"));
  const days = daysBetween(todayUtc(), parseDate(nextDeadline(call)));
  if (days === 0) badges.push("Deadline today");
  else if (days > 0) badges.push(`${days} day${days === 1 ? "" : "s"} left${call.stages === 2 ? " for stage 1" : ""}`);
  if (call.stages === 2) badges.push(glossaryLink("two-stage", "Two-stage"));
  if (call.budget_per_project_eur) badges.push(escapeHtml(`${formatBudget(call.budget_per_project_eur)} per project`));
  badges.push(escapeHtml(isOpenNow(call) ? "Open now"
    : call.opening_date ? `Opens ${formatDate(call.opening_date)}` : "Opening date: check portal"));
  return `<ul class="badges">${badges.map((b, i) => `<li class="badge${i === 0 ? " badge-scheme" : ""}">${b}</li>`).join("")}</ul>`;
}

function whyHtml(call) {
  const reasons = [];
  if (call.open_to_all_fields) reasons.push(`Open to all fields (${escapeHtml(call.open_to_all_fields)}).`);
  const profile = currentProfile();
  const fit = profile && call.fits && call.fits[profile.id];
  if (fit && fit.terms.length) {
    const whose = profile.kind === "department" ? "your department's terms" : `terms for ${profile.name}`;
    reasons.push(`Matches ${escapeHtml(whose)}: ${fit.terms.map(escapeHtml).join(", ")}.`);
  }
  if (!reasons.length) return "";
  return `<p class="why"><strong>Why this may fit you:</strong> ${reasons.join(" ")}</p>`;
}

function careerHtml(call) {
  const stage = state.guide.stage;
  const scheme = stage && careerScheme(call);
  const label = scheme && scheme.labels[stage];
  if (!label) return "";
  const verdict = FIT_LABELS[label.fit]
    ? `<strong class="fit fit-${label.fit}">${FIT_LABELS[label.fit]}.</strong> ` : "";
  return `<p class="career">${verdict}${escapeHtml(label.text)}
    <span class="sub">Rule: ${escapeHtml(scheme.rule)} <a href="${escapeHtml(scheme.source_url)}" rel="noopener">${escapeHtml(scheme.source_label)}</a></span></p>`;
}

function deadlineHtml(call) {
  if (!call.deadlines.length) return CHECK;
  if (call.stages === 2 && call.deadlines.length >= 2) {
    return `Stage 1: ${formatDate(call.deadlines[0])}<br>Stage 2: ${formatDate(call.deadlines[1])}`;
  }
  const upcoming = upcomingDeadlines(call);
  if (upcoming.length > 1) return `${upcoming.length} cut-off dates: ` + upcoming.map(formatDate).join(", ");
  return formatDate(nextDeadline(call));
}

function disciplineHtml(call) {
  const parts = [];
  if (call.erc_panels && call.erc_panels.length) parts.push("ERC panels " + call.erc_panels.join(", "));
  else if (call.erc_domains && call.erc_domains.length) {
    parts.push(call.erc_domains.length === 3 ? "All fields" : call.erc_domains.map((d) => ERC_DOMAIN_NAMES[d] || d).join(", "));
  }
  if (call.ssh_flag === true && !(call.erc_domains || []).includes("SH")) parts.push("open to social sciences and humanities");
  if (call.ssh_flag === false) parts.push("not aimed at social sciences and humanities");
  if (!parts.length) return "Not tagged yet";
  let text = escapeHtml(parts.join("; "));
  text += call.tag_status === "reviewed" ? " (checked by a person)" : " (suggested automatically)";
  if (call.tag_note) text += `<span class="sub">${escapeHtml(call.tag_note)}</span>`;
  return text;
}

function row(label, html) {
  return `<div class="row"><dt>${label}</dt><dd>${html}</dd></div>`;
}

function callHtml(call) {
  const term = actionTerm(call.type_of_action);
  const action = call.type_of_action
    ? escapeHtml(call.type_of_action) + (term ? ` ${glossaryLink(term, "What is this?")}` : "")
    : CHECK;
  const scheme = call.scheme
    ? escapeHtml(SCHEME_LABELS[call.scheme]) + (call.scheme_basis ? `<span class="sub">${escapeHtml(call.scheme_basis)}</span>` : "")
    : CHECK;
  const part = call.pillar_or_cluster
    ? escapeHtml(call.pillar_or_cluster) + (/^Cluster /.test(call.pillar_or_cluster) ? ` ${glossaryLink("cluster", "What is a cluster?")}` : "")
    : "";
  const meta = [call.identifier, call.programme, call.pillar_or_cluster].filter(Boolean).map(escapeHtml).join(" · ");
  const title = escapeHtml(call.title || call.identifier);
  const starred = isStarred(call.identifier);
  return `<li class="call">
    <div class="call-top">
      <h3 class="call-title">${title}</h3>
      <button type="button" class="star" data-id="${escapeHtml(call.identifier)}" aria-pressed="${starred}">
        <span class="star-icon" aria-hidden="true">${starred ? "★" : "☆"}</span>
        <span class="star-text">${starred ? "On shortlist" : "Add to shortlist"}</span></button>
    </div>
    ${badgesHtml(call)}
    ${whyHtml(call)}
    ${careerHtml(call)}
    <p class="meta">${meta}</p>
    <details class="more">
      <summary>Details<span class="visually-hidden">: ${title}</span></summary>
      <dl>
        ${row("Deadline", deadlineHtml(call))}
        ${row("Opens", formatDate(call.opening_date))}
        ${row("Who applies", scheme)}
        ${row("Budget per project", escapeHtml(formatBudget(call.budget_per_project_eur)))}
        ${row("Type of action", action)}
        ${part ? row("Part of the programme", part) : ""}
        ${row("Disciplines", disciplineHtml(call))}
        ${row("Last checked", escapeHtml(formatDate(call.last_checked)))}
      </dl>
    </details>
    <p class="call-actions"><a class="button" href="${escapeHtml(call.portal_url)}" rel="noopener">View on the EU portal<span class="visually-hidden">: ${title}</span></a></p>
  </li>`;
}

function groupHtml(title, intro, calls) {
  if (!calls.length) return "";
  return `<section class="group">
    <h2 class="group-title">${escapeHtml(title)} <span class="group-count">(${calls.length})</span></h2>
    ${intro ? `<p class="group-intro">${escapeHtml(intro)}</p>` : ""}
    <ol class="calls">${calls.map(callHtml).join("")}</ol>
  </section>`;
}

function emptyActionsHtml(f) {
  const actions = [];
  const profile = currentProfile();
  if (state.guide.who) actions.push(["who", `Remove “${profile ? profile.name : "Another faculty or unit"}”`]);
  const want = WANT_OPTIONS.find((o) => o.id === state.guide.want);
  if (want && want.id !== "all") actions.push(["want", `Remove “${want.title}”`]);
  if (f.month) actions.push(["month", `Show all months, not only ${MONTHS[Number(f.month) - 1]}`]);
  if (advancedActiveCount(f) > 0) actions.push(["advanced", "Clear advanced filters"]);
  return actions.map(([what, text]) => `<button type="button" class="button-secondary" data-relax="${what}">${escapeHtml(text)}</button>`).join(" ");
}

function setupEmptyState() {
  $("emptyActions").addEventListener("click", (e) => {
    const button = e.target.closest("[data-relax]");
    if (!button) return;
    const what = button.dataset.relax;
    if (what === "who" || what === "want") clearAnswer(what, false);
    else if (what === "month") { $("month").value = ""; onChange(); }
    else if (what === "advanced") {
      const month = $("month").value;
      $("filters").reset();
      setTimeout(() => { $("month").value = month; refreshClusterOptions(); onChange(); }, 0);
    }
    $("results").focus();
  });
}

function render(f) {
  const withoutMonth = state.calls.filter((c) => matches(c, f, true));
  const calls = f.month ? withoutMonth.filter((c) => matches(c, f)) : withoutMonth;
  renderMonths(f, withoutMonth);

  const pid = profileId();
  const profile = currentProfile();
  const byDeadline = (a, b) => nextDeadline(a).localeCompare(nextDeadline(b)) || a.identifier.localeCompare(b.identifier);
  const score = (c) => (c.fits && c.fits[pid] ? c.fits[pid].score : 0);
  const openAll = calls.filter((c) => c.open_to_all_fields).sort(byDeadline);
  const rest = calls.filter((c) => !c.open_to_all_fields)
    .sort((a, b) => (pid ? score(b) - score(a) : 0) || byDeadline(a, b));

  const restTitle = !profile ? "All other calls"
    : profile.kind === "department" ? "Calls that match your department" : `Calls that match ${profile.name}`;
  let restIntro = profile ? "Best match first, then soonest deadline." : "Soonest deadline first.";
  if (state.guide.want === "consortium") {
    restIntro += " Looking for a consortium to join? Each topic's page on the EU portal has a “Partner search announcements” section where teams post requests for partners.";
  }
  $("groups").innerHTML =
    groupHtml("Open to all fields", "These schemes accept proposals from any discipline, so they are worth a look whatever your field.", openAll)
    + groupHtml(restTitle, restIntro, rest);

  $("empty").hidden = calls.length > 0;
  if (!calls.length) $("emptyActions").innerHTML = emptyActionsHtml(f);

  const total = state.calls.length;
  const month = f.month ? ` with a deadline in ${MONTHS[Number(f.month) - 1]}` : "";
  $("count").textContent = calls.length === total ? `${total} calls` : `${calls.length} of ${total} calls match your choices${month}`;
  $("jumpLink").textContent = `See the ${calls.length} matching call${calls.length === 1 ? "" : "s"}`;
}

// ------------------------------------------------------------ start-up

function showRefreshed() {
  const iso = state.data.data_refreshed || state.data.generated_at;
  const el = $("refreshed");
  if (!iso) { el.textContent = "Date of last refresh unknown."; return; }
  el.textContent = `Data last refreshed: ${formatDate(iso)}.`;
  $("footerRefreshed").textContent = `Data refreshed nightly. Last refresh: ${formatDate(iso)}.`;
  const age = daysBetween(parseDate(iso), todayUtc());
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
  for (const call of state.calls) state.byId[call.identifier] = call;
  showRefreshed();
  setupFilters();
  setupGuide();
  setupShortlist();
  setupGlossary();
  setupMonths();
  setupEmptyState();
  onChange();
}).catch((err) => {
  console.error(err);
  $("refreshed").textContent = "The call data could not be loaded. Please try again later, or search the Funding & Tenders Portal directly.";
  $("refreshed").classList.add("stale");
});
