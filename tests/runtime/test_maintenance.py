"""Startup housekeeping: session auto-prune."""

from __future__ import annotations

import time

from clite.providers.testing import ScriptedClient, text_response
from clite.runtime import maintenance
from clite.runtime.factory import build_agent
from clite.state import get_session_db

DAY = 86400.0
MOCK = "model:\n  provider: mock\n  default: mock-1\n"


def _age(session_id: str, days: float) -> None:
    db = get_session_db()
    db.create_session(session_id, "cli")
    moment = time.time() - days * DAY
    db._conn.execute("UPDATE sessions SET started_at = ?, last_activity_at = ? WHERE id = ?", (moment, moment, session_id))
    db._conn.commit()


def test_auto_prune_is_off_by_default(clite_home):
    _age("ancient", 400)
    assert maintenance.auto_prune_sessions({"sessions": {"auto_prune": False, "retention_days": 90}}) is None
    assert get_session_db().get_session("ancient") is not None


def test_auto_prune_runs_at_most_once_a_day(clite_home):
    config = {"sessions": {"auto_prune": True, "retention_days": 30}}
    _age("ancient", 31)
    _age("recent", 5)
    now = time.time()
    assert maintenance.auto_prune_sessions(config, now=now) == 1
    assert get_session_db().get_session("ancient") is None and get_session_db().get_session("recent") is not None
    _age("ancient-2", 31)
    assert maintenance.auto_prune_sessions(config, now=now + 3600) is None  # too soon
    assert get_session_db().get_session("ancient-2") is not None
    assert maintenance.auto_prune_sessions(config, now=now + DAY + 1) == 1


def test_a_retention_of_zero_never_prunes(clite_home):
    _age("ancient", 400)
    assert maintenance.auto_prune_sessions({"sessions": {"auto_prune": True, "retention_days": 0}}) is None


def test_build_agent_prunes_once_and_spares_the_session_being_resumed(clite_home, monkeypatch):
    (clite_home / "config.yaml").write_text(MOCK + "sessions:\n  auto_prune: true\n  retention_days: 30\n")
    _age("resumed", 60)
    _age("stale", 60)
    agent = build_agent(session_id="resumed", client=ScriptedClient([text_response("back")]))
    try:
        db = get_session_db()
        assert db.get_session("stale") is None and db.get_session("resumed") is not None
        assert agent.chat("still there?") == "back"
        _age("stale-later", 60)
        db.set_meta(maintenance.LAST_AUTO_PRUNE_KEY, "0")
        build_agent(client=ScriptedClient([])).close()  # same process, same home: no second pass
        assert db.get_session("stale-later") is not None
    finally:
        agent.close()


def test_maintenance_failure_never_stops_a_session(clite_home, monkeypatch):
    (clite_home / "config.yaml").write_text(MOCK)

    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(maintenance, "auto_prune_sessions", boom)
    agent = build_agent(client=ScriptedClient([text_response("fine")]))
    try:
        assert agent.chat("hello") == "fine"
    finally:
        agent.close()
