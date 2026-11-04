"""C14 importer gate: CSV parses exactly or fails with its row; nothing unconfirmed starts a session;
a draft with an unresolved null can't be confirmed. tmp dirs only, never plants/*/confirmed.yaml."""

import io
import json
from pathlib import Path

import pytest
import yaml

from zerostate import cli
from zerostate.importers import draft as dr
from zerostate.importers.confirm import NotConfirmable, confirm, is_confirmed
from zerostate.importers.csv_import import CsvImportError, parse_csv
from zerostate.importers.draft import load_draft, save_draft, unresolved
from zerostate.importers.image_import import import_image
from zerostate.importers.text_import import import_text, system_prompt
from zerostate.models.envelope import IsolationList, IsolationPlan, ListPoint
from zerostate.models.plant_map import PlantMap

ROOT = Path(__file__).parents[1]
HEADER = "work_order,equipment,tag,required_state,apply_seq,isolation_type,lock_id,vent_tag,proving_tag,proves\n"
P2_ROWS = [
    "WO-1,F-210,XV-201,closed,1,proved,A-01,VV-213,BV-202,XV-201;XV-203",
    "WO-1,F-210,XV-203,closed,2,proved,A-02,VV-213,,",
    "WO-1,F-210,BV-202,open,3,,,VV-213,,",
    "WO-1,F-210,XV-204,closed,4,proved,A-03,VV-213,VV-213,XV-204",
]


def write_csv(tmp_path, rows, header=HEADER):
    p = tmp_path / "export.csv"
    p.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def test_csv_parses_the_p2_list_exactly(tmp_path):
    got = parse_csv(write_csv(tmp_path, P2_ROWS), "p2_gasline")
    want = IsolationList.model_validate(yaml.safe_load((ROOT / "plants/p2_gasline/isolation_list.yaml").read_text()))
    def fields(lst):
        return [(p.tag, p.required_state, p.seq, p.isolation_type) for p in lst.points]

    assert fields(got) == fields(want)
    assert (got.work_equipment, got.vent, got.proving) == (want.work_equipment, want.vent, want.proving)
    assert [p.lock_id for p in got.points] == ["A-01", "A-02", None, "A-03"]
    assert got.notes == ("work order WO-1",) and got.hold_minutes is None  # the export has no hold column


class FakeOpener:
    """Stands in for the proxy + Meta API: records requests, returns one canned chat reply each."""

    def __init__(self, *contents):
        self.contents, self.requests = list(contents), []

    def open(self, req, timeout=None):
        self.requests.append(json.loads(req.data))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": self.contents.pop(0)}}],
                                      "usage": {"prompt_tokens": 900, "completion_tokens": 200}}).encode())


@pytest.fixture
def model_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "fake-key-for-tests")  # pragma: allowlist secret
    monkeypatch.setenv("ZS_CREDITS", str(tmp_path / "credits.jsonl"))


def p_map(plant="p2_gasline"):
    return PlantMap.model_validate(yaml.safe_load((ROOT / "plants" / plant / "plant_map.yaml").read_text()))


def reply(**over):
    lst = {"plant": "anything", "work_equipment": "F-210", "vent": "VV-213", "hold_minutes": 10,
           "points": [{"tag": "XV-201", "required_state": "closed", "seq": 1, "isolation_type": "proved"},
                      {"tag": "XV-203", "required_state": "closed", "seq": 2, "isolation_type": "proved"}],
           "proving": [{"tag": "BV-202", "proves": ["XV-201", "XV-203"]}]}
    return json.dumps({**lst, **over})


def test_prompt_states_the_rule_and_lists_the_map_tags():
    prompt = system_prompt(p_map())
    assert "never add a point" in prompt and "extract only what the author wrote" in prompt.lower()
    assert "mark anything unclear as null with a note" in prompt
    assert all(t in prompt for t in p_map().tags()) and "$" not in prompt


def test_text_route_sends_the_text_and_keeps_only_written_tags(model_env):
    text = "F-210 job: close XV-201 first (proved), then XV-203 (proved). BV-202 proves both. Vent VV-213, hold 10."
    op = FakeOpener(reply(points=[{"tag": "XV-201", "required_state": "closed", "seq": 1, "isolation_type": "proved"},
                                  {"tag": "XV-203", "required_state": "closed", "seq": 2, "isolation_type": "proved"},
                                  {"tag": "XV-204", "required_state": "closed", "seq": 3, "isolation_type": "proved"}]))
    lst = import_text(text, p_map(), opener=op)
    msgs = op.requests[0]["messages"]
    assert msgs[0]["role"] == "system" and "XV-231" in msgs[0]["content"] and msgs[1]["content"] == text
    assert lst.plant == "p2_gasline"  # the plant comes from the map, not the model
    assert [p.tag for p in lst.points] == ["XV-201", "XV-203", None]  # XV-204 isn't in the text: nulled
    assert "not in the text" in lst.points[2].note and lst.vent == "VV-213"


