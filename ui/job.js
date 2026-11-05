// Screen B, Job (and C, Explain): permanent assumptions strip, two-track verdict banner (never green),
// live plant view, steps with who marked / verified, evidence charts with vent and hold windows shaded,
// findings with raw numbers + Explain, the idealised-camera evidence panel, and the Sign dialog.
// Live updates come from the SSE stream; state changes re-read GET /api/sessions/{id}.
import { api, el, s, errorText, fmt, NDF, time, verdictClass, verdictText, who, episodeTitle, plantName, stepName, ruleName, headline, verdictWord, valveName, ASSUMPTION } from "./lib.js";
import { plantView } from "./plant.js";
import { lineChart } from "./chart.js";

// live camera evaluations log models as {locate, read}; recorded ones as a list
export const modelNames = (m) => (Array.isArray(m) ? m : Object.values(m || {})).join(", ") || "—";
const MARK = { PASS: "✓ no discrepancy", FAIL: "✗ failed", UNKNOWN: "? could not tell" };
const CAMERA_LABEL = "idealised camera (renders the simulator's true state)";
const SIGN_ROLES = ["receiver", "approver", "planner", "installer", "verifier", "prover"];
const STREAM_REFRESH = ["session_start", "step", "step_verify", "step_reopen", "verdict", "finding", "camera_reading", "signature", "session_stopped"];

