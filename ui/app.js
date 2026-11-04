// Router and the session list. Screens: #/ (sessions), #/new (intake), #/job/<id>[?speed=N] (job).
import { api, el, errorText, verdictClass, verdictText, time } from "./lib.js";
import { intakeScreen } from "./intake.js";
import { jobScreen } from "./job.js";

const app = document.getElementById("app");
let cleanup = null;

async function sessionsScreen(root) {
  root.append(el("h1", {}, "Sessions"));
  const list = await api("/api/sessions");
  if (!list.length) {
    root.append(el("p", {}, "No sessions yet. Start with a new isolation."));
    return;
  }
  const verdictCell = (v) => el("td", {}, el("span", { class: `badge ${verdictClass(v)}` }, verdictText(v)));
  root.append(el("table", { class: "grid", id: "sessions" },
    el("thead", {}, el("tr", {}, ["Session", "Plant", "Started", "State", "Data-only track", "With-camera track", "Signed"].map((h) => el("th", {}, h)))),
    el("tbody", {}, list.map((x) => el("tr", { "data-session": x.id },
      el("td", {}, el("a", { href: `#/job/${encodeURIComponent(x.id)}` }, x.id)),
      el("td", {}, x.plant), el("td", {}, time(x.started)), el("td", {}, x.state),
      verdictCell(x.verdict), verdictCell(x.verdict_with_camera),
      el("td", {}, x.signed ? "signed" : "not signed"))))));
}

async function route() {
  if (cleanup) { cleanup(); cleanup = null; }
  app.replaceChildren();
  const [path, query] = location.hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(query || "");
  try {
    if (path.startsWith("/job/")) cleanup = await jobScreen(app, decodeURIComponent(path.slice(5)), params);
    else if (path === "/new") await intakeScreen(app);
    else await sessionsScreen(app);
  } catch (e) {
    app.append(el("p", { class: "error" }, errorText(e)));
  }
}

window.addEventListener("hashchange", route);
route();
