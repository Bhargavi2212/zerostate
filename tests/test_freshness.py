from datetime import UTC, datetime

from zerostate.adapters.freshness import FreshnessTracker
from zerostate.adapters.modbus import MapEntry
from zerostate.models.signal import Quality, Signal


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def entry(tag, group="tank", ok=(), placeholder=()):
    return MapEntry(
        tag=tag, host="h", table="ir", address=0, scale_min=0, scale_max=1, unit="x",
        source_group=group, max_static_wall_s=10,
        constant_ok_raw=ok if ok == "any" else list(ok), placeholder_raw=list(placeholder),
    )


def sig(tag, raw, quality=Quality.GOOD):
    return Signal(tag=tag, value=raw, raw=raw, quality=quality, source_ts=None, recv_ts=datetime.now(UTC))


def run(tracker, clock, t, **raws):
    clock.t = t
    return {k: v.quality for k, v in tracker.apply({k: sig(k, r) for k, r in raws.items()}).items()}


def setup(*entries):
    clock = Clock()
    return FreshnessTracker(entries, clock), clock


def test_placeholder_is_unknown():
    tr, c = setup(entry("pressure", placeholder=[309]))
    assert run(tr, c, 0, pressure=309) == {"pressure": Quality.UNKNOWN}


def test_change_resets_and_static_goes_stale():
    tr, c = setup(entry("pressure"), entry("level"))
    run(tr, c, 0, pressure=100, level=5)
    assert run(tr, c, 8, pressure=101, level=6)["pressure"] == Quality.GOOD
    q = run(tr, c, 15, pressure=101, level=7)  # pressure static 7 s
    assert q["pressure"] == Quality.GOOD
    q = run(tr, c, 19, pressure=101, level=8)  # pressure static 11 s
    assert q == {"pressure": Quality.STALE, "level": Quality.GOOD}


def test_any_constant_stays_good_with_static_for():
    tr, c = setup(entry("valve", ok="any"), entry("pressure"))
    run(tr, c, 0, valve=30000, pressure=1)
    assert run(tr, c, 60, valve=30000, pressure=2)["valve"] == Quality.GOOD
    assert tr.static_for_s("valve") == 60


def test_flow_only_constant_at_cutoff():
    tr, c = setup(entry("flow", group="feed1", ok=[0]), entry("flow2", group="feed2", ok=[0]))
    run(tr, c, 0, flow=26000, flow2=0)
    assert run(tr, c, 30, flow=26000, flow2=0) == {"flow": Quality.STALE, "flow2": Quality.GOOD}


def test_dead_group_marks_every_tag_stale():
    tr, c = setup(entry("pressure"), entry("level"), entry("valve", ok="any"))
    run(tr, c, 0, pressure=1, level=2, valve=3)
    q = run(tr, c, 11, pressure=1, level=2, valve=3)
    assert set(q.values()) == {Quality.STALE}


def test_group_without_noise_carrying_tags_is_not_dead():
    tr, c = setup(entry("valve", group="purge", ok="any"), entry("flow", group="purge", ok=[0]))
    run(tr, c, 0, valve=0, flow=0)
    assert set(run(tr, c, 100, valve=0, flow=0).values()) == {Quality.GOOD}


def test_bad_passes_through():
    tr, _ = setup(entry("pressure"))
    out = tr.apply({"pressure": Signal(tag="pressure", value=None, raw=None, quality=Quality.BAD,
                                       source_ts=None, recv_ts=datetime.now(UTC))})
    assert out["pressure"].quality == Quality.BAD
