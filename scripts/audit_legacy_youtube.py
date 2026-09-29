"""Read-only comparison of legacy publishing rows with the owner's YouTube API.

This report is for deliberate state recovery. It never marks a row published,
changes video privacy, or advances the Shorts cursor.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sqlite3


VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


def audit(database_path, service, expected_channel_id):
    if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", expected_channel_id):
        raise ValueError("Expected YouTube channel ID is missing or invalid")
    channels = service.channels().list(part="id", mine=True).execute().get("items", [])
    if expected_channel_id not in {item.get("id") for item in channels}:
        raise RuntimeError("YouTube credentials do not belong to the expected channel")

    with sqlite3.connect(f"file:{Path(database_path).resolve().as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = []
        for kind, table in (("short", "reel_history"), ("longform", "longform_history")):
            for row in db.execute(f"SELECT id, youtube_id FROM {table} WHERE status='uploaded'"):
                rows.append({"kind": kind, "history_id": row["id"], "video_id": row["youtube_id"]})

    ids = sorted({row["video_id"] for row in rows if row["video_id"] and VIDEO_ID.fullmatch(row["video_id"])})
    remote = {}
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        response = service.videos().list(part="snippet,status,processingDetails", id=",".join(batch),
                                         maxResults=50).execute()
        for item in response.get("items", []):
            remote[item["id"]] = item

    details = []
    for row in rows:
        video_id = row["video_id"]
        item = remote.get(video_id) if video_id else None
        if not video_id or not VIDEO_ID.fullmatch(video_id):
            outcome = "missing_or_invalid_id"
        elif item is None:
            outcome = "not_returned_by_owner_api"
        elif item.get("snippet", {}).get("channelId") != expected_channel_id:
            outcome = "wrong_channel"
        elif item.get("status", {}).get("uploadStatus") != "processed":
            outcome = "not_processed"
        else:
            privacy = item.get("status", {}).get("privacyStatus")
            outcome = "confirmed_public" if privacy == "public" else (privacy or "unknown_privacy")
        # The repository is public; the artifact must not expose unlisted IDs.
        details.append({"kind": row["kind"], "history_id": row["history_id"], "outcome": outcome})

    counts = Counter((row["kind"], row["outcome"]) for row in details)
    return {"expected_channel_id": expected_channel_id, "history_rows": len(details),
            "unique_valid_ids": len(ids), "summary": {f"{kind}:{outcome}": count
                                                  for (kind, outcome), count in sorted(counts.items())},
            "rows": details}


def main():
    import os
    from youtube.auth import get_authenticated_service

    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("database/quran_reels.db"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.database, get_authenticated_service(), os.environ["YOUTUBE_EXPECTED_CHANNEL_ID"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("history_rows", "unique_valid_ids", "summary")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
