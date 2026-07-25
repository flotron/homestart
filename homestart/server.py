#!/usr/bin/env python3
import json
import base64
import binascii
import hashlib
import ipaddress
import mimetypes
import os
import pwd
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
import yaml
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .api.router import ApiRouter
from .config import (
    CURATED_APPS,
    DEFAULT_CONFIG,
    deep_merge,
    load_config as load_config_data,
    load_json_file,
    save_config as save_config_data,
)
from .files.copy import CopyCancelled, CopyManager
from .system.network import (
    choose_monitor_interface as select_monitor_interface,
    endpoint_address as parse_endpoint_address,
    network_device_totals as parse_network_device_totals,
    parse_ss_tcp_counters as parse_socket_tcp_counters,
    parse_udev_properties as parse_network_udev_properties,
)
from .updates.github import GitHubReleaseClient, update_asset_version


BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "homestart.db"
BACKUP_DIR = DATA_DIR / "backups"
TRASH_DIR = DATA_DIR / "trash"
TRASH_INDEX = DATA_DIR / "trash.json"
TRASH_LAST_CLEANUP = 0
SAMBA_STATE_PATH = DATA_DIR / "samba-shares.json"
SAMBA_CONFIG_PATH = Path(os.environ.get("HOMESTART_SAMBA_CONFIG", "/etc/samba/smb.conf"))
SAMBA_MANAGED_PATH = Path(os.environ.get("HOMESTART_SAMBA_MANAGED_CONFIG", "/etc/samba/homestart-shares.conf"))
APP_ICON_DIR = DATA_DIR / "app-icons"
APP_ICON_INDEX = DATA_DIR / "app-icons.json"
STORE_CATALOG_CACHE = DATA_DIR / "app-store-catalog.json"
COMPOSE_APP_DIR = DATA_DIR / "compose-apps"
COMPOSE_APP_DATA_DIR = DATA_DIR / "app-data"
STORE_CATALOG_URL = os.environ.get(
    "HOMESTART_APP_CATALOG_URL",
    "https://raw.githubusercontent.com/flotron/homestart-apps/main/dist/catalog.json",
)
STORE_CATALOG_TTL = 15 * 60
PACKAGE_PATH = BASE_DIR / "package.json"
FILE_MOUNT_ROOT = Path("/mnt/homestart")
CONFIG_PATH = Path(os.environ.get("HOMESTART_CONFIG", BASE_DIR / "config.json"))
CPU_PREV = None
CPU_DETAIL_PREV = None
GPU_PREV = None
METRIC_LAST_WRITE = 0
NETWORK_LIVE_PREV = None
INSTALL_JOBS = {}
INSTALL_JOBS_LOCK = threading.Lock()
NETWORK_HISTORY_PREV = None
NETWORK_INTERFACE_CACHE = {"at": 0, "items": []}
CONTAINER_NETWORK_PREV = {}
CONTAINER_NETWORK_TOP = {"download": None, "upload": None}
CONTAINER_NETWORK_TARGETS = []
CONTAINER_NETWORK_TARGETS_AT = 0
CONTAINER_NETWORK_LOCK = threading.Lock()
HOST_TCP_PREV = {}
DOCKER_IDENTITY_CACHE = {"at": 0, "items": {}}
INTERFACE_ADDRESS_CACHE = {"at": 0, "interface": "", "items": set()}
FILE_COPY_JOBS = {}
FILE_COPY_JOBS_LOCK = threading.Lock()
COPY_MANAGER = None
GITHUB_RELEASE_CLIENT = None
DOCKERHUB_VERIFICATION_CACHE = {}
DOCKERHUB_VERIFICATION_LOCK = threading.Lock()
STORE_CATALOG_LOCK = threading.Lock()
ICON_CACHE = {}
APP_NAME_ALIASES = {
    "openspeedtest": "openspeedtest",
    "open speed test": "openspeedtest",
    "qbittorrent": "qbittorrent",
    "q bittorrent": "qbittorrent",
    "plex": "plex",
}
NATIVE_SERVICE_APP_DEFINITIONS = [
    {
        "name": "Tailscale",
        "service": "tailscaled.service",
        "command": "tailscale",
        "description": "Mesh VPN service",
        "tags": ["Native Linux", "Network"],
        "url_command": ["tailscale", "ip", "-4"],
        "url_template": "https://login.tailscale.com/admin/machines",
    },
]
INLINE_EXTENSIONS = {
    ".bmp",
    ".css",
    ".csv",
    ".gif",
    ".htm",
    ".html",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".log",
    ".md",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pdf",
    ".png",
    ".svg",
    ".txt",
    ".wav",
    ".webm",
    ".webp",
    ".xml",
}
ICON_CANDIDATES = [
    "/favicon.ico",
    "/favicon.png",
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
]
VIRTUAL_INTERFACE_PREFIXES = ("br-", "docker", "veth")
UPDATE_EXCLUDED = {"config.json", "data", ".git", "__pycache__", "dist", "backups", ".env", "homestart.service"}
UPDATE_ALLOWED_PREFIXES = {"static", "scripts", "docs", "homestart"}
UPDATE_ALLOWED_FILES = {
    ".gitignore",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "VERSION",
    "app.py",
    "config.example.json",
    "homestart.service.example",
    "install.sh",
    "package.json",
}
UPDATE_PRIVATE_SUFFIXES = (".db", ".sqlite", ".log")
UPDATE_PRIVATE_FRAGMENTS = (".sqlite-",)


def load_config_file():
    return load_config_data(CONFIG_PATH)


def save_config_file(config):
    return save_config_data(CONFIG_PATH, config)


def system_timezone():
    try:
        value = subprocess.check_output(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
        ).strip()
        if value:
            return value
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    try:
        value = Path("/etc/timezone").read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    try:
        resolved = str(Path("/etc/localtime").resolve())
        marker = "/zoneinfo/"
        if marker in resolved:
            return resolved.split(marker, 1)[1]
    except OSError:
        pass
    return "UTC"


def set_system_timezone(timezone_name):
    timezone_name = str(timezone_name or "").strip()
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ValueError("Unknown time zone region") from error
    try:
        subprocess.check_output(
            ["timedatectl", "set-timezone", timezone_name],
            text=True, timeout=15, stderr=subprocess.STDOUT,
        )
    except FileNotFoundError as error:
        raise ValueError("This Linux server does not provide timedatectl") from error
    except subprocess.CalledProcessError as error:
        raise ValueError((error.output or "").strip() or "Could not change the Linux server time zone") from error
    return timezone_name


def timezone_regions():
    regions = set(available_timezones())
    try:
        output = subprocess.check_output(
            ["timedatectl", "list-timezones"],
            text=True, timeout=10, stderr=subprocess.DEVNULL,
        )
        regions.update(item.strip() for item in output.splitlines() if item.strip())
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    regions.discard("localtime")
    return sorted(regions)


def settings_payload():
    config = load_config_file()
    return {
        "ok": True,
        "dashboard": config["dashboard"],
        "appearance": config["appearance"],
        "alerts": config["alerts"],
        "network": config["network"],
        "time": {"timezone": system_timezone(), "server_timestamp": int(time.time())},
        "trash": config["trash"],
        "timezones": timezone_regions(),
    }


def update_settings(payload):
    config = load_config_file()
    time_values = payload.get("time")
    if isinstance(time_values, dict):
        timezone_name = set_system_timezone(time_values.get("timezone", ""))
        config["time"] = deep_merge(config.get("time", {}), {"timezone": timezone_name})
    trash_values = payload.get("trash")
    if isinstance(trash_values, dict):
        try:
            retention = int(trash_values.get("retention_days", 0))
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid trash retention period") from error
        if retention not in {0, 7, 30, 90}:
            raise ValueError("Trash retention must be never, 7, 30 or 90 days")
        config["trash"] = deep_merge(config.get("trash", {}), {"retention_days": retention})
    for section in ("dashboard", "appearance", "alerts", "network"):
        values = payload.get(section)
        if isinstance(values, dict):
            config[section] = deep_merge(config.get(section, {}), values)
    save_config_file(config)
    return settings_payload()


def clamp_percent(value):
    if value is None:
        return None
    return max(0, min(100, round(value, 1)))


def local_ip():
    configured = os.environ.get("HOMESTART_HOST") or load_config_file()["dashboard"].get("host")
    if configured:
        return configured

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("1.1.1.1", 80))
            return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def public_app_url(url, host):
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return url

    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth = f"{auth}:{parsed.password}"
        netloc = f"{auth}@{netloc}"
    return parsed._replace(netloc=netloc).geturl()


def run_json(command):
    output = subprocess.check_output(command, text=True, timeout=5)
    return json.loads(output)


def removed_legacy_app_token():
    return "co" + "dex"


def removed_legacy_app_paths():
    token = removed_legacy_app_token()
    return {f"/{token}", f"/{token}/"}


def is_removed_legacy_config_app(app):
    if not isinstance(app, dict):
        return False
    token = removed_legacy_app_token()
    url = str(app.get("url") or "").strip().lower()
    parsed = urlparse(url)
    if url in removed_legacy_app_paths() or parsed.path in removed_legacy_app_paths():
        return True
    name = normalized_name(str(app.get("name") or ""))
    if name == token and normalize_app_type(app.get("app_type") or app.get("type")) == "supported":
        return True
    for requirement in app.get("requirements") or []:
        if str(requirement.get("name") or "").strip().lower() == token:
            return True
    return False


def prune_removed_legacy_config_apps():
    if not CONFIG_PATH.exists():
        return
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return

    changed = False
    for key in ("apps", "native_apps"):
        values = data.get(key)
        if not isinstance(values, list):
            continue
        filtered = [app for app in values if not is_removed_legacy_config_app(app)]
        if len(filtered) != len(values):
            data[key] = filtered
            changed = True

    if not changed:
        return
    try:
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        return


def load_config():
    prune_removed_legacy_config_apps()
    data = load_config_file()
    apps = []
    for key in ("apps", "native_apps"):
        values = data.get(key, [])
        if isinstance(values, list):
            for app in values:
                if (
                    app.get("name") == "Example App"
                    and app.get("description") == "Replace this with your own app"
                    and "localhost:8080" in str(app.get("url", ""))
                ):
                    continue
                if is_removed_legacy_config_app(app):
                    continue
                apps.append(app)
    return apps


def normalize_app_type(value):
    app_type = str(value or "").strip().lower().replace("_", "-")
    if app_type in {"docker", "container"}:
        return "docker"
    if app_type in {"native", "linux", "native-linux", "linux-native"}:
        return "native"
    if app_type in {"supported", "homestart-supported"}:
        return "supported"
    return ""


def app_type_label(app_type):
    return {
        "docker": "Docker",
        "native": "Native Linux",
        "supported": "Supported",
    }.get(app_type, "App")


def command_available(command):
    return shutil.which(command) is not None


def requirement_payload(requirement):
    req_type = requirement.get("type", "command")
    name = requirement.get("name", "")
    installed = False
    if req_type == "command":
        installed = command_available(name)
        if not installed:
            installed = any(Path(path).expanduser().exists() for path in requirement.get("paths", []))

    return {
        "type": req_type,
        "name": name,
        "installed": installed,
        "install_hint": requirement.get("install_hint", ""),
    }


def apply_app_metadata(app):
    app_type = normalize_app_type(app.get("app_type") or app.get("type") or app.get("source"))
    if not app_type:
        app_type = "supported" if app.get("requirements") else "native"

    requirements = [requirement_payload(item) for item in app.get("requirements", [])]
    missing = [item for item in requirements if not item["installed"]]
    tags = list(dict.fromkeys([app_type_label(app_type), *(app.get("tags") or [])]))

    app["app_type"] = app_type
    app["app_type_label"] = app_type_label(app_type)
    app["tags"] = tags
    app["requirements_status"] = requirements
    if missing:
        app["available"] = False
        app["status"] = f"Missing requirement: {', '.join(item['name'] for item in missing)}"
    else:
        app["available"] = True
    return app


def app_uninstall_enabled():
    return load_config_file().get("features", {}).get("app_uninstall", True)


def safe_uninstall_command(command):
    if not isinstance(command, list) or not command:
        return None
    if len(command) > 32:
        return None
    if not all(isinstance(part, str) and part.strip() for part in command):
        return None
    return [part.strip() for part in command]


def apply_uninstall_metadata(app):
    enabled = app_uninstall_enabled()
    command = safe_uninstall_command(app.get("uninstall_command"))
    app["uninstallable"] = False
    app["uninstall_reason"] = "Uninstall is disabled"

    if not enabled:
        return app

    if app.get("docker_name"):
        app["uninstallable"] = True
        app["uninstall_reason"] = "Removes the Docker container. Images and volumes are preserved."
        return app

    if command:
        app["uninstallable"] = True
        app["uninstall_reason"] = "Runs this app's configured uninstall command."
        return app

    app["uninstall_reason"] = "No uninstall command is configured for this app."
    return app


def normalized_name(name):
    lowered = re.sub(r"[^a-z0-9]+", "", name.lower())
    return APP_NAME_ALIASES.get(lowered, lowered)


