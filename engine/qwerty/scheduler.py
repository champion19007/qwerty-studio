"""
Scheduled warm-up — keep a profile's session from going stale, unattended.

A profile you log into once and then leave for three weeks looks, on your next
visit, like a browser that was frozen and thawed: no fresh cookies, no recent
history, a session token about to expire. Sites that score risk treat that
"cold" return with suspicion. Scheduled warm-up fixes it by running the ordinary
:mod:`qwerty.warmup` browse on a recurring interval, so each profile keeps a
believable, up-to-date trail without anyone sitting there clicking.

This module is only the *bookkeeping*: a small JSON-backed store of schedules
and the pure rule for which ones are due. Actually running the warm-up is left
to whoever owns a browser — the API server drives it from a background thread
(see :mod:`qwerty.server`), and ``qwerty schedule run-due`` drives it from
cron / Task Scheduler for people who don't run the server.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Optional

# A schedule can't fire more often than this, whatever interval is asked for —
# a runaway "every 0 hours" would just launch browsers back to back.
MIN_INTERVAL_HOURS = 0.25


class ScheduleStore:
    """A JSON-backed list of warm-up schedules, one file for the whole set.

    Every mutation is a read-modify-write of that one file, and the API server
    runs the scheduler on a background thread (see :mod:`qwerty.server`) while
    request handlers add, update and delete from the event loop. Without a lock
    those interleave and silently drop each other's writes, so all mutations go
    through :attr:`_lock`, and the file itself is replaced atomically so a reader
    never observes a half-written list.

    The lock is per data directory and per process. A second *process* mutating
    the same file concurrently (say ``qwerty schedule run-due`` from cron while
    the server is up) is still unsynchronised — run one or the other, as the
    module docstring describes, not both.
    """

    # One lock per schedules.json path, shared by every store pointing at it, so
    # two ScheduleStore instances over the same data dir still serialise.
    _locks: dict[str, threading.RLock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, root: Path):
        self.path = Path(root) / "schedules.json"
        key = str(self.path.resolve())
        with ScheduleStore._locks_guard:
            self._lock = ScheduleStore._locks.setdefault(key, threading.RLock())

    def list(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def _save(self, items: list[dict]) -> None:
        """Write the list atomically: a torn file would lose every schedule."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(items, fh, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, sid: str) -> Optional[dict]:
        return next((s for s in self.list() if s.get("id") == sid), None)

    def add(self, *, profile_id: str, every_hours: float, minutes: float = 5,
            preset: str = "general", enabled: bool = True,
            now: Optional[float] = None) -> dict:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "profileId": profile_id,
            "everyHours": max(MIN_INTERVAL_HOURS, float(every_hours)),
            "minutes": float(minutes),
            "preset": preset or "general",
            "enabled": bool(enabled),
            "lastRun": None,
            "createdAt": now,
        }
        with self._lock:
            items = self.list()
            items.append(entry)
            self._save(items)
        return entry

    def update(self, sid: str, patch: dict) -> Optional[dict]:
        # `id` identifies the schedule; letting a patch rewrite it would orphan
        # the entry the caller thinks it just edited.
        patch = {k: v for k, v in (patch or {}).items() if k != "id"}
        with self._lock:
            items = self.list()
            out = None
            for s in items:
                if s.get("id") == sid:
                    s.update(patch)
                    out = s
            if out:
                self._save(items)
            return out

    def delete(self, sid: str) -> bool:
        with self._lock:
            items = self.list()
            kept = [s for s in items if s.get("id") != sid]
            if len(kept) == len(items):
                return False
            self._save(kept)
            return True

    def mark_run(self, sid: str, when: float) -> Optional[dict]:
        return self.update(sid, {"lastRun": when})

    def delete_for_profile(self, profile_id: str) -> int:
        """Drop every schedule belonging to a profile. Returns how many went.

        Called when a profile is deleted: an orphaned schedule is never
        runnable, but it still showed up in `qwerty schedule list` as a bare
        hex id and got retried on every tick forever.
        """
        with self._lock:
            items = self.list()
            kept = [x for x in items if x.get("profileId") != profile_id]
            removed = len(items) - len(kept)
            if removed:
                self._save(kept)
            return removed


def next_run_at(schedule: dict) -> float:
    """When this schedule is next due, as a unix timestamp.

    Never run before? Due at creation time (so a new schedule fires on the next
    tick rather than waiting a full interval). Otherwise last run + interval.
    """
    interval = max(MIN_INTERVAL_HOURS, float(schedule.get("everyHours", 1))) * 3600
    last = schedule.get("lastRun")
    if last is None:
        return float(schedule.get("createdAt") or 0)
    return float(last) + interval


def due_schedules(schedules: list[dict], now: float) -> list[dict]:
    """The enabled schedules whose next-run time has arrived. Pure — no clock,
    no browser — so it can be tested directly."""
    return [s for s in schedules
            if s.get("enabled", True) and next_run_at(s) <= now]
