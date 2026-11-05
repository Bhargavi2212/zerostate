// "Check my isolation" (#/check[?session=<id>]): a worker asks, ZeroState walks through the logged checks
// one by one, out loud, with the camera frame zoomed to each valve. It never answers "go": the last line is a
// STOP with the deciding finding, or "No discrepancy found in N checks. This is not a safety call; the
// issuer signs." This view computes no verdict: every mark is a logged finding's status and the final
// line is the engine's logged verdict. Every logged finding is listed below the checklist, in log order.
// The request goes to POST /api/checks/resolve (read-only); the microphone records a WAV for Muse Voice
// Transcribe on the server. Speech output: window.speechSynthesis with an on-device voice only.
// Recorded session: the rows are stepped through at a readable pace. Running session (live step mode): the
// worker marks each step here after confirming the voice route's read-back; never verify, reopen or sign.
import { api, el, errorText, fmt, NDF, time } from "./lib.js";

export const CAMERA_CAPTION = "camera: GRFICSv3 simulator, pre-existing";
export const EXAMPLE = "I'm about to open the reactor for repair. I've locked out. Check my isolation.";
const PACE_MS = 2800; // a row on screen this long when nothing is spoken
const MARK = { FAIL: "✗", UNKNOWN: "?", PASS: "✓" };
const WORD = { FAIL: "Failed.", UNKNOWN: "Could not tell.", PASS: "No discrepancy." };
const RANK = { FAIL: 3, UNKNOWN: 2, PASS: 1 };

// ---------- speech: on-device voices only; nothing leaves this computer
function speaker(startMuted) {
  const synth = window.speechSynthesis;
  const st = { muted: startMuted, voice: null };
  const pick = () => { st.voice = synth ? synth.getVoices().find((v) => v.localService === true) || null : null; };
  if (synth) { pick(); synth.addEventListener?.("voiceschanged", pick); }
  st.say = (text) => new Promise((done) => {
    if (st.muted || !st.voice || !synth) { setTimeout(done, PACE_MS); return; }
    const u = new SpeechSynthesisUtterance(text);
    u.voice = st.voice;
    u.rate = 1.0;
    const t = setTimeout(done, 15000); // a stuck voice never stalls the walk-through
    u.onend = u.onerror = () => { clearTimeout(t); setTimeout(done, 400); };
    synth.speak(u);
  });
  st.stop = () => synth && synth.cancel();
  st.note = () => (st.muted ? "Muted. The spoken line is shown on screen. " : "") + (st.voice
    ? `Spoken by an on-device voice (${st.voice.name}); nothing leaves this computer.`
    : "No on-device voice on this computer: text only. Nothing is sent anywhere to speak it.");
  return st;
}

// ---------- microphone: mono 16-bit PCM WAV at 16 kHz, sent to the server for Muse Voice Transcribe
async function recordWav(stopSignal) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  proc.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  src.connect(proc); proc.connect(ctx.destination);
  await stopSignal;
  proc.disconnect(); src.disconnect(); stream.getTracks().forEach((t) => t.stop());
  const rate = ctx.sampleRate; await ctx.close();
  const all = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let o = 0; for (const c of chunks) { all.set(c, o); o += c.length; }
  const ratio = rate / 16000, n = Math.floor(all.length / ratio);
  const buf = new DataView(new ArrayBuffer(44 + n * 2));
  const str = (off, s) => [...s].forEach((ch, i) => buf.setUint8(off + i, ch.charCodeAt(0)));
  str(0, "RIFF"); buf.setUint32(4, 36 + n * 2, true); str(8, "WAVE"); str(12, "fmt ");
  buf.setUint32(16, 16, true); buf.setUint16(20, 1, true); buf.setUint16(22, 1, true); buf.setUint32(24, 16000, true);
  buf.setUint32(28, 32000, true); buf.setUint16(32, 2, true); buf.setUint16(34, 16, true); str(36, "data"); buf.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) buf.setInt16(44 + i * 2, Math.max(-1, Math.min(1, all[Math.floor(i * ratio)])) * 0x7fff, true);
  let bin = ""; const bytes = new Uint8Array(buf.buffer);
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

