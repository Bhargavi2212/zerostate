// Site only: maps the console's GET /api/... calls onto the recorded files under data/; every write is refused.
// The event stream becomes a recorded event list (data/sessions/<id>/stream.json), played at ?speed=N if given.
(() => {
  const realFetch = window.fetch.bind(window);
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  function file(path) {
    let m;
    if (path === "/api/sessions") return "data/sessions.json";
    if ((m = path.match(/^\/api\/plants\/([\w-]+)\/map$/))) return `data/plants/${m[1]}/map.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/camera\/(\d+)$/))) return `data/sessions/${m[1]}/camera/${m[2]}.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/stream(\?.*)?$/))) return `data/sessions/${m[1]}/stream.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)$/))) return `data/sessions/${m[1]}/detail.json`;
    return null;
  }
  window.fetch = (path, init = {}) => {
    if (typeof path !== "string" || !path.startsWith("/api/")) return realFetch(path, init);
    if ((init.method || "GET").toUpperCase() !== "GET") return Promise.resolve(json(409, { error: "replay", detail: "recorded replay: read-only" }));
    const f = file(path);
    return f ? realFetch(f) : Promise.resolve(json(404, { error: "not_found", detail: "not in this recorded replay" }));
  };
  class RecordedEvents {
    constructor(url) {
      this.listeners = {}; this.onerror = null; this.closed = false;
      const speed = Number(new URL(url, location.href).searchParams.get("speed")) || 0;
      window.fetch(url).then((r) => r.json()).then(async (list) => {
        let prev = null;
        for (const e of list) {
          const t = JSON.parse(e.data).t;
          if (speed && prev !== null && typeof t === "number") await new Promise((ok) => setTimeout(ok, Math.max(0, (t - prev) * 1000 / speed)));
          if (typeof t === "number") prev = t;
          if (this.closed) return;
          for (const fn of this.listeners[e.event] || []) fn({ data: e.data });
        }
        if (!this.closed && this.onerror) this.onerror();
      });
    }
    addEventListener(kind, fn) { (this.listeners[kind] = this.listeners[kind] || []).push(fn); }
    close() { this.closed = true; }
  }
  window.EventSource = RecordedEvents;
})();
