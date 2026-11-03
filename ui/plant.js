// Plant view: an SVG laid out from the plant map (nodes, pipes, instruments). Columns are breadth-first
// distance from the first source, so a line reads left to right. Open paths are drawn red AND listed in
// text; the work equipment gets a heavy outline and the word "work"; live valves show command, feedback
// and flow, and an outline plus the word "disagree" when they don't agree.
import { el, s, fmt } from "./lib.js";

const COL = 160, ROW = 120, PAD = 50;
const VALVES = new Set(["valve", "vent", "bleed", "relief"]);
const DISAGREE_PCT = 2; // command vs feedback, % of travel
const FLOW_CUTOFF_PCT = 1; // a closed valve with flow above 1 % of full scale

function layout(map) {
  const adj = new Map(map.nodes.map((n) => [n.id, []]));
  for (const p of map.pipes) { adj.get(p.a).push(p.b); adj.get(p.b).push(p.a); }
  const layer = new Map();
  const seeds = [...map.nodes.filter((n) => n.kind === "source"), ...map.nodes];
  for (const seed of seeds) {
    if (layer.has(seed.id)) continue;
    const base = layer.size ? Math.max(...layer.values()) + 1 : 0;
    layer.set(seed.id, base);
    const queue = [seed.id];
    while (queue.length) {
      const id = queue.shift();
      for (const nb of adj.get(id)) if (!layer.has(nb)) { layer.set(nb, layer.get(id) + 1); queue.push(nb); }
    }
  }
  const rows = new Map(), pos = new Map();
  for (const n of map.nodes) {
    const c = layer.get(n.id), r = rows.get(c) || 0;
    rows.set(c, r + 1);
    pos.set(n.id, { x: PAD + c * COL, y: PAD + r * ROW });
  }
  return { pos, width: PAD * 2 + Math.max(...layer.values()) * COL + 60, height: PAD * 2 + (Math.max(...rows.values()) - 1) * ROW + 60 };
}

// Latest value of each instrument belonging to a valve, by role (command / feedback / flow).
function readings(map, point, live) {
  const out = {};
  for (const i of map.instruments || []) {
    if (i.point === point && live[i.signal_ref] !== undefined) out[i.role] = { tag: i.signal_ref, v: live[i.signal_ref] };
  }
  return out;
}

const pctOfSpan = (v, span) => (span ? (100 * (v - span[0])) / (span[1] - span[0]) : null);

/** opts: {work: node id, paths: [[node ids]], live: {tag: value}, spans: {tag: [lo, hi]}} */
export function plantView(map, opts = {}) {
  const { work = null, paths = [], live = null, spans = {} } = opts;
  const { pos, width, height } = layout(map);
  const red = new Set();
  for (const p of paths) for (let i = 0; i + 1 < p.length; i++) red.add([p[i], p[i + 1]].sort().join("|"));
  const svg = s("svg", { class: "plant", viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": `plant view ${map.plant}` });
  for (const p of map.pipes) {
    const a = pos.get(p.a), b = pos.get(p.b);
    const open = red.has([p.a, p.b].sort().join("|"));
    svg.append(s("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: open ? "pipe open-path" : "pipe", "data-pipe": `${p.a}|${p.b}` }));
  }
  for (const n of map.nodes) {
    const { x, y } = pos.get(n.id);
    const g = s("g", { class: `node k-${n.kind}${n.id === work ? " work" : ""}`, "data-node": n.id });
    const lines = [];
    let disagree = false;
    if (VALVES.has(n.kind)) {
      const r = live ? readings(map, n.id, live) : {};
      const fb = r.feedback ? r.feedback.v : null;
      const shut = fb !== null && fb < 1;
      g.append(s("polygon", { points: `${x - 16},${y - 10} ${x + 16},${y + 10} ${x + 16},${y - 10} ${x - 16},${y + 10}`, class: fb === null ? "valve" : shut ? "valve shut" : "valve opened" }));
      if (r.command) lines.push(`cmd ${fmt(r.command.v, 0)} %`);
      if (r.feedback) lines.push(`fb ${fmt(fb, 0)} % (${shut ? "closed" : "open"})`);
      if (r.flow) {
        const pct = pctOfSpan(r.flow.v, spans[r.flow.tag]);
        lines.push(pct === null ? `flow ${fmt(r.flow.v)} (raw units)` : `flow ${fmt(pct, 2)} % FS`);
        if (shut && pct !== null && pct > FLOW_CUTOFF_PCT) disagree = true;
      }
      if (r.command && r.feedback && Math.abs(r.command.v - fb) > DISAGREE_PCT) disagree = true;
      if (!live && n.normal_state) lines.push(`normally ${n.normal_state}`);
    } else if (n.kind === "source") {
      g.append(s("circle", { cx: x, cy: y, r: 16, class: "box" }));
      lines.push(n.pressure_kpa_abs ? `source ${n.pressure_kpa_abs} kPa abs` : "source");
    } else {
      g.append(s("rect", { x: x - 24, y: y - 16, width: 48, height: 32, rx: n.kind === "vessel" ? 8 : 2, class: "box" }));
      lines.push(n.kind);
    }
    if (live && !VALVES.has(n.kind)) {
      for (const i of map.instruments || []) {
        if (i.at === n.id && !i.point && live[i.signal_ref] !== undefined) {
          const unit = { pressure: "kPa", level: "%", mode: "" }[i.role] ?? "";
          lines.push(i.role === "mode" ? `${i.tag} ${live[i.signal_ref] ? "on" : "off"}` : `${i.tag} ${fmt(live[i.signal_ref])} ${unit}`);
        }
      }
    }
    if (n.id === work) {
      g.append(s("rect", { x: x - 34, y: y - 26, width: 68, height: 52, class: "work-outline" }));
      lines.unshift("work");
    }
    if (disagree) {
      g.append(s("rect", { x: x - 40, y: y - 30, width: 80, height: 60, class: "disagree-outline" }));
      lines.push("disagree");
    }
    g.append(s("text", { x, y: y - (n.id === work ? 32 : 22), class: "id" }, n.id));
    lines.forEach((t, i) => g.append(s("text", { x, y: y + 30 + i * 12, class: t === "disagree" ? "small alarm-text" : "small" }, t)));
    svg.append(g);
  }
  const wrap = el("figure", { class: "plantwrap" }, svg);
  for (const p of paths) wrap.append(el("p", { class: "open-path-text" }, `◆ Open path: ${p.join(" → ")}`));
  return wrap;
}
