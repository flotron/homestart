"""Portable, best-effort disk health inspection."""

import concurrent.futures
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


def smartctl_reports_standby(payload, returncode=0):
    """Recognize the explicit ``-n standby,3`` early-exit result."""
    payload = payload if isinstance(payload, dict) else {}
    power_mode = str(payload.get("power_mode") or "").strip().lower()
    if power_mode in {"sleep", "standby"}:
        return True
    messages = (payload.get("smartctl") or {}).get("messages") or []
    text = " ".join(
        str(item.get("string") or "")
        for item in messages
        if isinstance(item, dict)
    ).lower()
    return int(returncode or 0) == 3 and (
        "standby" in text or "sleep" in text
    )


class SmartHealthMonitor:
    """Background SMART collector whose readers only consume cached results."""

    def __init__(self, ttl_seconds=24 * 60 * 60, workers=2, clock=None, wall_clock=None):
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.workers = max(1, min(4, int(workers)))
        self.clock = clock or time.monotonic
        self.wall_clock = wall_clock or time.time
        self.cache = {}
        self.lock = threading.Lock()
        self.collection_lock = threading.Lock()

    def _read(self, device, transport=""):
        command = shutil.which("smartctl")
        if not command:
            return {
                "status": "unavailable",
                "healthy": None,
                "detail": "smartctl is not installed",
            }
        try:
            arguments = [command]
            if (
                str(transport or "").strip().lower() != "nvme"
                and not str(device).startswith("/dev/nvme")
            ):
                arguments.extend(["-n", "standby,3"])
            arguments.extend(["-H", "-j", device])
            result = subprocess.run(
                arguments,
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
        if smartctl_reports_standby(payload, result.returncode):
            return {
                "status": "standby",
                "healthy": None,
                "detail": "Drive is in standby; SMART was not checked",
                "smartctl_exit_code": int(result.returncode),
            }
        health = parse_smartctl_health(payload, result.returncode)
        health["smartctl_exit_code"] = int(result.returncode)
        return health

    @staticmethod
    def _previous_assessment(cached):
        health = dict((cached or {}).get("health") or {})
        if health.get("status") in {"healthy", "failing"}:
            return {
                "last_status": health.get("status"),
                "last_healthy": health.get("healthy"),
                "last_detail": health.get("detail", ""),
                "last_checked_at": health.get("checked_at", 0),
            }
        return {
            key: health.get(key)
            for key in (
                "last_status",
                "last_healthy",
                "last_detail",
                "last_checked_at",
            )
            if key in health
        }

    def _record(self, device, health, checked_monotonic, checked_at):
        with self.lock:
            previous = self.cache.get(device)
        health = dict(health)
        previous_assessment = self._previous_assessment(previous)
        if health.get("status") in {"healthy", "failing"}:
            health.update({
                "last_status": health.get("status"),
                "last_healthy": health.get("healthy"),
                "last_detail": health.get("detail", ""),
                "last_checked_at": int(checked_at),
            })
        else:
            health.update(previous_assessment)
        health["checked_at"] = int(checked_at)
        with self.lock:
            self.cache[device] = {
                "checked_monotonic": checked_monotonic,
                "health": health,
            }

    def collect(self, disks, force=False):
        """Refresh due devices. Intended to run only from a background thread."""
        if not self.collection_lock.acquire(blocking=False):
            return False
        try:
            now = self.clock()
            device_metadata = {
                str(disk.get("device") or "").strip(): {
                    "transport": str(disk.get("transport") or "").strip(),
                }
                for disk in disks
                if str(disk.get("device") or "").startswith("/dev/")
            }
            devices = list(device_metadata)
            with self.lock:
                due = [
                    device
                    for device in devices
                    if force
                    or device not in self.cache
                    or now - self.cache[device]["checked_monotonic"] >= self.ttl_seconds
                ]
            if due:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(self.workers, len(due)),
                    thread_name_prefix="homestart-smart",
                ) as executor:
                    futures = {
                        executor.submit(
                            self._read,
                            device,
                            device_metadata[device]["transport"],
                        ): device
                        for device in due
                    }
                    for future in concurrent.futures.as_completed(futures):
                        device = futures[future]
                        try:
                            health = future.result()
                        except Exception:
                            health = {
                                "status": "unknown",
                                "healthy": None,
                                "detail": "SMART health could not be read",
                            }
                        self._record(
                            device,
                            health,
                            self.clock(),
                            self.wall_clock(),
                        )
            active = set(devices)
            with self.lock:
                for device in list(self.cache):
                    if device not in active:
                        self.cache.pop(device, None)
            return True
        finally:
            self.collection_lock.release()

    def snapshot(self, disks):
        """Return immediately with cached data; never invokes ``smartctl``."""
        now = self.clock()
        results = {}
        for disk in disks:
            device = str(disk.get("device") or "").strip()
            if not device.startswith("/dev/"):
                continue
            with self.lock:
                cached = self.cache.get(device)
            if not cached:
                results[device] = {
                    "status": "checking",
                    "healthy": None,
                    "detail": "Waiting for the background SMART check",
                    "checked_at": 0,
                    "stale": False,
                }
                continue
            health = dict(cached["health"])
            age = max(0, now - cached["checked_monotonic"])
            health["age_seconds"] = round(age)
            health["stale"] = age > self.ttl_seconds * 2
            results[device] = health
        return results
