"""Lightweight server-side analytics for tracking API usage."""

import fcntl
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


_DATA_DIR = Path(os.environ.get("RAROC_ANALYTICS_DIR", "/tmp/raroc_analytics"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_EVENTS_PATH = _DATA_DIR / "events.jsonl"


def track(event: str, **props):
    """Append an analytics event. Fire-and-forget, never raises."""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **props,
        }
        with open(_EVENTS_PATH, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass


def get_stats(days: int = 30) -> dict:
    """Aggregate events for the last N days."""
    if not _EVENTS_PATH.exists():
        return {"total_events": 0, "by_event": {}, "by_day": {}}

    now = datetime.now(timezone.utc)
    by_event = defaultdict(int)
    by_day = defaultdict(lambda: defaultdict(int))
    total = 0

    with open(_EVENTS_PATH) as f:
        for line in f:
            try:
                e = json.loads(line)
                ts = datetime.fromisoformat(e["ts"])
                delta = (now - ts).days
                if delta > days:
                    continue
                total += 1
                event = e["event"]
                by_event[event] += 1
                day = ts.strftime("%Y-%m-%d")
                by_day[day][event] += 1
            except Exception:
                continue

    return {
        "total_events": total,
        "days": days,
        "by_event": dict(by_event),
        "by_day": {d: dict(v) for d, v in sorted(by_day.items())},
    }
