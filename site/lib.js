// Shared helpers for the console: DOM building (text only, never innerHTML from data), API calls,
// verdict wording and the runner-name substitution.

export const RUNNER_NAMES = new Set(["eval-operator", "eval-verifier", "eval-runner"]);
export const NDF = "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF";

export function el(tag, attrs = {}, ...children) {
  const n = tag === "svg" || attrs.svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "svg" || v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "text") n.textContent = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) n.append(c instanceof Node ? c : String(c));
  return n;
}

export const s = (tag, attrs = {}, ...children) => el(tag, { ...attrs, svg: true }, ...children);

export class ApiError extends Error {
  constructor(status, body) {
    super(body && body.detail ? `${body.error}: ${body.detail}` : `HTTP ${status}`);
    this.status = status;
    this.body = body || {};
  }
}

export async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, init);
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, body);
  return body;
}

export function errorText(e) {
  if (e instanceof ApiError && e.body.error === "replay") return "Recorded session (replay mode): read-only, nothing was changed.";
  if (e instanceof ApiError && e.body.error === "test_name_on_real_data") return "Refused: the test name is not accepted on real plant data.";
  return e.message || String(e);
}

// Runner names are the benchmark's, never a person.
export const who = (name) => (name === null || name === undefined ? "—" : RUNNER_NAMES.has(name) ? "automated test run" : name);

export function verdictText(v, reasons = []) {
  const why = reasons && reasons.length ? reasons[0] : "see findings";
  if (v === "BLOCKED") return `STOP: ${why}`;
  if (v === "ESCALATED") return `A person needs to look: ${why}`;
  if (v === NDF) return "No discrepancy found, awaiting signature";
  return "Evaluating…";
}

export const verdictClass = (v) => ({ BLOCKED: "v-blocked", ESCALATED: "v-escalated", [NDF]: "v-ndf" })[v] || "v-eval";

// Shape as well as colour: FAIL a filled diamond, UNKNOWN a triangle, PASS a hollow circle.
export const statusMark = (st) => ({ FAIL: "◆ FAIL", UNKNOWN: "▲ UNKNOWN", PASS: "○ PASS" })[st] || "– pending";

export const time = (t) => (t ? new Date(t * 1000).toLocaleTimeString() : "—");
export const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(d));

// ---------- plain names for display only (the log, rules and data keep their ids)
export const PLANT = { p1_grfics: "Chemical reactor (GRFICSv3 simulator, pre-existing)", p2_gasline: "Nitrogen gas line (our simulator)" };
export const plantName = (p) => PLANT[p] || p || "—";
const VALVE = { f1: "Feed 1 valve", f2: "Feed 2 valve", product: "Product valve", purge: "Vent valve", manual_mode: "Manual mode" };
export const valveName = (t) => VALVE[t] || (t ? `${t} valve` : "—");
const STEP = { mode: "Switch the plant to manual", isolate: "Close", vent_open: "Open the vent", vent_close: "Close the vent", hold: "Pressure hold test", final: "Final check" };
export function stepName(x) {
  const targets = (x.targets && x.targets.length ? x.targets : x.target ? [x.target] : []).map(valveName);
  if (x.kind === "isolate") return `Close ${targets.join(" and ")}`;
  if (x.kind === "vent_open" || x.kind === "vent_close") return `${STEP[x.kind]} (${targets.join(", ")})`;
  return STEP[x.kind] || x.kind;
}
const RULE = { "LIVE-VALVE": "Valve vs flow", "LIVE-QUALITY": "Instrument health", "LIVE-HOLD": "Pressure hold", "LIVE-ALIVE": "Instrument responding",
  "LIVE-RELATION": "Instruments agree", "LIVE-UPSTREAM": "Upstream pressure present", "LIVE-CAMERA": "Camera", "PROC-SEQUENCE": "Steps in order",
  "PROC-INDEPENDENCE": "Checked by a second person", "PROC-RESET": "Reopened step re-checked" };
export const ruleName = (r) => RULE[r] || r;
const EPISODE = [["S4-small", "Gas line: pressure crept back during the hold test"], ["S0", "Clean job: every check passes"],
  ["S8", "Feed valve stuck open, but its sensor says closed"], ["S7", "A step was skipped"]];
export const episodeTitle = (sid) => ((EPISODE.find(([k]) => String(sid).startsWith(`${k}_`)) || [])[1]) || sid;
export const VERDICT_WORD = { BLOCKED: "STOP", ESCALATED: "A person needs to look", [NDF]: "No discrepancy found, awaiting signature" };
export const verdictWord = (v) => VERDICT_WORD[v] || "Evaluating…";
export const ASSUMPTION = { "positive isolation upstream assumed": "Assumed: the upstream isolation, outside this simulator, is in place." };

// one plain sentence from a finding's own logged values; anything not recognised keeps its logged message
const tagValve = (tag) => valveName(String(tag).replace(/_(flow|valve_pos|pos)$/, ""));
const num = (v) => { const n = Number(v); return Number.isFinite(n) ? String(Math.round(n * 10) / 10) : v; };
export function headline(f) {
  const m = f.message || "";
  let x;
  if (f.rule_id === "LIVE-VALVE" && (x = m.match(/(\S+?)_flow = ([-\d.]+) while (\S+?)_valve_pos = ([-\d.]+) %/))) {
    return `${tagValve(x[3])} says closed (${num(x[4])}%), but flow is still going through it (${num(x[2])}). Either it's leaking or its sensor is wrong.`;
  }
  if (f.rule_id === "LIVE-CAMERA" && (x = m.match(/camera shows ([-\d.]+) % while the instrument says ([-\d.]+) %.*\((\S+?)\)/))) {
    return `The camera reads ${tagValve(x[3])}'s display at ${num(x[1])}% open. The control system says ${num(x[2])}%.`;
  }
  if (f.status === "PASS") return `${ruleName(f.rule_id)}: no discrepancy.`;
  return `${ruleName(f.rule_id)}: ${m}`;
}
