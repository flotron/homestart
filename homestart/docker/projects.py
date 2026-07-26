"""Managed Docker Compose project lifecycle and template risk analysis."""

import json
import os
import re
import shutil
import time
from pathlib import Path

import yaml


PROJECT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
SENSITIVE_BIND_PATHS = (
    "/",
    "/boot",
    "/dev",
    "/etc",
    "/proc",
    "/root",
    "/run",
    "/sys",
    "/var/run",
)


def _labels_dict(value):
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    result = {}
    for item in value if isinstance(value, list) else []:
        key, separator, label_value = str(item).partition("=")
        if separator:
            result[key] = label_value
    return result


def _volume_source(volume):
    if isinstance(volume, dict):
        if str(volume.get("type") or "") != "bind":
            return ""
        return str(volume.get("source") or "")
    if not isinstance(volume, str):
        return ""
    source, separator, _target = volume.partition(":")
    return source if separator and source.startswith("/") else ""


def path_within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def managed_data_paths(compose, data_root):
    result = []
    for service in (compose.get("services") or {}).values():
        if not isinstance(service, dict):
            continue
        for volume in service.get("volumes") or []:
            source = _volume_source(volume)
            if source and path_within(source, data_root) and source not in result:
                result.append(source)
    return result


def compose_risk_report(compose):
    warnings = []

    def add(service_name, code, severity, message):
        warnings.append({
            "service": str(service_name),
            "code": code,
            "severity": severity,
            "message": message,
        })

    for service_name, service in (compose.get("services") or {}).items():
        if not isinstance(service, dict):
            continue
        if service.get("privileged") is True:
            add(service_name, "privileged", "high", "Runs as a privileged container")
        if str(service.get("network_mode") or "") == "host":
            add(service_name, "host-network", "high", "Uses the host network namespace")
        if str(service.get("pid") or "") == "host":
            add(service_name, "host-pid", "high", "Uses the host process namespace")
        if str(service.get("ipc") or "") == "host":
            add(service_name, "host-ipc", "high", "Uses the host IPC namespace")
        if service.get("devices"):
            add(service_name, "host-devices", "high", "Accesses host devices")
        if service.get("cap_add"):
            add(service_name, "capabilities", "medium", "Adds Linux capabilities")
        security_options = [str(value).lower() for value in service.get("security_opt") or []]
        if any("unconfined" in value for value in security_options):
            add(service_name, "unconfined-security", "high", "Disables a container security profile")
        user = str(service.get("user") or "").strip().lower()
        if user in {"0", "0:0", "root", "root:root"}:
            add(service_name, "root-user", "medium", "Explicitly runs as root")
        for volume in service.get("volumes") or []:
            source = os.path.normpath(_volume_source(volume)) if _volume_source(volume) else ""
            if not source:
                continue
            if source in {"/var/run/docker.sock", "/run/docker.sock"}:
                add(service_name, "docker-socket", "critical", "Mounts the Docker control socket")
            elif source == "/" or any(
                source == protected or source.startswith(protected + "/")
                for protected in SENSITIVE_BIND_PATHS
                if protected != "/"
            ):
                add(service_name, "sensitive-bind", "high", f"Mounts sensitive host path {source}")

    order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    level = "none"
    for warning in warnings:
        if order[warning["severity"]] > order[level]:
            level = warning["severity"]
    return {
        "level": level,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


class ComposeProjectManager:
    def __init__(self, project_root, data_root, run_docker):
        self.project_root = Path(project_root)
        self.data_root = Path(data_root)
        self.run_docker = run_docker

    @staticmethod
    def validate_project_name(project):
        project = str(project or "").strip()
        if not PROJECT_NAME_PATTERN.fullmatch(project):
            raise ValueError("Invalid Docker Compose project")
        return project

    @staticmethod
    def _read_json(path, fallback):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, type(fallback)) else fallback
        except (OSError, json.JSONDecodeError):
            return fallback

    @staticmethod
    def _write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(path)

    def _compose_record(self, compose_path):
        try:
            compose = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return None
        if not isinstance(compose, dict):
            return None
        project = str(compose.get("name") or "").strip()
        if not PROJECT_NAME_PATTERN.fullmatch(project):
            return None
        template_id = ""
        for service in (compose.get("services") or {}).values():
            labels = _labels_dict(service.get("labels") if isinstance(service, dict) else {})
            template_id = labels.get("com.homestart.template", template_id)
        saved = self._read_json(compose_path.parent / "project.json", {})
        return {
            "project": project,
            "template_id": str(saved.get("template_id") or template_id),
            "name": str(saved.get("name") or saved.get("template_name") or template_id or project),
            "compose_file": str(compose_path),
            "project_dir": str(compose_path.parent),
            "managed_data_paths": [
                path for path in saved.get("managed_data_paths", [])
                if isinstance(path, str) and path_within(path, self.data_root)
            ] or managed_data_paths(compose, self.data_root),
            "risk": saved.get("risk") if isinstance(saved.get("risk"), dict) else compose_risk_report(compose),
            "state": str(saved.get("state") or "installed"),
            "created_at": int(saved.get("created_at") or 0),
            "updated_at": int(saved.get("updated_at") or 0),
        }

    def projects(self):
        result = {}
        if not self.project_root.is_dir():
            return result
        for compose_path in self.project_root.glob("*/compose.yaml"):
            record = self._compose_record(compose_path)
            if record:
                result[record["project"]] = record
        return result

    def project(self, project):
        project = self.validate_project_name(project)
        record = self.projects().get(project)
        if not record:
            raise ValueError("Managed Docker Compose project was not found")
        return record

    def record_install(self, compose_path, project, template_id, name, compose):
        project = self.validate_project_name(project)
        now = int(time.time())
        record_path = Path(compose_path).parent / "project.json"
        previous = self._read_json(record_path, {})
        record = {
            "schema_version": 1,
            "project": project,
            "template_id": str(template_id or ""),
            "name": str(name or template_id or project),
            "managed_data_paths": managed_data_paths(compose, self.data_root),
            "risk": compose_risk_report(compose),
            "state": "installed",
            "created_at": int(previous.get("created_at") or now),
            "updated_at": now,
        }
        self._write_json(record_path, record)
        return record

    def _set_state(self, record, state):
        record_path = Path(record["project_dir"]) / "project.json"
        value = self._read_json(record_path, {})
        value.update({
            "schema_version": 1,
            "project": record["project"],
            "template_id": record.get("template_id", ""),
            "name": record.get("name", record["project"]),
            "managed_data_paths": record.get("managed_data_paths", []),
            "risk": record.get("risk", {}),
            "state": state,
            "created_at": int(value.get("created_at") or record.get("created_at") or time.time()),
            "updated_at": int(time.time()),
        })
        self._write_json(record_path, value)

    def action(self, project, action, delete_data=False):
        record = self.project(project)
        compose_file = record["compose_file"]
        base = ["compose", "-f", compose_file, "-p", record["project"]]
        if action == "start":
            output = self.run_docker([*base, "up", "-d"], timeout=240)
            self._set_state(record, "installed")
            message = f"Started Compose application {record['name']}"
        elif action == "stop":
            output = self.run_docker([*base, "stop"], timeout=180)
            self._set_state(record, "stopped")
            message = f"Stopped Compose application {record['name']}"
        elif action == "restart":
            output = self.run_docker([*base, "restart"], timeout=240)
            self._set_state(record, "installed")
            message = f"Restarted Compose application {record['name']}"
        elif action == "update":
            self.run_docker([*base, "pull"], timeout=1200)
            output = self.run_docker([*base, "up", "-d", "--remove-orphans"], timeout=300)
            self._set_state(record, "installed")
            message = f"Updated Compose application {record['name']}"
        elif action == "uninstall":
            command = [*base, "down", "--remove-orphans"]
            if delete_data:
                command.append("--volumes")
            output = self.run_docker(command, timeout=300)
            deleted_paths = []
            if delete_data:
                for path_value in record.get("managed_data_paths", []):
                    path = Path(path_value)
                    if path_within(path, self.data_root) and path.resolve() != self.data_root.resolve():
                        if path.is_dir() and not path.is_symlink():
                            shutil.rmtree(path)
                        elif path.exists() or path.is_symlink():
                            path.unlink()
                        deleted_paths.append(str(path))
                shutil.rmtree(record["project_dir"])
            else:
                self._set_state(record, "data-preserved")
            return {
                "ok": True,
                "action": action,
                "project": record["project"],
                "message": (
                    f"Removed {record['name']} and its HomeStart-managed data"
                    if delete_data
                    else f"Removed {record['name']}; data and volumes were preserved"
                ),
                "data_deleted": delete_data,
                "deleted_paths": deleted_paths,
                "output": output,
            }
        else:
            raise ValueError("Invalid Docker Compose action")
        return {
            "ok": True,
            "action": action,
            "project": record["project"],
            "message": message,
            "output": output,
        }
