from unittest.mock import MagicMock

import pytest

from app import monitoring
from app.monitoring import Heartbeat


@pytest.mark.parametrize("fails", [False, True])
def test_heartbeat_throttles_successes_and_failures(monkeypatch, caplog, fails):
    clock = iter([0, 30, 60])
    monkeypatch.setattr(monitoring.time, "monotonic", lambda: next(clock))
    send = MagicMock()
    send.return_value.__enter__.return_value.status = 200
    if fails:
        send.side_effect = TimeoutError("https://hc-ping.com/private-token")
    monkeypatch.setattr(monitoring, "urlopen", send)
    heartbeat = Heartbeat("https://hc-ping.com/private-token", "collecting")
    for _ in range(3):
        heartbeat.ping()
    assert send.call_count == 2
    request = send.call_args.args[0]
    assert request.get_method() == "POST"
    assert send.call_args.kwargs["timeout"] == 3
    assert "private-token" not in caplog.text


def test_disabled_heartbeat_never_connects(monkeypatch):
    send = MagicMock()
    monkeypatch.setattr(monitoring, "urlopen", send)
    Heartbeat("", "collecting").ping()
    send.assert_not_called()


@pytest.mark.parametrize("remote,fails,expected", [(False, False, 0), (True, False, 1),
                                                   (True, True, 0)])
def test_backup_signals_only_after_remote_success(tmp_path, monkeypatch, remote, fails, expected):
    import sqlite3

    from app.backup import backup_once
    from app.backup_repository import Repository

    source = tmp_path / "source.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE sample (value TEXT)")
    monkeypatch.setenv("BACKUP_REMOTE_ENABLED", str(remote).lower())
    monkeypatch.setattr(Repository, "__init__", lambda self: None)
    events = []

    def upload(*args):
        events.append("upload")
        if fails:
            raise OSError("upload failed")

    monkeypatch.setattr(Repository, "backup", upload)
    ping = MagicMock(side_effect=lambda: events.append("ping"))
    monkeypatch.setattr(Heartbeat, "ping", ping)
    if fails:
        with pytest.raises(OSError):
            backup_once(source, tmp_path / "backups", 7)
    else:
        backup_once(source, tmp_path / "backups", 7)
    assert ping.call_count == expected
    if expected:
        assert events == ["upload", "ping"]


@pytest.mark.parametrize("fails", [False, True])
def test_publisher_signals_only_after_success(tmp_path, monkeypatch, fails):
    from app import publisher
    from app.config import Settings
    from app.r2_publisher import R2Publisher

    settings = Settings(_env_file=None, dashboard_storage="r2", dashboard_output_dir=tmp_path)
    monkeypatch.setattr(publisher, "get_settings", lambda: settings)
    monkeypatch.setattr(publisher.signal, "signal", lambda *args: None)
    stop = MagicMock()
    stop.is_set.side_effect = [False, True]
    monkeypatch.setattr(publisher.threading, "Event", lambda: stop)
    monkeypatch.setattr(publisher, "build_snapshot", lambda settings: object())
    monkeypatch.setattr(R2Publisher, "__init__", lambda self, settings: None)
    publish = MagicMock(return_value={"version": "test"})
    if fails:
        publish.side_effect = OSError("R2 unavailable")
    monkeypatch.setattr(R2Publisher, "publish", publish)
    ping = MagicMock()
    monkeypatch.setattr(Heartbeat, "ping", ping)
    publisher.main()
    assert ping.call_count == (0 if fails else 1)
