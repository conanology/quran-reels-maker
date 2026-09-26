import hashlib
import io
import json
import sqlite3
import zipfile
import pytest
from scripts.ci_run import build_arguments
from scripts.ci_state import create_checkpoint, restore_archive


@pytest.mark.parametrize("field, value", [("QRM_SLOT", '$(touch injected)'),
                                         ("QRM_RECITER", 'alafasy; echo injected'),
                                         ("QRM_DRY_RUN", 'true\nanything')])
def test_workflow_inputs_are_rejected_as_literals(field, value):
    env = {"QRM_ROUTE": "longform" if field == "QRM_RECITER" else "growth", field: value}
    with pytest.raises(ValueError):
        build_arguments(env)


def test_workflow_preview_never_requests_upload():
    assert build_arguments({"QRM_ROUTE": "growth", "QRM_DRY_RUN": "true"})[-1] == "--dry-run"
    assert build_arguments({"QRM_ROUTE": "longform", "QRM_TEST_MODE": "true"})[-1] == "--test"


def make_archive(files, **identity):
    buffer = io.BytesIO()
    manifest = {"version": 1, "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    manifest.update(identity)
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("checkpoint.json", json.dumps(manifest))
    return buffer.getvalue()


def test_checkpoint_roundtrip_retains_db_and_receipt(tmp_path):
    source = tmp_path / "original"
    (source / "database/upload_receipts").mkdir(parents=True)
    with sqlite3.connect(source / "database/quran_reels.db") as db:
        db.execute("CREATE TABLE example (value TEXT)")
        db.execute("INSERT INTO example VALUES ('preserve')")
    receipt_name = "database/upload_receipts/11111111-1111-1111-1111-111111111111.json"
    (source / receipt_name).write_text('{"job_id":"one","receipts":{}}')
    checkpoint = tmp_path / "checkpoint"
    manifest = create_checkpoint(source, checkpoint)
    assert receipt_name in manifest["files"]
    payload = make_archive({name: (checkpoint / name).read_bytes() for name in manifest["files"]})
    destination = tmp_path / "restored"
    restore_archive(payload, destination)
    with sqlite3.connect(destination / "database/quran_reels.db") as db:
        assert db.execute("SELECT value FROM example").fetchone()[0] == "preserve"
    assert json.loads((destination / receipt_name).read_text())["job_id"] == "one"


def test_corrupt_checkpoint_preserves_existing_destination(tmp_path):
    db = tmp_path / "database/quran_reels.db"
    db.parent.mkdir()
    db.write_bytes(b"original sentinel")
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        restore_archive(make_archive({"database/quran_reels.db": b"invalid sqlite"}), tmp_path)
    assert db.read_bytes() == b"original sentinel"


def test_traversal_checkpoint_never_writes(tmp_path):
    with pytest.raises(RuntimeError, match="Unsafe"):
        restore_archive(make_archive({"database/quran_reels.db": b"ignored", "../escape.json": b"{}"}), tmp_path)
    assert not list(tmp_path.rglob("*"))


def test_workflow_shells_have_no_expression_interpolation():
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    paths = list((root / ".github/workflows").glob("*.yml"))
    assert len(paths) >= 3
    for path in paths:
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        assert workflow["permissions"]["contents"] == "read"
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                command = step.get("run", "")
                assert "${{" not in command
                assert "git push" not in command and "git pull --rebase" not in command
    shared = yaml.load((root / ".github/workflows/publishing.yml").read_text(), Loader=yaml.BaseLoader)
    assert shared["concurrency"]["cancel-in-progress"] == "false"
    assert "github.event.repository.default_branch" in shared["jobs"]["run"]["if"]
    steps = shared["jobs"]["run"]["steps"]
    checkpoint = next(step for step in steps if step.get("id") == "checkpoint")
    assert "steps.restore.outcome == 'success'" in checkpoint["if"]
    persist = next(step for step in steps if step.get("name") == "Persist authoritative state")
    assert "steps.checkpoint.outcome == 'success'" in persist["if"]


def test_credential_json_is_literal_and_never_shell_code(tmp_path, monkeypatch):
    import scripts.ci_state as ci
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    payload = {"token": "synthetic '\" $() `command`\nnew line"}
    monkeypatch.setenv("YOUTUBE_TOKEN_JSON", json.dumps(payload))
    monkeypatch.delenv("YOUTUBE_CLIENT_SECRETS_JSON", raising=False)
    monkeypatch.delenv("TIKTOK_TOKEN_JSON", raising=False)
    ci.write_credentials()
    assert json.loads((tmp_path / "token.json").read_text()) == payload


def test_checkpoint_refuses_stale_destination_and_records_attempt(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    root = tmp_path / "state"
    (root / "database").mkdir(parents=True)
    with sqlite3.connect(root / "database/quran_reels.db") as database:
        database.execute("CREATE TABLE example(value TEXT)")
    manifest = create_checkpoint(root)
    assert (manifest["run_id"], manifest["run_attempt"]) == ("123", 1)
    with pytest.raises(RuntimeError, match="stale snapshot"):
        create_checkpoint(root)


def mock_ci_api(tmp_path, monkeypatch, *, artifact=True, source_attempt=1, latest_attempt=1,
                other_runs=(), jobs=(), jobs_by_attempt=None):
    import requests
    import scripts.ci_state as ci
    monkeypatch.setenv("GITHUB_REPOSITORY", "synthetic/repository")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_RUN_ID", "200")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-token")
    monkeypatch.delenv("QRM_ALLOW_STATE_BOOTSTRAP", raising=False)
    fixture = tmp_path / "source.db"
    with sqlite3.connect(fixture) as database:
        database.execute("CREATE TABLE example(value TEXT)")
    payload = make_archive({"database/quran_reels.db": fixture.read_bytes()},
                           run_id="100", run_attempt=source_attempt)
    calls = []
    class Response:
        def __init__(self, value=None):
            self.value = value
        def raise_for_status(self):
            pass
        def json(self):
            return self.value
        def iter_content(self, size):
            yield payload
    class Session:
        headers = {}
        def get(self, url, **kwargs):
            calls.append(url)
            if url.endswith("/actions/artifacts"):
                return Response({"artifacts": [{"id": 1, "created_at": "2026-09-25T12:00:00Z",
                    "workflow_run": {"id": 100, "head_branch": "main"}}] if artifact else []})
            if url.endswith("/actions/runs/100"):
                return Response({"run_attempt": latest_attempt, "created_at": "2026-09-25T10:00:00Z"})
            if "/actions/workflows/" in url:
                return Response({"workflow_runs": [{"run_attempt": 1, **run} for run in other_runs]})
            if url.endswith("/jobs"):
                if jobs_by_attempt is not None:
                    attempt = int(url.split("/attempts/")[1].split("/")[0])
                    return Response({"jobs": jobs_by_attempt.get(attempt, [])})
                return Response({"jobs": list(jobs)})
            if url.endswith("/zip"):
                return Response()
            raise AssertionError("Unexpected synthetic API path: " + url)
    monkeypatch.setattr(requests, "Session", Session)
    original_restore = ci.restore_archive
    restored = tmp_path / "restored"
    monkeypatch.setattr(ci, "restore_archive", lambda data, **identity:
                        original_restore(data, restored, **identity))
    return ci, calls, restored


def test_bootstrap_creates_no_intermediate_uploadable_checkpoint(tmp_path, monkeypatch):
    ci, calls, restored = mock_ci_api(tmp_path, monkeypatch, artifact=False)
    monkeypatch.setenv("QRM_ALLOW_STATE_BOOTSTRAP", "true")
    monkeypatch.setattr(ci, "create_checkpoint", lambda: pytest.fail("Bootstrap must not create a stale artifact"))
    assert ci.restore_latest() == {"bootstrap": True}
    assert not restored.exists()


def test_publishing_rerun_rejected_before_state_or_network(tmp_path, monkeypatch):
    ci, calls, restored = mock_ci_api(tmp_path, monkeypatch)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(RuntimeError, match="reruns require"):
        ci.restore_latest()
    assert calls == []
    assert not restored.exists()


def test_prior_attempt_artifact_rejected_before_any_state_write(tmp_path, monkeypatch):
    ci, calls, restored = mock_ci_api(tmp_path, monkeypatch, source_attempt=1, latest_attempt=2)
    with pytest.raises(RuntimeError, match="earlier workflow attempt"):
        ci.restore_latest()
    assert not restored.exists()


def test_current_attempt_checkpoint_restored(tmp_path, monkeypatch):
    ci, calls, restored = mock_ci_api(tmp_path, monkeypatch)
    assert ci.restore_latest()["run_attempt"] == 1
    assert (restored / "database/quran_reels.db").exists()


def test_older_dispatched_run_with_later_activity_requires_recovery(tmp_path, monkeypatch):
    run = {"id": 90, "created_at": "2026-09-25T09:00:00Z", "updated_at": "2026-09-25T13:00:00Z"}
    jobs = [{"conclusion": "failure", "steps": [
        {"name": "Restore durable publishing state", "conclusion": "success"},
        {"name": "Generate or publish intended occurrence", "conclusion": "failure"}]}]
    ci, calls, restored = mock_ci_api(tmp_path, monkeypatch, other_runs=[run], jobs=jobs)
    with pytest.raises(RuntimeError, match="Later publishing activity"):
        ci.restore_latest()
    assert not restored.exists()


@pytest.mark.parametrize("skipped_step", ["Restore durable publishing state",
                                        "Generate or publish intended occurrence"])
def test_later_preview_or_prepublication_failure_does_not_block(tmp_path, monkeypatch, skipped_step):
    run = {"id": 150, "created_at": "2026-09-25T13:00:00Z", "updated_at": "2026-09-25T14:00:00Z"}
    jobs = [{"steps": [{"name": skipped_step, "conclusion": "skipped"}]}]
    ci, calls, restored = mock_ci_api(tmp_path, monkeypatch, other_runs=[run], jobs=jobs)
    assert ci.restore_latest()["run_id"] == "100"


def test_later_unknown_jobs_fail_closed(tmp_path, monkeypatch):
    run = {"id": 150, "created_at": "2026-09-25T13:00:00Z", "updated_at": "2026-09-25T14:00:00Z"}
    ci, calls, restored = mock_ci_api(tmp_path, monkeypatch, other_runs=[run])
    with pytest.raises(RuntimeError, match="Later publishing activity"):
        ci.restore_latest()
    assert not restored.exists()


@pytest.mark.parametrize("jobs", [[], [{"steps": [
    {"name": "Restore durable publishing state", "conclusion": "success"},
    {"name": "Generate or publish intended occurrence", "conclusion": "failure"}]}]])
def test_missing_first_artifact_does_not_allow_rebootstrap_after_transfer_or_unknown_history(tmp_path, monkeypatch, jobs):
    run = {"id": 150, "created_at": "2026-09-25T13:00:00Z", "updated_at": "2026-09-25T14:00:00Z"}
    ci, calls, restored = mock_ci_api(tmp_path, monkeypatch, artifact=False, other_runs=[run], jobs=jobs)
    monkeypatch.setenv("QRM_ALLOW_STATE_BOOTSTRAP", "true")
    with pytest.raises(RuntimeError, match="Prior publishing activity"):
        ci.restore_latest()
    assert not restored.exists()


def test_bootstrap_allows_proven_prior_previews_without_writing_snapshot(tmp_path, monkeypatch):
    run = {"id": 150, "created_at": "2026-09-25T13:00:00Z", "updated_at": "2026-09-25T14:00:00Z"}
    jobs = [{"steps": [{"name": "Restore durable publishing state", "conclusion": "skipped"}]}]
    ci, calls, restored = mock_ci_api(tmp_path, monkeypatch, artifact=False, other_runs=[run], jobs=jobs)
    monkeypatch.setenv("QRM_ALLOW_STATE_BOOTSTRAP", "true")
    monkeypatch.setattr(ci, "create_checkpoint", lambda: pytest.fail("Bootstrap must not stage old state"))
    assert ci.restore_latest() == {"bootstrap": True}
    assert not restored.exists()


@pytest.mark.parametrize("artifact", [True, False])
def test_skipped_rerun_does_not_hide_earlier_transfer_uncertainty(tmp_path, monkeypatch, artifact):
    run = {"id": 150, "run_attempt": 2, "created_at": "2026-09-25T13:00:00Z", "updated_at": "2026-09-25T14:00:00Z"}
    jobs_by_attempt = {
        1: [{"steps": [{"name": "Generate or publish intended occurrence", "conclusion": "failure"}]}],
        2: [{"steps": [{"name": "Generate or publish intended occurrence", "conclusion": "skipped"}]}]}
    ci, calls, restored = mock_ci_api(tmp_path, monkeypatch, artifact=artifact,
                                     other_runs=[run], jobs_by_attempt=jobs_by_attempt)
    monkeypatch.setenv("QRM_ALLOW_STATE_BOOTSTRAP", "true")
    with pytest.raises(RuntimeError, match="publishing activity"):
        ci.restore_latest()
    assert not restored.exists()
