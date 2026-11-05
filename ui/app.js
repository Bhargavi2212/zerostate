// Router and the session list. Screens: #/ (sessions), #/new (intake), #/job/<id>[?speed=N] (job),
// #/check[?session=<id>] (check my isolation).
import { api, el, s, errorText, verdictClass, time, episodeTitle, plantName, verdictWord } from "./lib.js";
import { intakeScreen } from "./intake.js";
import { jobScreen } from "./job.js";
import { checkScreen } from "./check.js";

const app = document.getElementById("app");
let cleanup = null;

const HIDE = new Set([]); // sessions left off the landing cards (the site lists its demo runs under Check my isolation)
const RESULTS = null; // the site's results page

// benchmark summary (the site only: GET /api/summary is its build's copy of the score files)
function summaryView(sm) {
  const tile = (n, label) => el("div", { class: "tile" }, el("div", { class: "tile-n" }, n), el("div", { class: "tile-l" }, label));
  const W = 900, rowH = 34, L = 250, H = sm.batches.length * rowH + 10;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "verdicts per batch" });
  sm.batches.forEach((b, i) => {
    const y = 6 + i * rowH, tot = b.blocked + b.escalated + b.ndf || 1;
    let x = L;
    svg.append(s("text", { x: 0, y: y + 18, class: "lab" }, `Batch ${b.batch} · ${b.n} episodes`));
    for (const [k, cls] of [["blocked", "c-stop"], ["escalated", "c-esc"], ["ndf", "c-ndf"]]) {
      const w = ((W - L - 10) * b[k]) / tot;
      if (!w) continue;
      svg.append(s("rect", { x, y, width: w, height: 24, rx: 4, class: cls }));
      if (w > 26) svg.append(s("text", { x: x + w / 2, y: y + 17, "text-anchor": "middle", class: "in" }, String(b[k])));
      x += w;
    }
  });
  return [el("div", { class: "section-title" }, "Benchmark, every episode scored from sealed seeds"),
    el("div", { class: "tiles" },
      tile(String(sm.episodes), "episodes scored, on two simulated plants"),
      tile(`${sm.dangerous_misses} / ${sm.episodes}`, "dangerous misses: a hazard present and no STOP"),
      tile(`${sm.false_blocks} / ${sm.clean}`, "STOPs on clean runs (false blocks)"),
      tile(`${sm.camera_blocked} / ${sm.camera_n}`, "camera-track STOPs in batch 2, every one matched by plant data")),
    el("div", { class: "panel vbar" }, el("h2", {}, "Verdicts per batch"), svg,
      el("div", { class: "legend" }, el("span", {}, el("i", { class: "c-stop" }), "STOP"), el("span", {}, el("i", { class: "c-esc" }), "A person needs to look"),
        el("span", {}, el("i", { class: "c-ndf" }), "No discrepancy found, awaiting signature")),
      RESULTS ? el("p", { class: "small" }, el("a", { href: RESULTS }, "All numbers, per scenario, with the seal check →")) : null)];
}

async function sessionsScreen(root) {
  root.append(el("section", { class: "landing-hero" },
    el("h1", {}, "ZeroState: a second check before anyone opens a pipe"),
    el("p", { class: "lede" }, "It compares the isolation plan with the plant's live data and a camera, and says STOP when they disagree. It never gives the go-ahead; a person signs."),
    el("div", { class: "how" },
      el("div", {}, el("b", {}, "1 · The plan"), "A person confirms which valves close, which vent opens, and the hold test."),
      el("div", {}, el("b", {}, "2 · Three witnesses"), "Each step is checked against the control system, the flow meters and a camera on the valve's display."),
      el("div", {}, el("b", {}, "3 · STOP or sign"), "Any disagreement is a STOP with the reason. Otherwise it says what it found, and a person signs."))));
  const summary = await api("/api/summary").catch(() => null);
  if (summary) root.append(...summaryView(summary));
  root.append(el("div", { class: "section-title" }, "Sessions"));
  const list = (await api("/api/sessions")).filter((x) => !HIDE.has(x.id));
  if (!list.length) {
    root.append(el("p", {}, "No sessions yet. Start with a new isolation."));
    return;
  }
  const worst = (x) => ([x.verdict, x.verdict_with_camera].includes("BLOCKED") ? "BLOCKED" : [x.verdict, x.verdict_with_camera].includes("ESCALATED") ? "ESCALATED" : x.verdict);
  root.append(el("div", { class: "cards", id: "sessions" }, list.map((x) => el("a", { class: `card ${verdictClass(worst(x))}`, "data-session": x.id, href: `#/job/${encodeURIComponent(x.id)}` },
    el("div", { class: "card-verdict" }, verdictWord(worst(x))),
    el("div", { class: "card-title" }, episodeTitle(x.id)),
    el("div", { class: "small" }, plantName(x.plant)),
    el("div", { class: "small" }, `Plant data: ${verdictWord(x.verdict)} · Plant data + camera: ${verdictWord(x.verdict_with_camera)} · ${x.signed ? "signed" : "not signed"}`),
    el("div", { class: "small muted card-id" }, `${x.id} · ${x.state} · started ${time(x.started)}`)))));
  if (RESULTS) root.append(el("p", { class: "lede" }, el("a", { href: RESULTS, id: "results-link" }, "Benchmark results: every episode, scored →")));
}

async function route() {
  if (cleanup) { cleanup(); cleanup = null; }
  app.replaceChildren();
  const [path, query] = location.hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(query || "");
  try {
    if (path.startsWith("/job/")) cleanup = await jobScreen(app, decodeURIComponent(path.slice(5)), params);
    else if (path === "/new") await intakeScreen(app);
    else if (path === "/check") cleanup = await checkScreen(app, params);
    else await sessionsScreen(app);
  } catch (e) {
    app.append(el("p", { class: "error" }, errorText(e)));
  }
}

window.addEventListener("hashchange", route);
route();
