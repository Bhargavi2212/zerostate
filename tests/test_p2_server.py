"""P2-6 / C1 for OPC UA: the P2 server's own permission check. `zerostate` can read but every write is
refused and logged; `operator` can write *.CMD but not PV/FB; SourceTimestamp advances (in-process server)."""

import json
import time

import pytest
from asyncua import ua
from asyncua.sync import Client
from conftest import P2_USERS


def connect(url, user=None, pw=None):
    c = Client(url, timeout=5)
    if user:
        c.set_user(user)
        c.set_password(pw if pw is not None else P2_USERS[user])
    try:
        c.connect()
    except BaseException:
        c.tloop.stop()  # its thread would otherwise keep the test process alive
        raise
    return c


def dv(x):
    return ua.DataValue(ua.Variant(float(x), ua.VariantType.Double))


def log(p):
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


@pytest.fixture
def plant(p2_server):
    """The shared server, with an empty write log and the update loop running."""
    _url, p, path = p2_server
    path.unlink(missing_ok=True)
    p.control({"request": "updates", "on": True})
    yield p2_server
    p.control({"request": "updates", "on": True})


def test_zerostate_reads_good_values_with_source_timestamps(plant):
    url, _, _ = plant
    c = connect(url, "zerostate")
    try:
        names = ["PT-211.PV", "FT-213.PV", "XV-201.FB", "XV-201.CMD"]
        first = c.read_attributes([c.get_node(f"ns=2;s={n}") for n in names])
        assert all(d.StatusCode.is_good() and d.SourceTimestamp is not None for d in first)
        assert 1500 < first[0].Value.Value < 2000 and first[2].Value.Value == 100
        time.sleep(0.3)
        later = c.read_attributes([c.get_node("ns=2;s=PT-211.PV")])[0]
        assert later.SourceTimestamp > first[0].SourceTimestamp
    finally:
        c.disconnect()


@pytest.mark.parametrize("node", ["XV-201.CMD", "PT-211.PV", "XV-201.FB"])
def test_every_zerostate_write_is_refused_and_logged(plant, node):
    url, p, path = plant
    before = dict(p.model.cmd)
    c = connect(url, "zerostate")
    try:
        with pytest.raises(ua.UaStatusCodeError):
            c.get_node(f"ns=2;s={node}").write_value(dv(0))
    finally:
        c.disconnect()
    assert log(path) == [{**log(path)[0], "user": "zerostate", "nodes": [node], "allowed": False}]
    assert p.model.cmd == before


def test_operator_may_write_cmd_only(plant):
    url, p, path = plant
    c = connect(url, "operator")
    try:
        c.get_node("ns=2;s=XV-201.CMD").write_value(dv(0))
        for node in ("PT-211.PV", "XV-201.FB"):
            with pytest.raises(ua.UaStatusCodeError):
                c.get_node(f"ns=2;s={node}").write_value(dv(0))
        time.sleep(0.6)  # 10 process-s of travel at x30 is 0.33 s
        assert c.get_node("ns=2;s=XV-201.FB").read_value() == 0 and p.model.pos["XV-201"] == 0
        c.get_node("ns=2;s=XV-201.CMD").write_value(dv(100))  # leave the shared plant as found
    finally:
        c.disconnect()
    assert [(e["user"], e["nodes"], e["allowed"]) for e in log(path)] == [
        ("operator", ["XV-201.CMD"], True), ("operator", ["PT-211.PV"], False), ("operator", ["XV-201.FB"], False),
        ("operator", ["XV-201.CMD"], True)]


@pytest.mark.parametrize("user,pw", [(None, None), ("zerostate", "wrong"), ("intruder", "x")])
def test_anonymous_and_unknown_users_are_refused(plant, user, pw):
    url, _, _ = plant
    with pytest.raises(Exception):  # noqa: B017 - asyncua raises its own error types per failure point
        connect(url, user, pw)


def test_stopped_update_loop_leaves_source_timestamp_old(plant):
    url, p, _ = plant
    c = connect(url, "zerostate")
    try:
        assert p.control({"request": "updates", "on": False})["updating"] is False
        time.sleep(0.15)
        a = c.read_attributes([c.get_node("ns=2;s=PT-211.PV")])[0]
        time.sleep(0.3)
        b = c.read_attributes([c.get_node("ns=2;s=PT-211.PV")])[0]
        assert b.SourceTimestamp == a.SourceTimestamp and b.Value.Value == a.Value.Value
    finally:
        c.disconnect()


def test_control_sets_faults_and_reads_truth(plant):
    _, p, _ = plant
    truth = p.control({"request": "set", "data": {"XV-204.leak_pct": 0.5, "PT-211.fault_mode": 1}})
    assert truth["faults"]["leak_pct"]["XV-204"] == 0.5 and truth["faults"]["sensor"]["PT-211"]["mode"] == 1
    assert "F-210" in truth["pressure_kpa_abs"] and p.control({"request": "nope"})["error"]
    p.control({"request": "set", "data": {"XV-204.leak_pct": 0, "PT-211.fault_mode": 0}})



def _p2_operator():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("p2_operator", Path(__file__).parents[1] / "plants" / "p2_gasline" / "operator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_p2_operator_sets_cmd_as_operator_and_never_prints_the_password(plant, monkeypatch, capsys):
    url, _, path = plant
    op = _p2_operator()
    monkeypatch.setenv("P2_PASSWORD_OPERATOR", P2_USERS["operator"])
    assert op.main(["--endpoint", url, "set", "XV-231", "0"]) == 0
    assert [(r["user"], r["allowed"], r["nodes"]) for r in log(path)] == [("operator", True, ["XV-231.CMD"])]
    assert op.main(["--endpoint", url, "status"]) == 0
    assert json.loads(capsys.readouterr().out)["command_pct"]["XV-231"] == 0
    assert op.main(["--endpoint", url, "wait-pressure-below", "PT-211", "1", "--mean-of", "2",
                    "--timeout-process-s", "30", "--process-time-scale", "30"]) == 2  # 1 kPa never reached: timeout
    assert op.main(["--endpoint", url, "set", "XV-231", "100"]) == 0
    monkeypatch.setenv("P2_PASSWORD_OPERATOR", "wrong")
    assert op.main(["--endpoint", url, "set", "XV-231", "0"]) == 1
    out = capsys.readouterr()
    assert P2_USERS["operator"] not in out.out + out.err and "wrong" not in out.out + out.err


def test_p2_operator_write_carries_a_source_timestamp(plant, monkeypatch):
    """Updates stopped, so no tick re-stamps the node: the value read back is the operator's own write.
    Unstamped, ZeroState reads it STALE (tuning seed 310)."""
    url, p, _ = plant
    monkeypatch.setenv("P2_PASSWORD_OPERATOR", P2_USERS["operator"])
    op = _p2_operator()
    p.control({"request": "updates", "on": False})
    try:
        assert op.main(["--endpoint", url, "set", "XV-231", "0"]) == 0
        c = connect(url, "zerostate")
        try:
            dv = c.read_attributes([c.get_node("ns=2;s=XV-231.CMD")])[0]
        finally:
            c.disconnect()
        assert dv.SourceTimestamp is not None
    finally:
        p.control({"request": "updates", "on": True})
