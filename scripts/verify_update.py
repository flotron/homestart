#!/usr/bin/env python3
"""Verify a restarted HomeStart service and roll back a failed update."""

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.rollback-{uuid.uuid4().hex}.tmp"
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def safe_relative(value):
    path = Path(str(value or ""))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Invalid rollback path")
    return path


def healthy(install_dir, expected_version, port):
    try:
        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", "homestart.service"],
            timeout=8,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    if not active:
        return False
    try:
        installed = (install_dir / "VERSION").read_text(encoding="utf-8").strip()
        if installed != expected_version:
            return False
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            return int(getattr(response, "status", 0)) == 200
    except (OSError, urllib.error.URLError):
        return False


def rollback(install_dir, backup_dir):
    transaction = json.loads((backup_dir / "transaction.json").read_text(encoding="utf-8"))
    for value in reversed(transaction.get("created", [])):
        target = install_dir / safe_relative(value)
        if target.is_file() or target.is_symlink():
            target.unlink()
    for value in transaction.get("replaced", []) + transaction.get("removed", []):
        relative = safe_relative(value)
        source = backup_dir / relative
        if source.is_file():
            atomic_copy(source, install_dir / relative)
    (backup_dir / "rollback.json").write_text(
        json.dumps({"rolled_back_at": int(time.time())}, indent=2) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "restart", "homestart.service"], timeout=30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", required=True, type=Path)
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--delay", type=int, default=8)
    args = parser.parse_args()
    time.sleep(max(0, min(args.delay, 60)))
    for _attempt in range(5):
        if healthy(args.install_dir, args.version, args.port):
            (args.backup_dir / "verified.json").write_text(
                json.dumps({"verified_at": int(time.time())}, indent=2) + "\n",
                encoding="utf-8",
            )
            return
        time.sleep(2)
    rollback(args.install_dir, args.backup_dir)


if __name__ == "__main__":
    main()
