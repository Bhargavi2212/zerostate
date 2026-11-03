// Screen A, New isolation: import (Type / Upload / CSV) -> editable draft table with "plant default"
// badges and unclear cells -> live plan check + plant view -> Confirm dialog (a person, by name).
// Confirm stays disabled while anything is unclear; the API refuses it too (409).
import { api, el, errorText, statusMark } from "./lib.js";
import { plantView } from "./plant.js";

const PLANTS = ["p2_gasline", "p1_grfics"];
const STATES = ["", "open", "closed"];
const TYPES = ["", "positive", "proved", "non_proved"];

export async function intakeScreen(root) {
  const st = { plant: PLANTS[0], map: null, draft: null, photo: null, error: null };
  root.append(el("h1", {}, "New isolation"));
  const top = el("section", { class: "panel" });
  const body = el("div", { id: "draft" });
  root.append(top, body);

  const plantSel = el("select", { id: "plant", onchange: async () => { st.plant = plantSel.value; await loadMap(); } },
    PLANTS.map((p) => el("option", { value: p }, p)));
  async function loadMap() { st.map = await api(`/api/plants/${st.plant}/map`); draw(); }

  // --- import tabs
  const panes = {
    text: el("div", { class: "tabpane" },
      el("label", { class: "block" }, "Describe the isolation in words", el("textarea", { id: "text-in", rows: 5, cols: 70 }))),
    image: el("div", { class: "tabpane", hidden: true },
      el("label", {}, "Photo or PDF of the isolation sheet ", el("input", { type: "file", id: "image-in", accept: "image/*,application/pdf" }))),
    csv: el("div", { class: "tabpane", hidden: true },
      el("label", {}, "CSV export ", el("input", { type: "file", id: "csv-in", accept: ".csv,text/csv" }))),
  };
  let tab = "text";
  const tabs = el("div", { class: "tabs", role: "tablist" }, [["text", "Type"], ["image", "Upload"], ["csv", "CSV"]].map(([k, label]) =>
    el("button", { type: "button", role: "tab", "data-tab": k, "aria-selected": k === tab ? "true" : "false", onclick: (ev) => {
      tab = k;
      for (const [kk, p] of Object.entries(panes)) p.hidden = kk !== k;
      for (const b of tabs.children) b.setAttribute("aria-selected", b === ev.currentTarget ? "true" : "false");
    } }, label)));
  const status = el("p", { class: "muted", id: "import-status" });
  top.append(el("label", {}, "Plant ", plantSel), tabs, ...Object.values(panes),
    el("button", { type: "button", id: "import", onclick: doImport }, "Read into table"), status);

  async function doImport() {
    const fd = new FormData();
    fd.append("route", tab);
    fd.append("plant", st.plant);
    st.photo = null;
    if (tab === "text") fd.append("text", panes.text.querySelector("textarea").value);
    else {
      const f = panes[tab].querySelector("input").files[0];
      if (!f) { status.textContent = "Choose a file first."; return; }
      fd.append("file", f);
      if (tab === "image") st.photo = { name: f.name, url: f.type.startsWith("image/") ? URL.createObjectURL(f) : null };
    }
    status.textContent = "Reading…";
    try {
      st.draft = await api("/api/plans/import", { method: "POST", body: fd });
      status.textContent = `Draft ${st.draft.id} (${st.draft.route}). Check every cell before confirming.`;
    } catch (e) { status.textContent = errorText(e); }
    draw();
  }

  // --- the draft
  function listFromTable() {
    const v = (sel) => { const x = body.querySelector(sel).value.trim(); return x === "" ? null : x; };
    const rows = [...body.querySelectorAll("tr[data-point]")].map((tr) => {
      const c = (name) => { const x = tr.querySelector(`[name=${name}]`).value.trim(); return x === "" ? null : x; };
      return { tag: c("tag"), required_state: c("required_state"), seq: c("seq") === null ? null : Number(c("seq")),
        isolation_type: c("isolation_type"), lock_id: c("lock_id"), note: c("note") };
    });
    const proving = [...body.querySelectorAll("tr[data-proving]")].map((tr) => ({
      tag: tr.querySelector("[name=ptag]").value.trim() || null,
      proves: tr.querySelector("[name=proves]").value.split(",").map((x) => x.trim()).filter(Boolean) }));
    const hold = v("#hold_minutes");
    return { ...st.draft.list, work_equipment: v("#work_equipment"), vent: v("#vent"), hold_minutes: hold === null ? null : Number(hold), points: rows, proving };
  }

  async function save(list = listFromTable()) {
    try {
      st.draft = await api(`/api/plans/drafts/${st.draft.id}`, { method: "PUT", json: { list } });
      st.error = null;
    } catch (e) { st.error = errorText(e); }
    draw();
  }

  const input = (name, value, opts = {}) => el("input", { name, id: opts.id, value: value ?? "", placeholder: value === null && opts.required ? "unclear" : "",
    class: value === null && opts.required ? "unclear" : null, size: opts.size || 10, onchange: () => save(), "aria-invalid": value === null && opts.required ? "true" : null });
  const select = (name, value, options, required) => el("select", { name, onchange: () => save(), class: value === null && required ? "unclear" : null },
    options.map((o) => el("option", { value: o, selected: (value ?? "") === o }, o === "" ? (required ? "unclear" : "—") : o)));

  function draw() {
    body.replaceChildren();
    if (!st.draft) {
      if (st.map) body.append(el("h2", {}, "Plant"), plantView(st.map));
      return;
    }
    const d = st.draft, lst = d.list;
    const defaults = Object.fromEntries((d.defaults || []).map((x) => [x.field, x]));
    const badge = (field) => defaults[field] ? el("span", { class: "badge default", "data-default": field }, `plant default: ${defaults[field].value}`) : null;
    const fields = el("div", { class: "fields" },
      el("label", {}, "Work equipment ", input("work_equipment", lst.work_equipment, { id: "work_equipment", required: true })),
      el("label", {}, "Vent ", input("vent", lst.vent, { id: "vent" })),
      el("label", {}, "Hold (process min) ", input("hold_minutes", lst.hold_minutes, { id: "hold_minutes", size: 5 }), badge("hold_minutes")));
    const table = el("table", { class: "grid", id: "points" },
      el("thead", {}, el("tr", {}, ["Seq", "Tag", "Required state", "Isolation type", "Lock", "Note", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, lst.points.map((p, i) => el("tr", { "data-point": i },
        el("td", {}, input("seq", p.seq, { required: true, size: 3 })),
        el("td", {}, input("tag", p.tag, { required: true })),
        el("td", {}, select("required_state", p.required_state, STATES, true)),
        el("td", {}, select("isolation_type", p.isolation_type, TYPES, p.required_state === "closed")),
        el("td", {}, input("lock_id", p.lock_id, { size: 6 })),
        el("td", {}, input("note", p.note, { size: 18 })),
        el("td", {}, el("button", { type: "button", onclick: () => { const l = listFromTable(); l.points.splice(i, 1); save(l); } }, "Remove"))))));
    const proving = el("table", { class: "grid", id: "proving" },
      el("thead", {}, el("tr", {}, el("th", {}, "Proving point"), el("th", {}, "Proves (comma list)"))),
      el("tbody", {}, lst.proving.map((g, i) => el("tr", { "data-proving": i },
        el("td", {}, input("ptag", g.tag, { required: true })), el("td", {}, input("proves", g.proves.join(", "), { size: 24 }))))));
    const addRow = el("button", { type: "button", onclick: () => {
      st.draft.list = listFromTable();
      st.draft.list.points.push({ tag: null, required_state: null, seq: null, isolation_type: null, lock_id: null, note: null });
      draw();
    } }, "Add point");

    const table_side = el("section", { class: "panel" }, el("h2", {}, "Isolation list (editable)"), fields, table, addRow, proving,
      st.error ? el("p", { class: "error" }, st.error) : null);
    const sideBySide = d.route === "image" ? el("section", { class: "panel side", id: "photo-transcript" },
      el("div", {}, el("h3", {}, "Photo"), st.photo && st.photo.url ? el("img", { src: st.photo.url, alt: "uploaded sheet", class: "photo" }) : el("p", { class: "muted" }, st.photo ? st.photo.name : "photo not available in this view")),
      el("div", {}, el("h3", {}, "Transcript (model's verbatim reading)"), el("pre", { class: "transcript" }, d.transcript || "no transcript")),
      el("div", {}, el("h3", {}, "Table"), el("p", { class: "muted" }, "Compare the table with the photo and transcript, cell by cell."))) : null;

    // plan check
    const fails = d.findings.filter((f) => f.status !== "PASS");
    const check = el("section", { class: "panel", id: "plan-check" }, el("h2", {}, "Plan check"),
      d.unresolved.length ? el("p", { class: "muted" }, "The plan check runs once nothing is unclear.") : null,
      el("ul", { class: "findings" }, d.findings.map((f) => el("li", { class: `f-${f.status}` },
        el("span", { class: "mark" }, statusMark(f.status)), " ", el("code", {}, f.rule_id), ` v${f.rule_version}: ${f.message}`,
        f.path && f.path.length ? el("span", { class: "small" }, ` (path: ${f.path.join(" → ")})`) : null))),
      !d.unresolved.length && !fails.length ? el("p", {}, "No plan-check finding against this list.") : null);
    const paths = d.findings.filter((f) => f.status !== "PASS" && f.path && f.path.length).map((f) => f.path);
    const view = el("section", { class: "panel" }, el("h2", {}, "Plant view"), st.map ? plantView(st.map, { work: lst.work_equipment, paths }) : null);

    // confirm
    const blocked = d.unresolved.length > 0 || !d.plan_hash;
    const confirmBox = el("section", { class: "panel", id: "confirm-box" },
      el("h2", {}, "Confirm"),
      d.unresolved.length ? el("div", { class: "blocked-list" }, el("p", {}, `Confirm is blocked: ${d.unresolved.length} unclear item(s).`),
        el("ul", {}, d.unresolved.map((u) => el("li", {}, u)))) : null,
      d.defaults && d.defaults.length ? el("p", {}, "Values taken from the plant, not written on the list: ",
        d.defaults.map((x) => el("span", { class: "badge default" }, `${x.field} = ${x.value} (plant default)`))) : null,
      el("button", { type: "button", id: "confirm-open", disabled: blocked, onclick: () => confirmDialog(d) }, "Confirm plan…"),
      d.plan_hash ? el("p", { class: "small muted" }, `plan hash ${d.plan_hash}`) : null);

    body.append(...[sideBySide].filter(Boolean), el("div", { class: "cols" }, el("div", {}, table_side, check, confirmBox), el("div", {}, view)));
  }

  function confirmDialog(d) {
    const name = el("input", { id: "confirm-name", size: 24 });
    const tick = el("input", { type: "checkbox", id: "confirm-reviewed" });
    const msg = el("p", { class: "error", id: "confirm-msg" });
    const submit = el("button", { type: "submit", id: "confirm-submit", disabled: true }, "Confirm plan");
    const sync = () => { submit.disabled = !(name.value.trim() && tick.checked); };
    name.addEventListener("input", sync); tick.addEventListener("change", sync);
    const dlg = el("dialog", { id: "confirm-dialog" }, el("form", { method: "dialog", onsubmit: async (ev) => {
      ev.preventDefault();
      try {
        const rec = await api(`/api/plans/drafts/${d.id}/confirm`, { json: { by: name.value.trim(), role: "issuer" } });
        dlg.close(); dlg.remove();
        confirmed(rec);
      } catch (e) { msg.textContent = errorText(e); }
    } },
      el("h2", {}, "Confirm this isolation plan"),
      el("p", {}, `Plan hash ${d.plan_hash}`),
      el("label", {}, "Your name ", name), el("p", {}, "Role: issuer"),
      el("label", {}, tick, " I have reviewed this plan"),
      msg, el("menu", {}, submit, el("button", { type: "button", onclick: () => { dlg.close(); dlg.remove(); } }, "Cancel"))));
    document.body.append(dlg);
    dlg.showModal();
  }

  function confirmed(rec) {
    const box = body.querySelector("#confirm-box");
    const by = el("input", { id: "start-by", size: 20 });
    const override = el("input", { id: "start-override", size: 50, placeholder: "only if the plan check did not pass" });
    const msg = el("p", { class: "error", id: "start-msg" });
    box.replaceChildren(el("h2", {}, "Confirmed"),
      el("p", { id: "confirmed-record" }, `Confirmed by ${rec.by} (${rec.role}) at ${rec.date}. Plan hash ${rec.plan_hash}.`),
      el("h3", {}, "Start a job on this plan"),
      el("label", {}, "Your name ", by), el("label", {}, "Plan-check override text ", override),
      el("button", { type: "button", id: "start", onclick: async () => {
        try {
          const r = await api("/api/sessions", { json: { plant: st.plant, plan_hash: rec.plan_hash, by: by.value.trim(), plan_check_override: override.value.trim() || null } });
          location.hash = `#/job/${encodeURIComponent(r.session)}`;
        } catch (e) { msg.textContent = errorText(e); }
      } }, "Start job"), msg);
  }

  await loadMap();
}
