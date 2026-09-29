import sqlite3
from unittest.mock import MagicMock

import pytest

from scripts.audit_legacy_youtube import audit


CHANNEL = "UC" + "a" * 22


def _database(path):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE reel_history (id INTEGER, status TEXT, youtube_id TEXT)")
        db.execute("CREATE TABLE longform_history (id INTEGER, status TEXT, youtube_id TEXT)")
        db.executemany("INSERT INTO reel_history VALUES (?, ?, ?)",
                       [(1, "uploaded", "A" * 11), (2, "uploaded", "B" * 11),
                        (3, "generated", "Z" * 11)])
        db.execute("INSERT INTO longform_history VALUES (4, 'uploaded', ?)", ("C" * 11,))


def test_legacy_audit_reports_remote_truth_without_changing_history(tmp_path):
    db_path = tmp_path / "history.sqlite"
    _database(db_path)
    service = MagicMock()
    service.channels.return_value.list.return_value.execute.return_value = {"items": [{"id": CHANNEL}]}
    service.videos.return_value.list.return_value.execute.return_value = {"items": [
        {"id": "A" * 11, "snippet": {"channelId": CHANNEL},
         "status": {"uploadStatus": "processed", "privacyStatus": "public"}},
        {"id": "B" * 11, "snippet": {"channelId": CHANNEL},
         "status": {"uploadStatus": "processed", "privacyStatus": "unlisted"}},
    ]}
    report = audit(db_path, service, CHANNEL)
    assert report["summary"] == {"longform:not_returned_by_owner_api": 1,
                                 "short:confirmed_public": 1, "short:unlisted": 1}
    assert report["history_rows"] == 3
    assert service.videos.return_value.list.call_args.kwargs["id"] == ",".join(("A" * 11, "B" * 11, "C" * 11))
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM reel_history").fetchone()[0] == 3


def test_legacy_audit_rejects_wrong_channel_before_video_lookup(tmp_path):
    db_path = tmp_path / "history.sqlite"
    _database(db_path)
    service = MagicMock()
    service.channels.return_value.list.return_value.execute.return_value = {"items": [{"id": "UC" + "b" * 22}]}
    with pytest.raises(RuntimeError, match="expected channel"):
        audit(db_path, service, CHANNEL)
    service.videos.assert_not_called()
