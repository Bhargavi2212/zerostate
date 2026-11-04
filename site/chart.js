// Evidence chart: one measure (one unit, one axis) per chart, inline SVG. ISA-101 greys: series are told
// apart by dash pattern and a legend + end label, never by colour. Vent and hold windows are shaded
// bands with their name written in them. Hover shows a crosshair and the values at that time.
import { el, s, fmt } from "./lib.js";

const W = 560, H = 170, L = 52, R = 90, T = 18, B = 24;
const DASHES = ["", "6 3", "2 3", "10 3 2 3", "1 2"];

/** {title, unit, series: [{name, points: [[t, v]]}], bands: [{t0, t1, label}]} */
export function lineChart({ title, unit, series, bands = [] }) {
  const pts = series.flatMap((x) => x.points);
  const box = el("figure", { class: "chart", "data-chart": title });
  box.append(el("figcaption", {}, `${title} (${unit})`));
  if (!pts.length) {
    box.append(el("p", { class: "muted" }, "No samples yet."));
    return box;
  }
  const ts = pts.map((p) => p[0]).concat(bands.flatMap((b) => [b.t0, b.t1]));
  const t0 = Math.min(...ts), t1 = Math.max(...ts);
  let lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const x = (t) => L + ((t - t0) / (t1 - t0 || 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": `${title} chart` });
  for (const b of bands) {
    svg.append(s("rect", { x: x(b.t0), y: T, width: Math.max(1, x(b.t1) - x(b.t0)), height: H - T - B, class: `band band-${b.label}` }));
    svg.append(s("text", { x: x(b.t0) + 3, y: T + 11, class: "small band-label" }, `${b.label} window`));
  }
  svg.append(s("line", { x1: L, y1: H - B, x2: W - R, y2: H - B, class: "axis" }));
  svg.append(s("line", { x1: L, y1: T, x2: L, y2: H - B, class: "axis" }));
  const tick = { "% of full scale": "% FS", "% open": "%" }[unit] || unit;
  svg.append(s("text", { x: L - 4, y: T + 4, class: "small tick end" }, `${fmt(hi)} ${tick}`));
  svg.append(s("text", { x: L - 4, y: H - B, class: "small tick end" }, `${fmt(lo)} ${tick}`));
  svg.append(s("text", { x: L, y: H - 6, class: "small tick" }, new Date(t0 * 1000).toLocaleTimeString()));
  svg.append(s("text", { x: W - R, y: H - 6, class: "small tick end" }, new Date(t1 * 1000).toLocaleTimeString()));
  const ends = [];
  series.forEach((ser, i) => {
    if (!ser.points.length) return;
    const d = ser.points.map((p, j) => `${j ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
    svg.append(s("path", { d, class: "series", "stroke-dasharray": DASHES[i % DASHES.length] }));
    ends.push({ name: ser.name, y: y(ser.points[ser.points.length - 1][1]) + 4 });
  });
  // end labels, pushed apart so they never print over each other (bottom up, then clamped to the top)
  ends.sort((a, b) => b.y - a.y);
  ends.forEach((e, i) => { if (i) e.y = Math.min(e.y, ends[i - 1].y - 11); });
  for (const e of ends) svg.append(s("text", { x: W - R + 4, y: Math.max(e.y, 10), class: "small" }, e.name));
  const cross = s("line", { x1: 0, x2: 0, y1: T, y2: H - B, class: "crosshair", visibility: "hidden" });
  svg.append(cross);
  const readout = el("p", { class: "readout small" }, " ");
  svg.addEventListener("mousemove", (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    if (px < L || px > W - R) return;
    const t = t0 + ((px - L) / (W - L - R)) * (t1 - t0);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
    const vals = series.map((ser) => {
      let best = null;
      for (const p of ser.points) if (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
      return best ? `${ser.name} ${fmt(best[1], 2)} ${unit}` : null;
    }).filter(Boolean);
    readout.textContent = `${new Date(t * 1000).toLocaleTimeString()}: ${vals.join(" · ")}`;
  });
  svg.addEventListener("mouseleave", () => cross.setAttribute("visibility", "hidden"));
  box.append(svg);
  if (series.length > 1) {
    box.append(el("p", { class: "legend small" }, series.map((ser, i) => `${["solid", "dashed", "dotted", "dash-dot", "fine dots"][i % 5]}: ${ser.name}`).join(" · ")));
  }
  box.append(readout);
  return box;
}
