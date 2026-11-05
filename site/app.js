// Router and the session list. Screens: #/ (sessions), #/new (intake), #/job/<id>[?speed=N] (job),
// #/check[?session=<id>] (check my isolation).
import { api, el, errorText, verdictClass, time, episodeTitle, plantName, verdictWord } from "./lib.js";
import { jobScreen } from "./job.js";
import { checkScreen } from "./check.js";

const app = document.getElementById("app");
let cleanup = null;

const HIDE = new Set(["S8_seed503_20261104T125324", "S0_seed502_20261104T124516"]); // sessions left off the landing cards (the site lists its demo runs under Check my isolation)
const RESULTS = "results.html"; // the site's results page

async function sessionsScreen(root) {
  root.append(el("h1", {}, "ZeroState: a second check before anyone opens a pipe"),
    el("p", { class: "lede" }, "It compares the isolation plan with the plant's live data and a camera, and says STOP when they disagree. It never gives the go-ahead; a person signs."),
    el("h2", {}, "Recorded episodes"));
  const list = (await api("/api/sessions")).filter((x) => !HIDE.has(x.id));
  if (!list.length) {
    root.append(el("p", {}, "No recorded episodes in this build."));
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
    else if (path === "/check") cleanup = await checkScreen(app, params);
    else await sessionsScreen(app);
  } catch (e) {
    app.append(el("p", { class: "error" }, errorText(e)));
  }
}

window.addEventListener("hashchange", route);
route();
