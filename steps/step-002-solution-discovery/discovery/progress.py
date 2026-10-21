"""Progress and a timing profile for this step (release 5), without importing the backend.

The same protocol as every other step: ``##progress {json}`` lines on stderr, which the platform's process runner
reads for its stall limit and the job page — at every phase, every 2 seconds at most while items go by, and every 10
seconds regardless (a heartbeat). ``progress.json`` and ``timing-profile.json`` in the output folder are rewritten
with each line, so a step stopped part-way leaves behind where it was. Paths and durations only, never file content.
"""

import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_SECONDS = 10
EMIT_SECONDS = 2
SLOWEST = 25


class Progress:
    def __init__(self, output_dir: str | Path | None):
        self.output_dir = Path(output_dir) if output_dir else None
        self.started = time.monotonic()
        self.position = {"phase": "starting", "done": 0, "total": None, "item": None}
        self.phases: list[dict] = []
        self.items: dict[str, list[dict]] = {}
        self._phase_started = self.started
        self._open = None
        self._emitted = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._heartbeat, daemon=True).start()
        self._emit()

    def phase(self, name: str, total: int | None = None) -> None:
        self._end()
        with self._lock:
            self._close_phase()
            self.position = {"phase": name, "done": 0, "total": total, "item": None}
        self._emit()

    def begin(self, path: str, kind: str = "file") -> None:
        """The next item: ends the one begun before and starts timing this one."""
        self._end()
        with self._lock:
            self.position = {**self.position, "item": path}
            self._open = (path, kind, time.monotonic())
        self._emit(force=False)

    def finish(self, outcome: str = "completed") -> None:
        self._end()
        with self._lock:
            self._close_phase()
            self.position = {**self.position, "phase": outcome, "item": None}
        self._stop.set()
        self._emit()

    def _end(self) -> None:
        with self._lock:
            if self._open is None:
                return
            path, kind, started = self._open
            self._open = None
            self.items.setdefault(kind, []).append({"path": path, "seconds": round(time.monotonic() - started, 3)})
            self.position = {**self.position, "done": (self.position.get("done") or 0) + 1}

    def _close_phase(self) -> None:
        now = time.monotonic()
        if self.position.get("phase") not in (None, "starting"):
            self.phases.append({"phase": self.position["phase"], "seconds": round(now - self._phase_started, 3),
                                "items": self.position.get("done") or 0})
        self._phase_started = now

    def _heartbeat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            self._emit()

    def _emit(self, force: bool = True) -> None:
        now = time.monotonic()
        with self._lock:
            if not force and now - self._emitted < EMIT_SECONDS:
                return
            self._emitted = now
            snapshot = {**self.position, "elapsedSeconds": round(now - self.started, 1),
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            profile = {
                "format": 1,
                "note": "Durations and paths only: no code, no file content, no values.",
                "elapsedSeconds": snapshot["elapsedSeconds"],
                "position": {k: self.position.get(k) for k in ("phase", "done", "total", "item")},
                "phases": list(self.phases),
                "slowest": {kind: sorted(rows, key=lambda r: -r["seconds"])[:SLOWEST] for kind, rows in self.items.items()},
            }
        try:
            sys.stderr.write("##progress " + json.dumps(snapshot, ensure_ascii=False) + "\n")
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
        if self.output_dir:
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                (self.output_dir / "progress.json").write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
                (self.output_dir / "timing-profile.json").write_text(json.dumps(profile, indent=1), encoding="utf-8")
            except OSError:
                pass
