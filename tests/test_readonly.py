"""C1: no plant-protocol write path anywhere in src/zerostate."""

import ast
from pathlib import Path

SRC = Path(__file__).parents[1] / "src" / "zerostate"
FORBIDDEN_CALLS = {
    "mask_write_register", "readwrite_registers",
    "write_value", "set_value", "write_attribute",  # asyncua
    "execute", "send",  # raw request paths that could carry a write PDU
}
WRITE_REQUEST_HINTS = ("Write", "MaskWrite", "ReadWrite")


def violations(source: str, path: str) -> list[str]:
    tree = ast.parse(source)
    in_adapters = "adapters" in Path(path).parts
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            name = node.func.attr
            if name.startswith("write_") or name in FORBIDDEN_CALLS:
                found.append(f"{path}:{node.lineno} calls .{name}()")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = node.module or "" if isinstance(node, ast.ImportFrom) else ""
            names = [a.name for a in node.names]
            roots = [mod.split(".")[0]] if mod else [n.split(".")[0] for n in names]
            if {"pymodbus", "asyncua"} & set(roots) and not in_adapters:
                found.append(f"{path}:{node.lineno} imports a plant protocol outside adapters/")
            if mod.startswith("pymodbus") and any(h in n for n in names for h in WRITE_REQUEST_HINTS):
                found.append(f"{path}:{node.lineno} imports a write request class")
        if in_adapters and isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.lstrip("_").startswith(("write", "set")):
                    found.append(f"{path}:{item.lineno} defines {node.name}.{item.name}")
    return found


def test_src_has_no_write_path():
    found = []
    for py in SRC.rglob("*.py"):
        found += violations(py.read_text(), str(py.relative_to(SRC.parent)))
    assert found == []


def test_scanner_catches_planted_writes():
    bad = """
from pymodbus.pdu.register_message import WriteSingleRegisterRequest
c.write_register(1, 2)
c.execute(req)
node.write_value(3)
class Adapter:
    def set_point(self): ...
"""
    found = violations(bad, "zerostate/adapters/evil.py")
    assert len(found) == 5, found
    assert violations("import pymodbus\n", "zerostate/gate.py")
    assert violations("f.write('x')\n", "zerostate/audit/log.py") == []