SHEET = ("Work: F-210 | Vent: VV-213 | Hold 10 min\n1 | XV-201 | closed | proved\n"
         "2 | XV-203 | closed | proved\nBleed BV-202 proves XV-201, XV-203")


def test_image_route_transcribes_then_grounds_like_typed_text(model_env, tmp_path):
    from PIL import Image

    png, pdf = tmp_path / "sheet.png", tmp_path / "sheet.pdf"
    Image.new("RGB", (60, 40), "white").save(png)
    Image.new("RGB", (60, 40), "white").save(pdf)
    transcript = json.dumps({"text": SHEET})
    op = FakeOpener(transcript, reply(), transcript, reply())
    for path in (png, pdf):
        lst, text = import_image(path, p_map(), opener=op)
        assert text == SHEET and lst.plant == "p2_gasline" and lst.points[0].tag == "XV-201"
    first, second = op.requests[0], op.requests[1]  # 1: verbatim transcription of the image; 2: the typed route
    assert first["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "verbatim" in first["messages"][0]["content"] and "never add a point" in second["messages"][0]["content"]
    assert second["messages"][1]["content"] == SHEET  # the list is built from the transcript, not the pixels
    with pytest.raises(ValueError, match="expected"):
        import_image(tmp_path / "sheet.gif", p_map(), opener=op)


def test_image_route_nulls_a_real_map_tag_the_sheet_never_had(model_env, tmp_path):
    """The dangerous case: an added tag that exists in the plant map (PLAN-MAPPING can't see it)."""
    from PIL import Image

    png = tmp_path / "sheet.png"
    Image.new("RGB", (60, 40), "white").save(png)
    added = json.loads(reply())
    added["points"].append({"tag": "XV-204", "required_state": "closed", "seq": 3, "isolation_type": "proved"})
    lst, _ = import_image(png, p_map(), opener=FakeOpener(json.dumps({"text": SHEET}), json.dumps(added)))
    assert lst.points[2].tag is None and "not in the text" in lst.points[2].note  # blocks confirmation


def test_draft_shows_the_plant_default_hold_and_keeps_the_transcript(tmp_path):
    lst = IsolationList.model_validate({**json.loads(reply()), "plant": "p2_gasline", "hold_minutes": None})
    d = dr.save_draft(lst, "image", "sheet.png", tmp_path, transcript=SHEET)
    assert dr.load_draft(d["id"], tmp_path)["transcript"] == SHEET
    assert dr.defaults_used(lst, p_map()) == [{"field": "hold_minutes", "value": 10.0, "source": "plant default"}]
    assert dr.defaults_used(lst.model_copy(update={"hold_minutes": 10.0}), p_map()) == []


@pytest.mark.parametrize("rows, header, match", [
    (P2_ROWS, HEADER.replace("apply_seq,", ""), "row 1: missing columns"),
    ([P2_ROWS[0], P2_ROWS[1].replace("closed", "shut")], HEADER, "row 3: required_state 'shut'"),
    ([P2_ROWS[0], P2_ROWS[1].replace(",2,", ",two,")], HEADER, "row 3: apply_seq 'two'"),
    ([P2_ROWS[0], P2_ROWS[1].replace("F-210", "C-202")], HEADER, "row 3: equipment"),
    ([P2_ROWS[0], P2_ROWS[1].replace("VV-213", "BV-202")], HEADER, "row 3: vent_tag"),
    ([P2_ROWS[0], P2_ROWS[1].replace(",proved,", ",double,")], HEADER, "row 3: isolation_type"),
    ([P2_ROWS[0], P2_ROWS[1].replace("XV-203", "", 1)], HEADER, "row 3: empty tag"),
    ([P2_ROWS[0], "WO-1,F-210,XV-203,closed,2,proved,A-02,VV-213,BV-202,XV-201"], HEADER, "row 3: proving_tag BV-202"),
    ([], HEADER, "no rows"),
])
def test_csv_errors_raise_with_the_row(tmp_path, rows, header, match):
    with pytest.raises(CsvImportError, match=match):
        parse_csv(write_csv(tmp_path, rows, header), "p2_gasline")


# ---- the gate: confirm, refuse ------------------------------------------------------------------
class ReachedAdapter(Exception):
    pass


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """A copy of P1's plan in a tmp config dir; ZS_DATA / ZS_CONFIG in tmp. Never the repo's plants/."""
    cfg = tmp_path / "config" / "p1_grfics"
    cfg.mkdir(parents=True)
    plan_file = cfg / "envelope.yaml"
    plan_file.write_text((ROOT / "plants/p1_grfics/envelope.yaml").read_text(encoding="utf-8-sig"), encoding="utf-8")
    monkeypatch.setenv("ZS_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("ZS_CONFIG", str(tmp_path / "config"))
    monkeypatch.setenv("ZS_THRESHOLDS", str(ROOT / "plants/p1_grfics/thresholds.yaml"))
    monkeypatch.setenv("ZS_MAP", str(ROOT / "plants/p1_grfics/modbus_map.yaml"))  # as deploy/Dockerfile sets it

    def no_lab(*_a, **_k):
        raise ReachedAdapter  # past every refusal: would now open the plant connection
    monkeypatch.setattr(cli, "open_adapter", no_lab)  # the gate must refuse before any plant access
    plan_hash = IsolationPlan.model_validate(yaml.safe_load(plan_file.read_text())).content_hash()
    return plan_file, plan_hash, tmp_path


def start(plan_file, plan_hash):
    return cli.main(["session", "start", "--plan", str(plan_file), "--plan-hash", plan_hash, "--session", "s1"])


def test_unconfirmed_plan_refuses_to_start_and_confirmed_one_gets_past(lab, capsys):
    plan_file, plan_hash, tmp = lab
    assert start(plan_file, plan_hash) == 1
    assert "not confirmed" in capsys.readouterr().err
    assert is_confirmed(plan_hash, [plan_file.parent], tmp / "data") is None

    rec = confirm(str(plan_file), "Owner", data_dir=tmp / "data")
    book = yaml.safe_load((plan_file.parent / "confirmed.yaml").read_text())
    assert book == [rec] and rec["plan_hash"] == plan_hash and (rec["by"], rec["role"]) == ("Owner", "issuer")
    assert is_confirmed(plan_hash, [plan_file.parent], tmp / "data") == rec
    assert is_confirmed("0" * 64, [plan_file.parent], tmp / "data") is None
    with pytest.raises(ReachedAdapter):
        start(plan_file, plan_hash)


def test_confirmation_is_logged_in_session_start(tmp_path):
    from checks.synth import PARAMS, PLAN, SPANS

    from zerostate.audit.log import AuditLog
    from zerostate.session import Session

    rec = {"plan_hash": PLAN.content_hash(), "by": "Owner", "role": "issuer", "date": "2026-11-03T09:00:00+00:00"}
    log = AuditLog(tmp_path / "audit.sqlite")
    Session("s1", PLAN, PLAN.content_hash(), PARAMS, 10.0, SPANS, log, 0.0, confirmation=rec)
    assert log.events("s1")[0]["payload"]["confirmation"] == rec


def test_confirm_needs_a_name_and_the_issuer_role(lab):
    plan_file, _, tmp = lab
    for by, role in (("", "issuer"), ("Owner", "receiver")):
        with pytest.raises(NotConfirmable):
            confirm(str(plan_file), by, role, data_dir=tmp / "data")
    assert not (plan_file.parent / "confirmed.yaml").exists()


def test_draft_with_nulls_cannot_be_confirmed(lab, capsys):
    _, _, tmp = lab
    lst = IsolationList(plant="p2_gasline", work_equipment="F-210", points=(
        ListPoint(tag="XV-201", required_state="closed", seq=1, isolation_type="proved"),
        ListPoint(tag=None, required_state="closed", seq=2, isolation_type="proved", note="tag scribbled over"),
        ListPoint(tag="XV-204", required_state="closed", seq=None, isolation_type=None)))
    d = save_draft(lst, "image", "sheet.png", tmp / "data")
    assert json.loads((tmp / "data" / "drafts" / f"{d['id']}.json").read_text())["list"]["points"][1]["tag"] is None
    assert unresolved(lst) == ["point 2 (?): tag is unclear - tag scribbled over", "point 3 (XV-204): seq is unclear",
                               "point 3 (XV-204): isolation_type is unclear"]
    map_file = ROOT / "plants/p2_gasline/plant_map.yaml"
    with pytest.raises(NotConfirmable, match="unresolved"):
        confirm(d["id"], "Owner", data_dir=tmp / "data", map_path=map_file)
    assert cli.main(["plan", "confirm", d["id"], "--by", "Owner", "--map", str(map_file)]) == 1
    assert "unresolved" in capsys.readouterr().err
    assert not (tmp / "data" / "plans").exists()
    assert cli.main(["plan", "show", d["id"], "--map", str(map_file)]) == 0
    view = json.loads(capsys.readouterr().out)
    assert view["plan_hash"] is None and len(view["unresolved"]) == 3
    with pytest.raises(FileNotFoundError):
        load_draft("../../etc", tmp / "data")


def test_csv_draft_merges_checks_and_confirms(lab, capsys):
    """Runs once graph/build.py and checks/plan (P2-2) are merged in."""
    pytest.importorskip("zerostate.graph.build")
    pytest.importorskip("zerostate.checks.plan")
    _, _, tmp = lab
    map_file = ROOT / "plants/p2_gasline/plant_map.yaml"
    assert cli.main(["plan", "import", "--csv", str(write_csv(tmp, P2_ROWS)), "--plant", "p2_gasline", "--map", str(map_file)]) == 0
    view = json.loads(capsys.readouterr().out)
    assert view["unresolved"] == [] and view["plan_hash"] and view["draft"]["route"] == "csv"
    assert cli.main(["plan", "confirm", view["draft"]["id"], "--by", "Owner", "--map", str(map_file)]) == 0
    assert capsys.readouterr().out.strip() == view["plan_hash"]
    rec = is_confirmed(view["plan_hash"], [], tmp / "data")
    assert rec["by"] == "Owner" and rec["plan_hash"] == view["plan_hash"]


# ---- eval/importer_accuracy.py scoring (host side, no model) --------------------------------------
def accuracy_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("importer_accuracy", ROOT / "eval" / "importer_accuracy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_accuracy_scoring_and_the_invented_point_stop(tmp_path, capsys):
    acc = accuracy_module()
    cases = acc.load_cases(ROOT / "eval" / "importer_set")
    assert len(cases) == 12 and sum(1 for c in cases if c.get("ambiguity")) == 2
    perfect = {c["id"]: {"route": c["route"], "list": c["gold"], "error": None} for c in cases}
    rep = acc.score(perfect, cases, tmp_path)["routes"]
    for route in ("text", "image", "csv"):
        assert (rep[route]["precision"], rep[route]["invented"]) == (1.0, 0)
    assert rep["text"]["recall"] == rep["image"]["recall"] == 1.0
    assert sorted(e.split(":")[0] for e in rep["csv"]["errors"]) == ["s05", "t02"]  # a null tag can't be exported

    t01 = perfect["t01"]["list"]
    out = tmp_path / "out.json"
    out.write_text(json.dumps({**perfect, "t01": {**perfect["t01"], "list": {**t01, "points": [
        *t01["points"], {"tag": "f2", "required_state": "closed", "seq": 4, "isolation_type": "non_proved"}]}}}))
    assert acc.main(["score", str(out)]) == 2
    assert "STOP: invented point" in capsys.readouterr().err


def test_csv_may_state_the_hold_and_must_state_it_once(tmp_path):
    header = HEADER.rstrip("\n") + ",hold_minutes\n"
    rows = [r + ",10" for r in P2_ROWS]
    assert parse_csv(write_csv(tmp_path, rows, header), "p2_gasline").hold_minutes == 10.0
    assert parse_csv(write_csv(tmp_path, P2_ROWS), "p2_gasline").hold_minutes is None  # not written: plant default, shown
    with pytest.raises(CsvImportError, match="hold_minutes"):
        parse_csv(write_csv(tmp_path, [rows[0], P2_ROWS[1] + ",5", *rows[2:]], header), "p2_gasline")


# importer case t02 as Muse Spark drafted it in the measured run (eval/results/importer_out_2026-11-04.json)
T02 = {"plant": "p1_grfics", "work_equipment": "Reactor", "points": [
    {"tag": "product", "required_state": "closed", "seq": 1, "isolation_type": "non_proved", "lock_id": "21", "note": None},
    {"tag": None, "required_state": "closed", "seq": 2, "isolation_type": "non_proved", "lock_id": "22",
     "note": "cannot tell which feed tag the author means - author states not sure which feed line this job is on"},
    {"tag": "purge", "required_state": "open", "seq": None, "isolation_type": None, "lock_id": None, "note": None}],
    "vent": None, "proving": [], "hold_minutes": None, "notes": []}
T02_MESSAGE = "purge is a vent/bleed on this plant, listed here as an isolation point. Move it to the vent field or remove it."


def test_t02_vent_listed_as_an_isolation_point_is_named_on_the_confirm_screen():
    from zerostate.config import load_thresholds
    params = load_thresholds(ROOT / "plants" / "p1_grfics" / "thresholds.yaml")
    plan, out = dr.check_draft({"list": T02}, p_map("p1_grfics"), params)
    assert plan is None and out["unresolved"][0] == T02_MESSAGE  # the cause first, before the missing fields
    fixed = {**T02, "points": [p for p in T02["points"] if p["tag"] != "purge"], "vent": "purge"}
    fixed["points"][1] = {**fixed["points"][1], "tag": "f1", "note": None}
    _, out = dr.check_draft({"list": fixed}, p_map("p1_grfics"), params)
    assert T02_MESSAGE not in out["unresolved"]  # moved to the vent field: no longer flagged
