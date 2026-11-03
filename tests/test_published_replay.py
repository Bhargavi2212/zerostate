"""C11 regression gate: every published P1 episode still replays to its logged findings and verdicts
under today's rules and thresholds. Any change to a rule, the gate or the session must keep this green
(SUPERSEDED episodes are the logged QUALITY v1 false trips: their replay differs by design)."""

import json
from pathlib import Path

import pytest

from zerostate.audit.log import AuditLog
from zerostate.audit.replay import replay
from zerostate.config import load_thresholds

ROOT = Path(__file__).parents[1]
EPISODES = sorted(p for p in (ROOT / "eval" / "results" / "episodes").iterdir()
                  if (p / "audit_export.json").exists() and not (p / "SUPERSEDED.md").exists())


def test_there_are_published_episodes():
    assert len(EPISODES) >= 25


@pytest.mark.parametrize("run", EPISODES, ids=lambda p: p.name)
def test_published_episode_replays_identically(run, tmp_path):
    log = AuditLog(tmp_path / "audit.sqlite")
    for e in json.loads((run / "audit_export.json").read_text(encoding="utf-8")):
        log.append(e["session"], e["kind"], e["payload"], ts=e["ts"])
    params = load_thresholds(ROOT / "plants" / "p1_grfics" / "thresholds.yaml")
    assert replay(log, run.name, params) == []
