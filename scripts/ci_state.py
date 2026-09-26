"""Serialized CI state checkpoints, without Git writes or credential artifacts.

Run only from authorized Actions jobs. Restore fails closed if state is missing,
expired, corrupt, or a newer publishing run lacks a checkpoint.
"""
import argparse
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STATE_NAME = "qrm-publishing-state"
MAX_STATE_BYTES = 64 * 1024 * 1024
WORKFLOWS = ("growth-engine.yml", "scheduled-longform.yml")


def allowed_state_name(name):
    if name in {"database/quran_reels.db", "database/background_usage_history.json",
                "outputs/longform/background_usage.json"}:
        return True
    return bool(re.fullmatch(r"database/upload_receipts/[0-9a-f-]{36}\.json", name)
                or re.fullmatch(r"database/upload_attempts/[0-9a-f-]{36}-(youtube|tiktok)\.json", name))


def create_checkpoint(root=ROOT, destination=None):
    root = Path(root)
    destination = Path(destination or root / ".ci-state")
    # Each Actions checkout gets one final snapshot. A previous snapshot must
    # never be republished after a partial/failed attempt to overwrite it.
    if destination.exists():
        raise RuntimeError("Checkpoint destination already exists; refusing stale snapshot reuse")
    destination.mkdir(parents=True, exist_ok=True)
    db = root / "database/quran_reels.db"
    if not db.is_file():
        raise RuntimeError("No initialized publishing state; refusing checkpoint")
    database_copy = destination / "database/quran_reels.db"
    database_copy.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(database_copy)) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("State database failed integrity check")
    files = [database_copy]
    for name in ["database/background_usage_history.json", "outputs/longform/background_usage.json"]:
        source_path = root / name
        if source_path.is_file():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source_path.read_bytes())
            files.append(target)
    evidence = list((root / "database/upload_receipts").glob("*.json"))
    evidence += list((root / "database/upload_attempts").glob("*.json"))
    for receipt in evidence:
        name = receipt.relative_to(root).as_posix()
        if not allowed_state_name(name):
            raise RuntimeError("Invalid receipt filename")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(receipt.read_bytes())
        files.append(target)
    manifest = {"version": 1, "run_id": os.getenv("GITHUB_RUN_ID"),
                "run_attempt": int(os.getenv("GITHUB_RUN_ATTEMPT", "1")),
                "files": {file.relative_to(destination).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
                          for file in files}}
    (destination / "checkpoint.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def restore_archive(payload, root=ROOT, *, expected_run_id=None, expected_run_attempt=None):
    """Validate the entire archive before touching any destination file."""
    if len(payload) > MAX_STATE_BYTES:
        raise RuntimeError("Checkpoint archive exceeds bound")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(item.file_size for item in entries) > MAX_STATE_BYTES:
            raise RuntimeError("Checkpoint expansion exceeds bound")
        names = [entry.filename for entry in entries if not entry.is_dir()]
        if len(names) != len(set(names)) or "checkpoint.json" not in names:
            raise RuntimeError("Missing or duplicate checkpoint manifest")
        manifest = json.loads(archive.read("checkpoint.json"))
        if manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict):
            raise RuntimeError("Unsupported checkpoint")
        if expected_run_id is not None and str(manifest.get("run_id")) != str(expected_run_id):
            raise RuntimeError("Checkpoint workflow run identity mismatch")
        if expected_run_attempt is not None and manifest.get("run_attempt") != expected_run_attempt:
            raise RuntimeError("Checkpoint is from an earlier workflow attempt; reconcile before publishing")
        if set(names) != set(manifest["files"]) | {"checkpoint.json"}:
            raise RuntimeError("Unexpected checkpoint files")
        if "database/quran_reels.db" not in manifest["files"]:
            raise RuntimeError("Checkpoint has no state database")
        contents = {}
        for name, checksum in manifest["files"].items():
            if not allowed_state_name(name):
                raise RuntimeError("Unsafe checkpoint path")
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != checksum:
                raise RuntimeError("Checkpoint checksum mismatch")
            contents[name] = data
    # Validate SQLite bytes in a disposable file before replacing any state.
    with tempfile.TemporaryDirectory(prefix="qrm-checkpoint-") as temporary:
        temporary_db = Path(temporary) / "state.db"
        temporary_db.write_bytes(contents["database/quran_reels.db"])
        with closing(sqlite3.connect(f"file:{temporary_db.as_posix()}?mode=ro", uri=True)) as database:
            if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Checkpoint state failed integrity check")
    from core.runtime_safety import atomic_write_bytes
    root = Path(root).resolve()
    for name, data in contents.items():
        destination = (root / name).resolve()
        if not destination.is_relative_to(root):
            raise RuntimeError("Checkpoint destination escaped workspace")
        if name.endswith(".json"):
            json.loads(data)
    for name, data in contents.items():
        atomic_write_bytes(root / name, data)
    return manifest


