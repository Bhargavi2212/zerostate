"""C1: the product never imports test plants or eval code and never names a truth endpoint."""

import ast
from pathlib import Path

SRC = Path(__file__).parents[1] / "src" / "zerostate"
TRUTH_STRINGS = ("index.php", "55555")


def test_no_plant_or_eval_imports_and_no_truth_endpoints():
    found = []
    for py in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            found += [f"{py}: imports {m}" for m in mods if m.split(".")[0] in ("plants", "eval")]
            if isinstance(node, ast.Constant):
                if isinstance(node.value, str) and any(t in node.value for t in TRUTH_STRINGS):
                    found.append(f"{py}:{node.lineno} names a truth endpoint")
                if node.value == 55555 and not isinstance(node.value, bool):
                    found.append(f"{py}:{node.lineno} names the simulator truth port")
    assert found == []
