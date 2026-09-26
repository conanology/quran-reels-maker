"""Construct literal CLI arguments from typed workflow inputs."""
import datetime
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_SLOTS = {"0 2 * * *": "morning_short", "0 18 * * 0-4,6": "evening_short",
                  "0 18 * * 5": "friday_long", "0 19 * * 6": "saturday_sleep"}
VALID_SLOTS = {"auto", "morning_short", "evening_short", "friday_long", "saturday_sleep"}
VALID_RECITERS = {"auto", "alafasy", "shuraym", "sudais", "husary", "shaatree",
                 "maher_muaiqly", "abdul_basit_mujawwad", "abdul_basit_murattal",
                 "minshawi_mujawwad", "hudhaify", "banna"}


def build_arguments(environ):
    route = environ.get("QRM_ROUTE", "growth")
    if route not in {"growth", "longform"}:
        raise ValueError("Invalid workflow route")
    arguments = [sys.executable, str(ROOT / "main.py")]
    test = environ.get("QRM_TEST_MODE", "false")
    dry = environ.get("QRM_DRY_RUN", "false")
    if test not in {"true", "false"} or dry not in {"true", "false"}:
        raise ValueError("Invalid boolean input")
    if route == "growth":
        slot = environ.get("QRM_SLOT", "auto") or "auto"
        schedule = environ.get("QRM_SCHEDULE", "")
        if schedule:
            if schedule not in SCHEDULE_SLOTS:
                raise ValueError("Unknown schedule expression")
            slot = SCHEDULE_SLOTS[schedule]
        if slot not in VALID_SLOTS:
            raise ValueError("Invalid slot")
        arguments.extend(["growth-engine", "run"])
        if slot != "auto":
            arguments.extend(["--slot", slot])
        if dry == "true" or test == "true":
            arguments.append("--dry-run")
    else:
        reciter = environ.get("QRM_RECITER", "auto") or "auto"
        if reciter not in VALID_RECITERS:
            raise ValueError("Invalid reciter")
        arguments.extend(["longform", "auto"])
        if reciter != "auto":
            arguments.extend(["--reciter", reciter])
        if test == "true" or dry == "true":
            arguments.append("--test")
    return arguments


def scheduled_run_is_current(environ, *, now=None):
    if not environ.get("QRM_SCHEDULE"):
        return True
    import requests
    response = requests.get(
        f"https://api.github.com/repos/{environ['GITHUB_REPOSITORY']}/actions/runs/{environ['GITHUB_RUN_ID']}",
        headers={"Authorization": "Bearer " + environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json"},
        timeout=30)
    response.raise_for_status()
    created = datetime.datetime.fromisoformat(response.json()["created_at"].replace("Z", "+00:00"))
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not 0 <= (now - created).total_seconds() <= 7200:
        return False
    if environ.get("QRM_ROUTE", "growth") == "growth":
        import pytz
        mecca = now.astimezone(pytz.timezone("Asia/Riyadh"))
        slot = SCHEDULE_SLOTS.get(environ["QRM_SCHEDULE"])
        if slot == "morning_short":
            return 5 <= mecca.hour < 7
        if slot == "evening_short":
            return 21 <= mecca.hour < 23
        if slot == "friday_long":
            return mecca.weekday() == 4 and 21 <= mecca.hour < 23
        if slot == "saturday_sleep":
            return mecca.weekday() == 5 and 22 <= mecca.hour < 24
        return False
    return True


def main():
    arguments = build_arguments(os.environ)
    if not scheduled_run_is_current(os.environ):
        print("Scheduled occurrence expired; skipped without publishing")
        return 0
    return subprocess.call(arguments, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