// ---------- checklist rows, in plan order, from the plan only
function buildRows(plan) {
  const rows = [], steps = (plan && plan.steps) || [];
  const witness = (point, role) => ((plan.witnesses || []).find((w) => w.point === point && w.role === role) || {}).signal_ref || null;
  const pct = (v) => (v === null || v === undefined ? "" : v <= 5 ? "closed" : v >= 95 ? "open" : `${fmt(v, 0)} % open`);
  for (const s of steps) {
    const targets = s.targets && s.targets.length ? s.targets : s.target ? [s.target] : [];
    if (s.kind === "final") continue;
    if (s.kind === "hold") { rows.push({ step: s.k, kind: "hold", label: "Hold test", points: [] }); continue; }
    if (s.kind === "mode") { rows.push({ step: s.k, kind: "mode", label: `PLC mode: ${targets.join(", ")} = ${s.required_state}`, tag: targets[0], points: [] }); continue; }
    for (const t of targets) {
      const tags = { fb: witness(t, "feedback"), flow: witness(t, "flow"), cmd: witness(t, "command") };
      const what = s.kind === "vent_open" ? "vent" : s.kind === "vent_close" ? "vent" : "valve";
      rows.push({ step: s.k, kind: "valve", point: t, tags, multi: targets.length > 1, label: `${what} ${t}: ${pct(s.required_state)}`, required: s.required_state, points: [t] });
    }
  }
  rows.push({ kind: "process", label: "Procedure: steps in order, independence, reset", points: [] });
  rows.forEach((r, i) => { r.n = i + 1; r.findings = []; r.camera = []; });
  return rows;
}

function rowFor(rows, f, cameraPoint) {
  if (f.source === "process") return rows.filter((r) => r.kind === "process");
  if (f.source === "camera") return rows.filter((r) => r.step === f.step && r.point === cameraPoint);
  const mine = rows.filter((r) => r.step === f.step);
  if (!mine.length) return [];
  const refs = new Set(f.refs || []);
  if (!refs.size || mine.length === 1) return mine;
  // a multi-valve step: the finding belongs to the rows whose own tags it names
  const named = mine.filter((r) => r.points.some((p) => refs.has(p)) || Object.values(r.tags || {}).some((t) => t && refs.has(t)));
  return named.length ? named : mine;
}

const worst = (fs) => fs.reduce((w, f) => (RANK[f.status] > (RANK[w] || 0) ? f.status : w), null);

