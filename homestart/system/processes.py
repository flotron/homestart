"""Instantaneous host CPU attribution from Linux procfs counters."""

import threading
import time
from pathlib import Path


def proc_cpu_snapshot(proc_root=Path("/proc")):
    try:
        fields = proc_root.joinpath("stat").read_text(
            encoding="utf-8", errors="replace",
        ).splitlines()[0].split()[1:]
        # guest and guest_nice are already included in user and nice.
        total = sum(int(value) for value in fields[:8])
    except (OSError, ValueError, IndexError):
        return 0, {}
    processes = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            content = entry.joinpath("stat").read_text(
                encoding="utf-8", errors="replace",
            )
            _, separator, tail = content.rpartition(")")
            fields = tail.strip().split()
            if not separator or len(fields) < 13:
                continue
            processes[int(entry.name)] = int(fields[11]) + int(fields[12])
        except (OSError, ValueError):
            continue
    return total, processes


class ProcessCpuTracker:
    def __init__(self, snapshot=None, clock=None, minimum_interval=1):
        self.snapshot = snapshot or proc_cpu_snapshot
        self.clock = clock or time.monotonic
        self.minimum_interval = float(minimum_interval)
        self.previous = None
        self.latest = None
        self.lock = threading.Lock()

    def top(self, identity):
        now = self.clock()
        with self.lock:
            if self.previous and now - self.previous["at"] < self.minimum_interval:
                return dict(self.latest) if self.latest else None
            total, processes = self.snapshot()
            previous = self.previous
            self.previous = {
                "at": now,
                "total": total,
                "processes": processes,
            }
            if not previous:
                self.latest = None
                return None
            total_delta = total - previous["total"]
            if total_delta <= 0:
                return dict(self.latest) if self.latest else None
            candidates = []
            for pid, ticks in processes.items():
                delta = ticks - previous["processes"].get(pid, ticks)
                if delta > 0:
                    candidates.append((delta, pid))
            if not candidates:
                self.latest = None
                return None
            process_delta, pid = max(candidates)
            resolved = identity(pid)
            self.latest = {
                "pid": pid,
                "name": resolved.get("name") or f"PID {pid}",
                "kind": resolved.get("kind") or "process",
                "percent": round(min(100, process_delta / total_delta * 100), 1),
            }
            return dict(self.latest)
