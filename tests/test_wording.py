"""The one never-say checker (src/zerostate/wording.py): list matches PROJECT.md, docs and src are clean."""

import ast
from pathlib import Path

from zerostate import wording

ROOT = Path(__file__).resolve().parents[1]


def test_banned_text_is_caught():
    text = ("The episode was Safe. Label: fault-but-safe. Simulated camera, not visible to ZeroState. "
            "It verifies isolation, is safety-rated, never misses and would have prevented Buncefield.")
    found = {h.lower() for h in wording.hits(text)}
    assert {"safe", "simulated camera", "not visible to zerostate", "verifies isolation", "safety-rated",
            "never misses", "would have prevented"} <= found


def test_clean_text_passes():
    text = ("NO DISCREPANCY FOUND, awaiting sign-off. Idealised camera (renders the simulator's true state). "
            "Not safety-rated. Fault below hazard limits. Unsafe episodes are labelled from truth.")
    assert wording.hits(text) == []


def test_list_matches_project_md():
    line = next(l for l in (ROOT / "docs" / "PROJECT.md").read_text(encoding="utf-8").splitlines()
                if l.startswith(wording.DEFINITION))
    assert line[len(wording.DEFINITION):].rstrip(".").split("; ") == list(wording.NEVER_SAY)


def test_every_list_item_is_caught_by_its_own_patterns():
    # each item's own wording (quotes and the "/" alternatives aside) hits at least one pattern
    for item in wording.NEVER_SAY:
        assert wording.hits(item.replace('"', "")), item


def test_cli_exit_codes(tmp_path, capsys):
    bad, good = tmp_path / "bad.md", tmp_path / "good.md"
    bad.write_text("all clear\nthe plant is safe\n", encoding="utf-8")
    good.write_text("all clear\n", encoding="utf-8")
    assert wording.main([str(good)]) == 0
    assert wording.main([str(good), str(bad)]) == 1
    assert "bad.md:2: 'safe'" in capsys.readouterr().out


def test_docs_are_clean(capsys):
    docs = sorted(str(p) for p in (ROOT / "docs").glob("*.md"))  # docs/specs/ quotes banned words as rules
    assert wording.main(docs) == 0, capsys.readouterr().out


def test_src_string_literals_are_clean():
    hits = []
    for py in (ROOT / "src" / "zerostate").rglob("*.py"):
        if py.name == "wording.py":  # holds the list itself
            continue
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and wording.hits(node.value):
                hits.append(f"{py.relative_to(ROOT)}:{node.lineno}: {wording.hits(node.value)}")
    assert hits == []
