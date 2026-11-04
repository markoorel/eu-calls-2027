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

const state = { data: null, calls: [] };
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
  const params = new URLSearchParams();
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
  return true;
}

function onChange(event) {
  if (event && event.target && event.target.id === "programme") refreshClusterOptions();
  const f = getFilters();
  writeFiltersToUrl(f);
  const active = Object.values(f).filter(Boolean).length;
  document.querySelector("#filterBox > summary").textContent = active ? `Filters (${active} active)` : "Filters";
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
  const sorted = calls.slice().sort((a, b) => nextDeadline(a).localeCompare(nextDeadline(b)));
  $("calls").innerHTML = sorted.map(callHtml).join("");
  $("empty").hidden = sorted.length > 0;
  const total = state.calls.length;
  $("count").textContent = sorted.length === total
    ? `${total} call${total === 1 ? "" : "s"}, soonest deadline first`
    : `${sorted.length} of ${total} calls match, soonest deadline first`;
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

// On narrow screens start with the filters folded so the calls are visible.
if (window.matchMedia("(max-width: 760px)").matches) $("filterBox").open = false;

load().then((data) => {
  state.data = data;
  state.calls = (data.calls || []).filter((c) => c.deadlines && c.deadlines.length);
  showRefreshed();
  setupFilters();
  onChange();
}).catch(() => {
  $("refreshed").textContent = "The call data could not be loaded. Please try again later, or search the Funding & Tenders Portal directly.";
  $("refreshed").classList.add("stale");
});
