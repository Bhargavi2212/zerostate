"""Baselines (eval/baselines/): the gauge rule on committed p1 episodes, and its scoring in eval/score.py."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
BENCH = ROOT / "eval" / "results" / "bench" / "p1"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gauge = _load("gauge_rule", ROOT / "eval" / "baselines" / "gauge_rule.py")
score = _load("score", ROOT / "eval" / "score.py")


def _ep(prefix):
    return next(p for p in BENCH.iterdir() if p.name.startswith(prefix))


def test_gauge_rule_passes_a_clean_vented_episode():
    d = gauge.decide(_ep("S0_seed1184053442_"))
    assert d["answer"] == "pass" and d["values"]["pressure"] < 150


def test_gauge_rule_passes_a_leak_below_the_meter_cutoff():
    d = gauge.decide(_ep("S4-small_seed1318434843_"))  # true f1 leak, measured 0 below the cutoff
    assert d["answer"] == "pass" and d["values"]["f1_flow"] == 0


def test_gauge_rule_blocks_on_pressure_or_flow_at_the_last_mark():
    d = gauge.decide(_ep("S4-large_seed1200348533_"))  # stopped at step 2, still at plant pressure
    assert d["answer"] == "block" and d["values"]["pressure"] >= 150


def test_nearest_sample_and_missing_reading():
    sig = {"t": [10.0, 11.0, 12.0], "pressure": [1.0, 2.0, None]}
    assert gauge.at(sig, "pressure", 10.6) == 2.0
    assert gauge.at(sig, "pressure", 12.0) == 2.0  # a missing sample is skipped
    assert gauge.at(sig, "f1_flow", 10.0) is None


def test_gauge_rule_scored_with_the_same_hazard_code():
    eps = {p.name: score.load_episode(p) for p in (_ep("S0_seed1184053442_"), _ep("S4-small_seed1318434843_"))}
    b = score.baselines(eps, score.P1_FULL_SCALE, ROOT / "no_muse_results.json")
    g = b["gauge_rule"]
    assert g["dangerous_miss"]["primary"]["k"] == 0 and g["dangerous_miss"]["primary"]["n"] == 2
    assert g["dangerous_miss"]["secondary"]["k"] == 1  # the passed leak: true f1 above 0.1 % after the mark
    assert "muse_alone" not in b


muse = _load("muse_alone", ROOT / "eval" / "baselines" / "muse_alone.py")


class FakeCall:
    """Stands in for client.spark_json: records each call, returns a pinned decision. No network."""

    def __init__(self, decision="pass", fail=False):
        self.decision, self.fail, self.calls = decision, fail, []

    def __call__(self, messages, schema, purpose, temperature=None):
        self.calls.append({"messages": messages, "purpose": purpose, "temperature": temperature})
        if self.fail:
            raise muse.client.ModelUnavailable("fake: no reply")
        return schema(decision=self.decision, reason="fake")


def test_muse_alone_one_call_temperature_zero_and_pinned_mapping():
    fake = FakeCall("block")
    r = muse.run_one(_ep("S0_seed1184053442_"), call=fake)
    assert r["answer"] == "block" and r["t"] is not None
    assert len(fake.calls) == 1 and fake.calls[0]["temperature"] == 0
    text = fake.calls[0]["messages"][0]["content"]
    assert text.startswith((ROOT / "eval" / "baselines" / "muse_alone_v1.md").read_text(encoding="utf-8"))
    assert "PLAN:" in text and "MEASURED SERIES" in text and "pressure" in text
    assert "truth" not in text.lower()  # measured signals only, never simulator internals
    assert muse.ANSWER == {"pass": "pass", "block": "block"}


def test_muse_alone_unavailable_is_listed_not_counted(tmp_path):
    out = tmp_path / "muse.json"
    res = muse.run_batch([_ep("S0_seed1184053442_")], out, call=FakeCall(fail=True))
    assert next(iter(res["episodes"].values()))["answer"] == "unavailable"
    fake = FakeCall("pass")
    res = muse.run_batch([_ep("S0_seed1184053442_")], out, call=fake)  # resumes: retries the unavailable one
    assert len(fake.calls) == 1 and next(iter(res["episodes"].values()))["answer"] == "pass"
    muse.run_batch([_ep("S0_seed1184053442_")], out, call=fake)
    assert len(fake.calls) == 1  # an answered episode is never called again


def test_muse_alone_scored_by_score_py(tmp_path):
    ep = _ep("S4-small_seed1318434843_")
    out = tmp_path / "muse.json"
    muse.run_batch([ep], out, call=FakeCall("pass"))
    b = score.baselines({ep.name: score.load_episode(ep)}, score.P1_FULL_SCALE, out)
    assert b["muse_alone"]["dangerous_miss"]["primary"] == {"k": 0, "n": 1, "ci_low": 0.0, "ci_high": 0.7935, "ci_high_pct": 79}
    assert b["muse_alone"]["dangerous_miss"]["secondary"]["k"] == 1


def test_muse_alone_dry_run_projects_without_calling(capsys, monkeypatch):
    monkeypatch.setattr(muse.client, "spark_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    p = muse.projection([_ep("S0_seed1184053442_"), _ep("S4-small_seed1318434843_")])
    assert p["calls"] == 2 and p["input_tokens_est"] > 0 and p["usd_est"] > 0


def test_spark_json_sends_temperature_only_when_given(tmp_path, monkeypatch):
    import io
    import json as js

    class Opener:
        def __init__(self):
            self.bodies = []

        def open(self, req, timeout=None):
            self.bodies.append(js.loads(req.data))
            return io.BytesIO(js.dumps({"choices": [{"message": {"content": '{"decision": "pass", "reason": "x"}'}}],
                                        "usage": {}}).encode())

    monkeypatch.setenv("MODEL_API_KEY", "fake-key-for-test")  # pragma: allowlist secret
    monkeypatch.setenv("ZS_CREDITS", str(tmp_path / "credits.jsonl"))
    op = Opener()
    muse.client.spark_json([{"role": "user", "content": "x"}], muse.Decision, "t", opener=op, temperature=0)
    muse.client.spark_json([{"role": "user", "content": "x"}], muse.Decision, "t", opener=op)
    assert op.bodies[0]["temperature"] == 0 and "temperature" not in op.bodies[1]
