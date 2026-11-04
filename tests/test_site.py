"""site/ (P3-6): built from the replay API and the score files only; banner everywhere; no write path; clean wording."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SITE = ROOT / "site"
spec = importlib.util.spec_from_file_location("build_site_data", ROOT / "eval" / "tools" / "build_site_data.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)
spec = importlib.util.spec_from_file_location("export_bundle", ROOT / "eval" / "tools" / "export_bundle.py")
eb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eb)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    return out, bs.build(out)


def test_site_data_builds_and_matches_the_committed_site(built):
    _, texts = built
    assert "data/sessions.json" in texts and "results.html" in texts
    sessions = json.loads(texts["data/sessions.json"])
    assert {s["id"] for s in sessions} == {p.parent.name for p, _ in bs.EPISODES}
    for s in sessions:
        assert f"data/sessions/{s['id']}/detail.json" in texts and f"data/sessions/{s['id']}/stream.json" in texts
    committed = {p.relative_to(SITE).as_posix(): p.read_text(encoding="utf-8") for p in SITE.rglob("*") if p.is_file()}
    assert committed == texts, "site/ is stale: run python eval/tools/build_site_data.py"


def test_every_included_bundle_validates():
    for p, _ in bs.EPISODES:
        b = eb.load(p)
        assert b.episode == p.parent.name and b.result["valid"] is True


def test_every_number_on_the_results_page_equals_the_score_file():
    page = (SITE / "results.html").read_text(encoding="utf-8")
    cells = re.findall(r'<section class="batch" data-batch="([^"]+)">(.*?)</section>', page, re.DOTALL)
    assert {b for b, _ in cells} == {b for b, _ in bs.BATCHES}
    checked = 0
    for batch, body in cells:
        p = ROOT / "eval" / "results" / f"score_{batch}.json"
        sealed = (ROOT / "eval" / f"sealed_hash_{batch}.txt").read_text(encoding="utf-8").strip()
        assert re.search(rf'data-seal="{batch}">{sealed}<', body)
        if not p.exists():
            assert "Scoring in progress" in body and "data-k" not in body
            continue
        score = json.loads(p.read_text(encoding="utf-8"))
        assert score["engine"] in body
        for key, shown in re.findall(r'data-k="([^"]+)">([^<]*)<', body):
            assert shown == str(bs._v(score, key)), (batch, key)
            checked += 1
        assert re.search(r'data-k="dangerous_miss\.secondary\.ci_high"', body) and 'data-k="invalid.k"' in body
    assert checked > 50


def test_banner_on_every_page():
    for p in SITE.glob("*.html"):
        assert bs.BANNER in p.read_text(encoding="utf-8"), p


def test_wording_clean_and_nothing_key_like():
    for p in SITE.rglob("*"):
        if p.is_file():
            bs.check_text(str(p), p.read_text(encoding="utf-8"))  # raises on a hit


def test_no_write_endpoint_or_sign_control():
    code = "\n".join(p.read_text(encoding="utf-8") for p in SITE.glob("*") if p.suffix in (".js", ".html"))
    for bad in ("/sign", "/confirm", "/explain", "/steps/", "/plans/", "intake.js", "sign-open", "sign-wait",
                "Accept and sign", "Mark done", "data-action", "explain-ask", "<button", '"button"'):
        assert bad not in code, bad
    assert not (SITE / "intake.js").exists()