export async function checkScreen(root, params) {
  // automated runs (tests, recordings) start muted: navigator.webdriver, or ?mute=1
  const voice = speaker(navigator.webdriver === true || params.get("mute") === "1");
  const st = { plans: [], plan: null, sid: null, detail: null, rows: [], evals: new Map(), cams: new Map(), es: null, closed: false, run: 0 };
  const text = el("textarea", { id: "check-text", rows: 2, cols: 70, placeholder: EXAMPLE });
  const status = el("div", { id: "check-status" });
  const sessionLine = el("div", { id: "check-session" });
  const list = el("div", { id: "check-list" });
  const camera = el("div", { id: "check-camera", class: "panel" });
  const finalLine = el("div", { id: "check-final" });
  const stepPanel = el("div", { id: "check-steps" });
  const explain = el("div", { id: "check-explain" });
  const all = el("details", { id: "check-findings" });
  const voiceNote = el("p", { class: "small muted", id: "voice-note" }, voice.note());
  const spokenLine = el("p", { id: "spoken-line", class: "spoken" });
  const mute = el("button", { type: "button", id: "mute", onclick: () => {
    voice.muted = !voice.muted; if (voice.muted) voice.stop(); mute.textContent = voice.muted ? "Unmute" : "Mute"; voiceNote.textContent = voice.note();
  } }, voice.muted ? "Unmute" : "Mute");
  let recording = null;
  const mic = el("button", { type: "button", id: "mic", title: "Hold a short request; Muse Voice Transcribe turns it into text on the server",
    onclick: async () => {
      if (recording) { recording.stop(); return; }
      let stop; const sig = new Promise((r) => { stop = r; });
      recording = { stop };
      mic.textContent = "■ Stop recording";
      try {
        const audio = await recordWav(sig);
        mic.textContent = "🎤 Speak";
        await resolve({ audio });
      } catch (e) { status.replaceChildren(el("p", { class: "error" }, `Microphone: ${errorText(e)}`)); mic.textContent = "🎤 Speak"; }
      recording = null;
    } }, "🎤 Speak");
  setTimeout(() => { voiceNote.textContent = voice.note(); }, 800); // voices load late in some browsers

  root.append(el("h1", {}, "Check my isolation"),
    el("p", { class: "small muted" }, "ZeroState reads the logged checks back to you, one by one. It can raise a STOP; it never tells you to go. You decide, and the issuer signs."),
    el("p", { class: "small", id: "site-mode" }, "On this site the plant data is recorded (demo runs on the GRFICS simulator, tuning seeds; the operator actions in them are by the test harness). Your typed or spoken request, step commands and Why? go live to Muse Spark and Muse Voice Transcribe. ", ...[["S8_seed503_20261104T125324", "feedback lied (S8)"], ["S0_seed502_20261104T124516", "clean job (S0)"]].flatMap(([sid, what]) => [el("br"), `${what}: `, el("a", { href: `#/check?session=${sid}` }, "walk through the recorded checks"), " · ", el("a", { href: `#/check?session=${sid}&steps=1` }, "mark the steps yourself")])),
    el("section", { class: "panel", id: "check-request" },
      el("label", { class: "block" }, "What are you about to do? ", text),
      el("div", { class: "actions" },
        el("button", { type: "button", id: "check-go", onclick: () => resolve({ text: text.value.trim() || EXAMPLE }) }, "Check"),
        mic, mute, el("span", { class: "small muted" }, "The microphone recording goes to Muse Voice Transcribe through this site's model function; no browser speech service is used.")),
      voiceNote, status),
    sessionLine, stepPanel, spokenLine, el("div", { class: "cols check-cols" }, el("div", {}, list, finalLine, explain), el("div", {}, camera)), all);

  // ---------- request -> plan (read-only)
  async function resolve(body) {
    status.replaceChildren(el("p", { class: "muted" }, "Matching your request to a confirmed plan…"));
    try {
      const r = await api("/api/checks/resolve", { json: body });
      st.plans = r.plans;
      if (body.audio) text.value = r.text || "";
      if (!r.plan) {
        status.replaceChildren(el("p", { id: "check-unclear", class: "unclear-msg" },
          `I can't tell which equipment you mean${r.reason ? `: ${r.reason}` : "."} Pick one of the confirmed plans:`), planPicker(r.plans));
        return;
      }
      status.replaceChildren(el("p", { id: "check-picked" }, `Plan: ${r.plan.equipment} (${r.plan.task || "no task text"}) on ${r.plan.plant}, confirmed by ${r.plan.confirmed_by}. ${r.reason || ""}`));
      await attach(r.plan);
    } catch (e) {
      status.replaceChildren(el("p", { class: "error" }, e.status === 503 ? "The model is not available here, so I can't match your request. Pick a confirmed plan:" : errorText(e)));
      if (e.status === 503) status.append(planPicker(await api("/api/checks/plans").catch(() => [])));
    }
  }
  function planPicker(plans) {
    return el("ul", { id: "plan-picker" }, plans.map((p) => el("li", {},
      el("button", { type: "button", "data-plan": p.id, onclick: () => { status.replaceChildren(el("p", {}, `Plan: ${p.equipment} on ${p.plant} (picked by you).`)); attach(p); } },
        `${p.equipment} — ${p.task || "no task text"} (${p.plant}, plan ${p.plan_hash.slice(0, 8)}…, confirmed by ${p.confirmed_by})`))));
  }

  // ---------- plan -> the current or most recent session of that plan
  async function attach(plan) {
    st.plan = plan;
    const sessions = (await api("/api/sessions")).filter((x) => x.plan_hash === plan.plan_hash);
    if (!sessions.length) { sessionLine.replaceChildren(el("p", { class: "panel" }, "No session has run on this plan yet. A session is started from the console by a person; this view only reads.")); return; }
    const want = params.get("session");
    const s = sessions.find((x) => x.id === want) || sessions[0];
    const pick = el("select", { id: "session-pick", onchange: () => open(pick.value, sessions) },
      sessions.map((x) => el("option", { value: x.id, selected: x.id === s.id }, `${x.id} · started ${new Date(x.started * 1000).toLocaleString()}`)));
    sessionLine.replaceChildren(el("div", { class: "panel" }, el("label", {}, "Session ", pick), " ", el("span", { id: "recorded-label" })));
    await open(s.id, sessions);
  }

  async function open(sid, sessions) {
    const run = ++st.run;
    if (st.es) st.es.close();
    voice.stop();
    st.sid = sid; st.evals = new Map(); st.cams = new Map();
    st.detail = await api(`/api/sessions/${encodeURIComponent(sid)}`);
    st.rows = buildRows(st.detail.plan);
    const last = Math.max(st.detail.started || 0, ...st.detail.findings.map((f) => f.t || 0));
    const recorded = !st.detail.rehearsal && (["closed", "stopped", "refused"].includes(st.detail.state) || st.detail.signature || Date.now() / 1000 - last > 120);
    const sum = sessions.find((x) => x.id === sid);
    document.getElementById("recorded-label").replaceChildren(
      el("span", { class: recorded ? "badge recorded" : "badge" }, recorded ? "Recorded session" : "Rehearsal: your marks on a recorded session"),
      ` ${sid}, started ${sum ? new Date(sum.started * 1000).toLocaleString() : time(st.detail.started)}`);
    finalLine.replaceChildren(); explain.replaceChildren(); stepPanel.replaceChildren(); camera.replaceChildren(el("p", { class: "muted" }, "Camera view appears with each valve check."));
    drawList(new Set());
    // the stream carries each evaluation's window (the readings) and every finding, in log order
    await new Promise((ready) => {
      const es = new EventSource(`/api/sessions/${encodeURIComponent(sid)}/stream`);
      st.es = es;
      let seen = 0;
      const total = st.detail.findings.length;
      es.addEventListener("evaluation", (ev) => { const e = JSON.parse(ev.data); st.evals.set(e.id, e.payload); });
      es.addEventListener("finding", () => { seen += 1; if (recorded && seen >= total) { es.close(); ready(); } });
      for (const k of ["verdict", "signature", "session_stopped"]) es.addEventListener(k, () => refreshDetail(run));
      if (!recorded) for (const k of ["evaluation", "finding", "step", "step_verify", "step_reopen", "verdict", "camera_reading", "signature", "session_stopped"]) es.addEventListener(k, () => liveSoon(run));
      es.onerror = () => { es.close(); ready(); };
      if (!recorded || total === 0) ready();
    });
    if (run !== st.run) return;
    if (recorded) await walk(run, recorded);
    else liveMode(run);
  }
  async function refreshDetail(run) {
    if (run !== st.run || st.closed) return;
    st.detail = await api(`/api/sessions/${encodeURIComponent(st.sid)}`).catch(() => st.detail);
  }

  // ---------- assign logged findings to rows (log order, nothing dropped)
  function assign() {
    for (const r of st.rows) { r.findings = []; r.camera = []; }
    for (const f of st.detail.findings) {
      const e = st.evals.get(f.eval_id) || {};
      for (const r of rowFor(st.rows, f, e.point)) (f.source === "camera" ? r.camera : r.findings).push(f);
    }
  }
  const lastSample = (tag, evalIds) => {
    for (const id of [...evalIds].reverse()) {
      const w = (st.evals.get(id) || {}).window;
      const rows = w && w.samples && w.samples[tag];
      if (rows && rows.length) return { v: rows[rows.length - 1][1], span: (w.spans || {})[tag] };
    }
    return null;
  };
  async function cameraOf(r) {
    const f = r.camera[r.camera.length - 1];
    if (!f) return null;
    if (!st.cams.has(f.eval_id)) st.cams.set(f.eval_id, await api(`/api/sessions/${encodeURIComponent(st.sid)}/camera/${f.eval_id}`).catch(() => null));
    return st.cams.get(f.eval_id);
  }
  function readings(r, cam) {
    const ids = r.findings.filter((f) => f.source === "step").map((f) => f.eval_id);
    const evalIds = ids.length ? ids : r.findings.map((f) => f.eval_id);
    const out = {};
    if (r.kind === "valve") {
      const fb = r.tags.fb && lastSample(r.tags.fb, evalIds), fl = r.tags.flow && lastSample(r.tags.flow, evalIds);
      out.plc = fb ? `${fmt(fb.v, 1)} % open` : "no reading logged";
      out.flow = fl ? `${fmt(fl.v, 1)}${fl.span ? ` (${fmt((100 * (fl.v - fl.span[0])) / (fl.span[1] - fl.span[0]), 0)} % of full scale)` : ""}` : r.tags.flow ? "no reading logged" : "no flow meter on this valve";
      const vals = cam ? cam.readings.map((x) => (x.readable ? `${fmt(x.value, 0)} %` : "unreadable")) : [];
      out.cam = cam ? `${vals.join(", ")} open` : r.camera.length ? "camera evidence not available" : "no camera reading";
    } else if (r.kind === "mode") {
      const m = lastSample(r.tag, evalIds);
      out.plc = m ? `${fmt(m.v, 0)}` : "no reading logged";
    }
    return out;
  }
  const rowStatus = (r) => worst([...r.findings, ...r.camera]);

  function spoken(r, rd) {
    const s = rowStatus(r);
    const end = s ? WORD[s] : "Not checked.";
    if (r.kind === "valve") return `Check ${r.n}: ${r.label.split(":")[0]}. PLC feedback reads ${rd.plc}. Flow meter reads ${rd.flow}. Camera reads ${rd.cam}. ${end}`;
    if (r.kind === "hold") { const h = r.findings.find((f) => f.rule_id === "LIVE-HOLD"); return `Check ${r.n}: hold test. ${h ? h.message : "no hold result logged"}. ${end}`; }
    if (r.kind === "mode") return `Check ${r.n}: PLC manual mode reads ${rd.plc}. ${end}`;
    return `Check ${r.n}: procedure. ${end}`;
  }

  // ---------- render
  function drawList(shown, current = null) {
    const tbl = el("table", { class: "grid", id: "checklist" },
      el("thead", {}, el("tr", {}, ["#", "Check", "PLC feedback", "Flow meter", "Camera", "Mark", "Logged findings", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, st.rows.map((r) => {
        const on = shown.has(r.n), s = on ? rowStatus(r) : null;
        const rd = on ? r.rd || {} : {};
        const fails = [...r.findings, ...r.camera].filter((f) => f.status !== "PASS");
        return el("tr", { "data-row": r.n, class: `${on ? `f-${s || "none"}` : "pending"}${current === r.n ? " current" : ""}` },
          el("td", {}, r.n), el("td", {}, r.label),
          el("td", {}, rd.plc || "—"), el("td", {}, rd.flow || "—"), el("td", {}, rd.cam || "—"),
          el("td", { class: "mark", "data-mark": on ? s || "none" : "pending" }, on ? (s ? `${MARK[s]} ${s}` : "– not checked") : "…"),
          el("td", { class: "small" }, on ? (fails.length ? `${fails[0].id}: ${fails[0].message}` : r.findings.length || r.camera.length ? `${r.findings.length + r.camera.length} logged, all PASS` : "no logged finding") : ""),
          el("td", {}, on && s === "FAIL" ? el("button", { type: "button", class: "why", "data-why": r.n, onclick: () => why(r, fails[0]) }, "Why?") : null));
      })));
    list.replaceChildren(el("h2", {}, "Checklist (plan order)"), tbl);
    const fs = st.detail ? st.detail.findings : [];
    all.replaceChildren(el("summary", {}, `All logged findings (${fs.length}), in log order`),
      el("ol", { class: "small" }, fs.map((f) => el("li", { id: `finding-${f.id}` }, `${f.id} · ${f.status} · ${f.source} step ${f.step ?? "—"} · ${f.message}`))));
  }

  async function drawCamera(r, cam, animate = true) {
    if (r.kind !== "valve") return; // no camera for this check: the panel keeps the last valve
    const head = el("h2", {}, `Check ${r.n}: ${r.label.split(":")[0]}`);
    const side = el("div", { class: "witnesses", id: "witnesses" },
      ["PLC feedback", "Flow meter", "Camera"].map((k, i) => el("div", { class: "witness" }, el("div", { class: "small muted" }, k),
        el("div", { class: "witness-value" }, [r.rd.plc, r.rd.flow, r.rd.cam][i] || "—"))));
    const reading = cam && cam.readings.find((x) => x.frame_url && x.box);
    if (!reading) { camera.replaceChildren(head, el("p", { id: "no-frame", class: "no-frame" }, "no camera frame for this check"), side); return; }
    const canvas = el("canvas", { id: "zoom", width: 640, height: 360, class: "zoom" });
    camera.replaceChildren(head, el("figure", { class: "zoomfig" }, canvas, el("figcaption", { id: "camera-caption", class: "camera-label" }, CAMERA_CAPTION)),
      el("p", { class: "small muted" }, `SAM 3.1 box (dashed) around ${cam.point}'s display; frame ${reading.frame_sha256.slice(0, 12)}…, ${time(reading.t)}. ${cam.label}.`), side);
    const img = new Image();
    img.src = reading.frame_url;
    await img.decode().catch(() => null);
    if (!img.naturalWidth) { canvas.replaceWith(el("p", { id: "no-frame", class: "no-frame" }, "no camera frame for this check")); return; }
    const [x1, y1, x2, y2] = reading.box, W = img.naturalWidth, H = img.naturalHeight;
    const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2, zw = Math.min(W, Math.max(6 * (x2 - x1), 240)), zh = zw * 9 / 16;
    const target = { x: Math.max(0, Math.min(W - zw, cx - zw / 2)), y: Math.max(0, Math.min(H - zh, cy - zh / 2)), w: zw, h: zh };
    const full = { x: 0, y: 0, w: W, h: W * 9 / 16 > H ? H : W * 9 / 16 };
    const g = canvas.getContext("2d");
    const t0 = performance.now() - (animate ? 0 : 1200); // the return to the deciding check is shown zoomed at once
    await new Promise((done) => {
      const frame = (now) => {
        const k = Math.min(1, (now - t0) / 1200), e = k * k * (3 - 2 * k);
        const v = { x: full.x + (target.x - full.x) * e, y: full.y + (target.y - full.y) * e, w: full.w + (target.w - full.w) * e, h: full.h + (target.h - full.h) * e };
        g.drawImage(img, v.x, v.y, v.w, v.h, 0, 0, canvas.width, canvas.height);
        const sx = canvas.width / v.w, sy = canvas.height / v.h;
        g.setLineDash([8, 4]); g.lineWidth = 3; g.strokeStyle = "#000"; g.strokeRect((x1 - v.x) * sx, (y1 - v.y) * sy, (x2 - x1) * sx, (y2 - y1) * sy);
        g.setLineDash([]); g.lineWidth = 1; g.strokeStyle = "#fff"; g.strokeRect((x1 - v.x) * sx - 2, (y1 - v.y) * sy - 2, (x2 - x1) * sx + 4, (y2 - y1) * sy + 4);
        if (k < 1) requestAnimationFrame(frame); else done();
      };
      requestAnimationFrame(frame);
    });
  }

  // ---------- final line: exactly one of STOP / no discrepancy, from the engine's logged verdict
  function finalText(checked) {
    const d = st.detail, t = d.tracks || {};
    const data = t.data_only ? t.data_only.verdict : d.verdict, cam = t.with_camera ? t.with_camera.verdict : d.verdict_with_camera;
    const equip = (d.plan && d.plan.work && d.plan.work.equipment) || "the equipment";
    const verdicts = [data, cam].filter(Boolean);
    if (verdicts.includes("BLOCKED") || verdicts.includes("ESCALATED")) {
      const blocked = verdicts.includes("BLOCKED");
      const reason = ((blocked ? [t.data_only, t.with_camera].find((x) => x && x.verdict === "BLOCKED") : [t.data_only, t.with_camera].find((x) => x && x.verdict === "ESCALATED")) || {}).reasons || [];
      const want = blocked ? "FAIL" : "UNKNOWN";
      const f = d.findings.find((x) => x.status === want && reason.some((s) => s === `${x.rule_id}: ${x.message}`)) || d.findings.find((x) => x.status === want);
      const r = f && st.rows.find((x) => [...x.findings, ...x.camera].some((y) => y.id === f.id));
      let plain = f ? f.message : reason[0] || "see the logged findings";
      const head = blocked ? `STOP. Do not open the ${equip}.` : "STOP: ZeroState could not tell.";
      let say = `${head} ${r ? `Check ${r.n}, ${r.label.split(":")[0]}` : f ? f.rule_id : "A check"} ${blocked ? "failed" : "could not be read"}.`;
      if (r && r.kind === "valve" && r.rd) {
        const flowSays = r.findings.some((x) => x.status === "FAIL" && r.tags.flow && (x.refs || []).includes(r.tags.flow));
        const camSays = r.camera.some((x) => x.status === "FAIL");
        const n = (flowSays ? 1 : 0) + (camSays ? 1 : 0);
        plain = `${r.point}: the PLC reads ${r.rd.plc}, the flow meter reads ${r.rd.flow}, the camera reads ${r.rd.cam}.${n ? ` ${n} of 3 witnesses disagree with the PLC.` : ""} Logged finding ${f.id}: ${f.message}.`;
        const what = [flowSays ? "the flow meter reads flow" : null, camSays ? "the camera reads it open" : null].filter(Boolean);
        if (what.length && !r.rd.plc.startsWith("no ")) say = `${head} ${r.point}: ${what.join(" and ")} while the PLC reads ${r.rd.plc}. ${n} of 3 witnesses disagree.`;
      } else if (f) plain = `Logged finding ${f.id}: ${f.message}.`;
      return { stop: true, text: `${head} ${plain}`, say, f, row: r };
    }
    if (data === NDF && (cam === NDF || cam === null || cam === undefined)) {
      const text = `No discrepancy found in ${checked} checks. This is not a safety call; the issuer signs.`;
      return { stop: false, text, say: text };
    }
    return null;
  }

  async function walk(run, recorded) {
    assign();
    const shown = new Set();
    for (const r of st.rows) {
      if (run !== st.run || st.closed) return;
      const has = r.findings.length || r.camera.length;
      if (!has) { shown.add(r.n); continue; } // shown as "not checked" without being spoken
      const cam = await cameraOf(r);
      r.rd = readings(r, cam);
      shown.add(r.n);
      drawList(shown, r.n);
      const said = spoken(r, r.rd);
      spokenLine.textContent = `🔈 ${said}`;
      await Promise.all([drawCamera(r, cam), voice.say(said)]);
    }
    if (run !== st.run || st.closed) return;
    drawList(shown);
    if (!recorded) await refreshDetail(run);
    await showFinal(run);
  }

  async function showFinal(run) {
    const fin = finalText(st.rows.filter((r) => r.findings.length || r.camera.length).length);
    if (!fin) { finalLine.replaceChildren(el("p", { class: "final evaluating", id: "final-line" }, "Evaluating… no verdict is logged yet.")); return null; }
    finalLine.replaceChildren(el("p", { class: `final ${fin.stop ? "final-stop" : "final-ndf"}`, id: "final-line" }, fin.text),
      el("p", { class: "small muted" }, "This view only reads the log. Sign-off is done by a person in the lab console, never on this site."));
    spokenLine.textContent = `🔈 ${fin.say}`;
    // a STOP brings the camera back to the deciding check
    const back = fin.row && fin.row.kind === "valve" ? drawCamera(fin.row, await cameraOf(fin.row), false) : null;
    if (run === st.run && !st.closed) await Promise.all([back, voice.say(fin.say)]);
    return fin;
  }

  // ---------- live step mode: the worker marks each step here (typed or spoken), only after confirming the
  // read-back of the existing voice route; it never verifies, reopens or signs. Rows tick as the engine logs them.
  const live = { shown: new Set(), sig: new Map(), checking: null, pendingK: null, ended: false, timer: null, chain: Promise.resolve() };
  const stepText = (x) => {
    const what = (x.targets || []).join(" and ") || x.kind.replace("_", " ");
    const rs = x.required_state;
    return `${what}${x.kind === "mode" ? ` = ${rs}` : rs === null || rs === undefined ? "" : rs <= 5 ? " closed" : rs >= 95 ? " open" : ` ${rs} %`}`;
  };
  const say = (t) => { spokenLine.textContent = `🔈 ${t}`; return voice.say(t); };
  function liveSoon(run) {
    if (live.timer) return;
    live.timer = setTimeout(() => { live.timer = null; live.chain = live.chain.then(() => liveTick(run)).catch(() => null); }, 250);
  }
  function liveMode(run) {
    Object.assign(live, { shown: new Set(), sig: new Map(), checking: null, pendingK: null, ended: false });
    const name = el("input", { id: "worker-name", size: 18, placeholder: "your name" });
    const cmd = el("input", { id: "step-cmd", size: 36, placeholder: "e.g. step 1 done" });
    const readBack = el("div", { id: "read-back" });
    let rec = null;
    const micStep = el("button", { type: "button", id: "step-mic", onclick: async () => {
      if (rec) { rec.stop(); return; }
      let stop; const sig = new Promise((r) => { stop = r; });
      rec = { stop }; micStep.textContent = "■ Stop";
      try { await command({ audio: await recordWav(sig) }); } catch (e) { readBack.replaceChildren(el("p", { class: "error" }, `Microphone: ${errorText(e)}`)); }
      rec = null; micStep.textContent = "🎤 Speak";
    } }, "🎤 Speak");
    async function command(body) {
      if (live.ended) return;
      const r = await api("/api/voice/command", { json: { session: st.sid, ...body } }).catch((e) => ({ intent: "unknown", read_back: errorText(e) }));
      if (body.audio) cmd.value = r.transcript || "";
      if (r.intent === "confirm" && live.pendingK !== null) { await confirmMark(); return; }
      if (r.intent === "cancel") { live.pendingK = null; readBack.replaceChildren(el("p", { id: "read-back-text" }, r.read_back)); say(r.read_back); return; }
      if (r.intent === "step_done") {
        live.pendingK = r.k;
        readBack.replaceChildren(el("p", { id: "read-back-text" }, r.read_back),
          el("button", { type: "button", id: "confirm-mark", onclick: confirmMark }, "Confirm"), " ",
          el("button", { type: "button", id: "cancel-mark", onclick: () => { live.pendingK = null; readBack.replaceChildren(el("p", {}, "Cancelled. Nothing was marked.")); } }, "Cancel"));
      } else readBack.replaceChildren(el("p", { id: "read-back-text" }, r.read_back || "I did not catch that."));
      say(r.read_back || "I did not catch that.");
    }
    async function confirmMark() {
      const k = live.pendingK, by = name.value.trim();
      if (k === null) return;
      if (!by) { readBack.replaceChildren(el("p", { class: "error" }, "Type your name first: the mark is logged under it.")); return; }
      live.pendingK = null;
      try {
        await api(`/api/sessions/${encodeURIComponent(st.sid)}/steps/${k}/done`, { json: { by } });
        live.checking = k; cmd.value = "";
        readBack.replaceChildren(el("p", { id: "read-back-text" }, `Step ${k} marked done by ${by}.`));
        say(`ZeroState is checking step ${k}.`);
      } catch (e) { readBack.replaceChildren(el("p", { class: "error" }, errorText(e))); }
      drawSteps();
      liveSoon(run);
    }
    live.ui = { readBack };
    live.form = el("div", { class: "actions", id: "step-form" }, el("label", {}, "Your name ", name),
      el("label", {}, " Step ", cmd),
      el("button", { type: "button", id: "step-send", onclick: () => cmd.value.trim() && command({ transcript: cmd.value.trim(), asr: "typed" }) }, "Send"),
      micStep, el("span", { class: "small muted" }, "A step is marked only after you confirm the read-back. Verify, reopen and sign stay in the job screen."));
    drawSteps();
    liveSoon(run);
  }
  function drawSteps() {
    const d = st.detail, steps = d.steps.filter((x) => x.kind !== "final");
    const next = steps.find((x) => !x.marked_by);
    const checked = (k) => d.findings.some((f) => f.step === k && f.source === "step");
    if (live.checking !== null && checked(live.checking)) live.checking = null;
    const waiting = steps.filter((x) => x.marked_by && !checked(x.k)).pop(); // marked (here or in the console), not yet evaluated
    if (live.checking === null && waiting) live.checking = waiting.k;
    let prompt;
    if (live.ended) prompt = "No further steps are prompted.";
    else if (live.checking !== null) prompt = `ZeroState is checking step ${live.checking}…`;
    else if (next) prompt = `Waiting: do step ${next.k} (${stepText(next)}), then say "step ${next.k} done".`;
    else prompt = "Every step is marked. Waiting for the engine's verdict.";
    const verify = steps.filter((x) => x.kind === "isolate" && x.marked_by && !x.verified_by).map((x) => el("li", { "data-verify": x.k },
      `Step ${x.k}: the recording's second-person verification appears with this step's result `, el("a", { href: `#/job/${encodeURIComponent(st.sid)}` }, "open the job page")));
    stepPanel.replaceChildren(el("section", { class: "panel", id: "live-steps" }, el("h2", {}, "Live steps"),
      el("p", { id: "step-prompt", class: "step-prompt" }, prompt),
      el("ol", { class: "small" }, steps.map((x) => el("li", { "data-step": x.k },
        `Step ${x.k}: ${stepText(x)} — ${x.marked_by ? `marked by ${x.marked_by}` : "not marked"}${x.verified_by ? `, verified by ${x.verified_by}` : ""}`))),
      verify.length ? el("ul", { id: "verify-wait" }, verify) : null,
      live.ended ? null : live.form, live.ended ? null : live.ui.readBack));
  }
  async function liveTick(run) {
    if (run !== st.run || st.closed) return;
    await refreshDetail(run);
    assign();
    for (const r of st.rows) {
      if (!(r.findings.length || r.camera.length)) continue;
      const sig = `${rowStatus(r)}:${r.camera.length > 0}`;
      if (live.sig.get(r.n) === sig) continue;
      live.sig.set(r.n, sig);
      const cam = await cameraOf(r);
      r.rd = readings(r, cam);
      live.shown.add(r.n);
      drawList(live.shown, r.n);
      drawSteps();
      await Promise.all([drawCamera(r, cam), say(spoken(r, r.rd))]);
      if (run !== st.run || st.closed) return;
    }
    drawList(live.shown);
    const d = st.detail, t = d.tracks || {};
    const v = [t.data_only ? t.data_only.verdict : d.verdict, t.with_camera ? t.with_camera.verdict : d.verdict_with_camera];
    const stop = v.includes("BLOCKED") || v.includes("ESCALATED");
    const hold = d.steps.find((x) => x.kind === "hold");
    const done = v[0] === NDF && d.steps.filter((x) => x.kind !== "final").every((x) => x.marked_by) && (!hold || hold.result !== null);
    if ((stop || done) && !live.ended) {
      live.ended = true; // on a STOP no further steps are prompted
      drawSteps();
      for (const r of st.rows) live.shown.add(r.n);
      drawList(live.shown);
      await showFinal(run);
      return;
    }
    drawSteps();
  }

  // ---------- "Why?" -> explain on that finding (read-only)
  async function why(r, f) {
    const q = `Why did check ${r.n} (${r.label}) fail? Finding ${f.id}.`;
    explain.replaceChildren(el("h2", {}, "Why?"), el("p", { class: "small" }, q), el("p", { class: "muted" }, "Asking…"));
    try {
      const a = await api(`/api/sessions/${encodeURIComponent(st.sid)}/explain`, { json: { question: q } });
      explain.replaceChildren(el("h2", {}, "Why?"), el("p", { class: "small" }, q), el("p", { id: "why-answer" }, a.answer),
        el("p", { class: "small" }, "Cited: ", a.cites.length ? a.cites.flatMap((id, i) => [i ? ", " : null, el("a", { href: `#/job/${encodeURIComponent(st.sid)}`, class: "cite" }, id)]) : "none"),
        el("p", { class: "small muted" }, "Muse Spark explains the logged findings only; it can't change a verdict."));
      await voice.say(a.answer);
    } catch (e) {
      explain.replaceChildren(el("h2", {}, "Why?"), el("p", { class: "error" }, e.status === 503 ? "Explain needs the model, which is not available here." : errorText(e)),
        el("p", {}, `Logged finding ${f.id}: ${f.message}`));
    }
  }

  if (params.get("q")) { text.value = params.get("q"); resolve({ text: text.value }); }
  return () => { st.closed = true; voice.stop(); if (st.es) st.es.close(); };
}
