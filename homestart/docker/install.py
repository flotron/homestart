"""Docker and Compose installation orchestration and background progress jobs.

Application services and shared job state are injected explicitly. This module
has no dependency on HTTP handlers or homestart.server.
"""
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import yaml

from .store import (
    normalize_image as normalize_docker_image,
    normalize_port as normalize_container_port,
    safe_environment_assignment as safe_env_assignment,
    safe_volume_mapping,
)


def image_repository(image):
    value = str(image or "").strip().lower().split("@", 1)[0]
    last_slash = value.rfind("/")
    last_colon = value.rfind(":")
    if last_colon > last_slash:
        value = value[:last_colon]
    if value.startswith("docker.io/"):
        value = value[len("docker.io/"):]
    if value.startswith("library/"):
        value = value[len("library/"):]
    return value


def compose_project_name(app_id, instance):
    value = re.sub(r"[^a-z0-9_-]+", "-", f"homestart-{app_id}-{instance}".lower()).strip("-_")
    return value[:63] or f"homestart-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class InstallServices:
    catalog_app: Callable
    require_catalog_architecture: Callable
    render_compose: Callable
    verify_image: Callable
    projects: Callable
    run_docker: Callable
    container_exists: Callable
    normalize_name: Callable
    enabled: Callable
    installed_images: Callable


