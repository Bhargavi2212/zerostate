"""C14 importer gate: CSV parses exactly or fails with its row; nothing unconfirmed starts a session;
a draft with an unresolved null can't be confirmed. tmp dirs only, never plants/*/confirmed.yaml."""

import io
import json
from pathlib import Path

import pytest
import yaml

from zerostate.importers.csv_import import CsvImportError, parse_csv
from zerostate.importers.image_import import import_image
from zerostate.importers.text_import import import_text, system_prompt
from zerostate.models.envelope import IsolationList
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


def test_image_route_sends_png_and_pdf_page_one_as_data_urls(model_env, tmp_path):
    from PIL import Image

    png, pdf = tmp_path / "sheet.png", tmp_path / "sheet.pdf"
    Image.new("RGB", (60, 40), "white").save(png)
    Image.new("RGB", (60, 40), "white").save(pdf)
    op = FakeOpener(reply(), reply())
    for path in (png, pdf):
        lst = import_image(path, p_map(), opener=op)
        assert lst.plant == "p2_gasline" and lst.points[0].tag == "XV-201"
    for req in op.requests:
        content = req["messages"][1]["content"]
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "never add a point" in req["messages"][0]["content"]
    with pytest.raises(ValueError, match="expected"):
        import_image(tmp_path / "sheet.gif", p_map(), opener=op)


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
