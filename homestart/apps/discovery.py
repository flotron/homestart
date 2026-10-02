"""Application inventory with explicit live dependencies and no HTTP/server imports."""
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class DiscoveryServices:
    docker_inspect: Callable
    docker_port_mappings: Callable
    select_docker_web_mapping: Callable
    docker_ports_for_display: Callable
    docker_url_from_mapping: Callable
    with_icon: Callable
    normalized_name: Callable
    compose_project_manager: Callable
    app_uninstall_enabled: Callable
    apply_uninstall_metadata: Callable
    service_status: Callable
    command_available: Callable
    local_ip: Callable
    load_config: Callable
    apply_app_metadata: Callable
    public_app_url: Callable
    load_config_file: Callable
    check_output: Callable
    service_definitions: Callable
    listener_snapshot: Callable


class AppDiscovery:
    def __init__(self, services):
        self.services = services

    def docker_apps(self, host, all_containers=True):
        try:
            command = [
                "docker",
                "container",
                "ls",
                "--format",
                "{{json .}}",
            ]
            if all_containers:
                command.insert(3, "-a")

            output = self.services.check_output(
                command,
                text=True,
                timeout=3,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

        apps = []
        for line in output.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            details = self.services.docker_inspect(item.get("Names", "")) or {}
            labels = details.get("Config", {}).get("Labels") or {}
            mappings = self.services.docker_port_mappings(item.get("Names", ""), details)
            selected_port = self.services.select_docker_web_mapping(mappings)
            ports = self.services.docker_ports_for_display(mappings, selected_port)
            url = self.services.docker_url_from_mapping(host, selected_port)
            apps.append(
                self.services.with_icon(
                    {
                        "name": item.get("Names", "Docker app"),
                        "kind": "Docker",
                        "status": item.get("Status", ""),
                        "image": item.get("Image", ""),
                        "ports": ports,
                        "port_mappings": mappings,
                        "selected_port": selected_port,
                        "url": url,
                        "source": "docker",
                        "app_type": "docker",
                        "app_type_label": "Docker",
                        "tags": ["Docker"],
                        "available": True,
                        "docker_name": item.get("Names", ""),
                        "docker_running": str(item.get("State", "")).lower() == "running",
                        "compose_project": labels.get("com.docker.compose.project", ""),
                        "compose_service": labels.get("com.docker.compose.service", ""),
                        "compose_managed": labels.get("com.homestart.managed") == "true",
                        "template_id": labels.get("com.homestart.template", ""),
                    }
                )
            )

        return apps

    def managed_compose_apps(self, host, containers):
        manager = self.services.compose_project_manager()
        records = manager.projects()
        grouped = {}
        regular = []
        for container in containers:
            project = str(container.get("compose_project") or "")
            if project and (container.get("compose_managed") or project in records):
                grouped.setdefault(project, []).append(container)
            else:
                regular.append(container)

        apps = []
        for project in sorted(set(records) | set(grouped)):
            services = grouped.get(project, [])
            record = records.get(project, {
                "project": project,
                "name": project,
                "template_id": services[0].get("template_id", "") if services else "",
                "state": "installed",
                "risk": {"level": "none", "warning_count": 0, "warnings": []},
            })
            running = [service for service in services if service.get("docker_running")]
            primary = next((service for service in services if service.get("url")), services[0] if services else {})
            ports = []
            for service in services:
                for port in service.get("ports") or []:
                    if port not in ports:
                        ports.append(port)
            if services:
                status = f"{len(running)}/{len(services)} services running"
            elif record.get("state") == "data-preserved":
                status = "Removed · data preserved"
            else:
                status = "Stopped"
            app = {
                "name": record.get("name") or project,
                "kind": "Docker Compose",
                "status": status,
                "description": (
                    f"Managed Compose project · {len(services)} services"
                    if services
                    else "Managed Compose project ready to be started"
                ),
                "image": primary.get("image", ""),
                "ports": ports,
                "url": primary.get("url", ""),
                "source": "docker-compose",
                "app_type": "docker",
                "app_type_label": "Docker Compose",
                "tags": ["Docker Compose", f"{len(services)} services"],
                "available": True,
                "docker_name": primary.get("docker_name", ""),
                "docker_running": bool(running),
                "compose_project": project,
                "compose_managed": True,
                "compose_services": [
                    {
                        "name": service.get("compose_service") or service.get("name"),
                        "container": service.get("docker_name"),
                        "status": service.get("status"),
                        "running": service.get("docker_running"),
                        "image": service.get("image"),
                    }
                    for service in services
                ],
                "template_id": record.get("template_id", ""),
                "risk": record.get("risk") or {"level": "none", "warning_count": 0, "warnings": []},
                "uninstallable": self.services.app_uninstall_enabled(),
                "uninstall_reason": "Removes the complete Docker Compose application.",
            }
            apps.append(self.services.with_icon(app))
        return regular + apps

    def conf_text(self, path):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def strip_config_comments(self, text):
        lines = []
        for line in text.splitlines():
            clean = line.split("#", 1)[0].strip()
            if clean:
                lines.append(clean)
        return "\n".join(lines)

    def clean_config_value(self, value):
        return str(value or "").strip().strip(";").strip('"').strip("'")

    def web_root_name(self, root):
        path = Path(root)
        name = path.name
        if name.lower() in {"html", "htdocs", "public", "public_html", "web", "www"} and path.parent.name:
            name = path.parent.name
        return re.sub(r"[-_]+", " ", name).strip().title() or str(path)

    def local_web_url(self, host, port, tls=False):
        scheme = "https" if tls or str(port) == "443" else "http"
        port = str(port or ("443" if scheme == "https" else "80"))
        default = (scheme == "http" and port == "80") or (scheme == "https" and port == "443")
        return f"{scheme}://{host}" if default else f"{scheme}://{host}:{port}"

    def detected_native_web_app(self, root, port, host, server="Web server", tls=False):
        try:
            resolved_root = Path(root).expanduser().resolve()
        except OSError:
            return None
        if not resolved_root.exists() or not resolved_root.is_dir():
            return None
        if str(resolved_root) in {"/", "/var/www", "/srv", "/opt"}:
            return None

        name = self.web_root_name(resolved_root)
        return self.services.with_icon(
            {
                "name": name,
                "kind": "Native Linux",
                "status": f"Detected {server} web root",
                "description": str(resolved_root),
                "url": self.local_web_url(host, port, tls),
                "source": "native-discovery",
                "app_type": "native",
                "app_type_label": "Native Linux",
                "tags": ["Native Linux", server],
                "available": True,
            }
        )

    def apache_vhost_apps(self, host):
        apps = []
        paths = [
            *Path("/etc/apache2/sites-enabled").glob("*"),
            *Path("/etc/httpd/conf.d").glob("*.conf"),
            *Path("/etc/apache2/conf-enabled").glob("*.conf"),
        ]
        for path in paths:
            if not path.is_file():
                continue
            text = self.strip_config_comments(self.conf_text(path))
            roots = [self.clean_config_value(match) for match in re.findall(r"(?im)^\s*DocumentRoot\s+(.+)$", text)]
            if not roots:
                continue
            ports = re.findall(r"(?i)<VirtualHost\s+[^>]*:(\d+)[^>]*>", text)
            port = ports[0] if ports else "443" if re.search(r"(?im)^\s*SSLEngine\s+on\b", text) else "80"
            tls = str(port) == "443" or bool(re.search(r"(?im)^\s*SSLEngine\s+on\b", text))
            for root in roots:
                app = self.detected_native_web_app(root, port, host, "Apache", tls)
                if app:
                    apps.append(app)
        return apps

    def nginx_vhost_apps(self, host):
        apps = []
        paths = [
            *Path("/etc/nginx/sites-enabled").glob("*"),
            *Path("/etc/nginx/conf.d").glob("*.conf"),
        ]
        for path in paths:
            if not path.is_file():
                continue
            text = self.strip_config_comments(self.conf_text(path))
            roots = [self.clean_config_value(match) for match in re.findall(r"(?im)^\s*root\s+(.+)$", text)]
            if not roots:
                continue
            listens = [self.clean_config_value(match) for match in re.findall(r"(?im)^\s*listen\s+([^;]+)", text)]
            listen = listens[0] if listens else "80"
            port_match = re.search(r"(?<!:)\b(\d{2,5})\b", listen)
            port = port_match.group(1) if port_match else "443" if "ssl" in listen.lower() else "80"
            tls = str(port) == "443" or "ssl" in listen.lower()
            for root in roots:
                app = self.detected_native_web_app(root, port, host, "Nginx", tls)
                if app:
                    apps.append(app)
        return apps

    def native_web_apps(self, host):
        apps = []
        seen = set()
        for app in [*self.apache_vhost_apps(host), *self.nginx_vhost_apps(host)]:
            key = (self.services.normalized_name(app.get("name", "")), app.get("url", ""))
            if key in seen:
                continue
            seen.add(key)
            self.services.apply_uninstall_metadata(app)
            apps.append(app)
        return apps

    def native_service_apps(self):
        apps = []
        for definition in self.services.service_definitions():
            service = definition.get("service", "")
            command = definition.get("command", "")
            service_data = self.services.service_status(service) if service else None
            command_installed = self.services.command_available(command) if command else False
            if not service_data and not command_installed:
                continue

            active = (service_data or {}).get("active", "unknown")
            sub = (service_data or {}).get("sub", "")
            status = "Installed"
            if service_data:
                status = f"{active}{f' ({sub})' if sub else ''}"
            elif command_installed:
                status = "Command installed"

            app = self.services.with_icon(
                {
                    "name": definition.get("name") or service or command,
                    "kind": "Native Linux",
                    "status": status,
                    "description": definition.get("description", ""),
                    "url": definition.get("url_template", ""),
                    "source": "native-service-discovery",
                    "app_type": "native",
                    "app_type_label": "Native Linux",
                    "tags": list(dict.fromkeys(["Native Linux", *(definition.get("tags") or [])])),
                    "available": active in {"active", "unknown"} or command_installed,
                    "service_name": service,
                    "service_actionable": bool(service_data and service),
                }
            )
            self.services.apply_uninstall_metadata(app)
            apps.append(app)
        return apps

    def native_listener_apps(self, host):
        try:
            home_port = int(os.environ.get("PORT", "80"))
        except (TypeError, ValueError):
            home_port = 80
        apps = self.services.listener_snapshot(host, home_port)
        for app in apps:
            self.services.with_icon(app)
            self.services.apply_uninstall_metadata(app)
        return apps

    def app_payload(self):
        host = self.services.local_ip()
        raw_containers = self.docker_apps(host)
        containers = {self.services.normalized_name(app["name"]): app for app in raw_containers}
        discovered_docker = self.managed_compose_apps(host, raw_containers)
        configured = self.services.load_config()
        discovered_native = self.native_web_apps(host)
        discovered_listeners = self.native_listener_apps(host)
        discovered_services = self.native_service_apps()

        for app in configured:
            container = containers.get(self.services.normalized_name(app.get("name", "")))
            if container:
                app["source"] = "docker"
                app["app_type"] = "docker"
                app["docker_name"] = container["docker_name"]
                app["status"] = container["status"]
                app["image"] = container["image"]
            self.services.apply_app_metadata(app)
            self.services.apply_uninstall_metadata(app)
            app["url"] = self.services.public_app_url(app.get("url", ""), host)
            self.services.with_icon(app)

        seen = {self.services.normalized_name(app.get("name", "")) for app in configured}
        seen_urls = {str(app.get("url") or "") for app in configured if app.get("url")}
        discovered = [
            app for app in discovered_docker if self.services.normalized_name(app.get("name", "")) not in seen
        ]
        for app in discovered:
            self.services.apply_uninstall_metadata(app)
            if app.get("url"):
                seen_urls.add(app["url"])

        native_discovered = [
            app
            for app in discovered_native
            if self.services.normalized_name(app.get("name", "")) not in seen and str(app.get("url") or "") not in seen_urls
        ]
        seen.update(self.services.normalized_name(app.get("name", "")) for app in [*discovered, *native_discovered])
        listener_discovered = [
            app
            for app in discovered_listeners
            if self.services.normalized_name(app.get("name", "")) not in seen
            and str(app.get("url") or "") not in seen_urls
        ]
        seen.update(self.services.normalized_name(app.get("name", "")) for app in listener_discovered)
        service_discovered = [
            app
            for app in discovered_services
            if self.services.normalized_name(app.get("name", "")) not in seen
        ]

        return {
            "dashboard": self.services.load_config_file().get("dashboard", {}),
            "host": host,
            "apps": configured + discovered + native_discovered + listener_discovered + service_discovered,
            "features": self.services.load_config_file().get("features", {}),
        }

