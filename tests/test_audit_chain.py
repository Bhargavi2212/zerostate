"""C11: the audit log is append-only and hash-chained."""

import sqlite3
from itertools import pairwise

import pytest

from zerostate.audit.log import AuditLog


def filled(tmp_path):
    log = AuditLog(tmp_path / "audit.sqlite")
    for i in range(5):
        log.append("s1", "step_done", {"k": i})
    return log


def test_chain_verifies(tmp_path):
    log = filled(tmp_path)
    assert log.verify() == (True, None)
    ev = log.events("s1")
    assert all(b["prev_hash"] == a["hash"] for a, b in pairwise(ev))


@pytest.mark.parametrize("sql", ["UPDATE events SET kind = 'x' WHERE id = 2", "DELETE FROM events WHERE id = 2"])
def test_update_and_delete_are_rejected(tmp_path, sql):
    log = filled(tmp_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        log.db.execute(sql)


def test_tampering_is_detected(tmp_path):
    log = filled(tmp_path)
    log.db.execute("DROP TRIGGER events_no_update")  # an attacker with file access
    log.db.execute("""UPDATE events SET payload_json = '{"k":99}' WHERE id = 3""")
    assert log.verify() == (False, 3)
