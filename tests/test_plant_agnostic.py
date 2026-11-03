"""C2 (decision D4): no plant-specific name appears in src/zerostate, in string literals or identifiers.

Names = plant ids plus every node id and tag in plants/*/plant_map.yaml and the protocol maps
(modbus_map.yaml / opcua_map.yaml, including OPC UA node ids). Instrument role words of the plant-map
schema ("pressure", "level") are vocabulary, not plant names, so they are not counted.
"""

import ast
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "zerostate"

# Today's offenders; P3-9 removes them (the map comes from ZS_MAP / compose only).
KNOWN_OFFENDERS = {
    ("src/zerostate/cli.py", "p1_grfics"),  # cli.py:43 default thresholds path, cli.py:120 default map path
    ("src/zerostate/importers/image_import.py", "XV-203"),  # image_import.py:9 docstring example
}


def plant_names() -> set[str]:
    names, roles = set(), set()
    for f in [*ROOT.glob("plants/*/plant_map.yaml"), *ROOT.glob("plants/*/modbus_map.yaml"),
              *ROOT.glob("plants/*/opcua_map.yaml")]:
        y = yaml.safe_load(f.read_text(encoding="utf-8-sig"))
        names |= {f.parent.name, y.get("plant") or f.parent.name}
        names |= {n["id"] for n in y.get("nodes", [])}
        for t in [*y.get("tags", []), *y.get("instruments", [])]:
            names |= {t["tag"], t.get("signal_ref") or t["tag"], t.get("node") or t["tag"]}
            roles.add(t.get("role"))
    return names - roles


def offenders() -> set[tuple[str, str]]:
    pats = {n: re.compile(rf"(?<![\w-]){re.escape(n)}(?![\w-])") for n in plant_names()}
    found = set()
    for py in SRC.rglob("*.py"):
        rel = py.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
            elif isinstance(node, ast.Name):
                text = node.id
            elif isinstance(node, ast.Attribute):
                text = node.attr
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                text = node.name
            elif isinstance(node, ast.arg):
                text = node.arg
            else:
                continue
            found |= {(rel, n) for n, p in pats.items() if p.search(text)}
    return found


def test_names_cover_both_plants():
    names = plant_names()
    assert {"p1_grfics", "p2_gasline", "f1_valve_pos", "XV-204", "ns=2;s=PT-211.PV"} <= names
    assert "pressure" not in names  # a role word, not a plant name


def test_offenders_are_exactly_the_known_ones():
    # a new offender fails here; a fixed one too, so KNOWN_OFFENDERS (and the xfail below) get updated
    assert offenders() == KNOWN_OFFENDERS


@pytest.mark.xfail(strict=True, reason="P3-9 removes cli/image_import plant defaults: "
                   "cli.py:43 and cli.py:120 (p1_grfics paths), importers/image_import.py:9 (XV-203)")
def test_no_plant_specific_name_in_src():
    assert offenders() == set()
