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
export const who = (name) => (name === null || name === undefined ? "—" : RUNNER_NAMES.has(name) ? "test harness" : name);

export function verdictText(v, reasons = []) {
  const why = reasons && reasons.length ? reasons[0] : "see findings";
  if (v === "BLOCKED") return `BLOCKED: ${why}`;
  if (v === "ESCALATED") return `ESCALATED: ${why}`;
  if (v === NDF) return "NO DISCREPANCY FOUND — awaiting sign-off";
  return "Evaluating…";
}

export const verdictClass = (v) => ({ BLOCKED: "v-blocked", ESCALATED: "v-escalated", [NDF]: "v-ndf" })[v] || "v-eval";

// Shape as well as colour: FAIL a filled diamond, UNKNOWN a triangle, PASS a hollow circle.
export const statusMark = (st) => ({ FAIL: "◆ FAIL", UNKNOWN: "▲ UNKNOWN", PASS: "○ PASS" })[st] || "– pending";

export const time = (t) => (t ? new Date(t * 1000).toLocaleTimeString() : "—");
export const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(d));
