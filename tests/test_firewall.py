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


HTTP_CLIENTS = ("urllib.request", "http.client", "requests", "httpx", "urllib3", "aiohttp")
HTTP_ALLOWED = {"llm/client.py", "camera/client.py"}
# The data-only verdict path: nothing here may reach model or camera code (C10: headline verdicts use no model output).
DATA_PATH = ("gate.py", "session.py", "checks/plan", "checks/process", "checks/live")
DATA_PATH_EXEMPT = {"checks/live/camera.py"}  # LIVE-CAMERA feeds only the with-camera track


def _imports(py: Path) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            out += [node.module] + [f"{node.module}.{a.name}" for a in node.names]
    return out


def test_only_the_model_client_names_the_meta_api_and_only_two_files_speak_http():
    found = []
    for py in SRC.rglob("*.py"):
        rel = py.relative_to(SRC).as_posix()
        if rel != "llm/client.py" and "api.meta.ai" in py.read_text(encoding="utf-8"):
            found.append(f"{rel} names the Meta API host")
        if rel not in HTTP_ALLOWED:
            found += [f"{rel} imports {m}" for m in _imports(py) if m.startswith(HTTP_CLIENTS)]
    assert found == []


def test_data_only_verdict_path_imports_no_model_or_camera_code():
    found = []
    for py in SRC.rglob("*.py"):
        rel = py.relative_to(SRC).as_posix()
        if rel.startswith(DATA_PATH) and rel not in DATA_PATH_EXEMPT:
            found += [f"{rel} imports {m}" for m in _imports(py)
                      if m.startswith(("zerostate.llm", "zerostate.camera")) or m == "zerostate.checks.live.camera"]
    assert found == []