class InstallManager:
    def __init__(self, services, project_dir, jobs, lock):
        self.services = services
        self._project_dir = project_dir
        self.jobs = jobs
        self.lock = lock

    @property
    def project_dir(self):
        value = self._project_dir
        return Path(value() if callable(value) else value)


    def update_install_job(self, job_id, **values):
        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                job.update(values)
                job["updated_at"] = int(time.time())

    def docker_pull_with_progress(self, image, job_id):
        process = subprocess.Popen(
            ["docker", "pull", image],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        recent = []
        completed_layers = set()
        progress = 15
        for raw_line in process.stdout or []:
            line = raw_line.strip()
            if not line:
                continue
            recent = (recent + [line])[-12:]
            layer = line.split(":", 1)[0].strip()
            if "Pull complete" in line or "Already exists" in line:
                completed_layers.add(layer)
            progress = max(progress, min(80, 15 + len(completed_layers) * 4))
            self.update_install_job(job_id, stage="pulling", progress=progress, message=line, log=recent)
        return_code = process.wait()
        if return_code:
            detail = recent[-1] if recent else f"docker pull exited with code {return_code}"
            raise ValueError(detail)

    def compose_command_with_progress(self, command, job_id, stage, start, end):
        process = subprocess.Popen(
            ["docker", "compose", *command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        recent = []
        line_count = 0
        for raw_line in process.stdout or []:
            line = raw_line.strip()
            if not line:
                continue
            line_count += 1
            recent = (recent + [line])[-16:]
            progress = min(end - 1, start + min(end - start - 1, line_count))
            self.update_install_job(job_id, stage=stage, progress=progress, message=line, log=recent)
        return_code = process.wait()
        if return_code:
            detail = recent[-1] if recent else f"docker compose exited with code {return_code}"
            raise ValueError(detail)
        return recent

    def compose_store_install(self, payload, job_id=None):
        app = self.services.catalog_app(payload.get("template_id"))
        self.services.require_catalog_architecture(app)
        compose, values = self.services.render_compose(app, payload.get("values"))
        for image in {
            str(service.get("image") or "")
            for service in compose["services"].values()
            if service.get("image")
        }:
            self.services.verify_image(image)
        managed = [
            record for record in self.services.projects().projects().values()
            if record.get("template_id") == app["id"]
        ]
        if managed:
            raise ValueError(
                f"{app['name']} is already managed as {managed[0].get('name') or managed[0]['project']}"
            )
        existing = self.services.run_docker(
            ["ps", "-a", "--filter", f"label=com.homestart.template={app['id']}", "--format", "{{.Names}}"],
            timeout=15,
        )
        if existing:
            raise ValueError(f"{app['name']} is already installed as {', '.join(existing.splitlines())}")
        container_names = [
            str(service.get("container_name") or "")
            for service in compose["services"].values()
            if service.get("container_name")
        ]
        for name in container_names:
            self.services.normalize_name(name)
            if self.services.container_exists(name):
                raise ValueError(f"A Docker container named {name} already exists")
        try:
            self.services.run_docker(["compose", "version"], timeout=15)
        except ValueError as error:
            raise ValueError("Docker Compose is required to install catalog apps") from error

        instance = values.get("container_name") or app["id"]
        project = compose_project_name(app["id"], instance)
        compose["name"] = project
        project_dir = self.project_dir / f"{app['id']}--{project[-24:]}"
        project_dir.mkdir(parents=True, exist_ok=True)
        compose_path = project_dir / "compose.yaml"
        temporary = compose_path.with_suffix(".yaml.tmp")
        temporary.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(compose_path)

        base = ["-f", str(compose_path), "-p", project]
        if job_id:
            self.update_install_job(job_id, stage="pulling", progress=10, message=f"Downloading images for {app['name']}…")
            self.compose_command_with_progress([*base, "pull"], job_id, "pulling", 12, 78)
            self.update_install_job(job_id, stage="creating", progress=82, message="Creating the Compose project…")
            self.compose_command_with_progress([*base, "up", "-d"], job_id, "creating", 84, 97)
        else:
            self.services.run_docker(["compose", *base, "pull"], timeout=900)
            self.services.run_docker(["compose", *base, "up", "-d"], timeout=180)
        running = self.services.run_docker(["compose", *base, "ps", "--status", "running", "-q"], timeout=30)
        state = "running" if running else "created"
        self.services.projects().record_install(
            compose_path,
            project,
            app["id"],
            app["name"],
            compose,
        )
        return {
            "ok": True,
            "container": ", ".join(container_names) or app["name"],
            "containers": container_names,
            "image": next(iter(compose["services"].values()))["image"],
            "template_id": app["id"],
            "compose_file": str(compose_path),
            "project": project,
            "message": f"Installed {app['name']} with Docker Compose",
            "state": state,
        }

    def docker_store_install(self, payload, job_id=None):
        if not self.services.enabled():
            raise ValueError("Docker app store is disabled")
        if payload.get("template_id"):
            return self.compose_store_install(payload, job_id)

        image = normalize_docker_image(payload.get("image", ""))
        self.services.verify_image(image)
        installed = self.services.installed_images()
        if image_repository(image) in installed:
            names = ", ".join(installed[image_repository(image)])
            raise ValueError(f"This image is already installed as {names}")
        container_name = self.services.normalize_name(payload.get("name") or image.rsplit("/", 1)[-1].split(":", 1)[0])
        host_port = normalize_container_port(payload.get("host_port"))
        container_port = normalize_container_port(payload.get("container_port"))
        restart_policy = str(payload.get("restart_policy") or "unless-stopped").strip()
        if restart_policy not in {"no", "always", "unless-stopped", "on-failure"}:
            raise ValueError("Invalid restart policy")
        if self.services.container_exists(container_name):
            raise ValueError(f"A Docker container named {container_name} already exists")

        env_values = [safe_env_assignment(item) for item in payload.get("env", []) if str(item or "").strip()]
        volume_values = [safe_volume_mapping(item) for item in payload.get("volumes", []) if str(item or "").strip()]

        if job_id:
            self.update_install_job(job_id, stage="pulling", progress=10, message=f"Downloading {image}…")
            self.docker_pull_with_progress(image, job_id)
            self.update_install_job(job_id, stage="creating", progress=85, message="Creating container…")
        else:
            self.services.run_docker(["pull", image], timeout=600)

        command = ["run", "-d", "--name", container_name, "--restart", restart_policy]
        if host_port and container_port:
            command.extend(["-p", f"{host_port}:{container_port}"])
        for value in env_values:
            command.extend(["-e", value])
        for value in volume_values:
            command.extend(["-v", value])
        command.append(image)

        container_id = self.services.run_docker(command, timeout=120).strip()
        if job_id:
            self.update_install_job(job_id, stage="starting", progress=95, message="Container created; checking status…")
            try:
                state = self.services.run_docker(["inspect", "--format", "{{.State.Status}}", container_name], timeout=15).strip()
            except ValueError:
                state = "created"
        return {
            "ok": True,
            "container": container_name,
            "container_id": container_id[:12],
            "image": image,
            "message": f"Installed {container_name} from {image}",
            "state": state if job_id else "running",
        }

    def run_store_install_job(self, job_id, payload):
        try:
            result = self.docker_store_install(payload, job_id)
            self.update_install_job(job_id, status="completed", stage="completed", progress=100,
                               message=f"{result['container']} is {result.get('state', 'running')}", result=result)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            self.update_install_job(job_id, status="failed", stage="failed", message=str(error), error=str(error))

    def start_store_install(self, payload):
        job_id = uuid.uuid4().hex
        now = int(time.time())
        with self.lock:
            self.jobs[job_id] = {"id": job_id, "status": "running", "stage": "validating", "progress": 3,
                                    "message": "Validating installation…", "log": [], "created_at": now, "updated_at": now}
            expired = [key for key, job in self.jobs.items() if now - job.get("updated_at", now) > 86400]
            for key in expired:
                self.jobs.pop(key, None)
        threading.Thread(target=self.run_store_install_job, args=(job_id, payload), name=f"install-{job_id[:8]}", daemon=True).start()
        return {"ok": True, "job_id": job_id}

    def store_install_status(self, job_id):
        with self.lock:
            job = self.jobs.get(str(job_id or ""))
            if not job:
                raise ValueError("Installation job not found")
            return {"ok": True, **job}
