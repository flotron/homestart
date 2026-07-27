"""Portable, best-effort disk health inspection."""

import json
import shutil
import subprocess
import threading
import time


def parse_smartctl_health(payload, returncode=0):
    payload = payload if isinstance(payload, dict) else {}
    passed = (payload.get("smart_status") or {}).get("passed")
    critical_warning = (
        payload.get("nvme_smart_health_information_log") or {}
    ).get("critical_warning")
    failing = passed is False or bool(int(returncode or 0) & 8)
    if critical_warning not in (None, 0, "0"):
        try:
            failing = failing or int(critical_warning) != 0
        except (TypeError, ValueError):
            pass
    if failing:
        return {
            "status": "failing",
            "healthy": False,
            "detail": "The drive reports a failed SMART health assessment",
        }
    if passed is True or critical_warning in (0, "0"):
        return {
            "status": "healthy",
            "healthy": True,
            "detail": "SMART health assessment passed",
        }
    return {
        "status": "unknown",
        "healthy": None,
        "detail": "This drive did not provide an overall SMART health result",
    }


class SmartHealthMonitor:
    def __init__(self, ttl_seconds=300, clock=None):
        self.ttl_seconds = int(ttl_seconds)
        self.clock = clock or time.monotonic
        self.cache = {}
        self.lock = threading.Lock()

    def _read(self, device):
        command = shutil.which("smartctl")
        if not command:
            return {
                "status": "unavailable",
                "healthy": None,
                "detail": "smartctl is not installed",
            }
        try:
            result = subprocess.run(
                [command, "-H", "-j", device],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return {
                "status": "unknown",
                "healthy": None,
                "detail": "SMART health could not be read",
            }
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            payload = {}
        health = parse_smartctl_health(payload, result.returncode)
        health["smartctl_exit_code"] = int(result.returncode)
        return health

    def inspect(self, disks):
        now = self.clock()
        results = {}
        for disk in disks:
            device = str(disk.get("device") or "").strip()
            if not device.startswith("/dev/"):
                continue
            with self.lock:
                cached = self.cache.get(device)
            if cached and now - cached["checked_at"] < self.ttl_seconds:
                results[device] = dict(cached["health"])
                continue
            health = self._read(device)
            with self.lock:
                self.cache[device] = {"checked_at": now, "health": dict(health)}
            results[device] = health
        return results

