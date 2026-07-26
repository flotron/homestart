#!/usr/bin/env python3
"""Run a real two-service Compose stack through the HomeStart lifecycle."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from homestart.docker.projects import ComposeProjectManager


def docker(command, timeout=60):
    result = subprocess.run(
        ["docker", *command],
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "Docker command failed").strip())
    return result.stdout.strip()


def main():
    docker(["compose", "version"], timeout=20)
    with tempfile.TemporaryDirectory(prefix="homestart-compose-integration-") as temporary:
        root = Path(temporary)
        project_root = root / "compose-apps"
        data_root = root / "app-data"
        project_dir = project_root / "multi-container"
        managed_data = data_root / "multi-container"
        project_dir.mkdir(parents=True)
        managed_data.mkdir(parents=True)
        project = "homestart-ci-multi"
        compose = {
            "name": project,
            "services": {
                "web": {
                    "image": "nginx:alpine",
                    "labels": {
                        "com.homestart.managed": "true",
                        "com.homestart.template": "ci-multi",
                    },
                    "volumes": [f"{managed_data}:/usr/share/nginx/html"],
                },
                "cache": {
                    "image": "redis:alpine",
                    "labels": {
                        "com.homestart.managed": "true",
                        "com.homestart.template": "ci-multi",
                    },
                },
            },
        }
        compose_path = project_dir / "compose.yaml"
        compose_path.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
        manager = ComposeProjectManager(project_root, data_root, docker)
        manager.record_install(compose_path, project, "ci-multi", "CI Multi-container", compose)
        base = ["compose", "-f", str(compose_path), "-p", project]
        try:
            manager.action(project, "start")
            running = docker([*base, "ps", "--status", "running", "-q"], timeout=30).splitlines()
            if len(running) != 2:
                raise RuntimeError(f"Expected two running services, found {len(running)}")
            manager.action(project, "stop")
            if docker([*base, "ps", "--status", "running", "-q"], timeout=30):
                raise RuntimeError("Compose stop left a service running")
            manager.action(project, "start")
            manager.action(project, "restart")
            manager.action(project, "update")
            manager.action(project, "uninstall", delete_data=False)
            if not project_dir.is_dir() or not managed_data.is_dir():
                raise RuntimeError("Preserve-data uninstall removed managed data")
            manager.action(project, "start")
            manager.action(project, "uninstall", delete_data=True)
            if project_dir.exists() or managed_data.exists():
                raise RuntimeError("Delete-data uninstall left managed project data")
        finally:
            if compose_path.is_file():
                subprocess.run(
                    ["docker", *base, "down", "--volumes", "--remove-orphans"],
                    text=True,
                    capture_output=True,
                    timeout=120,
                )
            shutil.rmtree(project_root, ignore_errors=True)
            shutil.rmtree(data_root, ignore_errors=True)
    print("PASS real multi-container Compose lifecycle")


if __name__ == "__main__":
    main()