def docker_inspect(container_name):
    if not container_name:
        return None

    try:
        output = subprocess.check_output(
            ["docker", "inspect", container_name],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
        data = json.loads(output)[0]
    except (IndexError, json.JSONDecodeError, subprocess.SubprocessError, FileNotFoundError):
        return None

    return data


def docker_container_diagnostics(container_name):
    data = docker_inspect(container_name)
    if not data:
        return None
    labels = data.get("Config", {}).get("Labels") or {}
    restart_policy = data.get("HostConfig", {}).get("RestartPolicy") or {}
    state = data.get("State") or {}
    return {
        "id": str(data.get("Id") or "")[:12],
        "name": str(data.get("Name") or "").lstrip("/"),
        "image": data.get("Config", {}).get("Image") or data.get("Image") or "",
        "state": state.get("Status") or "",
        "running": bool(state.get("Running")),
        "restart_policy": restart_policy.get("Name") or "",
        "compose_project": labels.get("com.docker.compose.project", ""),
        "compose_service": labels.get("com.docker.compose.service", ""),
    }


WEB_CONTAINER_PORTS = ["80", "443", "3000", "5000", "5601", "8000", "8080", "8081", "8096", "9000", "9443"]
NON_WEB_CONTAINER_PORTS = {"22", "2222", "25", "53", "110", "143", "465", "587", "993", "995", "3306", "5432", "6379"}
HTTPS_PORTS = {"443", "8443", "9443"}


def parse_container_port(value):
    port, _, protocol = str(value or "").partition("/")
    return port if port.isdigit() else "", protocol or "tcp"


def docker_port_mappings(container_name):
    data = docker_inspect(container_name)
    if not data:
        return []

    mappings = []
    if data.get("HostConfig", {}).get("NetworkMode") != "host":
        bindings = data.get("HostConfig", {}).get("PortBindings") or {}
        for container, values in bindings.items():
            container_port, protocol = parse_container_port(container)
            for item in values or []:
                host_port = str(item.get("HostPort", ""))
                if host_port.isdigit() and container_port:
                    mappings.append(
                        {
                            "host_port": host_port,
                            "container_port": container_port,
                            "protocol": protocol,
                        }
                    )

        network_ports = data.get("NetworkSettings", {}).get("Ports") or {}
        for container, values in network_ports.items():
            container_port, protocol = parse_container_port(container)
            for item in values or []:
                host_port = str(item.get("HostPort", ""))
                if host_port.isdigit() and container_port:
                    mappings.append(
                        {
                            "host_port": host_port,
                            "container_port": container_port,
                            "protocol": protocol,
                        }
                    )
    else:
        exposed = data.get("Config", {}).get("ExposedPorts") or {}
        for value in exposed:
            container_port, protocol = parse_container_port(value)
            if container_port and protocol == "tcp":
                mappings.append(
                    {
                        "host_port": container_port,
                        "container_port": container_port,
                        "protocol": protocol,
                    }
                )

    unique = []
    seen = set()
    for mapping in mappings:
        key = (mapping["host_port"], mapping["container_port"], mapping["protocol"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(mapping)
    return unique


def docker_port_score(mapping):
    if mapping.get("protocol") != "tcp":
        return -10000
    host_port = mapping.get("host_port", "")
    container_port = mapping.get("container_port", "")
    score = 0
    if container_port in WEB_CONTAINER_PORTS:
        score += 1000 - WEB_CONTAINER_PORTS.index(container_port)
    if host_port in WEB_CONTAINER_PORTS:
        score += 180 - WEB_CONTAINER_PORTS.index(host_port)
    if container_port in NON_WEB_CONTAINER_PORTS:
        score -= 900
    if host_port in NON_WEB_CONTAINER_PORTS:
        score -= 120
    if score == 0 and host_port.isdigit():
        score = 10
    return score


def select_docker_web_mapping(mappings):
    if not mappings:
        return None
    tcp_mappings = [mapping for mapping in mappings if mapping.get("protocol") == "tcp"]
    if not tcp_mappings:
        return None
    return sorted(
        tcp_mappings,
        key=lambda mapping: (docker_port_score(mapping), -int(mapping["host_port"])),
        reverse=True,
    )[0]


def docker_ports_for_display(mappings, selected=None):
    ports = []
    if selected:
        ports.append(selected["host_port"])
    for mapping in sorted(mappings, key=lambda item: int(item["host_port"])):
        if mapping.get("protocol") != "tcp":
            continue
        port = mapping["host_port"]
        if port not in ports:
            ports.append(port)
    return ports


def docker_url_from_mapping(host, mapping):
    if not mapping:
        return ""
    host_port = mapping["host_port"]
    container_port = mapping["container_port"]
    scheme = "https" if host_port in HTTPS_PORTS or container_port in HTTPS_PORTS else "http"
    default_port = (scheme == "http" and host_port == "80") or (scheme == "https" and host_port == "443")
    return f"{scheme}://{host}" if default_port else f"{scheme}://{host}:{host_port}"


def docker_apps(host, all_containers=True):
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

        output = subprocess.check_output(
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

        mappings = docker_port_mappings(item.get("Names", ""))
        selected_port = select_docker_web_mapping(mappings)
        ports = docker_ports_for_display(mappings, selected_port)
        url = docker_url_from_mapping(host, selected_port)
        apps.append(
            with_icon(
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
                }
            )
        )

    return apps


def docker_map(host):
    return {normalized_name(app["name"]): app for app in docker_apps(host)}


def conf_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def strip_config_comments(text):
    lines = []
    for line in text.splitlines():
        clean = line.split("#", 1)[0].strip()
        if clean:
            lines.append(clean)
    return "\n".join(lines)


def clean_config_value(value):
    return str(value or "").strip().strip(";").strip('"').strip("'")


def web_root_name(root):
    path = Path(root)
    name = path.name
    if name.lower() in {"html", "htdocs", "public", "public_html", "web", "www"} and path.parent.name:
        name = path.parent.name
    return re.sub(r"[-_]+", " ", name).strip().title() or str(path)


def local_web_url(host, port, tls=False):
    scheme = "https" if tls or str(port) == "443" else "http"
    port = str(port or ("443" if scheme == "https" else "80"))
    default = (scheme == "http" and port == "80") or (scheme == "https" and port == "443")
    return f"{scheme}://{host}" if default else f"{scheme}://{host}:{port}"


def detected_native_web_app(root, port, host, server="Web server", tls=False):
    try:
        resolved_root = Path(root).expanduser().resolve()
    except OSError:
        return None
    if not resolved_root.exists() or not resolved_root.is_dir():
        return None
    if str(resolved_root) in {"/", "/var/www", "/srv", "/opt"}:
        return None

    name = web_root_name(resolved_root)
    return with_icon(
        {
            "name": name,
            "kind": "Native Linux",
            "status": f"Detected {server} web root",
            "description": str(resolved_root),
            "url": local_web_url(host, port, tls),
            "source": "native-discovery",
            "app_type": "native",
            "app_type_label": "Native Linux",
            "tags": ["Native Linux", server],
            "available": True,
        }
    )


def apache_vhost_apps(host):
    apps = []
    paths = [
        *Path("/etc/apache2/sites-enabled").glob("*"),
        *Path("/etc/httpd/conf.d").glob("*.conf"),
        *Path("/etc/apache2/conf-enabled").glob("*.conf"),
    ]
    for path in paths:
        if not path.is_file():
            continue
        text = strip_config_comments(conf_text(path))
        roots = [clean_config_value(match) for match in re.findall(r"(?im)^\s*DocumentRoot\s+(.+)$", text)]
        if not roots:
            continue
        ports = re.findall(r"(?i)<VirtualHost\s+[^>]*:(\d+)[^>]*>", text)
        port = ports[0] if ports else "443" if re.search(r"(?im)^\s*SSLEngine\s+on\b", text) else "80"
        tls = str(port) == "443" or bool(re.search(r"(?im)^\s*SSLEngine\s+on\b", text))
        for root in roots:
            app = detected_native_web_app(root, port, host, "Apache", tls)
            if app:
                apps.append(app)
    return apps


def nginx_vhost_apps(host):
    apps = []
    paths = [
        *Path("/etc/nginx/sites-enabled").glob("*"),
        *Path("/etc/nginx/conf.d").glob("*.conf"),
    ]
    for path in paths:
        if not path.is_file():
            continue
        text = strip_config_comments(conf_text(path))
        roots = [clean_config_value(match) for match in re.findall(r"(?im)^\s*root\s+(.+)$", text)]
        if not roots:
            continue
        listens = [clean_config_value(match) for match in re.findall(r"(?im)^\s*listen\s+([^;]+)", text)]
        listen = listens[0] if listens else "80"
        port_match = re.search(r"(?<!:)\b(\d{2,5})\b", listen)
        port = port_match.group(1) if port_match else "443" if "ssl" in listen.lower() else "80"
        tls = str(port) == "443" or "ssl" in listen.lower()
        for root in roots:
            app = detected_native_web_app(root, port, host, "Nginx", tls)
            if app:
                apps.append(app)
    return apps


def native_web_apps(host):
    apps = []
    seen = set()
    for app in [*apache_vhost_apps(host), *nginx_vhost_apps(host)]:
        key = (normalized_name(app.get("name", "")), app.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        apply_uninstall_metadata(app)
        apps.append(app)
    return apps


def native_service_apps():
    apps = []
    for definition in NATIVE_SERVICE_APP_DEFINITIONS:
        service = definition.get("service", "")
        command = definition.get("command", "")
        service_data = service_status(service) if service else None
        command_installed = command_available(command) if command else False
        if not service_data and not command_installed:
            continue

        active = (service_data or {}).get("active", "unknown")
        sub = (service_data or {}).get("sub", "")
        status = "Installed"
        if service_data:
            status = f"{active}{f' ({sub})' if sub else ''}"
        elif command_installed:
            status = "Command installed"

        app = with_icon(
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
        apply_uninstall_metadata(app)
        apps.append(app)
    return apps


def with_icon(app):
    key = app_icon_key(app)
    app["icon_key"] = key
    custom_icon = custom_app_icon_url(key)
    if custom_icon:
        app["icon_url"] = custom_icon
        app["custom_icon"] = True
        return app

    if app.get("icon_url") or not app.get("url"):
        return app
    if urlparse(app.get("url", "")).scheme not in {"http", "https"}:
        return app

    app["icon_url"] = f"/api/icon?url={quote(app['url'], safe='')}"
    return app


def fetch_url(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "HomeStart/1.0",
            "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        content_type = response.headers.get_content_type()
        if not content_type.startswith("image/"):
            return None

        body = response.read(512 * 1024 + 1)
        if len(body) > 512 * 1024:
            return None

        return {
            "content_type": content_type,
            "body": body,
        }


def fetch_html_icon_urls(app_url):
    request = urllib.request.Request(
        app_url,
        headers={
            "User-Agent": "HomeStart/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            return []

        html = response.read(256 * 1024).decode("utf-8", errors="replace")

    urls = []
    for tag in re.findall(r"<link\b[^>]*>", html, flags=re.IGNORECASE):
        rel = re.search(r"\brel=[\"']([^\"']+)[\"']", tag, flags=re.IGNORECASE)
        href = re.search(r"\bhref=[\"']([^\"']+)[\"']", tag, flags=re.IGNORECASE)
        if not rel or not href:
            continue
        if "icon" not in rel.group(1).lower():
            continue
        urls.append(urljoin(app_url, href.group(1)))
    return urls


def icon_candidates(app_url):
    parsed = urlparse(app_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []

    base = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [f"{base}{path}" for path in ICON_CANDIDATES]
    if parsed.path and parsed.path != "/":
        parent = parsed.path.rsplit("/", 1)[0] or ""
        candidates.extend(f"{base}{parent}{path}" for path in ICON_CANDIDATES)

    try:
        candidates.extend(fetch_html_icon_urls(app_url))
    except (urllib.error.URLError, TimeoutError, OSError):
        pass

    return candidates


def get_icon(app_url):
    if app_url in ICON_CACHE:
        return ICON_CACHE[app_url]

    for candidate in icon_candidates(app_url):
        try:
            icon = fetch_url(candidate)
        except (urllib.error.URLError, TimeoutError, OSError):
            continue

        if icon:
            ICON_CACHE[app_url] = icon
            return icon

    ICON_CACHE[app_url] = None
    return None


def app_icon_key(app):
    identity = [
        str(app.get("docker_name") or ""),
        str(app.get("name") or ""),
        str(app.get("url") or ""),
        str(app.get("image") or ""),
    ]
    raw = "\n".join(identity).strip().lower()
    if not raw:
        raw = str(uuid.uuid4())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def load_app_icon_index():
    try:
        data = json.loads(APP_ICON_INDEX.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    return data if isinstance(data, dict) else {}


def save_app_icon_index(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    APP_ICON_INDEX.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def custom_app_icon(app_key):
    item = load_app_icon_index().get(str(app_key or ""))
    if not isinstance(item, dict):
        return None
    filename = item.get("filename", "")
    if not re.fullmatch(r"[a-f0-9]{24}\.(png|jpg|jpeg|gif|webp|svg)", filename):
        return None
    path = APP_ICON_DIR / filename
    if not path.is_file():
        return None
    return {
        "path": path,
        "content_type": item.get("content_type", "image/png"),
    }


def custom_app_icon_url(app_key):
    return f"/api/apps/icon?key={quote(str(app_key), safe='')}" if custom_app_icon(app_key) else ""


def serve_custom_app_icon(handler, app_key, include_body=True):
    icon = custom_app_icon(app_key)
    if not icon:
        handler.send_response(HTTPStatus.NOT_FOUND)
        handler.end_headers()
        return

    body = icon["path"].read_bytes() if include_body else b""
    stat = icon["path"].stat()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", icon["content_type"])
    handler.send_header("Content-Length", str(stat.st_size if include_body else 0))
    handler.send_header("Cache-Control", "no-store")
    handler.skip_default_cache = True
    handler.end_headers()
    if include_body:
        handler.wfile.write(body)


def save_custom_app_icon(payload):
    app_key = str(payload.get("app_key") or "").strip()
    if not re.fullmatch(r"[a-f0-9]{24}", app_key):
        raise ValueError("Invalid app icon key")

    name = str(payload.get("filename") or "icon").lower()
    content = str(payload.get("content") or "")
    header = ""
    if content.startswith("data:") and "," in content:
        header, content = content.split(",", 1)

    content_type = ""
    match = re.match(r"data:([^;]+);base64", header)
    if match:
        content_type = match.group(1).lower()

    extension_map = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/svg+xml": "svg",
    }
    extension = extension_map.get(content_type)
    if extension is None:
        suffix = Path(name).suffix.lower().lstrip(".")
        if suffix in {"png", "jpg", "jpeg", "gif", "webp", "svg"}:
            extension = "jpg" if suffix == "jpeg" else suffix
            content_type = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "gif": "image/gif",
                "webp": "image/webp",
                "svg": "image/svg+xml",
            }[extension]

    if extension is None:
        raise ValueError("Icon must be a PNG, JPG, GIF, WebP, or SVG image")

    try:
        body = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid icon encoding") from error

    if len(body) > 512 * 1024:
        raise ValueError("Icon is too large")
    if extension == "svg" and b"<script" in body.lower():
        raise ValueError("SVG icons cannot contain scripts")

    APP_ICON_DIR.mkdir(parents=True, exist_ok=True)
    index = load_app_icon_index()
    old = custom_app_icon(app_key)
    if old:
        old["path"].unlink(missing_ok=True)

    filename = f"{app_key}.{extension}"
    path = APP_ICON_DIR / filename
    path.write_bytes(body)
    index[app_key] = {
        "filename": filename,
        "content_type": content_type,
        "original_name": name[:120],
        "updated_at": int(time.time()),
    }
    save_app_icon_index(index)
    return {
        "ok": True,
        "icon_url": custom_app_icon_url(app_key),
    }


def serve_icon(handler, app_url, include_body=True):
    icon = get_icon(app_url)
    if not icon:
        handler.send_response(HTTPStatus.NOT_FOUND)
        handler.end_headers()
        return

    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", icon["content_type"])
    handler.send_header("Content-Length", str(len(icon["body"])))
    handler.send_header("Cache-Control", "public, max-age=3600")
    handler.skip_default_cache = True
    handler.end_headers()
    if include_body:
        handler.wfile.write(icon["body"])


def read_cpu_times():
    with Path("/proc/stat").open("r", encoding="utf-8") as file:
        fields = file.readline().split()[1:]

    values = [int(value) for value in fields]
    idle = values[3] + values[4]
    total = sum(values)
    return total, idle


def read_cpu_counters():
    with Path("/proc/stat").open("r", encoding="utf-8") as file:
        fields = [int(value) for value in file.readline().split()[1:]]

    names = ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "guest", "guest_nice"]
    return dict(zip(names, fields + [0] * (len(names) - len(fields))))


def cpu_percent():
    global CPU_PREV
    current = read_cpu_times()
    if CPU_PREV is None:
        CPU_PREV = current
        return None

    total_delta = current[0] - CPU_PREV[0]
    idle_delta = current[1] - CPU_PREV[1]
    CPU_PREV = current
    if total_delta <= 0:
        return None

    return clamp_percent((1 - (idle_delta / total_delta)) * 100)


def cpu_detail_payload():
    global CPU_DETAIL_PREV
    current = read_cpu_counters()
    if CPU_DETAIL_PREV is None:
        CPU_DETAIL_PREV = current
        return {
            "user": None,
            "system": None,
            "iowait": None,
            "idle": None,
        }

    delta = {key: current.get(key, 0) - CPU_DETAIL_PREV.get(key, 0) for key in current}
    CPU_DETAIL_PREV = current
    total = sum(max(0, value) for value in delta.values())
    if total <= 0:
        return {
            "user": None,
            "system": None,
            "iowait": None,
            "idle": None,
        }

    user = delta.get("user", 0) + delta.get("nice", 0)
    system = delta.get("system", 0) + delta.get("irq", 0) + delta.get("softirq", 0)
    return {
        "user": clamp_percent(user / total * 100),
        "system": clamp_percent(system / total * 100),
        "iowait": clamp_percent(delta.get("iowait", 0) / total * 100),
        "idle": clamp_percent(delta.get("idle", 0) / total * 100),
    }


def memory_payload():
    values = {}
    with Path("/proc/meminfo").open("r", encoding="utf-8") as file:
        for line in file:
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = max(0, total - available)
    percent = (used / total * 100) if total else None
    return {
        "used_bytes": used,
        "total_bytes": total,
        "free_bytes": values.get("MemFree", 0),
        "available_bytes": available,
        "used_label": format_bytes(used),
        "total_label": format_bytes(total),
        "free_label": format_bytes(values.get("MemFree", 0)),
        "available_label": format_bytes(available),
        "percent": clamp_percent(percent),
    }


def read_first_match(paths, pattern):
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return match.group(1), str(path)
    return None, None


def gpu_debug_paths(filename):
    root = Path("/sys/kernel/debug/dri")
    if not root.exists():
        return []
    return sorted(root.glob(f"*/{filename}"))


def gpu_frequency():
    raw, source = read_first_match(
        gpu_debug_paths("i915_frequency_info"),
        r"Actual freq:\s+(\d+)\s+MHz",
    )
    if raw is None:
        return None, None
    return int(raw), source


def gpu_busy_percent():
    global GPU_PREV
    paths = gpu_debug_paths("i915_engine_info")
    engine_runtime = {}

    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        engine = None
        for line in lines:
            stripped = line.strip()
            if stripped and not line.startswith("\t") and re.match(r"^[a-z]+[0-9]+$", stripped):
                engine = stripped
                continue

            if engine and stripped.startswith("Runtime:"):
                match = re.search(r"Runtime:\s+(\d+)ms", stripped)
                if match:
                    engine_runtime[engine] = int(match.group(1))
                engine = None

    if not engine_runtime:
        return None

    now = time.monotonic()
    current = (now, engine_runtime)
    if GPU_PREV is None:
        GPU_PREV = current
        return None

    elapsed_ms = max(1, (now - GPU_PREV[0]) * 1000)
    previous = GPU_PREV[1]
    GPU_PREV = current

    deltas = [
        max(0, runtime - previous.get(engine, runtime))
        for engine, runtime in engine_runtime.items()
    ]
    if not deltas:
        return None

    return clamp_percent((sum(deltas) / (elapsed_ms * max(1, len(deltas)))) * 100)


def nvidia_gpus_payload():
    command = shutil.which("nvidia-smi")
    if not command:
        return []
    try:
        output = subprocess.check_output(
            [
                command,
                "--query-gpu=index,name,utilization.gpu,clocks.gr,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []

    gpus = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            index = len(gpus)
        try:
            percent = float(parts[2])
        except ValueError:
            percent = None
        try:
            frequency = int(float(parts[3]))
        except ValueError:
            frequency = None
        try:
            memory_used = int(float(parts[4])) * 1024 * 1024
            memory_total = int(float(parts[5])) * 1024 * 1024
        except ValueError:
            memory_used = 0
            memory_total = 0
        gpus.append(
            {
                "index": index,
                "name": parts[1] or f"NVIDIA GPU {index}",
                "percent": clamp_percent(percent),
                "frequency_mhz": frequency,
                "memory_used_bytes": memory_used,
                "memory_total_bytes": memory_total,
                "memory_used_label": format_bytes(memory_used),
                "memory_total_label": format_bytes(memory_total),
                "memory_percent": clamp_percent((memory_used / memory_total * 100) if memory_total else None),
                "available": percent is not None or frequency is not None,
                "source": "nvidia-smi",
            }
        )
    return gpus


def summarize_gpus(gpus):
    available = [gpu for gpu in gpus if gpu.get("available")]
    if not available:
        return {
            "name": "GPU",
            "count": 0,
            "percent": None,
            "frequency_mhz": None,
            "available": False,
            "source": "",
        }

    percents = [gpu["percent"] for gpu in available if gpu.get("percent") is not None]
    frequencies = [gpu["frequency_mhz"] for gpu in available if gpu.get("frequency_mhz")]
    return {
        "name": f"{len(gpus)} GPUs" if len(gpus) > 1 else available[0].get("name", "GPU"),
        "count": len(gpus),
        "percent": max(percents) if percents else None,
        "frequency_mhz": max(frequencies) if frequencies else None,
        "available": True,
        "source": available[0].get("source", ""),
    }


def system_payload(network_channel="live"):
    gpus = nvidia_gpus_payload()
    if gpus:
        gpu = summarize_gpus(gpus)
    else:
        gpu_freq, gpu_source = gpu_frequency()
        gpu_busy = gpu_busy_percent()
        intel_gpu = {
            "index": 0,
            "name": "Intel GPU",
            "percent": gpu_busy,
            "frequency_mhz": gpu_freq,
            "available": gpu_busy is not None or gpu_freq is not None,
            "source": gpu_source,
        }
        gpus = [intel_gpu] if intel_gpu["available"] else []
        gpu = summarize_gpus(gpus)
    payload = {
        "timestamp": int(time.time()),
        "cpu": {"percent": cpu_percent()},
        "memory": memory_payload(),
        "gpu": gpu,
        "gpus": gpus,
        "network": network_payload(network_channel) if network_channel else {},
        "temperature": temperature_payload(),
    }
    return payload


def metrics_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS system_metrics (
          captured_at INTEGER PRIMARY KEY,
          cpu REAL,
          memory REAL,
          gpu REAL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS network_metrics (
          captured_at INTEGER PRIMARY KEY,
          rx_bps REAL,
          tx_bps REAL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS container_network_metrics (
          captured_at INTEGER,
          container_key TEXT,
          name TEXT,
          rx_bytes REAL,
          tx_bytes REAL,
          rx_bps REAL,
          tx_bps REAL,
          PRIMARY KEY (captured_at, container_key)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS host_network_estimates (
          captured_at INTEGER,
          identity_key TEXT,
          name TEXT,
          kind TEXT,
          confidence TEXT,
          rx_bytes REAL,
          tx_bytes REAL,
          rx_bps REAL,
          tx_bps REAL,
          PRIMARY KEY (captured_at, identity_key)
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(system_metrics)")}
    for name in ("rx_bps", "tx_bps", "temperature"):
        if name not in columns:
            connection.execute(f"ALTER TABLE system_metrics ADD COLUMN {name} REAL")
    return connection


def record_system_metric(payload):
    global METRIC_LAST_WRITE
    captured_at = int(payload.get("timestamp") or time.time())
    if captured_at - METRIC_LAST_WRITE < 30:
        return
    METRIC_LAST_WRITE = captured_at
    with metrics_db() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO system_metrics (captured_at, cpu, memory, gpu, rx_bps, tx_bps, temperature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                captured_at,
                payload.get("cpu", {}).get("percent"),
                payload.get("memory", {}).get("percent"),
                payload.get("gpu", {}).get("percent"),
                payload.get("network", {}).get("rx_bps"),
                payload.get("network", {}).get("tx_bps"),
                payload.get("temperature", {}).get("celsius"),
            ),
        )
        connection.execute("DELETE FROM system_metrics WHERE captured_at < ?", (captured_at - 7 * 86400,))


def record_network_metric(payload):
    captured_at = int(payload.get("timestamp") or time.time())
    with metrics_db() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO network_metrics (captured_at, rx_bps, tx_bps) VALUES (?, ?, ?)",
            (captured_at, payload.get("rx_bps"), payload.get("tx_bps")),
        )
        connection.execute("DELETE FROM network_metrics WHERE captured_at < ?", (captured_at - 7 * 86400,))


def record_container_network_metrics(samples, captured_at=None):
    captured_at = int(captured_at or time.time())
    if not samples:
        return
    rows = [
        (
            captured_at,
            str(sample.get("key") or sample.get("name") or ""),
            str(sample.get("name") or "Unknown container"),
            max(0, float(sample.get("rx_bps") or 0) * float(sample.get("sample_seconds") or 2)),
            max(0, float(sample.get("tx_bps") or 0) * float(sample.get("sample_seconds") or 2)),
            max(0, float(sample.get("rx_bps") or 0)),
            max(0, float(sample.get("tx_bps") or 0)),
        )
        for sample in samples
        if sample.get("key") or sample.get("name")
    ]
    if not rows:
        return
    with metrics_db() as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO container_network_metrics
              (captured_at, container_key, name, rx_bytes, tx_bytes, rx_bps, tx_bps)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.execute(
            "DELETE FROM container_network_metrics WHERE captured_at < ?",
            (captured_at - 7 * 86400,),
        )


def record_host_network_estimates(samples, network, container_samples, captured_at=None):
    captured_at = int(captured_at or time.time())
    sample_seconds = max(.001, float(network.get("sample_seconds") or 2))
    rows = []
    estimated_rx = estimated_tx = 0
    for sample in samples:
        rx_bytes = max(0, float(sample.get("rx_bytes") or 0))
        tx_bytes = max(0, float(sample.get("tx_bytes") or 0))
        estimated_rx += rx_bytes
        estimated_tx += tx_bytes
        rows.append((
            captured_at,
            str(sample.get("key") or sample.get("name") or ""),
            str(sample.get("name") or "Unknown process"),
            str(sample.get("kind") or "process"),
            str(sample.get("confidence") or "medium"),
            rx_bytes,
            tx_bytes,
            max(0, float(sample.get("rx_bps") or 0)),
            max(0, float(sample.get("tx_bps") or 0)),
        ))

    measured_rx = sum(
        max(0, float(item.get("rx_bps") or 0) * float(item.get("sample_seconds") or sample_seconds))
        for item in container_samples
    )
    measured_tx = sum(
        max(0, float(item.get("tx_bps") or 0) * float(item.get("sample_seconds") or sample_seconds))
        for item in container_samples
    )
    host_rx = max(0, float(network.get("rx_bps") or 0) * sample_seconds)
    host_tx = max(0, float(network.get("tx_bps") or 0) * sample_seconds)
    unattributed_rx = max(0, host_rx - measured_rx - estimated_rx)
    unattributed_tx = max(0, host_tx - measured_tx - estimated_tx)
    if unattributed_rx or unattributed_tx:
        rows.append((
            captured_at,
            "unattributed",
            "Unattributed traffic",
            "unattributed",
            "low",
            unattributed_rx,
            unattributed_tx,
            unattributed_rx / sample_seconds,
            unattributed_tx / sample_seconds,
        ))
    if not rows:
        return
    with metrics_db() as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO host_network_estimates
              (captured_at, identity_key, name, kind, confidence, rx_bytes, tx_bytes, rx_bps, tx_bps)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.execute(
            "DELETE FROM host_network_estimates WHERE captured_at < ?",
            (captured_at - 7 * 86400,),
        )


def container_network_ranking(period=3600, limit=12):
    try:
        period = int(period)
    except (TypeError, ValueError):
        period = 3600
    if period not in {60, 3600, 86400}:
        raise ValueError("Ranking period must be 60, 3600, or 86400 seconds")
    limit = max(1, min(50, int(limit or 12)))
    since = int(time.time()) - period
    with metrics_db() as connection:
        rows = connection.execute(
            """
            SELECT name,
                   SUM(rx_bytes) AS rx_bytes,
                   SUM(tx_bytes) AS tx_bytes,
                   AVG(rx_bps) AS rx_avg_bps,
                   AVG(tx_bps) AS tx_avg_bps,
                   MAX(rx_bps) AS rx_peak_bps,
                   MAX(tx_bps) AS tx_peak_bps,
                   COUNT(*) AS sample_count
            FROM container_network_metrics
            WHERE captured_at >= ?
            GROUP BY name
            HAVING (SUM(rx_bytes) + SUM(tx_bytes)) > 0
            ORDER BY (SUM(rx_bytes) + SUM(tx_bytes)) DESC
            LIMIT ?
            """,
            (since, limit),
        ).fetchall()
        estimated_rows = connection.execute(
            """
            SELECT identity_key,
                   name,
                   kind,
                   confidence,
                   SUM(rx_bytes) AS rx_bytes,
                   SUM(tx_bytes) AS tx_bytes,
                   AVG(rx_bps) AS rx_avg_bps,
                   AVG(tx_bps) AS tx_avg_bps,
                   MAX(rx_bps) AS rx_peak_bps,
                   MAX(tx_bps) AS tx_peak_bps,
                   COUNT(*) AS sample_count
            FROM host_network_estimates
            WHERE captured_at >= ?
            GROUP BY identity_key, name, kind, confidence
            HAVING (SUM(rx_bytes) + SUM(tx_bytes)) > 0
            ORDER BY (SUM(rx_bytes) + SUM(tx_bytes)) DESC
            LIMIT ?
            """,
            (since, limit),
        ).fetchall()
    items = []
    for index, row in enumerate(rows, 1):
        item = dict(row)
        item["rank"] = index
        item["total_bytes"] = float(item.get("rx_bytes") or 0) + float(item.get("tx_bytes") or 0)
        items.append(item)
    estimated_items = []
    for index, row in enumerate(estimated_rows, 1):
        item = dict(row)
        item["rank"] = index
        item["total_bytes"] = float(item.get("rx_bytes") or 0) + float(item.get("tx_bytes") or 0)
        estimated_items.append(item)
    return {
        "ok": True,
        "period_seconds": period,
        "generated_at": int(time.time()),
        "items": items,
        "estimated_items": estimated_items,
        "scope": "docker_containers",
        "estimated_scope": "host_tcp_processes",
    }


def metrics_history(hours=24):
    automatic = str(hours).lower() == "auto"
    try:
        hours = 168 if automatic else max(1, min(168, int(hours)))
    except (TypeError, ValueError):
        hours = 24
    server_timestamp = int(time.time())
    since = server_timestamp - hours * 3600
    with metrics_db() as connection:
        rows = connection.execute(
            "SELECT captured_at, cpu, memory, gpu, rx_bps, tx_bps, temperature FROM system_metrics WHERE captured_at >= ? ORDER BY captured_at",
            (since,),
        ).fetchall()
        network_bounds = connection.execute(
            "SELECT MIN(captured_at), MAX(captured_at), COUNT(*) FROM network_metrics WHERE captured_at BETWEEN ? AND ?",
            (since, server_timestamp + 5),
        ).fetchone()
        available_span = max(0, (network_bounds[1] or 0) - (network_bounds[0] or 0))
        bucket_seconds = max(2, int((available_span + 1199) // 1200))
        network_rows = connection.execute(
            """
            SELECT (captured_at / ?) * ? AS captured_at,
                   MAX(rx_bps) AS rx_bps,
                   MAX(tx_bps) AS tx_bps,
                   AVG(rx_bps) AS rx_avg_bps,
                   AVG(tx_bps) AS tx_avg_bps,
                   COUNT(*) AS sample_count
            FROM network_metrics
            WHERE captured_at BETWEEN ? AND ?
            GROUP BY captured_at / ?
            ORDER BY captured_at
            """,
            (bucket_seconds, bucket_seconds, since, server_timestamp + 5, bucket_seconds),
        ).fetchall()
        if not network_rows:
            network_rows = connection.execute(
                "SELECT captured_at, rx_bps, tx_bps FROM system_metrics WHERE captured_at >= ? ORDER BY captured_at",
                (since,),
            ).fetchall()
    network_points = []
    for row in network_rows:
        point = dict(row)
        point.setdefault("rx_avg_bps", point.get("rx_bps"))
        point.setdefault("tx_avg_bps", point.get("tx_bps"))
        point.setdefault("sample_count", 1)
        network_points.append(point)
    gap_threshold = max(10, bucket_seconds * 3)
    gaps = [
        {"start": previous["captured_at"], "end": current["captured_at"],
         "seconds": current["captured_at"] - previous["captured_at"]}
        for previous, current in zip(network_points, network_points[1:])
        if current["captured_at"] - previous["captured_at"] > gap_threshold
    ]
    latest_sample = network_points[-1]["captured_at"] if network_points else None
    return {
        "ok": True,
        "hours": "auto" if automatic else hours,
        "server_timestamp": server_timestamp,
        "network_interface": default_network_interface(),
        "points": [dict(row) for row in rows],
        "network_points": network_points,
        "network_sample_seconds": 2,
        "network_bucket_seconds": bucket_seconds,
        "network_status": {
            "stored_samples": int(network_bounds[2] or 0),
            "first_timestamp": network_bounds[0],
            "last_timestamp": network_bounds[1],
            "last_sample_age_seconds": max(0, server_timestamp - latest_sample) if latest_sample else None,
            "gap_count": len(gaps),
            "largest_gap_seconds": max((gap["seconds"] for gap in gaps), default=0),
        },
        "retention_days": 7,
    }


def metrics_sampler():
    """Collect history independently from browser activity."""
    while True:
        started = time.monotonic()
        try:
            record_system_metric(system_payload(None))
            cleanup_expired_trash()
        except Exception as error:
            print(f"HomeStart metrics sampler: {error}", flush=True)
        elapsed = time.monotonic() - started
        time.sleep(max(1, 30 - elapsed))


def network_metrics_sampler():
    """Collect two-second network history independently from the browser."""
    while True:
        started = time.monotonic()
        try:
            network = network_payload("history")
            record_network_metric({"timestamp": int(time.time()), **network})
            container_samples = update_container_network_top()
            record_container_network_metrics(container_samples)
            host_samples = update_host_network_estimates(network.get("interface", ""))
            record_host_network_estimates(host_samples, network, container_samples)
        except Exception as error:
            print(f"HomeStart network sampler: {error}", flush=True)
        elapsed = time.monotonic() - started
        time.sleep(max(.25, 2 - elapsed))


def overview_payload():
    system = system_payload()
    status = status_payload()
    alerts = []
    cpu = system.get("cpu", {}).get("percent")
    memory = system.get("memory", {}).get("percent")
    temperature = system.get("temperature", {}).get("celsius")
    thresholds = load_config_file().get("alerts", {})
    if cpu is not None and cpu >= float(thresholds.get("cpu_percent", 90)):
        alerts.append({"id": "cpu-high", "level": "warning", "title": "High CPU usage", "detail": f"CPU is at {cpu:.0f}%"})
    if memory is not None and memory >= float(thresholds.get("memory_percent", 90)):
        alerts.append({"id": "memory-high", "level": "warning", "title": "High memory usage", "detail": f"Memory is at {memory:.0f}%"})
    if temperature is not None and temperature >= float(thresholds.get("temperature_c", 85)):
        alerts.append({"id": "temperature-high", "level": "critical", "title": "High temperature", "detail": f"Host temperature is {temperature:.0f} °C"})
    for disk in status["disks"]:
        if disk.get("percent", 0) >= float(thresholds.get("disk_percent", 90)):
            alerts.append({"id": f"disk-{disk['device']}", "level": "critical", "title": "Disk almost full", "detail": f"{disk['device']} is at {disk['percent']:.0f}%"})
    for service in status["services"]:
        if service.get("active") != "active":
            service_name = service.get("name", "Service")
            alerts.append({"id": f"service-{service_name}", "level": "critical", "title": "Service unavailable", "detail": service_name})
    stopped = [item for item in status["containers"] if not item.get("docker_running")]
    if stopped:
        stopped_names = [item.get("docker_name") or item.get("name") or "Unnamed container" for item in stopped]
        alerts.append({"id": "stopped-containers", "level": "info", "title": "Stopped containers",
                       "detail": f"{len(stopped_names)} stopped: {', '.join(stopped_names)}"})
    health = "critical" if any(item["level"] == "critical" for item in alerts) else "warning" if alerts else "healthy"
    return {
        "ok": True,
        "health": health,
        "hostname": socket.gethostname(),
        "uptime": uptime_label(),
        "system": system,
        "status": status,
        "alerts": alerts,
        "summary": {
            "containers_running": len(status["containers"]) - len(stopped),
            "containers_total": len(status["containers"]),
            "services_ok": sum(1 for item in status["services"] if item.get("active") == "active"),
            "services_total": len(status["services"]),
        },
    }


def network_device_totals(content):
    return parse_network_device_totals(content)


def parse_ss_tcp_counters(output):
    return parse_socket_tcp_counters(output)


def endpoint_address(endpoint):
    return parse_endpoint_address(endpoint)


def interface_ip_addresses(interface):
    global INTERFACE_ADDRESS_CACHE
    now = time.monotonic()
    if (
        interface
        and INTERFACE_ADDRESS_CACHE.get("interface") == interface
        and now - float(INTERFACE_ADDRESS_CACHE.get("at") or 0) < 30
    ):
        return set(INTERFACE_ADDRESS_CACHE.get("items") or set())
    addresses = set()
    if interface:
        try:
            output = subprocess.check_output(
                ["ip", "-j", "address", "show", "dev", interface],
                text=True,
                timeout=2,
                stderr=subprocess.DEVNULL,
            )
            for item in json.loads(output or "[]"):
                for address in item.get("addr_info") or []:
                    local = str(address.get("local") or "")
                    if local:
                        addresses.add(local)
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
            pass
    INTERFACE_ADDRESS_CACHE = {"at": now, "interface": interface, "items": addresses}
    return addresses


def docker_identity_names():
    global DOCKER_IDENTITY_CACHE
    now = time.monotonic()
    if now - float(DOCKER_IDENTITY_CACHE.get("at") or 0) < 15:
        return dict(DOCKER_IDENTITY_CACHE.get("items") or {})
    identities = {}
    try:
        output = run_docker_command(["ps", "--format", "{{.ID}}\t{{.Names}}"], timeout=10)
        for line in output.splitlines():
            identifier, separator, name = line.partition("\t")
            if separator and identifier.strip() and name.strip():
                identities[identifier.strip()] = name.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    DOCKER_IDENTITY_CACHE = {"at": now, "items": identities}
    return identities


def process_display_name(pid, fallback=""):
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        parts = [part.decode("utf-8", errors="replace") for part in command if part]
    except OSError:
        parts = []
    executable = Path(parts[0]).name if parts else str(fallback or "")
    interpreter = executable.lower() in {"python", "python3", "node", "bash", "sh", "perl", "ruby"}
    if interpreter and len(parts) > 1 and not parts[1].startswith("-"):
        return f"{executable} · {Path(parts[1]).name}"
    if executable:
        return executable
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except OSError:
        return f"PID {pid}"


def host_process_identity(pid, fallback="", docker_identities=None):
    docker_identities = docker_identities or {}
    try:
        cgroup = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        cgroup = ""
    for identifier, name in docker_identities.items():
        if identifier and identifier in cgroup:
            return {
                "key": f"host-container:{name}",
                "name": name,
                "kind": "host_container",
                "confidence": "medium",
            }
    name = process_display_name(pid, fallback)
    return {
        "key": f"process:{name}",
        "name": name,
        "kind": "process",
        "confidence": "medium" if name and not name.startswith("PID ") else "low",
    }


def ss_tcp_process_counters():
    command = shutil.which("ss")
    if not command:
        return None
    try:
        output = subprocess.check_output(
            [command, "-Htinp"],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_ss_tcp_counters(output)


def update_host_network_estimates(interface):
    global HOST_TCP_PREV
    connections = ss_tcp_process_counters()
    if connections is None:
        return []
    addresses = interface_ip_addresses(interface)
    if addresses:
        connections = [
            connection for connection in connections
            if endpoint_address(connection.get("local")) in addresses
        ]
    now = time.monotonic()
    current = {
        item["key"]: (now, item["rx_total"], item["tx_total"])
        for item in connections
    }
    identities = docker_identity_names()
    pid_identities = {}
    aggregated = {}
    for connection in connections:
        previous = HOST_TCP_PREV.get(connection["key"])
        if not previous:
            continue
        elapsed = max(.001, now - previous[0])
        rx_bytes = max(0, connection["rx_total"] - previous[1])
        tx_bytes = max(0, connection["tx_total"] - previous[2])
        if not rx_bytes and not tx_bytes:
            continue
        pid = connection["pid"]
        identity = pid_identities.setdefault(
            pid,
            host_process_identity(pid, connection.get("process", ""), identities),
        )
        item = aggregated.setdefault(identity["key"], {
            **identity,
            "rx_bytes": 0,
            "tx_bytes": 0,
            "elapsed_weight": 0,
        })
        item["rx_bytes"] += rx_bytes
        item["tx_bytes"] += tx_bytes
        item["elapsed_weight"] = max(item["elapsed_weight"], elapsed)
        if connection.get("owner_count", 1) > 1:
            item["confidence"] = "low"
    HOST_TCP_PREV = current
    samples = []
    for item in aggregated.values():
        elapsed = max(.001, item.pop("elapsed_weight"))
        item["sample_seconds"] = elapsed
        item["rx_bps"] = item["rx_bytes"] / elapsed
        item["tx_bps"] = item["tx_bytes"] / elapsed
        samples.append(item)
    return samples


def container_network_targets():
    global CONTAINER_NETWORK_TARGETS, CONTAINER_NETWORK_TARGETS_AT
    now = time.monotonic()
    if now - CONTAINER_NETWORK_TARGETS_AT < 15:
        return CONTAINER_NETWORK_TARGETS
    try:
        ids = run_docker_command(["ps", "-q"], timeout=10).split()
        if not ids:
            targets = []
        else:
            details = json.loads(run_docker_command(["inspect", *ids], timeout=15))
            targets = []
            seen_namespaces = set()
            for item in details:
                pid = int((item.get("State") or {}).get("Pid") or 0)
                network_mode = str((item.get("HostConfig") or {}).get("NetworkMode") or "")
                namespace = str((item.get("NetworkSettings") or {}).get("SandboxKey") or pid)
                if pid <= 0 or network_mode == "host" or namespace in seen_namespaces:
                    continue
                seen_namespaces.add(namespace)
                labels = (item.get("Config") or {}).get("Labels") or {}
                name = (labels.get("com.docker.compose.service") or str(item.get("Name") or "").lstrip("/") or item.get("Id", "")[:12])
                targets.append({"key": namespace, "pid": pid, "name": name})
    except (ValueError, OSError, json.JSONDecodeError, subprocess.SubprocessError):
        targets = []
    CONTAINER_NETWORK_TARGETS = targets
    CONTAINER_NETWORK_TARGETS_AT = now
    return targets


def update_container_network_top():
    global CONTAINER_NETWORK_PREV, CONTAINER_NETWORK_TOP
    now = time.monotonic()
    samples = []
    current = {}
    for target in container_network_targets():
        try:
            content = Path(f"/proc/{target['pid']}/net/dev").read_text(encoding="utf-8")
            received, transmitted = network_device_totals(content)
        except (OSError, ValueError, IndexError):
            continue
        current[target["key"]] = (now, received, transmitted)
        previous = CONTAINER_NETWORK_PREV.get(target["key"])
        if not previous:
            continue
        elapsed = max(.001, now - previous[0])
        samples.append({
            "key": target["key"],
            "name": target["name"],
            "kind": "container",
            "sample_seconds": elapsed,
            "rx_bps": max(0, round((received - previous[1]) / elapsed)),
            "tx_bps": max(0, round((transmitted - previous[2]) / elapsed)),
        })
    download = max(samples, key=lambda item: item["rx_bps"], default=None)
    upload = max(samples, key=lambda item: item["tx_bps"], default=None)
    if download and not download["rx_bps"]:
        download = None
    if upload and not upload["tx_bps"]:
        upload = None
    with CONTAINER_NETWORK_LOCK:
        CONTAINER_NETWORK_PREV = current
        CONTAINER_NETWORK_TOP = {"download": download, "upload": upload}
    return samples


def network_payload(channel="live"):
    global NETWORK_LIVE_PREV, NETWORK_HISTORY_PREV
    received = transmitted = 0
    selected_interface = default_network_interface()
    try:
        for line in Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]:
            interface, values = line.split(":", 1)
            interface = interface.strip()
            if interface == "lo" or (selected_interface and interface != selected_interface):
                continue
            fields = values.split()
            received += int(fields[0])
            transmitted += int(fields[8])
    except (OSError, ValueError, IndexError):
        return {"interface": selected_interface, "rx_bps": 0, "tx_bps": 0, "rx_label": "0 B/s", "tx_label": "0 B/s"}
    now = time.monotonic()
    rx_bps = tx_bps = 0
    sample_seconds = 0
    previous = NETWORK_HISTORY_PREV if channel == "history" else NETWORK_LIVE_PREV
    if previous and len(previous) >= 4 and previous[3] == selected_interface:
        sample_seconds = max(.001, now - previous[0])
        rx_bps = max(0, (received - previous[1]) / sample_seconds)
        tx_bps = max(0, (transmitted - previous[2]) / sample_seconds)
    if channel == "history":
        NETWORK_HISTORY_PREV = (now, received, transmitted, selected_interface)
    else:
        NETWORK_LIVE_PREV = (now, received, transmitted, selected_interface)
    result = {
        "interface": selected_interface,
        "rx_bps": round(rx_bps),
        "tx_bps": round(tx_bps),
        "sample_seconds": sample_seconds,
        "rx_label": f"{format_bytes(rx_bps)}/s",
        "tx_label": f"{format_bytes(tx_bps)}/s",
    }
    if channel == "live":
        with CONTAINER_NETWORK_LOCK:
            result["top_consumers"] = dict(CONTAINER_NETWORK_TOP)
    return result


def read_sysfs_value(path, fallback=""):
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return fallback


def parse_udev_properties(content):
    return parse_network_udev_properties(content)


def udev_network_properties(interface):
    try:
        result = subprocess.run(
            ["udevadm", "info", "--query=property", f"--path=/sys/class/net/{interface}"],
            capture_output=True, text=True, check=True, timeout=2,
        )
        return parse_udev_properties(result.stdout)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return {}


def network_interface_metadata(name, ip_item=None):
    root = Path("/sys/class/net") / name
    properties = udev_network_properties(name)
    vendor = properties.get("ID_VENDOR_FROM_DATABASE") or properties.get("ID_VENDOR", "").replace("_", " ")
    model = properties.get("ID_MODEL_FROM_DATABASE") or properties.get("ID_MODEL", "").replace("_", " ")
    try:
        driver = (root / "device" / "driver").resolve().name
    except OSError:
        driver = ""
    kind = "Wi-Fi" if (root / "wireless").exists() else "Ethernet"
    hardware = " ".join(part for part in (vendor, model) if part).strip()
    label = hardware or (f"{kind} · {driver}" if driver else f"{kind} interface")
    speed = read_sysfs_value(root / "speed")
    if not speed.isdigit() or int(speed) <= 0:
        speed = ""
    ipv4 = [
        address.get("local", "") for address in (ip_item or {}).get("addr_info", [])
        if address.get("family") == "inet" and address.get("local")
    ]
    return {
        "name": name,
        "label": label,
        "vendor": vendor,
        "model": model,
        "driver": driver,
        "kind": kind.lower(),
        "mac": (ip_item or {}).get("address") or read_sysfs_value(root / "address"),
        "state": (ip_item or {}).get("operstate") or read_sysfs_value(root / "operstate", "unknown"),
        "carrier": read_sysfs_value(root / "carrier") == "1",
        "speed_mbps": int(speed) if speed else None,
        "duplex": read_sysfs_value(root / "duplex"),
        "ipv4": ipv4,
    }


def monitorable_network_interfaces(refresh=False):
    global NETWORK_INTERFACE_CACHE
    now = time.monotonic()
    if not refresh and now - NETWORK_INTERFACE_CACHE["at"] < 15:
        return NETWORK_INTERFACE_CACHE["items"]
    try:
        addresses = run_json(["ip", "-j", "addr", "show"])
    except (json.JSONDecodeError, subprocess.SubprocessError, FileNotFoundError):
        addresses = []
    address_map = {item.get("ifname"): item for item in addresses}
    try:
        paths = list(Path("/sys/class/net").iterdir())
    except OSError:
        paths = []
    items = []
    for path in paths:
        name = path.name
        if name == "lo" or name.startswith(VIRTUAL_INTERFACE_PREFIXES):
            continue
        if not ((path / "device").exists() or (path / "wireless").exists()):
            continue
        items.append(network_interface_metadata(name, address_map.get(name)))
    NETWORK_INTERFACE_CACHE = {"at": now, "items": sorted(items, key=lambda item: item["name"])}
    return NETWORK_INTERFACE_CACHE["items"]


def choose_monitor_interface(items, configured="auto", route_names=None):
    return select_monitor_interface(items, configured, route_names)


def default_route_interfaces():
    names = []
    try:
        for line in Path("/proc/net/route").read_text(encoding="utf-8").splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 4 and fields[1] == "00000000" and int(fields[3], 16) & 2:
                names.append(fields[0])
    except (OSError, ValueError, IndexError):
        pass
    return names


def default_network_interface():
    config = load_config_file().get("network", {})
    return choose_monitor_interface(
        monitorable_network_interfaces(),
        config.get("monitor_interface", "auto"),
        default_route_interfaces(),
    )


def temperature_payload():
    values = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = float(path.read_text().strip())
            values.append(value / 1000 if value > 1000 else value)
        except (OSError, ValueError):
            continue
    celsius = max(values) if values else None
    return {"celsius": round(celsius, 1) if celsius is not None else None, "available": celsius is not None}


def uptime_label():
    try:
        seconds = int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        return "unknown"

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days} days, {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def task_summary():
    total = 0
    threads = 0
    running = 0
    sleeping = 0
    other = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue

        total += 1
        try:
            stat = entry.joinpath("stat").read_text(encoding="utf-8", errors="replace").split()
            status = entry.joinpath("status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        state = stat[2] if len(stat) > 2 else ""
        if state == "R":
            running += 1
        elif state in {"S", "I"}:
            sleeping += 1
        else:
            other += 1

        match = re.search(r"^Threads:\s+(\d+)$", status, flags=re.MULTILINE)
        if match:
            threads += int(match.group(1))

    return {
        "total": total,
        "threads": threads,
        "running": running,
        "sleeping": sleeping,
        "other": other,
    }


def process_payload(limit=12):
    try:
        output = subprocess.check_output(
            ["ps", "-eo", "pid,user,pcpu,pmem,rss,args", "--sort=-pcpu"],
            text=True,
            timeout=3,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []

    processes = []
    for line in output.splitlines()[1:]:
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue

        pid, user, cpu, memory, rss, command = parts
        if "ps -eo pid,user,pcpu,pmem,rss,args" in command or "docker stats --no-stream" in command:
            continue
        try:
            rss_bytes = int(rss) * 1024
            raw_cpu = float(cpu)
            memory_percent = float(memory)
        except ValueError:
            rss_bytes = 0
            raw_cpu = 0
            memory_percent = 0

        processes.append(
            {
                "pid": pid,
                "user": user,
                "cpu_percent": clamp_percent(raw_cpu),
                "cpu_raw_percent": raw_cpu,
                "memory_percent": memory_percent,
                "memory": format_bytes(rss_bytes),
                "command": command,
            }
        )
        if len(processes) >= limit:
            break
    return processes


def docker_stats_payload():
    try:
        output = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return {}

    stats = {}
    for line in output.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = item.get("Name", "")
        if name:
            stats[name] = item
    return stats


def container_resources_payload():
    stats = docker_stats_payload()
    containers = []
    for app in docker_apps(local_ip()):
        name = app.get("docker_name") or app.get("name")
        stat = stats.get(name, {})
        containers.append(
            {
                "name": name,
                "status": app.get("status", ""),
                "cpu": stat.get("CPUPerc", "0%"),
                "memory": stat.get("MemUsage", ""),
                "memory_percent": stat.get("MemPerc", ""),
                "ports": app.get("ports", []),
            }
        )
    return containers


def resources_payload():
    memory = memory_payload()
    return {
        "hostname": socket.gethostname(),
        "uptime": uptime_label(),
        "cpu": cpu_detail_payload(),
        "memory": memory,
        "containers": container_resources_payload(),
        "tasks": task_summary(),
        "processes": process_payload(),
    }


def format_bytes(size):
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def file_kind(path):
    if path.is_dir():
        return "directory"

    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}:
        return "image"
    if suffix in {".mp4", ".webm", ".mkv", ".avi", ".mov"}:
        return "video"
    if suffix in {".mp3", ".wav", ".ogg", ".flac", ".m4a"}:
        return "audio"
    if suffix in {".pdf"}:
        return "pdf"
    if suffix in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        return "archive"
    if suffix in {".txt", ".md", ".log", ".json", ".xml", ".csv", ".js", ".css", ".html"}:
        return "text"
    return "file"


def allowed_roots():
    config = load_config_file()
    roots = []
    candidates = config.get("file_roots", []) or DEFAULT_CONFIG["file_roots"]
    for item in candidates:
        try:
            root = Path(item).expanduser().resolve()
        except OSError:
            continue
        if root.exists():
            roots.append(root)
    return roots


def path_is_allowed(path, roots):
    return any(path == root or root in path.parents for root in roots)


def discovered_mount_roots(roots):
    if not roots:
        return []

    mounts = []
    ignored_prefixes = (
        "/dev",
        "/proc",
        "/run/docker",
        "/sys",
        "/var/lib/containerd",
        "/var/lib/docker",
    )
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        source, target, fstype = parts[:3]
        if not source.startswith("/dev/"):
            continue
        if fstype in {"autofs", "devtmpfs", "overlay", "proc", "sysfs", "tmpfs"}:
            continue
        if target == "/" or target.startswith(ignored_prefixes):
            continue
        try:
            mount = Path(target.replace("\\040", " ")).resolve()
        except OSError:
            continue
        if mount.exists() and path_is_allowed(mount, roots):
            mounts.append(mount)
    return mounts


def file_sidebar_roots():
    roots = allowed_roots()
    combined = []
    seen = set()
    for root in roots + discovered_mount_roots(roots):
        key = str(root)
        if key not in seen:
            seen.add(key)
            combined.append(root)
    return combined


def lsblk_payload():
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,PATH,TYPE,TRAN,FSTYPE,LABEL,MOUNTPOINTS,SIZE,MODEL"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def normalized_mountpoints(node):
    mountpoints = node.get("mountpoints") or []
    if isinstance(mountpoints, str):
        mountpoints = [mountpoints]
    return [str(item) for item in mountpoints if item]


def iter_block_nodes(payload):
    def visit(node, parent_disk=None):
        disk = node if node.get("type") == "disk" else parent_disk
        yield node, disk
        for child in node.get("children") or []:
            yield from visit(child, disk)

    for device in payload.get("blockdevices") or []:
        yield from visit(device)


def block_node_by_path(device_path):
    clean_path = str(device_path or "").strip()
    if not re.fullmatch(r"/dev/[A-Za-z0-9_./+-]+", clean_path):
        raise ValueError("Invalid block device path")
    payload = lsblk_payload()
    for node, disk in iter_block_nodes(payload):
        if node.get("path") == clean_path:
            return node, disk or node
    raise FileNotFoundError("Block device was not found")


def homestart_mountpoint(device_path):
    name = Path(device_path).name
    safe_name = re.sub(r"[^A-Za-z0-9_.+-]+", "-", name).strip("-")
    if not safe_name:
        raise ValueError("Invalid block device name")
    return FILE_MOUNT_ROOT / safe_name


def mountpoint_allowed(path):
    roots = allowed_roots()
    return bool(roots) and path_is_allowed(path, roots)


def mount_block_device_readonly(device_path):
    ensure_file_mounts_enabled()
    node, _disk = block_node_by_path(device_path)
    device_type = node.get("type") or ""
    filesystem = node.get("fstype") or ""
    if device_type not in {"part", "lvm", "crypt", "rom"}:
        raise ValueError("Only partitions and volumes can be mounted from HomeStart")
    if not filesystem:
        raise ValueError("The selected device does not expose a filesystem")
    mounts = normalized_mountpoints(node)
    if mounts:
        mount = Path(mounts[0]).resolve()
        if not mountpoint_allowed(mount):
            raise PermissionError("Mounted path is outside the allowed file roots")
        return {"ok": True, "action": "mount_readonly", "path": str(mount), "already_mounted": True}

    target = homestart_mountpoint(device_path).resolve()
    if not mountpoint_allowed(target):
        raise PermissionError("HomeStart mount path is outside the allowed file roots")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(exist_ok=True)
    if target.is_symlink():
        raise PermissionError("Mount point cannot be a symlink")
    if os.path.ismount(target):
        return {"ok": True, "action": "mount_readonly", "path": str(target), "already_mounted": True}

    options = "ro,nosuid,nodev,noexec"
    command = ["mount", "-o", options, str(device_path), str(target)]
    try:
        subprocess.check_output(command, text=True, timeout=20, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        output = (error.output or "").strip()
        raise ValueError(output or "Could not mount the device read-only") from error
    return {"ok": True, "action": "mount_readonly", "path": str(target), "readonly": True}


def unmount_homestart_device(device_path):
    ensure_file_mounts_enabled()
    node, _disk = block_node_by_path(device_path)
    target = homestart_mountpoint(device_path).resolve()
    mounts = [Path(item).resolve() for item in normalized_mountpoints(node)]
    if target not in mounts and not os.path.ismount(target):
        raise ValueError("This device is not mounted by HomeStart")
    if not path_is_allowed(target, [FILE_MOUNT_ROOT.resolve()]):
        raise PermissionError("Only HomeStart-managed mounts can be unmounted here")
    try:
        subprocess.check_output(["umount", str(target)], text=True, timeout=15, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        output = (error.output or "").strip()
        raise ValueError(output or "Could not unmount the device") from error
    try:
        target.rmdir()
    except OSError:
        pass
    return {"ok": True, "action": "unmount", "path": str(target)}


def block_mount_metadata():
    metadata = {}
    payload = lsblk_payload()
    if not payload:
        return metadata

    def visit(node, parent_disk=None):
        device_type = node.get("type") or ""
        disk = node if device_type == "disk" else parent_disk
        for mountpoint in normalized_mountpoints(node):
            try:
                mount = str(Path(mountpoint).resolve())
            except OSError:
                mount = str(mountpoint)
            disk_info = disk or node
            transport = disk_info.get("tran") or node.get("tran") or ""
            metadata[mount] = {
                "device": node.get("path") or node.get("name") or "",
                "disk": disk_info.get("path") or disk_info.get("name") or "",
                "filesystem": node.get("fstype") or "",
                "label": node.get("label") or disk_info.get("label") or "",
                "model": disk_info.get("model") or "",
                "size": node.get("size") or disk_info.get("size") or "",
                "transport": transport,
                "kind": "usb" if str(transport).lower() == "usb" else "disk",
            }
        for child in node.get("children") or []:
            visit(child, disk)

    for device in payload.get("blockdevices") or []:
        visit(device)
    return metadata


def physical_drive_entries():
    payload = lsblk_payload()
    roots = allowed_roots()
    entries = []

    def location_payload(node, disk, depth=0):
        mounts = []
        for mountpoint in normalized_mountpoints(node):
            try:
                mount = str(Path(mountpoint).resolve())
            except OSError:
                mount = mountpoint
            mounts.append(
                {
                    "path": mount,
                    "allowed": path_is_allowed(Path(mount), roots),
                }
            )
        transport = disk.get("tran") or node.get("tran") or ""
        device_path = node.get("path") or ""
        mount_target = homestart_mountpoint(device_path) if device_path else None
        mounted_by_homestart = any(
            path_is_allowed(Path(mount["path"]).resolve(), [FILE_MOUNT_ROOT.resolve()])
            for mount in mounts
        )
        can_mount = (
            file_mounts_enabled()
            and device_path
            and node.get("type") in {"part", "lvm", "crypt", "rom"}
            and bool(node.get("fstype"))
            and not mounts
            and mount_target is not None
            and mountpoint_allowed(mount_target.resolve())
        )
        return {
            "name": node.get("name") or node.get("path") or "",
            "path": device_path,
            "type": node.get("type") or "",
            "kind": "usb" if str(transport).lower() == "usb" else "disk",
            "transport": transport,
            "filesystem": node.get("fstype") or "",
            "label": node.get("label") or "",
            "size": node.get("size") or "",
            "model": node.get("model") or "",
            "mountpoints": mounts,
            "mount_target": str(mount_target) if mount_target else "",
            "can_mount": bool(can_mount),
            "can_unmount": bool(mounted_by_homestart),
            "mounted_by_homestart": bool(mounted_by_homestart),
            "depth": depth,
        }

    def visit_children(node, disk, depth):
        children = []
        for child in node.get("children") or []:
            item = location_payload(child, disk, depth)
            item["children"] = visit_children(child, disk, depth + 1)
            children.append(item)
        return children

    for disk in payload.get("blockdevices") or []:
        if disk.get("type") != "disk":
            continue
        item = location_payload(disk, disk, 0)
        item["children"] = visit_children(disk, disk, 1)
        entries.append(item)
    return entries


def file_sidebar_items():
    roots = file_sidebar_roots()
    disk_metadata = block_mount_metadata()
    items = []
    for root in roots:
        root_path = str(root)
        meta = disk_metadata.get(root_path, {})
        name = meta.get("label") or ("Root" if root_path == "/" else Path(root_path).name or root_path)
        kind = meta.get("kind") or ("root" if root_path == "/" else "folder")
        items.append(
            {
                "path": root_path,
                "name": name,
                "kind": kind,
                "device": meta.get("device", ""),
                "disk": meta.get("disk", ""),
                "filesystem": meta.get("filesystem", ""),
                "label": meta.get("label", ""),
                "model": meta.get("model", ""),
                "size": meta.get("size", ""),
                "transport": meta.get("transport", ""),
            }
        )
    return items


def resolve_file_path(raw_path):
    roots = allowed_roots()
    if not roots:
        raise FileNotFoundError("No file browser roots are available")

    if not raw_path:
        return None

    candidate = Path(raw_path).expanduser().resolve()
    for root in roots:
        if path_is_allowed(candidate, [root]):
            return candidate
    raise PermissionError("Path is outside the allowed roots")


def file_listing(raw_path):
    roots = allowed_roots()
    sidebar_items = file_sidebar_items()
    target = resolve_file_path(raw_path)

    if target is None:
        return {
            "path": "",
            "parent": "",
            "roots": [item["path"] for item in sidebar_items],
            "root_entries": sidebar_items,
            "drive_entries": physical_drive_entries(),
            "entries": [
                {
                    "name": item["path"],
                    "path": item["path"],
                    "type": "directory",
                    "kind": item["kind"],
                    "size": item.get("size", ""),
                    "size_bytes": 0,
                    "modified": int(Path(item["path"]).stat().st_mtime),
                }
                for item in sidebar_items
            ],
        }

    if not target.exists():
        raise FileNotFoundError("The path does not exist")
    if not target.is_dir():
        raise NotADirectoryError("The path is not a folder")

    entries = []
    for item in sorted(target.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower())):
        try:
            stat = item.stat()
        except OSError:
            continue

        entries.append(
            {
                "name": item.name,
                "path": str(item),
                "type": "directory" if item.is_dir() else "file",
                "kind": file_kind(item),
                "size": "" if item.is_dir() else format_bytes(stat.st_size),
                "size_bytes": 0 if item.is_dir() else stat.st_size,
                "modified": int(stat.st_mtime),
            }
        )

    parent = ""
    for root in roots:
        if target != root and (target == root or root in target.parents):
            parent = str(target.parent)
            break

    return {
        "path": str(target),
        "parent": parent,
        "roots": [item["path"] for item in sidebar_items],
        "root_entries": sidebar_items,
        "drive_entries": physical_drive_entries(),
        "entries": entries,
    }


def file_operations_enabled():
    return load_config_file().get("features", {}).get("file_operations", True)


def ensure_file_operations_enabled():
    if not file_operations_enabled():
        raise PermissionError("File operations are disabled")


def file_mounts_enabled():
    features = load_config_file().get("features", {})
    return features.get("file_operations", True) and features.get("file_mounts", True)


def ensure_file_mounts_enabled():
    if not file_mounts_enabled():
        raise PermissionError("File disk mounting is disabled")


def resolve_new_child(parent_path, name):
    parent = resolve_file_path(parent_path)
    if parent is None:
        raise FileNotFoundError("Select a folder first")
    if not parent.exists() or not parent.is_dir():
        raise NotADirectoryError("Parent path is not a folder")

    clean_name = str(name or "").strip()
    if not clean_name or clean_name in {".", ".."}:
        raise ValueError("Name is required")
    if any(separator in clean_name for separator in {"/", "\\"}):
        raise ValueError("Name cannot contain path separators")

    target = (parent / clean_name).resolve()
    resolve_file_path(str(target))
    return target


def create_folder(parent_path, name):
    ensure_file_operations_enabled()
    target = resolve_new_child(parent_path, name)
    if target.exists():
        raise FileExistsError("A file or folder with that name already exists")
    target.mkdir()
    inherit_parent_ownership(target)
    return {"ok": True, "path": str(target), "action": "mkdir"}


def inherit_parent_ownership(path):
    """Avoid root-owned browser content when HomeStart runs as a system service."""
    try:
        parent_stat = path.parent.stat()
        os.chown(path, parent_stat.st_uid, parent_stat.st_gid)
    except (OSError, PermissionError):
        pass


def delete_file_path(raw_path):
    ensure_file_operations_enabled()
    target = resolve_file_path(raw_path)
    if target is None:
        raise ValueError("Path is required")
    roots = allowed_roots()
    if any(target == root for root in roots):
        raise PermissionError("Allowed roots cannot be deleted")
    if not target.exists():
        raise FileNotFoundError("The path does not exist")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"ok": True, "path": str(target), "action": "delete"}


def path_usage(path, cancelled=None):
    total_bytes = 0
    file_count = 0
    folder_count = 0
    if cancelled and cancelled():
        raise CopyCancelled()
    if path.is_file():
        return path.stat().st_size, 1, 0
    for root, directories, files in os.walk(path, followlinks=False):
        if cancelled and cancelled():
            raise CopyCancelled()
        folder_count += 1
        for name in files:
            if cancelled and cancelled():
                raise CopyCancelled()
            item = Path(root) / name
            try:
                total_bytes += item.stat().st_size
                file_count += 1
            except OSError:
                continue
        for name in list(directories):
            item = Path(root) / name
            if item.is_symlink():
                try:
                    total_bytes += item.stat().st_size
                    file_count += 1
                except OSError:
                    pass
    return total_bytes, file_count, folder_count


def file_properties(raw_path):
    target = resolve_file_path(raw_path)
    if target is None:
        raise ValueError("Path is required")
    if not target.exists():
        raise FileNotFoundError("The path does not exist")
    stat = target.stat()
    total_bytes, file_count, folder_count = path_usage(target)
    return {
        "ok": True,
        "name": target.name or str(target),
        "path": str(target),
        "type": "directory" if target.is_dir() else "file",
        "kind": file_kind(target),
        "size_bytes": total_bytes,
        "size": format_bytes(total_bytes),
        "file_count": file_count,
        "folder_count": folder_count,
        "modified": int(stat.st_mtime),
        "permissions": oct(stat.st_mode & 0o777),
        "owner_uid": stat.st_uid,
        "group_gid": stat.st_gid,
    }


def resolve_copy_target(source_path, destination_path):
    source = resolve_file_path(source_path)
    destination = resolve_file_path(destination_path)
    if source is None or destination is None:
        raise ValueError("Source and destination are required")
    if not source.exists():
        raise FileNotFoundError("The source path does not exist")

    target = destination / source.name if destination.exists() and destination.is_dir() else destination
    if target.exists():
        stem = source.stem if source.is_file() else source.name
        suffix = source.suffix if source.is_file() else ""
        counter = 1
        while target.exists():
            label = "copy" if counter == 1 else f"copy {counter}"
            target = target.with_name(f"{stem} - {label}{suffix}")
            counter += 1
    resolve_file_path(str(target))
    if source.resolve() == target.resolve():
        raise ValueError("Source and destination are the same")
    if source.is_dir() and (target == source or source in target.parents):
        raise ValueError("A folder cannot be copied into itself")
    if target.exists():
        raise FileExistsError("The destination already exists")
    if not target.parent.exists() or not target.parent.is_dir():
        raise NotADirectoryError("Destination parent folder does not exist")
    return source, target


def copy_file_path(source_path, destination_path):
    ensure_file_operations_enabled()
    source, target = resolve_copy_target(source_path, destination_path)

    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)
    return {"ok": True, "path": str(target), "action": "copy", "message": f"Pasted as {target.name}"}


def copy_manager():
    global COPY_MANAGER
    if COPY_MANAGER is None:
        COPY_MANAGER = CopyManager(FILE_COPY_JOBS, FILE_COPY_JOBS_LOCK, path_usage)
    return COPY_MANAGER


def update_copy_job(job_id, **changes):
    return copy_manager().update_job(job_id, **changes)


def copy_job_cancelled(job_id):
    return copy_manager().cancelled(job_id)


def native_cp_path():
    return copy_manager().native_cp_path()


def native_cp_command(path, source, target):
    return CopyManager.native_cp_command(path, source, target)


def process_copy_bytes(pid):
    return CopyManager.process_copy_bytes(pid)


def native_copy_progress(process, source, target, total_bytes):
    return copy_manager().native_copy_progress(process, source, target, total_bytes)


def stop_native_copy(process):
    return CopyManager.stop_native_copy(process)


def run_native_copy(source, target, job_id, total_bytes):
    return copy_manager().run_native_copy(source, target, job_id, total_bytes)


def remove_incomplete_copy(target):
    return CopyManager.remove_incomplete(target)


def copy_file_with_progress(source, target, job_id):
    return copy_manager().copy_with_progress(source, target, job_id)


def start_copy_job(source_path, destination_path):
    ensure_file_operations_enabled()
    source, target = resolve_copy_target(source_path, destination_path)
    return copy_manager().start(source, target)


def copy_job_status(job_id):
    return copy_manager().status(job_id)


def cancel_copy_job(job_id):
    return copy_manager().cancel(job_id)


def decode_data_url(content):
    value = str(content or "")
    if "," in value and value.startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid upload encoding") from error


def upload_file(parent_path, name, content):
    ensure_file_operations_enabled()
    target = resolve_new_child(parent_path, name)
    if target.exists():
        raise FileExistsError("A file or folder with that name already exists")
    payload = decode_data_url(content)
    if len(payload) > 100 * 1024 * 1024:
        raise ValueError("Uploaded file is too large")
    target.write_bytes(payload)
    inherit_parent_ownership(target)
    return {
        "ok": True,
        "path": str(target),
        "action": "upload",
        "size": len(payload),
    }


def file_action(payload):
    action = payload.get("action", "")
    if action == "mkdir":
        return create_folder(payload.get("parent", ""), payload.get("name", ""))
    if action == "delete":
        return trash_file_path(payload.get("path", ""))
    if action == "rename":
        return rename_file_path(payload.get("path", ""), payload.get("name", ""))
    if action == "copy":
        return copy_file_path(payload.get("source", ""), payload.get("destination", ""))
    if action == "copy_start":
        return start_copy_job(payload.get("source", ""), payload.get("destination", ""))
    if action == "copy_cancel":
        return cancel_copy_job(payload.get("job_id", ""))
    if action == "upload":
        return upload_file(payload.get("parent", ""), payload.get("name", ""), payload.get("content", ""))
    if action == "mount_readonly":
        return mount_block_device_readonly(payload.get("device", ""))
    if action == "unmount":
        return unmount_homestart_device(payload.get("device", ""))
    raise ValueError("Invalid file action")


def samba_manager_enabled():
    return load_config_file().get("features", {}).get("samba_manager", True)


def ensure_samba_manager_enabled():
    if not samba_manager_enabled():
        raise PermissionError("Samba Share Manager is disabled")


def parse_samba_config(content):
    sections = {}
    current = None
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        match = re.fullmatch(r"\[([^\]]+)\]", line)
        if match:
            current = match.group(1).strip()
            sections[current] = {}
            continue
        if current and "=" in line:
            key, value = line.split("=", 1)
            sections[current][key.strip().lower()] = value.strip()
    return sections


def samba_user_tokens(value):
    return [item for item in re.split(r"[\s,]+", str(value or "").strip()) if item]


def samba_users():
    try:
        output = subprocess.check_output(
            ["pdbedit", "-L"], text=True, timeout=8, stderr=subprocess.DEVNULL
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    users = []
    for line in output.splitlines():
        name, separator, description = line.partition(":")
        if separator and name.strip():
            users.append({"name": name.strip(), "description": description.rsplit(":", 1)[-1].strip()})
    return sorted(users, key=lambda item: item["name"].lower())


def samba_testparm(config_path=SAMBA_CONFIG_PATH):
    try:
        return subprocess.check_output(
            ["testparm", "-s", str(config_path)],
            text=True, timeout=10, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as error:
        raise FileNotFoundError("Samba testparm is not installed") from error
    except subprocess.CalledProcessError as error:
        raise ValueError("Samba configuration validation failed") from error


def samba_state():
    state = load_json_file(SAMBA_STATE_PATH, {"shares": {}, "disabled": []})
    state.setdefault("shares", {})
    state.setdefault("disabled", [])
    return state


def samba_share_payload(name, values, state):
    path = values.get("path", "")
    valid_users = samba_user_tokens(values.get("valid users", ""))
    write_users = samba_user_tokens(values.get("write list", ""))
    read_users = samba_user_tokens(values.get("read list", ""))
    return {
        "name": name,
        "path": path,
        "enabled": str(values.get("available", "yes")).lower() not in {"no", "false", "0"},
        "browseable": str(values.get("browseable", values.get("browsable", "yes"))).lower() not in {"no", "false", "0"},
        "read_only": str(values.get("read only", "yes")).lower() not in {"no", "false", "0"},
        "guest_ok": str(values.get("guest ok", "no")).lower() in {"yes", "true", "1"},
        "valid_users": valid_users,
        "write_users": write_users,
        "read_users": read_users,
        "force_user": values.get("force user", ""),
        "managed": name in state["shares"],
        "disabled_by_homestart": name in state["disabled"],
    }


def samba_shares_payload():
    ensure_samba_manager_enabled()
    if not SAMBA_CONFIG_PATH.exists():
        return {
            "ok": True, "available": False, "shares": [], "users": [],
            "message": f"Samba configuration was not found at {SAMBA_CONFIG_PATH}",
        }
    try:
        effective = parse_samba_config(samba_testparm())
    except FileNotFoundError as error:
        return {"ok": True, "available": False, "shares": [], "users": [], "message": str(error)}
    state = samba_state()
    ignored = {"global", "homes", "printers", "print$"}
    shares = [
        samba_share_payload(name, values, state)
        for name, values in effective.items()
        if name.lower() not in ignored and values.get("path")
    ]
    shares.sort(key=lambda item: item["name"].lower())
    return {
        "ok": True,
        "available": True,
        "shares": shares,
        "users": samba_users(),
        "passwords_readable": False,
        "message": "Samba passwords are stored as non-reversible hashes and cannot be displayed.",
    }


def validate_samba_share_name(name):
    clean = str(name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}", clean):
        raise ValueError("Share name contains unsupported characters")
    if clean.lower() in {"global", "homes", "printers", "print$"}:
        raise ValueError("This Samba share name is reserved")
    return clean


def render_homestart_samba_config(state):
    lines = [
        "# Managed by HomeStart. Runtime server data is not included in HomeStart releases.",
        "",
    ]
    for name, share in sorted(state["shares"].items(), key=lambda item: item[0].lower()):
        lines.extend([
            f"[{name}]",
            f"    path = {share['path']}",
            f"    available = {'no' if name in state['disabled'] else 'yes'}",
            f"    browseable = {'yes' if share.get('browseable', True) else 'no'}",
            f"    read only = {'yes' if share.get('read_only', True) else 'no'}",
            f"    guest ok = {'yes' if share.get('guest_ok', False) else 'no'}",
        ])
        users = share.get("valid_users") or []
        if users:
            lines.append(f"    valid users = {' '.join(users)}")
        if share.get("force_user"):
            lines.extend([
                f"    force user = {share['force_user']}",
                "    create mask = 0664",
                "    directory mask = 0775",
                "    force create mode = 0660",
                "    force directory mode = 0770",
            ])
        lines.extend(["", ""])
    for name in sorted(set(state["disabled"]), key=str.lower):
        if name not in state["shares"]:
            lines.extend([f"[{name}]", "    available = no", "", ""])
    return "\n".join(lines).rstrip() + "\n"


def samba_config_with_include(content):
    include_line = f"    include = {SAMBA_MANAGED_PATH}"
    if re.search(rf"(?im)^\s*include\s*=\s*{re.escape(str(SAMBA_MANAGED_PATH))}\s*$", content):
        return content
    match = re.search(r"(?im)^\s*\[global\]\s*$", content)
    if not match:
        raise ValueError("Samba configuration does not contain a [global] section")
    position = match.end()
    return content[:position] + "\n" + include_line + content[position:]


def reload_samba():
    commands = [
        ["smbcontrol", "all", "reload-config"],
        ["systemctl", "reload", "smbd"],
        ["systemctl", "reload", "smb"],
    ]
    for command in commands:
        try:
            subprocess.check_output(command, text=True, timeout=15, stderr=subprocess.STDOUT)
            return
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    raise ValueError("The Samba configuration is valid, but Samba could not be reloaded")


def save_samba_state(new_state):
    ensure_samba_manager_enabled()
    original_main = SAMBA_CONFIG_PATH.read_text(encoding="utf-8")
    original_managed = SAMBA_MANAGED_PATH.read_text(encoding="utf-8") if SAMBA_MANAGED_PATH.exists() else None
    new_main = samba_config_with_include(original_main)
    SAMBA_MANAGED_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        SAMBA_CONFIG_PATH.write_text(new_main, encoding="utf-8")
        SAMBA_MANAGED_PATH.write_text(render_homestart_samba_config(new_state), encoding="utf-8")
        samba_testparm()
        reload_samba()
        SAMBA_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = SAMBA_STATE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(new_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(SAMBA_STATE_PATH)
    except Exception:
        SAMBA_CONFIG_PATH.write_text(original_main, encoding="utf-8")
        if original_managed is None:
            try:
                SAMBA_MANAGED_PATH.unlink()
            except FileNotFoundError:
                pass
        else:
            SAMBA_MANAGED_PATH.write_text(original_managed, encoding="utf-8")
        try:
            reload_samba()
        except (ValueError, OSError):
            pass
        raise
    return samba_shares_payload()


def samba_share_action(payload):
    ensure_samba_manager_enabled()
    action = str(payload.get("action") or "")
    if action == "set_password":
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}", username):
            raise ValueError("Invalid Linux username")
        if not 4 <= len(password) <= 128:
            raise ValueError("Samba password must contain between 4 and 128 characters")
        try:
            subprocess.check_output(["id", "-u", username], text=True, timeout=5, stderr=subprocess.DEVNULL)
        except (FileNotFoundError, subprocess.SubprocessError) as error:
            raise ValueError("The user must already exist as a Linux account") from error
        try:
            subprocess.run(
                ["smbpasswd", "-s", "-a", username],
                input=f"{password}\n{password}\n",
                text=True, capture_output=True, check=True, timeout=12,
            )
        except FileNotFoundError as error:
            raise FileNotFoundError("smbpasswd is not installed") from error
        except subprocess.CalledProcessError as error:
            raise ValueError((error.stderr or "").strip() or "Could not update the Samba password") from error
        return samba_shares_payload()
    state = samba_state()
    if action in {"create", "update"}:
        name = validate_samba_share_name(payload.get("name"))
        if action == "update" and name not in state["shares"]:
            raise PermissionError("Only shares created by HomeStart can be edited")
        target = resolve_file_path(payload.get("path", ""))
        if target is None or not target.exists() or not target.is_dir():
            raise NotADirectoryError("Select an existing folder inside the allowed File Browser roots")
        current_names = {item["name"].lower() for item in samba_shares_payload().get("shares", [])}
        if action == "create" and name.lower() in current_names:
            raise FileExistsError("A Samba share with this name already exists")
        requested_users = payload.get("valid_users") or []
        if isinstance(requested_users, str):
            requested_users = samba_user_tokens(requested_users)
        known_users = {item["name"] for item in samba_users()}
        unknown = [user for user in requested_users if not user.startswith("@") and user not in known_users]
        if unknown:
            raise ValueError(f"Unknown Samba user: {', '.join(unknown)}")
        if not payload.get("guest_ok") and not requested_users:
            raise ValueError("Choose at least one Samba user or enable guest access")
        guest_ok = bool(payload.get("guest_ok", False))
        read_only = bool(payload.get("read_only", True))
        force_user = ""
        ownership_before = None
        if guest_ok and not read_only:
            force_user = str(payload.get("force_user") or "").strip()
            if not force_user:
                for candidate in (target, *target.parents):
                    try:
                        owner = pwd.getpwuid(candidate.stat().st_uid)
                    except (KeyError, OSError):
                        continue
                    if owner.pw_uid != 0:
                        force_user = owner.pw_name
                        break
                if not force_user:
                    raise ValueError("Could not find a non-root Linux owner; enter a Linux write user")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}", force_user):
                raise ValueError("Invalid Linux write user")
            try:
                uid = int(subprocess.check_output(
                    ["id", "-u", force_user], text=True, timeout=5, stderr=subprocess.DEVNULL
                ).strip())
            except (FileNotFoundError, subprocess.SubprocessError, ValueError) as error:
                raise ValueError("Guest write user must be an existing Linux account") from error
            if uid == 0:
                raise PermissionError("Guest shares cannot write as root; choose a non-root Linux user")
            target_stat = target.stat()
            if target_stat.st_uid != uid:
                ownership_before = (target_stat.st_uid, target_stat.st_gid)
                try:
                    os.chown(target, uid, -1)
                except OSError as error:
                    raise PermissionError(f"Could not grant folder ownership to {force_user}") from error
        state["shares"][name] = {
            "path": str(target),
            "browseable": bool(payload.get("browseable", True)),
            "read_only": read_only,
            "guest_ok": guest_ok,
            "valid_users": requested_users,
            "force_user": force_user,
        }
        state["disabled"] = [item for item in state["disabled"] if item != name]
        try:
            return save_samba_state(state)
        except Exception:
            if ownership_before:
                try:
                    os.chown(target, ownership_before[0], ownership_before[1])
                except OSError:
                    pass
            raise
    elif action in {"disable", "enable", "delete"}:
        name = validate_samba_share_name(payload.get("name"))
        if action == "disable":
            if name not in state["disabled"]:
                state["disabled"].append(name)
        elif action == "enable":
            state["disabled"] = [item for item in state["disabled"] if item != name]
        elif name in state["shares"]:
            del state["shares"][name]
            state["disabled"] = [item for item in state["disabled"] if item != name]
        else:
            raise PermissionError("Existing Samba shares can be disabled but not deleted by HomeStart")
    else:
        raise ValueError("Invalid Samba share action")
    return save_samba_state(state)


def trash_file_path(raw_path):
    ensure_file_operations_enabled()
    target = resolve_file_path(raw_path)
    if target is None or not target.exists():
        raise FileNotFoundError("The file does not exist")
    if any(target == root for root in allowed_roots()):
        raise PermissionError("Allowed roots cannot be moved to trash")
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    destination = TRASH_DIR / f"{int(time.time())}-{uuid.uuid4().hex[:8]}-{target.name}"
    index = load_json_file(TRASH_INDEX, {})
    index[destination.name] = {"original": str(target), "name": target.name, "deleted_at": int(time.time())}
    shutil.move(str(target), destination)
    save_trash_index(index)
    return {"ok": True, "message": f"Moved {target.name} to HomeStart trash", "trash_path": str(destination)}


def trash_path_size(path):
    try:
        if path.is_file() or path.is_symlink():
            return path.lstat().st_size
        total = 0
        for root, _directories, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(root) / name).lstat().st_size
                except OSError:
                    continue
        return total
    except OSError:
        return 0


def save_trash_index(index):
    TRASH_INDEX.parent.mkdir(parents=True, exist_ok=True)
    temporary = TRASH_INDEX.with_suffix(".tmp")
    temporary.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(TRASH_INDEX)


def resolve_trash_item(key):
    raw_key = str(key or "")
    clean_key = Path(raw_key).name
    if clean_key != raw_key or clean_key in {"", ".", ".."}:
        raise ValueError("Invalid trash item")
    root = TRASH_DIR.resolve()
    path = root / clean_key
    if path.parent != root:
        raise ValueError("Invalid trash item")
    return clean_key, path


def delete_trash_item(key):
    key, path = resolve_trash_item(key)
    index = load_json_file(TRASH_INDEX, {})
    if key not in index or not path.exists():
        raise FileNotFoundError("Trash item not found")
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    index.pop(key, None)
    save_trash_index(index)
    return {"ok": True, "deleted": key}


def empty_trash():
    index = load_json_file(TRASH_INDEX, {})
    deleted = 0
    for key in list(index):
        try:
            delete_trash_item(key)
            deleted += 1
        except FileNotFoundError:
            index.pop(key, None)
    save_trash_index({})
    return {"ok": True, "deleted": deleted}


def cleanup_expired_trash(force=False):
    global TRASH_LAST_CLEANUP
    now = time.time()
    if not force and now - TRASH_LAST_CLEANUP < 3600:
        return 0
    TRASH_LAST_CLEANUP = now
    retention = int(load_config_file().get("trash", {}).get("retention_days", 0) or 0)
    if retention <= 0:
        return 0
    cutoff = now - retention * 86400
    index = load_json_file(TRASH_INDEX, {})
    expired = [key for key, item in index.items() if float(item.get("deleted_at", 0)) < cutoff]
    deleted = 0
    for key in expired:
        try:
            delete_trash_item(key)
            deleted += 1
        except FileNotFoundError:
            continue
    return deleted


def trash_listing():
    cleanup_expired_trash(force=True)
    index = load_json_file(TRASH_INDEX, {})
    items = []
    total_size = 0
    for key, metadata in index.items():
        path = TRASH_DIR / key
        if path.exists():
            size = trash_path_size(path)
            total_size += size
            items.append({"key": key, **metadata, "size": size, "type": "directory" if path.is_dir() else "file"})
    return {
        "ok": True,
        "items": sorted(items, key=lambda item: item.get("deleted_at", 0), reverse=True),
        "total_size": total_size,
        "retention_days": int(load_config_file().get("trash", {}).get("retention_days", 0) or 0),
    }


def restore_trash_item(key):
    key, source = resolve_trash_item(key)
    index = load_json_file(TRASH_INDEX, {})
    metadata = index.get(key)
    if not metadata or not source.exists():
        raise FileNotFoundError("Trash item not found")
    destination = resolve_file_path(metadata["original"])
    if destination.exists():
        destination = destination.with_name(f"{destination.stem}-restored{destination.suffix}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), destination)
    index.pop(key, None)
    save_trash_index(index)
    return {"ok": True, "path": str(destination)}


def rename_file_path(raw_path, raw_name):
    ensure_file_operations_enabled()
    target = resolve_file_path(raw_path)
    name = Path(str(raw_name or "")).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("Invalid name")
    destination = target.with_name(name)
    resolve_file_path(str(destination))
    if destination.exists():
        raise FileExistsError("A file with that name already exists")
    target.rename(destination)
    return {"ok": True, "path": str(destination)}


def serve_file(handler, raw_path, include_body=True):
    target = resolve_file_path(raw_path)
    if target is None:
        raise FileNotFoundError("No file was provided")
    if not target.exists():
        raise FileNotFoundError("The file does not exist")
    if not target.is_file():
        raise IsADirectoryError("The path is not a file")

    content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    disposition = "inline"
    stat = target.stat()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(stat.st_size))
    handler.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(target.name)}")
    handler.end_headers()

    if include_body:
        with target.open("rb") as file:
            shutil.copyfileobj(file, handler.wfile)


def disk_payload():
    try:
        output = subprocess.check_output(
            [
                "lsblk",
                "-J",
                "-b",
                "-o",
                "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL,TRAN",
            ],
            text=True,
            timeout=3,
        )
        devices = json.loads(output).get("blockdevices", [])
    except (json.JSONDecodeError, subprocess.SubprocessError, FileNotFoundError):
        return []

    disks = []
    for device in devices:
        if device.get("type") != "disk":
            continue

        mountpoints = []
        filesystems = []
        used_total = 0
        mounted_total = 0
        seen_mounts = set()
        for child in device.get("children", []):
            if child.get("fstype"):
                filesystems.append(child["fstype"])

            child_mounts = [
                mountpoint
                for mountpoint in (child.get("mountpoints") or [])
                if mountpoint and mountpoint not in seen_mounts
            ]
            mountpoints.extend(child_mounts)
            seen_mounts.update(child_mounts)
            if not child_mounts:
                continue

            try:
                usage = shutil.disk_usage(child_mounts[0])
            except OSError:
                continue

            used_total += usage.used
            mounted_total += usage.total

        disk_size = int(device.get("size") or 0)
        percent = used_total / mounted_total * 100 if mounted_total else 0
        disks.append(
            {
                "name": device.get("name", ""),
                "device": f"/dev/{device.get('name', '')}",
                "model": (device.get("model") or "").strip(),
                "serial": device.get("serial") or "",
                "transport": device.get("tran") or "",
                "filesystems": sorted(set(filesystems)),
                "mountpoints": mountpoints,
                "mountpoint": ", ".join(mountpoints) if mountpoints else "Not mounted",
                "used": used_total,
                "total": disk_size,
                "mounted_total": mounted_total,
                "free": max(0, mounted_total - used_total),
                "used_label": format_bytes(used_total),
                "total_label": format_bytes(disk_size),
                "free_label": format_bytes(max(0, mounted_total - used_total)),
                "percent": clamp_percent(percent),
            }
        )

    return sorted(disks, key=lambda disk: disk["device"])


def service_status(unit):
    try:
        output = subprocess.check_output(
            [
                "systemctl",
                "show",
                unit,
                "--property=Id,Description,LoadState,ActiveState,SubState",
                "--no-page",
            ],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.SubprocessError:
        return None

    data = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value

    if data.get("LoadState") == "not-found":
        return None

    return {
        "name": data.get("Id", unit),
        "description": data.get("Description", unit),
        "active": data.get("ActiveState", "unknown"),
        "sub": data.get("SubState", "unknown"),
    }


def status_payload():
    host = local_ip()
    services = load_config_file().get("services", [])
    return {
        "disks": disk_payload(),
        "services": [service for unit in services if (service := service_status(unit))],
        "containers": docker_apps(host),
    }


def normalize_docker_name(name):
    docker_name = str(name or "").strip().lstrip("/")
    if not re.match(r"^[A-Za-z0-9_.-]+$", docker_name):
        raise ValueError("Invalid container name")
    return docker_name


def run_docker_command(command, timeout=60):
    try:
        return subprocess.check_output(
            ["docker", *command],
            text=True,
            timeout=timeout,
            stderr=subprocess.STDOUT,
        ).strip()
    except FileNotFoundError as error:
        raise ValueError("Docker is not installed") from error
    except subprocess.CalledProcessError as error:
        output = (error.output or "").strip()
        raise ValueError(output or "Docker command failed") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("Docker command timed out") from error


def docker_logs(name, tail=300):
    name = normalize_docker_name(name)
    try:
        tail = max(20, min(2000, int(tail)))
    except (TypeError, ValueError):
        tail = 300
    return {"ok": True, "name": name, "logs": run_docker_command(["logs", "--tail", str(tail), "--timestamps", name], timeout=15)}


def create_backup(destination=None):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if destination is None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        destination = BACKUP_DIR / f"homestart-backup-{stamp}.tar.gz"
    else:
        destination = Path(destination)
    with tarfile.open(destination, "w:gz") as archive:
        if CONFIG_PATH.exists():
            archive.add(CONFIG_PATH, arcname="config.json")
        if DB_PATH.exists():
            archive.add(DB_PATH, arcname="data/homestart.db")
        if APP_ICON_DIR.exists():
            archive.add(APP_ICON_DIR, arcname="data/app-icons")
        if APP_ICON_INDEX.exists():
            archive.add(APP_ICON_INDEX, arcname="data/app-icons.json")
    return {"ok": True, "name": destination.name, "size": destination.stat().st_size, "created_at": int(destination.stat().st_mtime)}


def serve_backup_download(handler):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"homestart-backup-{stamp}.tar.gz"
    with tempfile.NamedTemporaryFile(prefix="homestart-backup-", suffix=".tar.gz", delete=False) as temporary:
        destination = Path(temporary.name)
    try:
        create_backup(destination)
        size = destination.stat().st_size
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "application/gzip")
        handler.send_header("Content-Disposition", f"attachment; filename={filename}")
        handler.send_header("Content-Length", str(size))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        with destination.open("rb") as source:
            shutil.copyfileobj(source, handler.wfile)
    finally:
        destination.unlink(missing_ok=True)


def list_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = [{"name": item.name, "size": item.stat().st_size, "created_at": int(item.stat().st_mtime)} for item in BACKUP_DIR.glob("homestart-backup-*.tar.gz")]
    return {"ok": True, "backups": sorted(items, key=lambda item: item["created_at"], reverse=True)}


def backup_path(name):
    clean = Path(str(name or "")).name
    target = BACKUP_DIR / clean
    if not clean.startswith("homestart-backup-") or not clean.endswith(".tar.gz") or not target.is_file():
        raise FileNotFoundError("Backup not found")
    return target


def safe_extract_tar(archive, destination):
    destination = destination.resolve()
    for member in archive.getmembers():
        member_path = (destination / member.name).resolve()
        if destination != member_path and destination not in member_path.parents:
            raise ValueError("Backup contains an invalid path")
        if member.issym() or member.islnk() or member.isdev():
            raise ValueError("Backup contains an unsupported entry")
    archive.extractall(destination)


def restore_backup(name):
    source = backup_path(name)
    create_backup()
    with tempfile.TemporaryDirectory(prefix="homestart-restore-") as directory:
        target = Path(directory)
        with tarfile.open(source, "r:gz") as archive:
            safe_extract_tar(archive, target)
        restored = []
        config = target / "config.json"
        if config.exists():
            save_config_file(json.loads(config.read_text(encoding="utf-8")))
            restored.append("config.json")
        database = target / "data/homestart.db"
        if database.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(database, DB_PATH)
            restored.append("data/homestart.db")
        icons = target / "data/app-icons"
        if icons.exists():
            if APP_ICON_DIR.exists():
                shutil.rmtree(APP_ICON_DIR)
            shutil.copytree(icons, APP_ICON_DIR)
            restored.append("data/app-icons")
        index = target / "data/app-icons.json"
        if index.exists():
            shutil.copy2(index, APP_ICON_INDEX)
            restored.append("data/app-icons.json")
    return {"ok": True, "restored": restored, "message": f"Restored {source.name}"}


def serve_download(handler, raw_path, include_body=True):
    target = resolve_file_path(raw_path)
    if target is None or not target.exists():
        raise FileNotFoundError("The path does not exist")
    temporary = None
    if target.is_dir():
        temporary = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        temporary.close()
        with zipfile.ZipFile(temporary.name, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in target.rglob("*"):
                if item.is_file():
                    archive.write(item, item.relative_to(target.parent))
        download = Path(temporary.name)
        filename = f"{target.name}.zip"
        content_type = "application/zip"
    else:
        download = target
        filename = target.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    try:
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(download.stat().st_size))
        handler.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
        handler.end_headers()
        if include_body:
            with download.open("rb") as file:
                shutil.copyfileobj(file, handler.wfile)
    finally:
        if temporary:
            Path(temporary.name).unlink(missing_ok=True)


def docker_container_exists(name):
    try:
        run_docker_command(["inspect", name], timeout=10)
        return True
    except ValueError:
        return False


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


def installed_docker_images():
    try:
        output = run_docker_command(["ps", "-a", "--format", "{{.Image}}\t{{.Names}}"], timeout=15)
    except ValueError:
        return {}
    installed = {}
    for line in output.splitlines():
        image, separator, name = line.partition("\t")
        repository = image_repository(image)
        if separator and repository:
            installed.setdefault(repository, []).append(name.strip())
    return installed


def curated_store_apps():
    installed = installed_docker_images()
    return [dict(item) for item in CURATED_APPS if image_repository(item.get("image")) not in installed]


STORE_PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
STORE_INPUT_TYPES = {"text", "port", "path", "select", "timezone"}
STORE_RESERVED_VALUES = {"homestart_data", "server_timezone"}
STORE_COMPOSE_KEYS = {"services", "volumes", "networks", "configs", "secrets"}


def store_placeholders(value):
    if isinstance(value, dict):
        result = set()
        for key, item in value.items():
            result.update(store_placeholders(key))
            result.update(store_placeholders(item))
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result.update(store_placeholders(item))
        return result
    return set(STORE_PLACEHOLDER.findall(value)) if isinstance(value, str) else set()


def validate_store_catalog(catalog):
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 1:
        raise ValueError("Unsupported app catalog schema")
    if not isinstance(catalog.get("apps"), list) or len(catalog["apps"]) > 500:
        raise ValueError("Invalid app catalog list")
    normalized = {
        "schema_version": 1,
        "catalog_version": str(catalog.get("catalog_version") or ""),
        "name": str(catalog.get("name") or "HomeStart Apps")[:120],
        "apps": [],
    }
    seen = set()
    for source in catalog["apps"]:
        if not isinstance(source, dict):
            raise ValueError("Invalid app catalog entry")
        app_id = str(source.get("id") or "")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", app_id) or app_id in seen:
            raise ValueError(f"Invalid or duplicate catalog app id: {app_id}")
        seen.add(app_id)
        inputs = source.get("inputs")
        compose = source.get("compose")
        if not isinstance(inputs, list) or len(inputs) > 32:
            raise ValueError(f"{app_id}: invalid inputs")
        if not isinstance(compose, dict) or set(compose) - STORE_COMPOSE_KEYS:
            raise ValueError(f"{app_id}: unsupported Compose section")
        services = compose.get("services")
        if not isinstance(services, dict) or not services or len(services) > 16:
            raise ValueError(f"{app_id}: Compose services are required")
        input_ids = set()
        clean_inputs = []
        for item in inputs:
            if not isinstance(item, dict):
                raise ValueError(f"{app_id}: invalid input")
            input_id = str(item.get("id") or "")
            input_type = str(item.get("type") or "")
            if not re.fullmatch(r"[a-z][a-z0-9_]*", input_id) or input_id in input_ids:
                raise ValueError(f"{app_id}: invalid or duplicate input")
            if input_type not in STORE_INPUT_TYPES or "default" not in item:
                raise ValueError(f"{app_id}: unsupported input {input_id}")
            label = str(item.get("label") or "").strip()
            if not label or len(label) > 100:
                raise ValueError(f"{app_id}: invalid label for {input_id}")
            clean = {"id": input_id, "label": label, "type": input_type, "default": item["default"]}
            if store_placeholders(item["default"]) - STORE_RESERVED_VALUES:
                raise ValueError(f"{app_id}: input defaults may only use reserved placeholders")
            if "help" in item:
                clean["help"] = str(item["help"])[:240]
            if "pattern" in item:
                pattern = str(item["pattern"])
                if len(pattern) > 160:
                    raise ValueError(f"{app_id}: input pattern is too long")
                try:
                    re.compile(pattern)
                except re.error as error:
                    raise ValueError(f"{app_id}: invalid input pattern") from error
                clean["pattern"] = pattern
            if input_type == "select":
                options = [str(value) for value in item.get("options", [])]
                if not options or len(options) > 50:
                    raise ValueError(f"{app_id}: select input needs options")
                clean["options"] = options
            input_ids.add(input_id)
            clean_inputs.append(clean)
        unknown = store_placeholders(compose) - input_ids - STORE_RESERVED_VALUES
        if unknown:
            raise ValueError(f"{app_id}: undeclared Compose placeholders")
        for service_name, service in services.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(service_name)) or not isinstance(service, dict):
                raise ValueError(f"{app_id}: invalid Compose service")
            if not isinstance(service.get("image"), str) or not service["image"].strip() or "build" in service:
                raise ValueError(f"{app_id}: every Compose service needs a fixed image")
        clean_app = {
            "id": app_id,
            "name": str(source.get("name") or app_id)[:120],
            "description": str(source.get("description") or "")[:500],
            "category": str(source.get("category") or "Other")[:80],
            "verified": bool(source.get("verified")),
            "verification_label": str(source.get("verification_label") or "")[:100],
            "icon_url": str(source.get("icon_url") or "")[:1000],
            "homepage": str(source.get("homepage") or "")[:1000],
            "page_url": str(source.get("page_url") or "")[:1000],
            "link_label": str(source.get("link_label") or "Project page")[:40],
            "inputs": clean_inputs,
            "compose": compose,
        }
        for url_field in ("icon_url", "homepage", "page_url"):
            url = clean_app[url_field]
            if url:
                parsed = urlparse(url)
                if parsed.scheme != "https" or not parsed.hostname:
                    raise ValueError(f"{app_id}: {url_field} must use HTTPS")
        normalized["apps"].append(clean_app)
    return normalized


def store_catalog_url():
    return str(load_config_file().get("app_store", {}).get("catalog_url") or STORE_CATALOG_URL).strip()


def read_store_catalog_cache():
    wrapper = load_json_file(STORE_CATALOG_CACHE, {})
    if not isinstance(wrapper.get("catalog"), dict):
        return None, 0
    try:
        return validate_store_catalog(wrapper["catalog"]), int(wrapper.get("fetched_at") or 0)
    except (TypeError, ValueError):
        return None, 0


def save_store_catalog_cache(catalog):
    STORE_CATALOG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STORE_CATALOG_CACHE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"fetched_at": int(time.time()), "catalog": catalog}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STORE_CATALOG_CACHE)


def fetch_store_catalog(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("The app catalog URL must use HTTPS")
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "HomeStart/1.0"})
    with urllib.request.urlopen(request, timeout=8) as response:
        if int(getattr(response, "status", 200)) != 200:
            raise ValueError("The app catalog server returned an error")
        payload = response.read(4_000_001)
    if len(payload) > 4_000_000:
        raise ValueError("The app catalog is too large")
    return validate_store_catalog(json.loads(payload.decode("utf-8")))


def load_store_catalog(refresh=False):
    with STORE_CATALOG_LOCK:
        cached, fetched_at = read_store_catalog_cache()
        if cached and not refresh and time.time() - fetched_at < STORE_CATALOG_TTL:
            return cached, {"source": "cache", "stale": False, "fetched_at": fetched_at}
        url = store_catalog_url()
        if url:
            try:
                catalog = fetch_store_catalog(url)
                save_store_catalog_cache(catalog)
                return catalog, {"source": "remote", "stale": False, "fetched_at": int(time.time())}
            except (ValueError, OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as error:
                if cached:
                    return cached, {
                        "source": "cache",
                        "stale": True,
                        "fetched_at": fetched_at,
                        "warning": f"Using the last valid catalog: {error}",
                    }
                return None, {"source": "builtin", "stale": True, "warning": str(error)}
        if cached:
            return cached, {"source": "cache", "stale": True, "fetched_at": fetched_at}
        return None, {"source": "builtin", "stale": True}


def replace_store_placeholders(value, values):
    if isinstance(value, dict):
        return {
            replace_store_placeholders(key, values): replace_store_placeholders(item, values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [replace_store_placeholders(item, values) for item in value]
    if not isinstance(value, str):
        return value
    return STORE_PLACEHOLDER.sub(lambda match: str(values[match.group(1)]), value)


def catalog_defaults(app):
    reserved = {
        "homestart_data": str(COMPOSE_APP_DATA_DIR),
        "server_timezone": system_timezone(),
    }
    result = []
    for item in app["inputs"]:
        clean = dict(item)
        clean["default"] = replace_store_placeholders(item["default"], reserved)
        result.append(clean)
    return result


def store_templates_payload(refresh=False):
    catalog, metadata = load_store_catalog(refresh)
    if catalog is None:
        return {"ok": True, "templates": curated_store_apps(), "catalog": metadata}
    installed = installed_docker_images()
    templates = []
    for app in catalog["apps"]:
        images = [
            image_repository(service.get("image"))
            for service in app["compose"]["services"].values()
            if service.get("image")
        ]
        if any(image in installed for image in images):
            continue
        first_service = next(iter(app["compose"]["services"].values()))
        templates.append({
            "name": app["name"],
            "image": first_service["image"],
            "description": app["description"],
            "category": app["category"],
            "verified": app["verified"],
            "verification_label": app["verification_label"],
            "icon_url": app["icon_url"],
            "page_url": app["page_url"] or app["homepage"],
            "link_label": app["link_label"],
            "template_id": app["id"],
            "install_method": "compose",
            "inputs": catalog_defaults(app),
        })
    return {
        "ok": True,
        "templates": templates,
        "catalog": {
            **metadata,
            "name": catalog["name"],
            "version": catalog["catalog_version"],
            "schema_version": catalog["schema_version"],
        },
    }


def store_catalog_app(template_id):
    template_id = str(template_id or "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", template_id):
        raise ValueError("Invalid app template")
    catalog, _ = load_store_catalog()
    if catalog is None:
        raise ValueError("The declarative app catalog is not available")
    for app in catalog["apps"]:
        if app["id"] == template_id:
            return app
    raise ValueError("App template not found")


def dockerhub_page_url(name, official=False):
    clean = str(name or "").strip()
    if official and "/" not in clean:
        return f"https://hub.docker.com/_/{quote(clean)}"
    return f"https://hub.docker.com/r/{quote(clean, safe='/')}"


def dockerhub_verification(name, official=False):
    if official:
        return {"verified": True, "verification_label": "Docker Official Image", "trusted_rank": 3}
    key = str(name or "").strip().lower()
    now = time.time()
    with DOCKERHUB_VERIFICATION_LOCK:
        cached = DOCKERHUB_VERIFICATION_CACHE.get(key)
        if cached and now - cached[0] < 21600:
            return dict(cached[1])
    result = {"verified": False, "verification_label": "", "trusted_rank": 0}
    try:
        request = urllib.request.Request(dockerhub_page_url(key), headers={"User-Agent": "HomeStart/1.0"})
        with urllib.request.urlopen(request, timeout=6) as response:
            page = response.read(1_500_000).decode("utf-8", errors="ignore")
        if "Verified Publisher" in page:
            result = {"verified": True, "verification_label": "Verified Publisher", "trusted_rank": 2}
        elif "Docker-Sponsored Open Source" in page:
            result = {"verified": True, "verification_label": "Docker-Sponsored Open Source", "trusted_rank": 1}
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    with DOCKERHUB_VERIFICATION_LOCK:
        DOCKERHUB_VERIFICATION_CACHE[key] = (now, result)
    return dict(result)


def add_dockerhub_verification(results):
    pending = [item for item in results if not item.get("official")]
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(pending)))) as executor:
        checks = list(executor.map(lambda item: dockerhub_verification(item.get("name")), pending))
    for item in results:
        if item.get("official"):
            item.update(dockerhub_verification(item.get("name"), True))
    for item, verification in zip(pending, checks):
        item.update(verification)
    return results


def docker_action(name, action):
    if not load_config_file().get("features", {}).get("docker_actions", True):
        raise ValueError("Docker actions are disabled")

    docker_name = normalize_docker_name(name)
    if action not in {"stop", "restart"}:
        raise ValueError("Invalid action")

    output = run_docker_command([action, docker_name], timeout=30)
    return {"ok": True, "container": docker_name, "action": action, "message": output}


def native_service_actions_enabled():
    return load_config_file().get("features", {}).get("native_service_actions", True)


def allowed_native_service_units():
    units = {definition.get("service", "") for definition in NATIVE_SERVICE_APP_DEFINITIONS}
    for app in load_config():
        if normalize_app_type(app.get("app_type") or app.get("type")) == "native":
            units.add(str(app.get("service_name") or "").strip())
    return {unit for unit in units if unit}


def normalize_service_unit(unit):
    unit = str(unit or "").strip()
    if not unit:
        raise ValueError("Service name is required")
    if not unit.endswith(".service"):
        unit = f"{unit}.service"
    if not re.match(r"^[A-Za-z0-9_.@:-]+\.service$", unit):
        raise ValueError("Invalid service name")
    if unit not in allowed_native_service_units():
        raise ValueError("This service is not allowed for HomeStart actions")
    return unit


def service_action(unit, action):
    if not native_service_actions_enabled():
        raise ValueError("Native service actions are disabled")
    if action not in {"stop", "restart"}:
        raise ValueError("Invalid action")

    unit = normalize_service_unit(unit)
    try:
        output = subprocess.check_output(
            ["systemctl", action, unit],
            text=True,
            timeout=30,
            stderr=subprocess.STDOUT,
        ).strip()
    except subprocess.CalledProcessError as error:
        raise ValueError((error.output or "").strip() or f"Could not {action} {unit}") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"Timed out trying to {action} {unit}") from error

    status = service_status(unit) or {}
    return {
        "ok": True,
        "service": unit,
        "action": action,
        "status": status,
        "message": output or f"{unit} {action} requested",
    }


def docker_app_store_enabled():
    features = load_config_file().get("features", {})
    return features.get("docker_app_store", True) and features.get("docker_actions", True)


def dockerhub_repository_from_url(value):
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"hub.docker.com", "www.hub.docker.com"}:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "r":
        repository = "/".join(parts[1:3])
    elif len(parts) >= 2 and parts[0] == "_":
        repository = parts[1]
    else:
        return ""
    return repository if re.match(r"^[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)?$", repository, re.I) else ""


def dockerhub_search(query, limit=12):
    if not docker_app_store_enabled():
        raise ValueError("Docker app store is disabled")

    query = str(query or "").strip()
    direct_repository = dockerhub_repository_from_url(query)
    if len(query) < 2:
        return {"ok": True, "results": []}
    try:
        limit = max(1, min(25, int(limit)))
    except (TypeError, ValueError):
        limit = 12

    if direct_repository:
        api_repository = direct_repository if "/" in direct_repository else f"library/{direct_repository}"
        url = f"https://hub.docker.com/v2/repositories/{quote(api_repository, safe='/')}/"
    else:
        url = "https://hub.docker.com/v2/search/repositories/?" + urlencode(
            {"query": query, "page_size": limit}
        )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "HomeStart/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not search Docker Hub: {error}") from error

    if direct_repository:
        payload = {"results": [{
            "repo_name": direct_repository,
            "short_description": payload.get("description") or payload.get("full_description") or "Docker Hub image",
            "star_count": payload.get("star_count") or 0,
            "pull_count": payload.get("pull_count") or 0,
            "is_official": "/" not in direct_repository,
            "is_automated": False,
        }]}
        query = direct_repository
    query_tokens = [token for token in re.split(r"[^a-z0-9]+", query.lower()) if token]
    compact_query = "".join(query_tokens)
    results = []
    installed = installed_docker_images()
    for item in payload.get("results", []):
        name = str(item.get("repo_name") or "").strip()
        if not name:
            continue
        namespace, _, repo = name.rpartition("/")
        if not repo:
            namespace = "library" if item.get("is_official") else ""
            repo = name
        description = item.get("short_description") or ""
        icon_slug = dockerhub_icon_slug(name)
        results.append(
            {
                "name": name,
                "image": name,
                "namespace": namespace,
                "repo": repo,
                "page_url": dockerhub_page_url(name, bool(item.get("is_official"))),
                "description": description,
                "stars": item.get("star_count") or 0,
                "pulls": item.get("pull_count") or 0,
                "official": bool(item.get("is_official")),
                "automated": bool(item.get("is_automated")),
                "icon_url": f"https://cdn.simpleicons.org/{icon_slug}/38bdf8" if icon_slug else "",
                "icon_label": repo[:1].upper(),
                "relevance": dockerhub_result_score(name, description, query_tokens, compact_query, item),
                "installed": image_repository(name) in installed,
                "installed_containers": installed.get(image_repository(name), []),
            }
        )
    add_dockerhub_verification(results)
    results.sort(key=lambda item: (item.get("trusted_rank", 0), item["relevance"], item["pulls"], item["stars"]), reverse=True)
    return {"ok": True, "results": results}


def dockerhub_icon_slug(image):
    _, _, repo = str(image or "").rpartition("/")
    repo = repo or str(image or "")
    repo = repo.split(":", 1)[0].lower()
    aliases = {
        "home-assistant": "homeassistant",
        "homeassistant": "homeassistant",
        "postgres": "postgresql",
        "postgresql": "postgresql",
        "mariadb": "mariadb",
        "mongo": "mongodb",
        "mongodb": "mongodb",
        "node": "nodedotjs",
        "nextcloud": "nextcloud",
        "jellyfin": "jellyfin",
        "grafana": "grafana",
        "prometheus": "prometheus",
        "nginx": "nginx",
        "redis": "redis",
        "mysql": "mysql",
        "debian": "debian",
        "ubuntu": "ubuntu",
        "alpine": "alpinelinux",
        "portainer": "portainer",
        "pihole": "pihole",
        "vaultwarden": "vaultwarden",
        "forgejo": "forgejo",
        "gitea": "gitea",
        "immich": "immich",
        "plex": "plex",
        "sonarr": "sonarr",
        "radarr": "radarr",
        "qbittorrent": "qbittorrent",
    }
    if repo in aliases:
        return aliases[repo]
    slug = re.sub(r"[^a-z0-9]+", "", repo)
    return slug[:48]


def dockerhub_result_score(name, description, tokens, compact_query, item):
    normalized_name = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
    normalized_description = re.sub(r"[^a-z0-9]+", "", str(description or "").lower())
    score = 0
    if compact_query and compact_query in normalized_name:
        score += 1000
    if compact_query and compact_query in normalized_description:
        score += 120
    for token in tokens:
        if token in normalized_name:
            score += 180
        elif token in normalized_description:
            score += 25
    if item.get("is_official"):
        score += 60
    pulls = item.get("pull_count") or 0
    stars = item.get("star_count") or 0
    score += min(80, int(pulls).bit_length() * 4)
    score += min(40, int(stars).bit_length() * 3)
    return score


def normalize_docker_image(image):
    image = str(image or "").strip()
    if not image:
        raise ValueError("Docker image is required")
    if len(image) > 200:
        raise ValueError("Docker image is too long")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]*$", image):
        raise ValueError("Docker image contains invalid characters")
    if ".." in image or image.startswith(("-", "/")):
        raise ValueError("Docker image is invalid")
    return image


def normalize_container_port(value):
    port = str(value or "").strip()
    if not port:
        return ""
    if not port.isdigit():
        raise ValueError("Ports must be numeric")
    number = int(port)
    if number < 1 or number > 65535:
        raise ValueError("Ports must be between 1 and 65535")
    return str(number)


def safe_env_assignment(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if "\x00" in value or "\n" in value or "=" not in value:
        raise ValueError("Environment variables must use KEY=value")
    key, raw = value.split("=", 1)
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        raise ValueError(f"Invalid environment variable name: {key}")
    if len(raw) > 2048:
        raise ValueError(f"Environment variable {key} is too long")
    return f"{key}={raw}"


def safe_volume_mapping(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if "\x00" in value or "\n" in value:
        raise ValueError("Volume mappings must be one per line")
    parts = value.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError("Volumes must use /host/path:/container/path[:ro]")
    host_path, container_path = parts[0], parts[1]
    mode = parts[2] if len(parts) == 3 else ""
    if not host_path.startswith("/") or not container_path.startswith("/"):
        raise ValueError("Volume paths must be absolute")
    if mode and mode not in {"ro", "rw"}:
        raise ValueError("Volume mode must be ro or rw")
    return value


def update_install_job(job_id, **values):
    with INSTALL_JOBS_LOCK:
        job = INSTALL_JOBS.get(job_id)
        if job:
            job.update(values)
            job["updated_at"] = int(time.time())


def docker_pull_with_progress(image, job_id):
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
        update_install_job(job_id, stage="pulling", progress=progress, message=line, log=recent)
    return_code = process.wait()
    if return_code:
        detail = recent[-1] if recent else f"docker pull exited with code {return_code}"
        raise ValueError(detail)


def catalog_install_values(app, supplied):
    if supplied is None:
        supplied = {}
    if not isinstance(supplied, dict):
        raise ValueError("Invalid app settings")
    declared = {item["id"] for item in app["inputs"]}
    if set(supplied) - declared:
        raise ValueError("Unknown app setting")
    reserved = {
        "homestart_data": str(COMPOSE_APP_DATA_DIR),
        "server_timezone": system_timezone(),
    }
    values = {}
    for item in app["inputs"]:
        input_id = item["id"]
        default = replace_store_placeholders(item["default"], reserved)
        value = supplied.get(input_id, default)
        value = str(value).strip()
        if not value or len(value) > 2048 or "\x00" in value or "\n" in value:
            raise ValueError(f"{item['label']} is invalid")
        input_type = item["type"]
        if input_type == "port":
            value = str(normalize_container_port(value))
        elif input_type == "path":
            if not value.startswith("/"):
                raise ValueError(f"{item['label']} must be an absolute path")
            value = os.path.normpath(value)
        elif input_type == "timezone":
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as error:
                raise ValueError(f"{item['label']} is not a valid time zone") from error
        elif input_type == "select" and value not in item.get("options", []):
            raise ValueError(f"{item['label']} is not one of the allowed values")
        pattern = item.get("pattern")
        if pattern and not re.fullmatch(pattern, value):
            raise ValueError(f"{item['label']} has an invalid format")
        values[input_id] = value
    return {**reserved, **values}


def render_catalog_compose(app, supplied):
    values = catalog_install_values(app, supplied)
    compose = replace_store_placeholders(app["compose"], values)
    remaining = store_placeholders(compose)
    if remaining:
        raise ValueError("The app template contains unresolved values")
    for service_name, service in compose["services"].items():
        labels = service.get("labels")
        if labels is None:
            labels = {}
        elif isinstance(labels, list):
            converted = {}
            for label in labels:
                key, separator, value = str(label).partition("=")
                if separator:
                    converted[key] = value
            labels = converted
        elif not isinstance(labels, dict):
            raise ValueError(f"{app['id']}: invalid labels for {service_name}")
        labels.update({
            "com.homestart.managed": "true",
            "com.homestart.template": app["id"],
        })
        service["labels"] = labels
    compose["name"] = ""
    return compose, values


def compose_project_name(app_id, instance):
    value = re.sub(r"[^a-z0-9_-]+", "-", f"homestart-{app_id}-{instance}".lower()).strip("-_")
    return value[:63] or f"homestart-{uuid.uuid4().hex[:8]}"


def compose_command_with_progress(command, job_id, stage, start, end):
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
        update_install_job(job_id, stage=stage, progress=progress, message=line, log=recent)
    return_code = process.wait()
    if return_code:
        detail = recent[-1] if recent else f"docker compose exited with code {return_code}"
        raise ValueError(detail)
    return recent


def compose_store_install(payload, job_id=None):
    app = store_catalog_app(payload.get("template_id"))
    compose, values = render_catalog_compose(app, payload.get("values"))
    existing = run_docker_command(
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
        normalize_docker_name(name)
        if docker_container_exists(name):
            raise ValueError(f"A Docker container named {name} already exists")
    try:
        run_docker_command(["compose", "version"], timeout=15)
    except ValueError as error:
        raise ValueError("Docker Compose is required to install catalog apps") from error

    instance = values.get("container_name") or app["id"]
    project = compose_project_name(app["id"], instance)
    compose["name"] = project
    project_dir = COMPOSE_APP_DIR / f"{app['id']}--{project[-24:]}"
    project_dir.mkdir(parents=True, exist_ok=True)
    compose_path = project_dir / "compose.yaml"
    temporary = compose_path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(compose_path)

    base = ["-f", str(compose_path), "-p", project]
    if job_id:
        update_install_job(job_id, stage="pulling", progress=10, message=f"Downloading images for {app['name']}…")
        compose_command_with_progress([*base, "pull"], job_id, "pulling", 12, 78)
        update_install_job(job_id, stage="creating", progress=82, message="Creating the Compose project…")
        compose_command_with_progress([*base, "up", "-d"], job_id, "creating", 84, 97)
    else:
        run_docker_command(["compose", *base, "pull"], timeout=900)
        run_docker_command(["compose", *base, "up", "-d"], timeout=180)
    running = run_docker_command(["compose", *base, "ps", "--status", "running", "-q"], timeout=30)
    state = "running" if running else "created"
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


def docker_store_install(payload, job_id=None):
    if not docker_app_store_enabled():
        raise ValueError("Docker app store is disabled")
    if payload.get("template_id"):
        return compose_store_install(payload, job_id)

    image = normalize_docker_image(payload.get("image", ""))
    installed = installed_docker_images()
    if image_repository(image) in installed:
        names = ", ".join(installed[image_repository(image)])
        raise ValueError(f"This image is already installed as {names}")
    container_name = normalize_docker_name(payload.get("name") or image.rsplit("/", 1)[-1].split(":", 1)[0])
    host_port = normalize_container_port(payload.get("host_port"))
    container_port = normalize_container_port(payload.get("container_port"))
    restart_policy = str(payload.get("restart_policy") or "unless-stopped").strip()
    if restart_policy not in {"no", "always", "unless-stopped", "on-failure"}:
        raise ValueError("Invalid restart policy")
    if docker_container_exists(container_name):
        raise ValueError(f"A Docker container named {container_name} already exists")

    env_values = [safe_env_assignment(item) for item in payload.get("env", []) if str(item or "").strip()]
    volume_values = [safe_volume_mapping(item) for item in payload.get("volumes", []) if str(item or "").strip()]

    if job_id:
        update_install_job(job_id, stage="pulling", progress=10, message=f"Downloading {image}…")
        docker_pull_with_progress(image, job_id)
        update_install_job(job_id, stage="creating", progress=85, message="Creating container…")
    else:
        run_docker_command(["pull", image], timeout=600)

    command = ["run", "-d", "--name", container_name, "--restart", restart_policy]
    if host_port and container_port:
        command.extend(["-p", f"{host_port}:{container_port}"])
    for value in env_values:
        command.extend(["-e", value])
    for value in volume_values:
        command.extend(["-v", value])
    command.append(image)

    container_id = run_docker_command(command, timeout=120).strip()
    if job_id:
        update_install_job(job_id, stage="starting", progress=95, message="Container created; checking status…")
        try:
            state = run_docker_command(["inspect", "--format", "{{.State.Status}}", container_name], timeout=15).strip()
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


def run_store_install_job(job_id, payload):
    try:
        result = docker_store_install(payload, job_id)
        update_install_job(job_id, status="completed", stage="completed", progress=100,
                           message=f"{result['container']} is {result.get('state', 'running')}", result=result)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        update_install_job(job_id, status="failed", stage="failed", message=str(error), error=str(error))


def start_store_install(payload):
    job_id = uuid.uuid4().hex
    now = int(time.time())
    with INSTALL_JOBS_LOCK:
        INSTALL_JOBS[job_id] = {"id": job_id, "status": "running", "stage": "validating", "progress": 3,
                                "message": "Validating installation…", "log": [], "created_at": now, "updated_at": now}
        expired = [key for key, job in INSTALL_JOBS.items() if now - job.get("updated_at", now) > 86400]
        for key in expired:
            INSTALL_JOBS.pop(key, None)
    threading.Thread(target=run_store_install_job, args=(job_id, payload), name=f"install-{job_id[:8]}", daemon=True).start()
    return {"ok": True, "job_id": job_id}


def store_install_status(job_id):
    with INSTALL_JOBS_LOCK:
        job = INSTALL_JOBS.get(str(job_id or ""))
        if not job:
            raise ValueError("Installation job not found")
        return {"ok": True, **job}


def configured_app(name):
    target = normalized_name(name)
    for app in load_config():
        if normalized_name(app.get("name", "")) == target:
            return app
    return None


def app_action(payload):
    action = payload.get("action", "")
    docker_name = payload.get("docker_name", "")
    service_name = payload.get("service_name", "")

    if action in {"stop", "restart"}:
        if docker_name:
            return docker_action(docker_name, action)
        if service_name:
            return service_action(service_name, action)
        raise ValueError("No Docker container or native service is linked to this app")

    if action != "uninstall":
        raise ValueError("Invalid action")
    if not app_uninstall_enabled():
        raise ValueError("App uninstall is disabled")

    docker_name = str(docker_name or "").strip()
    if docker_name:
        docker_name = normalize_docker_name(docker_name)
        before = docker_container_diagnostics(docker_name)
        if not before:
            raise ValueError("Docker container was not found")
        output = run_docker_command(["rm", "-f", docker_name], timeout=90)
        time.sleep(0.6)
        after = docker_container_diagnostics(docker_name)
        if after:
            if after.get("id") != before.get("id"):
                raise ValueError(
                    "Container was removed, but another container with the same name appeared. "
                    "Check an external supervisor such as Docker Compose, systemd, or an auto-update service."
                )
            raise ValueError("Docker reported success, but the same container still exists")
        details = []
        if before.get("restart_policy"):
            details.append(f"restart policy: {before['restart_policy']}")
        if before.get("compose_project") or before.get("compose_service"):
            details.append(
                "compose: "
                + "/".join(item for item in [before.get("compose_project"), before.get("compose_service")] if item)
            )
        suffix = f" ({', '.join(details)})" if details else ""
        return {
            "ok": True,
            "container": docker_name,
            "container_id": before.get("id"),
            "action": action,
            "message": (output or f"Container {docker_name} removed") + f". Images and volumes were preserved.{suffix}",
        }

    app = configured_app(payload.get("app_name", ""))
    if not app:
        raise ValueError("App not found")
    command = safe_uninstall_command(app.get("uninstall_command"))
    if not command:
        raise ValueError("This app does not have an uninstall command configured")

    subprocess.check_output(
        command,
        text=True,
        timeout=120,
        stderr=subprocess.STDOUT,
    )
    return {"ok": True, "app": app.get("name"), "action": action}


def now_ms():
    return int(time.time() * 1000)


def speedtest_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS speedtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER NOT NULL,
            summary TEXT NOT NULL,
            raw TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def speedtest_run():
    if not shutil.which("speedtest"):
        raise ValueError("Ookla Speedtest CLI is not installed")

    env = os.environ.copy()
    env.setdefault("HOME", str(Path.home() if Path.home().exists() else Path(tempfile.gettempdir())))
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    env["PATH"] = env.get("PATH") or "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    result = subprocess.run(
        ["speedtest", "--accept-license", "--accept-gdpr", "--format=json"],
        text=True,
        capture_output=True,
        timeout=120,
        env=env,
    )
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        raise ValueError(output or "Speedtest failed")

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise ValueError(output or "Speedtest returned invalid JSON") from error

    download_bps = payload.get("download", {}).get("bandwidth")
    upload_bps = payload.get("upload", {}).get("bandwidth")
    summary = {
        "download_mbps": round(download_bps * 8 / 1_000_000, 2) if isinstance(download_bps, (int, float)) else None,
        "upload_mbps": round(upload_bps * 8 / 1_000_000, 2) if isinstance(upload_bps, (int, float)) else None,
        "ping_ms": payload.get("ping", {}).get("latency"),
        "jitter_ms": payload.get("ping", {}).get("jitter"),
        "packet_loss": payload.get("packetLoss"),
        "isp": payload.get("isp"),
        "server": payload.get("server", {}).get("name"),
        "location": payload.get("server", {}).get("location"),
        "result_url": payload.get("result", {}).get("url"),
    }
    created_at = now_ms()
    with speedtest_db() as connection:
        cursor = connection.execute(
            "INSERT INTO speedtest_results (created_at, summary, raw) VALUES (?, ?, ?)",
            (created_at, json.dumps(summary), json.dumps(payload)),
        )
        result_id = cursor.lastrowid

    return {
        "ok": True,
        "id": result_id,
        "created_at": created_at,
        "raw": payload,
        "summary": summary,
    }


def speedtest_history(limit=20):
    try:
        limit = max(1, min(100, int(limit)))
    except (TypeError, ValueError):
        limit = 20
    with speedtest_db() as connection:
        rows = connection.execute(
            "SELECT id, created_at, summary FROM speedtest_results ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {
        "ok": True,
        "results": [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "summary": json.loads(row["summary"]),
            }
            for row in rows
        ],
    }


def app_payload():
    host = local_ip()
    containers = docker_map(host)
    configured = load_config()
    discovered_native = native_web_apps(host)
    discovered_services = native_service_apps()

    for app in configured:
        container = containers.get(normalized_name(app.get("name", "")))
        if container:
            app["source"] = "docker"
            app["app_type"] = "docker"
            app["docker_name"] = container["docker_name"]
            app["status"] = container["status"]
            app["image"] = container["image"]
        apply_app_metadata(app)
        apply_uninstall_metadata(app)
        app["url"] = public_app_url(app.get("url", ""), host)
        with_icon(app)

    seen = {normalized_name(app.get("name", "")) for app in configured}
    seen_urls = {str(app.get("url") or "") for app in configured if app.get("url")}
    discovered = [
        app for app in containers.values() if normalized_name(app.get("name", "")) not in seen
    ]
    for app in discovered:
        apply_uninstall_metadata(app)
        if app.get("url"):
            seen_urls.add(app["url"])

    native_discovered = [
        app
        for app in discovered_native
        if normalized_name(app.get("name", "")) not in seen and str(app.get("url") or "") not in seen_urls
    ]
    seen.update(normalized_name(app.get("name", "")) for app in [*discovered, *native_discovered])
    service_discovered = [
        app
        for app in discovered_services
        if normalized_name(app.get("name", "")) not in seen
    ]

    return {
        "dashboard": load_config_file().get("dashboard", {}),
        "host": host,
        "apps": configured + discovered + native_discovered + service_discovered,
        "features": load_config_file().get("features", {}),
    }


def default_routes():
    try:
        routes = run_json(["ip", "-j", "route", "show", "default"])
    except (json.JSONDecodeError, subprocess.SubprocessError, FileNotFoundError):
        return {}
    return {route.get("dev"): route for route in routes if route.get("dev")}


def netplan_files():
    root = Path("/etc/netplan")
    if not root.exists():
        return []
    return sorted([*root.glob("*.yaml"), *root.glob("*.yml")])


def load_netplan_file(path):
    try:
        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}
    except (OSError, yaml.YAMLError):
        return {}


def netplan_interface_config(interface):
    for path in netplan_files():
        data = load_netplan_file(path)
        network = data.get("network", {})
        for section in ("ethernets", "wifis"):
            interfaces = network.get(section, {})
            if interface in interfaces:
                return path, interfaces[interface]
    return None, {}


def is_physical_network_interface(item):
    name = item.get("ifname", "")
    if item.get("link_type") not in {"ether"}:
        return False
    if name == "lo" or name.startswith(VIRTUAL_INTERFACE_PREFIXES):
        return False
    if "master" in item:
        return False
    link_kind = (item.get("linkinfo") or {}).get("info_kind")
    if link_kind:
        return False
    sysfs = Path("/sys/class/net") / name
    if not ((sysfs / "device").exists() or (sysfs / "wireless").exists()):
        return False
    return True


def network_interfaces_payload():
    try:
        addresses = run_json(["ip", "-j", "addr", "show"])
    except (json.JSONDecodeError, subprocess.SubprocessError, FileNotFoundError):
        addresses = []

    routes = default_routes()
    monitor_items = monitorable_network_interfaces(refresh=True)
    hardware_by_name = {item["name"]: item for item in monitor_items}
    interfaces = []
    for item in addresses:
        if not is_physical_network_interface(item):
            continue

        name = item.get("ifname", "")
        hardware = hardware_by_name.get(name, {})
        netplan_path, netplan_config = netplan_interface_config(name)
        ipv4 = [
            {
                "address": address.get("local"),
                "prefix": address.get("prefixlen"),
                "cidr": f"{address.get('local')}/{address.get('prefixlen')}",
            }
            for address in item.get("addr_info", [])
            if address.get("family") == "inet"
        ]
        route = routes.get(name, {})
        nameservers = netplan_config.get("nameservers", {}).get("addresses", [])
        mode = "dhcp" if netplan_config.get("dhcp4") else "static" if netplan_config else "unknown"
        interfaces.append(
            {
                "name": name,
                "label": hardware.get("label", ""),
                "vendor": hardware.get("vendor", ""),
                "model": hardware.get("model", ""),
                "driver": hardware.get("driver", ""),
                "kind": hardware.get("kind", ""),
                "carrier": hardware.get("carrier", False),
                "speed_mbps": hardware.get("speed_mbps"),
                "duplex": hardware.get("duplex", ""),
                "mac": item.get("address", ""),
                "state": item.get("operstate", "UNKNOWN"),
                "mtu": item.get("mtu"),
                "ipv4": ipv4,
                "gateway": route.get("gateway", ""),
                "dns": nameservers,
                "mode": mode,
                "netplan_file": str(netplan_path) if netplan_path else "",
                "managed_by": "netplan" if netplan_path else "unknown",
            }
        )

    selected = load_config_file().get("network", {}).get("monitor_interface", "auto")
    active = choose_monitor_interface(monitor_items, selected, default_route_interfaces())
    return {
        "renderer": "netplan",
        "interfaces": interfaces,
        "monitor": {
            "selected": selected,
            "active": active,
            "selection_missing": selected not in {"", "auto"} and selected not in {item["name"] for item in monitor_items},
            "interfaces": monitor_items,
        },
    }


def validate_interface_name(name):
    interfaces = {item["name"] for item in network_interfaces_payload()["interfaces"]}
    if name not in interfaces:
        raise ValueError("Unknown or unsupported network interface")


def update_netplan_interface(interface, mode, address, gateway, dns):
    validate_interface_name(interface)
    if mode not in {"dhcp", "static"}:
        raise ValueError("Invalid network mode")

    target_file, _ = netplan_interface_config(interface)
    if target_file is None:
        target_file = Path(f"/etc/netplan/90-homestart-{interface}.yaml")
        section = "wifis" if interface.startswith("wl") else "ethernets"
        data = {"network": {"version": 2, "renderer": "networkd", section: {}}}
    else:
        data = load_netplan_file(target_file)
        network = data.setdefault("network", {})
        network.setdefault("version", 2)
        network.setdefault("renderer", "networkd")
        section = "ethernets" if interface in network.get("ethernets", {}) else "wifis"
        network.setdefault(section, {})

    network = data.setdefault("network", {})
    interface_config = network.setdefault(section, {}).setdefault(interface, {})
    if mode == "dhcp":
        interface_config.clear()
        interface_config["dhcp4"] = True
    else:
        try:
            ipaddress.ip_interface(address)
            ipaddress.ip_address(gateway)
            dns_addresses = [str(ipaddress.ip_address(item.strip())) for item in dns if item.strip()]
        except ValueError as error:
            raise ValueError(f"Invalid network value: {error}") from error

        interface_config.clear()
        interface_config["dhcp4"] = False
        interface_config["addresses"] = [address]
        interface_config["routes"] = [{"to": "default", "via": gateway}]
        if dns_addresses:
            interface_config["nameservers"] = {"addresses": dns_addresses}

    backup = target_file.with_suffix(target_file.suffix + f".bak-{int(time.time())}")
    if target_file.exists():
        shutil.copy2(target_file, backup)

    with target_file.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, sort_keys=False)

    subprocess.check_output(["netplan", "generate"], text=True, timeout=10, stderr=subprocess.STDOUT)
    subprocess.check_output(["netplan", "apply"], text=True, timeout=20, stderr=subprocess.STDOUT)
    return {
        "ok": True,
        "interface": interface,
        "mode": mode,
        "backup": str(backup) if backup.exists() else "",
    }


def update_member_path(name):
    path = PurePosixPath(name)
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts:
        return None
    if parts[0] in {"homestart", "package"}:
        parts = parts[1:]
    if not parts or any(part == ".." for part in parts):
        return None
    lower_parts = [part.lower() for part in parts]
    if any(part in UPDATE_EXCLUDED for part in lower_parts):
        raise ValueError(f"Update package contains protected entry: {name}")
    if any(part.endswith(UPDATE_PRIVATE_SUFFIXES) for part in lower_parts):
        raise ValueError(f"Update package contains private data file: {name}")
    if any(fragment in part for part in lower_parts for fragment in UPDATE_PRIVATE_FRAGMENTS):
        raise ValueError(f"Update package contains private data file: {name}")
    if parts[0] in UPDATE_ALLOWED_PREFIXES or parts[0] in UPDATE_ALLOWED_FILES:
        return Path(*parts)
    return None


def update_member_parts(name):
    path = PurePosixPath(name)
    parts = [part for part in path.parts if part not in {"", "."}]
    if parts and parts[0] in {"homestart", "package"}:
        parts = parts[1:]
    return parts


def validate_update_manifest(archive):
    manifest_member = None
    for member in archive.getmembers():
        parts = update_member_parts(member.name)
        if parts == ["package.json"]:
            manifest_member = member
            break
    if manifest_member is None:
        raise ValueError("Update package is missing package.json metadata")
    if not manifest_member.isfile():
        raise ValueError("Update package metadata is invalid")

    source = archive.extractfile(manifest_member)
    if source is None:
        raise ValueError("Update package metadata could not be read")
    try:
        manifest = json.loads(source.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Update package metadata is invalid JSON") from error

    if manifest.get("name") != "homestart":
        raise ValueError("Update package is not a HomeStart package")
    if manifest.get("package_type") != "update":
        raise ValueError("This file is not a HomeStart update package")
    return manifest


def restart_service_later():
    def restart():
      subprocess.run(["systemctl", "restart", "homestart.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Leave enough time for ThreadingHTTPServer to flush the successful update
    # response before systemd terminates this process.
    threading.Timer(3.0, restart).start()


def apply_update_package(filename, content):
    if not filename.endswith((".tar.gz", ".tgz")):
        raise ValueError("Update file must be a .tar.gz or .tgz package")
    if "," in content:
        content = content.split(",", 1)[1]

    try:
        payload = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid update file encoding") from error
    if len(payload) > 30 * 1024 * 1024:
        raise ValueError("Update package is too large")

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_root = BACKUP_DIR / f"update-{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    changed = []

    with tempfile.NamedTemporaryFile(prefix="homestart-update-", suffix=".tar.gz", delete=False) as file:
        archive_path = Path(file.name)
        file.write(payload)

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            manifest = validate_update_manifest(archive)
            members = []
            for member in archive.getmembers():
                target = update_member_path(member.name)
                if target is None or member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError(f"Unsupported package entry: {member.name}")
                members.append((member, target))

            if not members:
                raise ValueError("No updatable files found in package")

            packaged_static = {
                relative_target
                for _member, relative_target in members
                if relative_target.parts and relative_target.parts[0] == "static"
            }
            for member, relative_target in members:
                target = BASE_DIR / relative_target
                if target.exists():
                    backup_target = backup_root / relative_target
                    backup_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup_target)
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    continue
                with target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                mode = member.mode & 0o777
                if mode:
                    os.chmod(target, mode)
                changed.append(str(relative_target))

            if packaged_static:
                for existing in STATIC_DIR.rglob("*"):
                    if not existing.is_file():
                        continue
                    relative_existing = existing.relative_to(BASE_DIR)
                    if relative_existing in packaged_static:
                        continue
                    backup_target = backup_root / relative_existing
                    backup_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(existing, backup_target)
                    existing.unlink()
                    changed.append(f"removed {relative_existing}")
    finally:
        archive_path.unlink(missing_ok=True)

    restart_service_later()
    return {
        "ok": True,
        "changed": changed,
        "backup": str(backup_root),
        "restart": True,
        "package": manifest,
    }


def installed_package_metadata():
    try:
        with PACKAGE_PATH.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def github_update_repo():
    repo = str(load_config_file().get("updates", {}).get("github_repo", "")).strip()
    if not repo:
        raise ValueError("GitHub update repository is not configured")
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
        raise ValueError("GitHub update repository must look like owner/repo")
    return repo


def github_release_client():
    global GITHUB_RELEASE_CLIENT
    if GITHUB_RELEASE_CLIENT is None:
        GITHUB_RELEASE_CLIENT = GitHubReleaseClient(github_update_repo, installed_package_metadata)
    return GITHUB_RELEASE_CLIENT


def fetch_github_json(url):
    return github_release_client().fetch_json(url)


def github_latest_update_asset():
    return github_release_client().latest()


def download_update_asset(url):
    return github_release_client().download(url)


def apply_github_update():
    status = github_latest_update_asset()
    if not status.get("download_url"):
        raise ValueError(status.get("message") or "No downloadable update package was found")
    if not status.get("update_available"):
        return {**status, "ok": True, "restart": False}

    payload = download_update_asset(status["download_url"])
    encoded = base64.b64encode(payload).decode("ascii")
    result = apply_update_package(status.get("asset_name", "homestart-update.tar.gz"), encoded)
    result["source"] = "github"
    result["latest_version"] = status.get("latest_version", "")
    return result


API_ROUTER = ApiRouter(sys.modules[__name__])


class HomeStartHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        if not API_ROUTER.get(self):
            super().do_GET()

    def do_HEAD(self):
        if not API_ROUTER.head(self):
            super().do_HEAD()

    def do_POST(self):
        API_ROUTER.post(self)

    def end_headers(self):
        if not getattr(self, "skip_default_cache", False):
            self.send_header("Cache-Control", "no-store")
        self.skip_default_cache = False
        super().end_headers()

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


def main():
    port = int(os.environ.get("PORT", "80"))
    threading.Thread(target=metrics_sampler, name="homestart-metrics", daemon=True).start()
    threading.Thread(target=network_metrics_sampler, name="homestart-network-metrics", daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), HomeStartHandler)
    print(f"HomeStart listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()


