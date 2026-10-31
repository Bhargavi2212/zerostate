import importlib.util
from pathlib import Path

from zerostate.adapters.modbus import load_map

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("modbus_scan", ROOT / "scripts" / "modbus_scan.py")
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
ENTRIES = {e.tag: e for e in load_map(ROOT / "plants" / "p1_grfics" / "modbus_map.yaml").tags}


def test_offset_check_finds_the_shift():
    # pressure 2700 kPa -> 55296, level 44 % -> 28835, placed one register later than the map says
    ir = {109: 55296, 110: 28835}
    assert scan.offset_check({"ir": ir}, ENTRIES) == {-1: False, 0: False, 1: True}
    assert scan.offset_check({"ir": None}, ENTRIES) == {-1: False, 0: False, 1: False}