def restore_latest():
    # A rerun can follow remote mutation with a failed artifact upload. Its old
    # run ID and checkpoint cannot prove that retrying the transfer is safe.
    if os.getenv("GITHUB_RUN_ATTEMPT", "1") != "1":
        raise RuntimeError("Automated publishing reruns require explicit state/remote reconciliation")
    import requests
    repository = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ["GITHUB_REF_NAME"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise RuntimeError("Invalid repository")
    base = f"https://api.github.com/repos/{repository}"
    session = requests.Session()
    session.headers.update(Authorization="Bearer " + os.environ["GITHUB_TOKEN"],
                           Accept="application/vnd.github+json", **{"X-GitHub-Api-Version": "2022-11-28"})
    def get_json(endpoint, **params):
        response = session.get(base + endpoint, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    current_run = int(os.environ["GITHUB_RUN_ID"])
    def attempt_proves_no_publication(run_id, attempt):
        jobs = []
        for page in range(1, 11):
            listing = get_json(f"/actions/runs/{run_id}/attempts/{attempt}/jobs", per_page=100, page=page)
            batch = listing.get("jobs", [])
            jobs.extend(batch)
            if len(batch) < 100:
                break
        else:
            return False
        if not jobs:
            return False
        for job in jobs:
            if job.get("conclusion") == "skipped":
                continue
            steps = {step.get("name"): step.get("conclusion") for step in job.get("steps", [])}
            if steps.get("Restore durable publishing state") == "skipped":
                continue  # Explicit dry-run/test workflow.
            if steps.get("Generate or publish intended occurrence") == "skipped":
                continue  # Failed before reaching the publishing command.
            return False
        return True
    def proves_no_publication(run):
        attempts = run.get("run_attempt")
        if type(attempts) is not int or not 1 <= attempts <= 10:
            return False
        # A later skipped rerun cannot erase uncertainty from an earlier
        # attempt whose transfer/checkpoint failed.
        return all(attempt_proves_no_publication(run["id"], attempt)
                   for attempt in range(1, attempts + 1))
    def prior_runs():
        for workflow in WORKFLOWS:
            for page in range(1, 11):
                listing = get_json(f"/actions/workflows/{workflow}/runs", branch=branch, per_page=100, page=page)
                runs = listing.get("workflow_runs", [])
                yield from (run for run in runs if run["id"] != current_run)
                if len(runs) < 100:
                    break
            else:
                raise RuntimeError("Workflow history exceeds recovery bound; explicit reconciliation required")
    candidates = []
    for page in range(1, 11):
        listing = get_json("/actions/artifacts", name=STATE_NAME, per_page=100, page=page)
        entries = listing.get("artifacts", [])
        candidates.extend(entry for entry in entries if not entry.get("expired")
                          and entry.get("workflow_run", {}).get("head_branch") == branch)
        if len(entries) < 100:
            break
    if not candidates:
        if os.getenv("QRM_ALLOW_STATE_BOOTSTRAP") == "true":
            # A missing first snapshot after transfer is uncertainty, not a
            # second bootstrap. A persistent repository variable cannot erase it.
            if any(not proves_no_publication(run) for run in prior_runs()):
                raise RuntimeError("Prior publishing activity has no checkpoint; bootstrap requires explicit recovery")
            # Only the final checkpoint step may create the artifact directory.
            return {"bootstrap": True}
        raise RuntimeError("No durable state checkpoint; explicit reviewed bootstrap/recovery is required")
    artifact = max(candidates, key=lambda entry: entry["created_at"])
    checkpoint_run = artifact["workflow_run"]["id"]
    checkpoint_info = get_json(f"/actions/runs/{checkpoint_run}")
    checkpoint_attempt = checkpoint_info["run_attempt"]
    if type(checkpoint_attempt) is not int or checkpoint_attempt < 1:
        raise RuntimeError("Invalid checkpoint workflow attempt")
    checkpoint_created = artifact["created_at"]
    for run in prior_runs():
        if run["id"] == checkpoint_run:
            continue
        if max(run["created_at"], run.get("updated_at", run["created_at"])) > checkpoint_created:
            if not proves_no_publication(run):
                raise RuntimeError("Later publishing activity has no selected checkpoint; reconcile before another run")
    response = session.get(base + f"/actions/artifacts/{artifact['id']}/zip", timeout=30, stream=True)
    response.raise_for_status()
    payload = bytearray()
    for chunk in response.iter_content(64 * 1024):
        payload.extend(chunk)
        if len(payload) > MAX_STATE_BYTES:
            raise RuntimeError("Checkpoint download exceeds bound")
    return restore_archive(bytes(payload), expected_run_id=checkpoint_run,
                           expected_run_attempt=checkpoint_attempt)


def write_credentials():
    from core.runtime_safety import atomic_write_json
    for variable, name in [("YOUTUBE_TOKEN_JSON", "token.json"),
                           ("YOUTUBE_CLIENT_SECRETS_JSON", "client_secrets.json"),
                           ("TIKTOK_TOKEN_JSON", "token_tiktok.json")]:
        value = os.getenv(variable, "")
        if value:
            data = json.loads(value)
            if not isinstance(data, dict):
                raise RuntimeError("Credential payload must be a JSON object")
            atomic_write_json(ROOT / name, data, private=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["restore", "checkpoint", "credentials"])
    args = parser.parse_args()
    if args.action == "restore":
        restore_latest()
    elif args.action == "checkpoint":
        create_checkpoint()
    else:
        write_credentials()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    main()
