// Site only: maps the console's GET /api/... calls onto the recorded files under data/. Writes are refused, except:
// - the "Check my isolation" model calls (request matching, speech-to-text, Why?) go live to /api/model;
// - with #/check?...&steps=1 the visitor marks steps on a recorded session in this page only (a rehearsal: step k's
//   recorded findings appear a moment after the visitor marks k; nothing is stored or sent anywhere).
// The event stream becomes a recorded event list (data/sessions/<id>/stream.json), played at ?speed=N if given.
(() => {
  const realFetch = window.fetch.bind(window);
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const REVEAL_MS = 2500;
  const rehearsing = () => new URLSearchParams(location.hash.split("?")[1] || "").get("steps") === "1";
  const marks = {}; // session id -> {k: {by, t}}, this page only
  const streams = new Set();
  function file(path) {
    let m;
    if (path === "/api/sessions") return "data/sessions.json";
    if (path === "/api/checks/plans") return "data/checks/plans.json";
    if ((m = path.match(/^\/api\/plants\/([\w-]+)\/map$/))) return `data/plants/${m[1]}/map.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/camera\/(\d+)$/))) return `data/sessions/${m[1]}/camera/${m[2]}.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/stream(\?.*)?$/))) return `data/sessions/${m[1]}/stream.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)$/))) return `data/sessions/${m[1]}/detail.json`;
    return null;
  }
  // the recorded session as it stands after the visitor's marks: later steps unmarked, their findings and the
  // verdict held back until the visitor reaches the last step the recording evaluated
  function rehearsal(d) {
    const mine = marks[d.id] || {}, now = Date.now();
    const evaluated = Math.max(0, ...d.findings.filter((f) => f.step !== null && f.step !== undefined).map((f) => f.step));
    const shown = Math.max(0, ...Object.entries(mine).filter(([, m]) => now - m.t >= REVEAL_MS).map(([k]) => Number(k)));
    const out = { ...d, state: "running", signature: null };
    out.steps = d.steps.map((s) => {
      const m = mine[s.k], seen = m && s.k <= shown;
      return { ...s, marked_by: m ? m.by : null, marked_t: m ? m.t / 1000 : null, result: seen ? s.result : null,
        verified_by: seen ? s.verified_by : null, verified_t: seen ? s.verified_t : null, finding_ids: seen ? s.finding_ids : [] };
    });
    out.findings = d.findings.filter((f) => (f.step === null || f.step === undefined ? shown >= evaluated : f.step <= shown));
    if (shown < evaluated) {
      out.verdict = null; out.verdict_with_camera = null;
      out.tracks = Object.fromEntries(Object.entries(d.tracks || {}).map(([k, t]) => [k, t && { ...t, verdict: null, reasons: [] }]));
    }
    out.rehearsal = { evaluated, shown };
    return out;
  }
  async function detail(sid) {
    const d = await (await realFetch(`data/sessions/${sid}/detail.json`)).json();
    return rehearsing() ? rehearsal(d) : d;
  }
  async function mark(sid, k, by) {
    const d = rehearsal(await (await realFetch(`data/sessions/${sid}/detail.json`)).json());
    const next = d.steps.find((s) => s.kind !== "final" && !s.marked_by);
    if (!by) return json(400, { error: "bad_input", detail: "type your name first" });
    if (!next || next.k !== k) return json(409, { error: "conflict", detail: next ? `mark step ${next.k} first` : "every step is marked" });
    if (k > d.rehearsal.evaluated) return json(409, { error: "conflict", detail: `the recording stops before step ${k}` });
    (marks[sid] = marks[sid] || {})[k] = { by, t: Date.now() };
    setTimeout(() => { for (const s of streams) if (!s.closed && s.sid === sid) s.emit("finding", "{}"); }, REVEAL_MS + 50);
    return json(200, { queued: true, k, by });
  }
  const model = (body) => realFetch("/api/model", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  window.fetch = async (path, init = {}) => {
    if (typeof path !== "string" || !path.startsWith("/api/")) return realFetch(path, init);
    let m;
    const method = (init.method || "GET").toUpperCase();
    if (method !== "GET") {
      const body = init.body ? JSON.parse(init.body) : {};
      if (path === "/api/checks/resolve") return model({ op: "resolve", ...body });
      if (path === "/api/voice/command") {
        const d = body.session ? await detail(body.session).catch(() => null) : null;
        return model({ op: "voice", ...body, detail: d && { plan: d.plan, steps: d.steps, verdict: d.verdict, verdict_with_camera: d.verdict_with_camera, tracks: d.tracks } });
      }
      if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/explain$/))) return model({ op: "explain", session: m[1], question: body.question });
      if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/steps\/(\d+)\/done$/)) && rehearsing()) return mark(m[1], Number(m[2]), String(body.by || "").trim());
      return json(409, { error: "replay", detail: "recorded replay: read-only" });
    }
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)$/))) return json(200, await detail(m[1]));
    const f = file(path);
    return f ? realFetch(f) : json(404, { error: "not_found", detail: "not in this recorded replay" });
  };
  class RecordedEvents {
    constructor(url) {
      this.listeners = {}; this.onerror = null; this.closed = false;
      this.sid = (url.match(/^\/api\/sessions\/([\w-]+)\/stream/) || [])[1];
      streams.add(this);
      const speed = Number(new URL(url, location.href).searchParams.get("speed")) || 0;
      window.fetch(url).then((r) => r.json()).then(async (list) => {
        let prev = null;
        for (const e of list) {
          const t = JSON.parse(e.data).t;
          if (speed && prev !== null && typeof t === "number") await new Promise((ok) => setTimeout(ok, Math.max(0, (t - prev) * 1000 / speed)));
          if (typeof t === "number") prev = t;
          if (this.closed) return;
          this.emit(e.event, e.data);
        }
        if (!this.closed && this.onerror && !rehearsing()) this.onerror(); // a rehearsal stays open for the visitor's marks
      });
    }
    emit(kind, data) { for (const fn of this.listeners[kind] || []) fn({ data }); }
    addEventListener(kind, fn) { (this.listeners[kind] = this.listeners[kind] || []).push(fn); }
    close() { this.closed = true; streams.delete(this); }
  }
  window.EventSource = RecordedEvents;
})();
