"""Explicit host power requests, handed off to systemd before replying."""

import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path


class PowerManager:
    DELAY_SECONDS = 5

    def __init__(self):
        self.lock = threading.Lock()
        self.pending = None

    def status(self):
        reason = ""
        if (Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()
                or Path("/run/systemd/container").exists()):
            reason = "Host power controls are unavailable inside a container."
        elif not Path("/run/systemd/system").is_dir():
            reason = "Host power controls require Linux running systemd."
        elif os.geteuid() != 0:
            reason = "Host power controls require the HomeStart system service to run as root."
        elif not shutil.which("systemctl") or not shutil.which("systemd-run"):
            reason = "The systemctl and systemd-run utilities are required."
        try:
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            boot_id = ""
        return {"ok": True, "hostname": socket.gethostname(), "available": not reason,
                "reason": reason, "boot_id": boot_id, "pending": self.pending}

    def request(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("A power request must be a JSON object")
        action = payload.get("action")
        if action not in ("reboot", "poweroff"):
            raise ValueError("Choose reboot or poweroff")
        if payload.get("confirmation") != action:
            raise ValueError("Explicit power confirmation is required")
        with self.lock:
            status = self.status()
            if payload.get("hostname") != status["hostname"]:
                raise ValueError("The host changed. Reopen the power confirmation.")
            if not status["available"]:
                raise ValueError(status["reason"])
            if self.pending:
                raise ValueError("A power request has already been accepted. Check the host before retrying.")
            # Fixed unit name also prevents duplicate requests across service restarts.
            # No shell, force, or user-provided command arguments. The timer survives
            # termination of HomeStart and gives HTTP enough time to flush its reply.
            result = subprocess.run(
                [shutil.which("systemd-run"), "--system", "--no-ask-password",
                 "--unit=homestart-host-power", "--on-active=5s",
                 "--timer-property=AccuracySec=1s", "--collect",
                 shutil.which("systemctl"), "--system", "--no-ask-password",
                 "--no-block", action],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if result.returncode:
                raise ValueError((result.stderr or "Systemd did not accept the power request").strip())
            self.pending = {"action": action, "requested_at": time.time(),
                            "delay_seconds": self.DELAY_SECONDS}
            return {**status, "pending": self.pending, "accepted": True}
