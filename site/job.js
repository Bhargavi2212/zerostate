// Screen B, Job (and C, Explain): permanent assumptions strip, two-track verdict banner (never green),
// live plant view, steps with who marked / verified, evidence charts with vent and hold windows shaded,
// findings with raw numbers + Explain, the idealised-camera evidence panel. Site copy: recorded replay, no write controls.
// Live updates come from the SSE stream; state changes re-read GET /api/sessions/{id}.
import { api, el, s, errorText, fmt, NDF, statusMark, time, verdictClass, verdictText, who } from "./lib.js";
import { plantView } from "./plant.js";
import { lineChart } from "./chart.js";

// live camera evaluations log models as {locate, read}; recorded ones as a list
export const modelNames = (m) => (Array.isArray(m) ? m : Object.values(m || {})).join(", ") || "—";
const CAMERA_LABEL = "idealised camera (renders the simulator's true state)";
const STREAM_REFRESH = ["session_start", "step", "step_verify", "step_reopen", "verdict", "finding", "camera_reading", "signature", "session_stopped"];

export async function jobScreen(root, sid, params) {
  const st = { detail: await api(`/api/sessions/${encodeURIComponent(sid)}`), map: null, series: new Map(), spans: {}, live: {}, windows: [], camera: {}, msg: "" };
  st.map = await api(`/api/plants/${st.detail.plant}/map`).catch(() => null);
  const parts = Object.fromEntries(["strip", "banner", "actions", "plant", "steps", "charts", "findings", "camera", "explain"].map((k) => [k, el("section", { id: k, class: k === "strip" || k === "banner" ? null : "panel" })]));
  root.append(el("h1", {}, `Job ${sid}`), parts.strip, parts.banner, parts.actions,
    el("div", { class: "cols" }, el("div", {}, parts.plant, parts.steps, parts.findings), el("div", {}, parts.charts, parts.camera, parts.explain)));
  const stepKind = (k) => (st.detail.steps.find((x) => x.k === k) || {}).kind;

  // ---------- data from the stream
  function ingestSample(tag, t, v) {
    if (v === null || v === undefined) return;
    if (!st.series.has(tag)) st.series.set(tag, new Map());
    st.series.get(tag).set(t, v);
    st.live[tag] = v;
  }
  function ingestEvaluation(ev) {
    const p = ev.payload || {}, w = p.window;
    if (!w) return;
    Object.assign(st.spans, w.spans || {});
    for (const [tag, rows] of Object.entries(w.samples || {})) for (const r of rows) ingestSample(tag, r[0], r[1]);
    // the latest value of a tag is the last sample of the newest window holding it
    for (const [tag, rows] of Object.entries(w.samples || {})) if (rows.length) st.live[tag] = rows[rows.length - 1][1];
    const kind = p.source === "step" ? stepKind(p.step) : null;
    if (kind === "vent_open" || kind === "hold") st.windows.push({ t0: w.t0, t1: w.t1, label: kind === "hold" ? "hold" : "vent" });
  }

  // ---------- rendering
  function drawStrip() {
    const d = st.detail;
    const a = d.assumptions === null || d.assumptions === undefined ? "not recorded" : d.assumptions.length ? d.assumptions.join(" · ") : "none stated";
    parts.strip.replaceChildren(el("div", { class: "strip", id: "assumptions" }, el("strong", {}, "Assumptions: "), a,
      d.plan_check_override ? [" · ", el("strong", {}, "plan check overridden: "), d.plan_check_override] : null));
  }

  function track(label, v, reasons, note) {
    return el("div", { class: `track ${verdictClass(v)}`, "data-track": label },
      el("div", { class: "track-label small" }, label), el("div", { class: "track-verdict" }, verdictText(v, reasons)),
      reasons && reasons.length > 1 ? el("ul", { class: "small" }, reasons.slice(1).map((r) => el("li", {}, r))) : null,
      note ? el("div", { class: "small" }, note) : null);
  }
  const cameraEvals = () => [...new Set(st.detail.findings.filter((f) => f.source === "camera").map((f) => f.eval_id))];
  const tracks = () => {
    const d = st.detail, t = d.tracks || {};
    return { data: t.data_only ? t.data_only.verdict : d.verdict, cam: t.with_camera ? t.with_camera.verdict : d.verdict_with_camera,
      dataReasons: t.data_only ? t.data_only.reasons : (d.stamp && d.stamp.reasons) || [], camReasons: t.with_camera ? t.with_camera.reasons : [] };
  };
  function drawBanner() {
    const tr = tracks();
    parts.banner.replaceChildren(el("div", { class: "banner", id: "verdict-banner" },
      track("Data-only track", tr.data, tr.dataReasons),
      track("With-camera track", tr.cam, tr.camReasons.length ? tr.camReasons : tr.dataReasons,
        cameraEvals().length ? null : "No camera readings in this session: this track equals the data-only track.")));
  }

  function drawActions() {
    const d = st.detail;
    const sig = d.signature;
    const out = [el("span", { class: "small" }, `State: ${d.state} · plant ${d.plant} · started ${time(d.started)} · plan hash ${(d.plan_hash || "").slice(0, 12)}…`)];
    if (sig) {
      out.push(el("p", { id: "signature", class: "signed" }, sig.outcome === "accepted"
        ? `Accepted and signed by ${who(sig.by)} (${sig.role}) at ${time(sig.t)}.`
        : `Closed — not accepted, by ${who(sig.by)} (${sig.role}) at ${time(sig.t)}. This records that the job was not accepted.`));
    } else out.push(el("p", { class: "muted", id: "replay-note" }, "Recorded replay: nothing can be marked, verified or closed here."));
    if (st.msg) out.push(el("p", { class: "msg", id: "action-msg" }, st.msg));
    parts.actions.replaceChildren(el("div", { class: "actions" }, out));
  }

  function drawPlant() {
    const d = st.detail;
    const paths = d.findings.filter((f) => f.status !== "PASS" && f.path && f.path.length).map((f) => f.path);
    parts.plant.replaceChildren(el("h2", {}, "Plant view (command / feedback / flow)"),
      st.map ? plantView(st.map, { work: d.plan && d.plan.work ? d.plan.work.equipment : null, paths, live: st.live, spans: st.spans }) : el("p", { class: "muted" }, "No plant map."));
  }

  const findingLink = (id) => el("a", { href: `#finding-${id}`, class: "cite", onclick: (ev) => {
    ev.preventDefault();
    const target = document.getElementById(`finding-${id}`);
    if (target) { target.scrollIntoView({ block: "center" }); target.classList.add("flash"); setTimeout(() => target.classList.remove("flash"), 1500); }
  } }, id);

  function drawSteps() {
    const d = st.detail, live = !d.signature && d.state !== "stopped" && d.state !== "refused";
    const req = (x) => x.required_state === null || x.required_state === undefined ? "—" : x.kind === "mode" ? (x.required_state ? "on" : "off") : `${fmt(x.required_state, 0)} %`;
    parts.steps.replaceChildren(el("h2", {}, "Steps"), el("table", { class: "grid", id: "steps-table" },
      el("thead", {}, el("tr", {}, ["k", "Step", "Targets", "Required", "Marked by", "Verified by", "Result", "Findings"].map((h) => el("th", {}, h)))),
      el("tbody", {}, d.steps.map((x) => el("tr", { "data-step": x.k },
        el("td", {}, x.k), el("td", {}, x.kind), el("td", {}, (x.targets || []).join(", ") || "—"), el("td", {}, req(x)),
        el("td", { class: "marked-by" }, x.marked_by ? `${who(x.marked_by)} ${time(x.marked_t)}` : "—"),
        el("td", { class: "verified-by" }, x.verified_by ? `${who(x.verified_by)} ${time(x.verified_t)}` : "—"),
        el("td", { class: x.result ? `f-${x.result}` : null }, statusMark(x.result)),
        el("td", {}, (x.finding_ids || []).flatMap((id, i) => [i ? " " : null, findingLink(id)])))))));
  }

  function drawCharts() {
    if (!st.map) return;
    const tags = (role) => st.map.instruments.filter((i) => i.role === role).map((i) => i.signal_ref).filter((t) => st.series.has(t));
    const pts = (tag, f = (v) => v) => [...st.series.get(tag).entries()].sort((a, b) => a[0] - b[0]).map(([t, v]) => [t, f(v)]);
    const pct = (tag) => { const sp = st.spans[tag]; return sp ? (v) => (100 * (v - sp[0])) / (sp[1] - sp[0]) : (v) => v; };
    parts.charts.replaceChildren(el("h2", {}, "Evidence"),
      lineChart({ title: "Pressure", unit: "kPa", series: tags("pressure").map((t) => ({ name: t, points: pts(t) })), bands: st.windows }),
      lineChart({ title: "Flow", unit: "% of full scale", series: tags("flow").map((t) => ({ name: t, points: pts(t, pct(t)) })), bands: st.windows }),
      lineChart({ title: "Valve feedback", unit: "% open", series: tags("feedback").map((t) => ({ name: t, points: pts(t) })), bands: st.windows }));
  }

  function drawFindings() {
    const d = st.detail;
    const rows = [...d.findings].sort((a, b) => (a.status === "PASS") - (b.status === "PASS"));
    parts.findings.replaceChildren(el("h2", {}, `Findings (${d.findings.length})`), el("table", { class: "grid", id: "findings-table" },
      el("thead", {}, el("tr", {}, ["Id", "Status", "Rule", "Evidence", "Step", "Source", "Time"].map((h) => el("th", {}, h)))),
      el("tbody", {}, rows.map((f) => el("tr", { id: `finding-${f.id}`, class: `f-${f.status}` },
        el("td", { class: "small" }, f.id), el("td", {}, statusMark(f.status)), el("td", {}, `${f.rule_id} v${f.rule_version}`),
        el("td", {}, f.message, f.refs && f.refs.length ? el("span", { class: "small muted" }, ` [${f.refs.join(", ")}]`) : null),
        el("td", {}, f.step ?? "—"), el("td", {}, f.source), el("td", { class: "small" }, time(f.t)))))));
  }

  async function drawCamera() {
    const ids = cameraEvals();
    const box = [el("h2", {}, "Camera evidence"), el("p", { class: "camera-label" }, `Label: ${CAMERA_LABEL}`)];
    if (!ids.length) { parts.camera.replaceChildren(...box, el("p", { class: "muted" }, "No camera readings in this session.")); return; }
    const id = ids[ids.length - 1];
    if (!st.camera[id]) st.camera[id] = await api(`/api/sessions/${encodeURIComponent(sid)}/camera/${id}`).catch((e) => ({ error: errorText(e) }));
    const c = st.camera[id];
    if (c.error) { parts.camera.replaceChildren(...box, el("p", { class: "error" }, c.error)); return; }
    const fb = c.feedback && c.feedback.length ? c.feedback[c.feedback.length - 1][1] : null;
    box.push(el("p", {}, `Evaluation ${c.eval_id} · step ${c.step} · point ${c.point} (${c.tag}) · ${c.mode} · models: ${modelNames(c.models)}`),
      el("p", {}, statusMark(c.finding.status), " ", `${c.finding.rule_id}: ${c.finding.message}`),
      el("p", {}, `Valve feedback value: ${fmt(fb)} % open`));
    for (const [i, r] of c.readings.entries()) {
      const fig = el("div", { class: "camera-reading", "data-reading": i });
      if (r.frame_url) {
        const wrap = el("div", { class: "frame" }, el("img", { src: r.frame_url, alt: "camera frame", class: "frame-img", onload: (ev) => {
          wrap.querySelector("svg").setAttribute("viewBox", `0 0 ${ev.target.naturalWidth} ${ev.target.naturalHeight}`);
        } }));
        const ov = s("svg", { class: "sam-box", preserveAspectRatio: "none" },
          r.box ? s("rect", { x: r.box[0], y: r.box[1], width: r.box[2] - r.box[0], height: r.box[3] - r.box[1] }) : null);
        wrap.append(ov);
        fig.append(wrap);
      } else fig.append(el("p", { class: "muted" }, "Frame not kept here (replay mode keeps hashes only)."));
      if (r.crop_url) fig.append(el("img", { src: r.crop_url, alt: "display crop", class: "crop" }));
      fig.append(el("p", { class: "small" }, `SAM 3.1 box: ${r.box ? r.box.join(", ") + " px" : "none"} · reading: ${r.readable ? `${fmt(r.value)} % open` : "unreadable"} · feedback at read: ${fmt(r.feedback_at)} % open · ${time(r.t)}`,
        r.note ? ` · ${r.note}` : "", ` · frame ${String(r.frame_sha256 || "").slice(0, 12)}…`));
      box.push(fig);
    }
    parts.camera.replaceChildren(...box);
  }

  parts.explain.append(el("h2", {}, "Explain"), el("p", { class: "small muted" }, "Explain needs the model; it is not part of this recorded replay."));

  // ---------- refresh + stream
  let closed = false;
  function drawAll() { drawStrip(); drawBanner(); drawActions(); drawPlant(); drawSteps(); drawFindings(); drawCharts(); drawCamera(); }
  async function refresh() {
    try { st.detail = await api(`/api/sessions/${encodeURIComponent(sid)}`); } catch (e) { st.msg = errorText(e); }
    drawAll();
  }
  const soon = (fn, ms) => { let pending = null; return () => { if (!pending) pending = setTimeout(() => { pending = null; if (!closed) fn(); }, ms); }; };
  const refreshSoon = soon(refresh, 250);
  const redrawLive = soon(() => { drawPlant(); drawCharts(); }, 250);

  drawAll();
  const speed = params.get("speed");
  const es = new EventSource(`/api/sessions/${encodeURIComponent(sid)}/stream${speed ? `?speed=${encodeURIComponent(speed)}` : ""}`);
  const streamNote = el("p", { class: "small muted", id: "stream-state" }, "Recorded events: loading");
  parts.strip.after(streamNote);
  const data = (ev) => JSON.parse(ev.data);
  es.addEventListener("evaluation", (ev) => { ingestEvaluation(data(ev)); redrawLive(); refreshSoon(); });
  es.addEventListener("signals", (ev) => {
    const d = data(ev);
    for (const [tag, v] of Object.entries(d)) if (tag !== "t" && Array.isArray(v)) ingestSample(tag, d.t, v[0]);
    redrawLive();
  });
  for (const k of STREAM_REFRESH) es.addEventListener(k, refreshSoon);
  const end = (why) => () => { es.close(); streamNote.textContent = `Recorded events: ${why}`; refreshSoon(); };
  es.addEventListener("signature", end("ended (signed)"));
  es.addEventListener("session_stopped", end("ended (session stopped)"));
  es.onerror = end("all shown"); // replay ends the stream; never auto-reconnect into a second copy
  return () => { closed = true; es.close(); };
}