export async function jobScreen(root, sid, params) {
  const st = { detail: await api(`/api/sessions/${encodeURIComponent(sid)}`), map: null, series: new Map(), spans: {}, live: {}, windows: [], camera: {}, msg: "" };
  st.map = await api(`/api/plants/${st.detail.plant}/map`).catch(() => null);
  const parts = Object.fromEntries(["strip", "hero", "witnesses", "banner", "actions", "plant", "steps", "charts", "findings", "camera", "explain"].map((k) => [k, el("section", { id: k, class: ["strip", "banner", "hero"].includes(k) ? null : "panel" })]));
  const techSummary = el("summary", {}, "Technical details");
  const techIds = el("p", { class: "small", id: "tech-ids" });
  root.append(el("h1", {}, episodeTitle(sid)), el("p", { class: "small muted", id: "job-id" }, `${sid} · ${plantName(st.detail.plant)}`),
    parts.strip, parts.hero, parts.witnesses, parts.banner, parts.actions, el("div", { class: "job-grid" }, parts.plant, parts.charts), parts.steps, parts.explain,
    el("details", { id: "tech", class: "panel" }, techSummary, techIds, parts.findings, parts.camera));
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
    const a = d.assumptions === null || d.assumptions === undefined ? "Assumptions: not recorded" : d.assumptions.length
      ? d.assumptions.map((x) => ASSUMPTION[x] || `Assumed: ${x}`).join(" · ") : "Assumptions: none stated";
    parts.strip.replaceChildren(el("div", { class: "strip", id: "assumptions" }, a,
      d.plan_check_override ? [" · ", el("strong", {}, "plan check overridden: "), d.plan_check_override] : null));
  }

  // a logged reason "RULE-ID: message" read as the finding's plain headline
  const plain = (r) => { const m = String(r).match(/^([A-Z]+(?:-[A-Z]+)+): (.*)$/s); return m ? headline({ rule_id: m[1], message: m[2], status: "FAIL" }) : r; };
  function track(label, v, rawReasons, note) {
    const reasons = (rawReasons || []).map(plain);
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
      track("Plant data", tr.data, tr.dataReasons),
      track("Plant data + camera", tr.cam, tr.camReasons.length ? tr.camReasons : tr.dataReasons,
        cameraEvals().length ? null : "No camera readings in this session: same as plant data alone.")));
  }

  // ---------- the one-line answer, then the three witnesses for the valve that decided it
  function deciding() {
    const tr = tracks(), d = st.detail;
    const v = [tr.data, tr.cam].includes("BLOCKED") ? "BLOCKED" : [tr.data, tr.cam].includes("ESCALATED") ? "ESCALATED" : tr.data;
    const want = v === "BLOCKED" ? "FAIL" : v === "ESCALATED" ? "UNKNOWN" : null;
    const reasons = [...tr.dataReasons, ...tr.camReasons];
    const f = want ? d.findings.find((x) => x.status === want && reasons.includes(`${x.rule_id}: ${x.message}`)) || d.findings.find((x) => x.status === want) : null;
    return { v, f };
  }
  function drawHero() {
    const { v, f } = deciding(), d = st.detail;
    const line = f ? headline(f) : v === NDF ? `No discrepancy found in ${d.findings.length} logged checks. This is not a safety call; a person signs.` : "No verdict is logged yet.";
    parts.hero.replaceChildren(el("div", { class: `hero ${verdictClass(v)}`, id: "verdict-hero" },
      el("div", { class: "hero-word" }, verdictWord(v)), el("div", { class: "hero-line" }, line)));
  }
  const pointOf = (f) => {
    if (!f) return null;
    if (f.source === "camera") return (st.camera[f.eval_id] || {}).point || null;
    const ref = (f.refs || []).find((r) => /_(valve_pos|flow)$/.test(r));
    return ref ? ref.replace(/_(valve_pos|flow)$/, "") : null;
  };
  async function drawWitnesses() {
    const { f } = deciding(), d = st.detail;
    if (f && f.source === "camera" && !st.camera[f.eval_id]) st.camera[f.eval_id] = await api(`/api/sessions/${encodeURIComponent(sid)}/camera/${f.eval_id}`).catch(() => ({}));
    const point = pointOf(f);
    if (!point) { parts.witnesses.replaceChildren(); parts.witnesses.hidden = true; return; }
    parts.witnesses.hidden = false;
    const valveF = d.findings.filter((x) => x.rule_id === "LIVE-VALVE" && (x.refs || []).includes(`${point}_valve_pos`) && x.status === "FAIL").pop();
    const m = valveF && valveF.message.match(/_flow = ([-\d.]+) while \S+?_valve_pos = ([-\d.]+) %/);
    for (const id of cameraEvals()) if (!st.camera[id]) st.camera[id] = await api(`/api/sessions/${encodeURIComponent(sid)}/camera/${id}`).catch(() => ({}));
    const cam = cameraEvals().map((id) => st.camera[id]).filter((c) => c && c.point === point && c.finding && c.finding.status === "FAIL").pop()
      || cameraEvals().map((id) => st.camera[id]).filter((c) => c && c.point === point).pop();
    const reads = cam ? cam.readings.filter((r) => r.readable).map((r) => `${fmt(r.value, 0)}%`) : [];
    const shot = cam && cam.readings.find((r) => r.frame_url && r.box);
    const crop = el("canvas", { class: "witness-crop", width: 240, height: 120 });
    if (shot) {
      const img = new Image();
      img.onload = () => { const [x1, y1, x2, y2] = shot.box, w = x2 - x1, h = y2 - y1, padX = w * 1.2, padY = h * 1.6;
        crop.getContext("2d").drawImage(img, x1 - padX, y1 - padY, w + 2 * padX, h + 2 * padY, 0, 0, crop.width, crop.height); };
      img.src = shot.frame_url;
    }
    const card = (label, value, extra) => el("div", { class: "witness" }, el("div", { class: "small muted" }, label), el("div", { class: "witness-value" }, value), extra || null);
    parts.witnesses.replaceChildren(el("h2", {}, `${valveName(point)}: three witnesses`), el("div", { class: "witnesses" },
      card("Control system says", m ? `${fmt(Number(m[2]), 0)}% open` : "no reading in the finding"),
      card("Flow meter says", m ? `${fmt(Number(m[1]), 1)} flowing` : "no flow reading in the finding"),
      card("Camera says", reads.length ? `${reads.join(", ")} open` : "no camera reading", shot ? [crop, el("div", { class: "small muted" }, "camera: GRFICSv3 simulator, pre-existing")] : null)));
  }

  function drawActions() {
    const d = st.detail;
    const sig = d.signature;
    const out = [el("span", { class: "small" }, `State: ${d.state} · started ${time(d.started)}`)];
    if (sig) {
      out.push(el("p", { id: "signature", class: "signed" }, sig.outcome === "accepted"
        ? `Accepted and signed by ${who(sig.by)} (${sig.role}) at ${time(sig.t)}.`
        : `Closed — not accepted, by ${who(sig.by)} (${sig.role}) at ${time(sig.t)}. This records that the job was not accepted.`));
    } else {
      const tr = tracks();
      const pending = d.camera_pending || 0;
      if (tr.data === NDF && tr.cam === NDF && pending > 0) {
        // a late camera reading can still block: acceptance waits until every started read is in
        out.push(el("button", { type: "button", id: "sign-wait", disabled: true },
          `Camera still checking (${pending} read${pending === 1 ? "" : "s"} pending) — sign-off waits`));
      } else {
        const accept = tr.data === NDF && tr.cam === NDF;
        out.push(el("button", { type: "button", id: "sign-open", onclick: () => signDialog(accept) }, accept ? "Accept and sign…" : "Close — not accepted…"));
      }
    }
    if (st.msg) out.push(el("p", { class: "msg", id: "action-msg" }, st.msg));
    parts.actions.replaceChildren(el("div", { class: "actions" }, out));
  }

  function drawPlant() {
    const d = st.detail;
    const paths = d.findings.filter((f) => f.status !== "PASS" && f.path && f.path.length).map((f) => f.path);
    parts.plant.replaceChildren(el("h2", {}, "Plant diagram (command / feedback / flow)"),
      st.map ? plantView(st.map, { work: d.plan && d.plan.work ? d.plan.work.equipment : null, paths, live: st.live, spans: st.spans }) : el("p", { class: "muted" }, "No plant map."));
  }

  const rowOf = new Map(); // finding id -> the merged row that holds it
  const findingLink = (id) => el("a", { href: `#finding-${id}`, class: "cite", onclick: (ev) => {
    ev.preventDefault();
    document.getElementById("tech").open = true;
    const target = document.getElementById(`finding-${rowOf.get(id) || id}`);
    if (target) { target.scrollIntoView({ block: "center" }); target.classList.add("flash"); setTimeout(() => target.classList.remove("flash"), 1500); }
  } }, id);

  function drawSteps() {
    const d = st.detail, live = !d.signature && d.state !== "stopped" && d.state !== "refused";
    const req = (x) => x.required_state === null || x.required_state === undefined ? "—" : x.kind === "mode" ? (x.required_state ? "on" : "off") : `${fmt(x.required_state, 0)} %`;
    parts.steps.replaceChildren(el("h2", {}, "Steps"), el("table", { class: "grid", id: "steps-table" },
      el("thead", {}, el("tr", {}, ["#", "Step", "Required", "Marked by", "Verified by", "Result", "Findings", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, d.steps.map((x) => el("tr", { "data-step": x.k },
        el("td", {}, x.k), el("td", {}, stepName(x)), el("td", {}, req(x)),
        el("td", { class: "marked-by" }, x.marked_by ? `${who(x.marked_by)} ${time(x.marked_t)}` : "—"),
        el("td", { class: "verified-by" }, x.verified_by ? `${who(x.verified_by)} ${time(x.verified_t)}` : "—"),
        el("td", { class: x.result ? `f-${x.result}` : null }, MARK[x.result] || "– not reached"),
        el("td", { class: "small" }, stepFindings(x)),
        el("td", {}, live && !x.marked_by ? el("button", { type: "button", "data-action": "done", onclick: () => stepAction(x, "done") }, "Mark done") : null,
          live && x.marked_by && !x.verified_by ? el("button", { type: "button", "data-action": "verify", onclick: () => stepAction(x, "verify") }, "Verify") : null))))));
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

  function stepFindings(x) {
    const fs = st.detail.findings.filter((f) => f.step === x.k);
    const bad = fs.filter((f) => f.status !== "PASS");
    if (!fs.length) return "—";
    return bad.length ? [headline(bad[0]), " ", findingLink(bad[0].id)] : `${fs.length} checks, no discrepancy`;
  }
  // repeated findings (same check, result, step and source) are one row: "x 30, 07:56:19-07:57:20"
  function merged() {
    const groups = new Map();
    for (const f of st.detail.findings) {
      const k = `${f.rule_id}|${f.status}|${f.step}|${f.source}`;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(f);
    }
    return [...groups.values()].sort((a, b) => (a[0].status === "PASS") - (b[0].status === "PASS"));
  }
  function drawFindings() {
    const d = st.detail, groups = merged();
    rowOf.clear();
    for (const g of groups) for (const f of g) rowOf.set(f.id, g[0].id);
    techSummary.textContent = `Technical details (${d.findings.length} checks logged)`;
    techIds.textContent = `Session ${sid} · plant id ${d.plant} · plan hash ${d.plan_hash || "—"}`;
    const when = (g) => { const ts = g.map((f) => f.t).filter(Boolean); return ts.length > 1 ? `${time(Math.min(...ts))}–${time(Math.max(...ts))}` : time(ts[0]); };
    const raw = (g) => el("details", { class: "raw small" }, el("summary", {}, "logged text"),
      el("ul", {}, [...new Set(g.map((f) => f.message))].slice(0, 5).map((m) => el("li", {}, m))),
      el("p", { class: "muted" }, `${g[0].rule_id} v${g[0].rule_version}${g[0].refs && g[0].refs.length ? ` · [${g[0].refs.join(", ")}]` : ""} · ids ${g.map((f) => f.id).slice(0, 6).join(", ")}${g.length > 6 ? " …" : ""}`));
    parts.findings.replaceChildren(el("h2", {}, `Findings (${d.findings.length} logged, ${groups.length} rows)`), el("table", { class: "grid", id: "findings-table" },
      el("thead", {}, el("tr", {}, ["Check", "Result", "What it found", "Step", "Source", "Count", "Time", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, groups.map((g) => { const f = g[g.length - 1]; return el("tr", { id: `finding-${g[0].id}`, class: `f-${f.status}` },
        el("td", {}, ruleName(f.rule_id)), el("td", {}, MARK[f.status] || f.status),
        el("td", {}, headline(f), raw(g)),
        el("td", {}, f.step ?? "—"), el("td", {}, f.source), el("td", {}, g.length > 1 ? `× ${g.length}` : "1"), el("td", { class: "small" }, when(g)),
        el("td", {}, el("button", { type: "button", class: "explain-btn", onclick: () => ask(`Explain finding ${f.id}: ${f.rule_id} ${f.status}.`) }, "Explain")));
      }))));
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
      el("p", {}, MARK[c.finding.status] || c.finding.status, " ", headline(c.finding)),
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

  // ---------- explain (screen C)
  const q = el("textarea", { id: "explain-q", rows: 2, cols: 50 });
  const answer = el("div", { id: "explain-answer" });
  parts.explain.append(el("h2", {}, "Explain"), el("p", { class: "small muted" }, "Answers come only from this session's logged findings and cite them. Explain cannot change anything."),
    q, el("button", { type: "button", id: "explain-ask", onclick: () => ask(q.value) }, "Ask"), answer);
  async function ask(question) {
    q.value = question;
    if (!question.trim()) return;
    answer.replaceChildren(el("p", { class: "muted" }, "Asking…"));
    try {
      const r = await api(`/api/sessions/${encodeURIComponent(sid)}/explain`, { json: { question } });
      answer.replaceChildren(el("p", {}, r.answer), el("p", { class: "small" }, "Cited: ", r.cites.length ? r.cites.flatMap((id, i) => [i ? ", " : null, findingLink(id)]) : "none"));
    } catch (e) {
      answer.replaceChildren(el("p", { class: "error" }, e.status === 503 ? "Explain needs the model, which is not available here." : errorText(e)));
    }
  }

  // ---------- human actions (names as typed; nothing here is authenticated)
  function nameDialog(title, { extra = null, check = () => null, submitText = "Submit" } = {}) {
    return new Promise((resolve) => {
      const name = el("input", { id: "dlg-name", size: 24 });
      const msg = el("p", { class: "error", id: "dlg-msg" });
      const dlg = el("dialog", { id: "name-dialog" }, el("form", { method: "dialog", onsubmit: (ev) => {
        ev.preventDefault();
        const n = name.value.trim();
        const bad = n ? check(n) : "Enter your name.";
        if (bad) { msg.textContent = bad; return; }
        dlg.close(); dlg.remove(); resolve({ name: n, form: dlg });
      } }, el("h2", {}, title), el("label", {}, "Your name ", name), extra, msg,
        el("menu", {}, el("button", { type: "submit", id: "dlg-submit" }, submitText),
          el("button", { type: "button", onclick: () => { dlg.close(); dlg.remove(); resolve(null); } }, "Cancel"))));
      document.body.append(dlg);
      dlg.showModal();
    });
  }

  async function post(path, body) {
    try { await api(path, { json: body }); st.msg = "Queued. The session logs it; the screen updates from the log."; }
    catch (e) { st.msg = errorText(e); }
    drawActions();
    setTimeout(refresh, 300);
  }

  async function stepAction(x, action) {
    const r = action === "done"
      ? await nameDialog(`Mark step ${x.k} done`, { submitText: "Mark done" })
      : await nameDialog(`Verify step ${x.k}`, { submitText: "Verify",
        check: (n) => n.toLowerCase() === String(x.marked_by || "").trim().toLowerCase() ? "Verify needs a different name from the person who marked the step." : null });
    if (r) await post(`/api/sessions/${encodeURIComponent(sid)}/steps/${x.k}/${action}`, { by: r.name });
  }

  async function signDialog(accept) {
    const role = el("select", { id: "sign-role" }, SIGN_ROLES.map((x) => el("option", { value: x }, x)));
    const note = el("input", { id: "sign-note", size: 40 });
    const extra = el("div", {},
      el("p", { class: accept ? null : "not-accepted" }, accept
        ? "Both tracks found no discrepancy. Your signature accepts the job; ZeroState itself never approves."
        : "This closes the session and records that the job was NOT accepted. It is not an approval."),
      el("label", {}, "Role ", role), el("label", {}, " Note ", note));
    const r = await nameDialog(accept ? "Accept and sign" : "Close — not accepted", { extra, submitText: accept ? "Accept and sign" : "Close — not accepted" });
    if (r) await post(`/api/sessions/${encodeURIComponent(sid)}/sign`, { by: r.name, role: role.value, note: note.value.trim() || null, outcome: accept ? "accepted" : "not_accepted" });
  }

  // ---------- refresh + stream
  let closed = false;
  function drawAll() { drawStrip(); drawHero(); drawBanner(); drawActions(); drawPlant(); drawSteps(); drawFindings(); drawCharts(); drawCamera().then(drawWitnesses); }
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
  const streamNote = el("p", { class: "small muted", id: "stream-state" }, "Live stream: connected");
  parts.strip.after(streamNote);
  const data = (ev) => JSON.parse(ev.data);
  es.addEventListener("evaluation", (ev) => { ingestEvaluation(data(ev)); redrawLive(); refreshSoon(); });
  es.addEventListener("signals", (ev) => {
    const d = data(ev);
    for (const [tag, v] of Object.entries(d)) if (tag !== "t" && Array.isArray(v)) ingestSample(tag, d.t, v[0]);
    redrawLive();
  });
  for (const k of STREAM_REFRESH) es.addEventListener(k, refreshSoon);
  const end = (why) => () => { es.close(); streamNote.textContent = `Live stream: ${why}`; refreshSoon(); };
  es.addEventListener("signature", end("ended (signed)"));
  es.addEventListener("session_stopped", end("ended (session stopped)"));
  es.onerror = end("closed"); // replay ends the stream; never auto-reconnect into a second copy
  return () => { closed = true; es.close(); };
}
