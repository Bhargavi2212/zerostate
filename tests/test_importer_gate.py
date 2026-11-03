"""C14 importer gate: CSV parses exactly or fails with its row; nothing unconfirmed starts a session;
a draft with an unresolved null can't be confirmed. tmp dirs only, never plants/*/confirmed.yaml."""

from pathlib import Path

import pytest
import yaml

from zerostate.importers.csv_import import CsvImportError, parse_csv
from zerostate.models.envelope import IsolationList

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
