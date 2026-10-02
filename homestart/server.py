#!/usr/bin/env python3
import json
import base64
import binascii
import gzip
import hashlib
import getpass
import mimetypes
import os
import re
import shutil
import socket
import ssl
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
import yaml
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .apps.discovery import AppDiscovery, DiscoveryServices
from .backup.manager import BackupManager
from .api.router import ApiRouter
from .auth import (
    AuthManager,
    LoginRateLimiter,
    address_in_networks,
    effective_client_ip as forwarded_client_ip,
    forwarded_https,
    normalize_cookie_secure_mode,
    normalize_trusted_proxies,
    trusted_proxy_networks,
)
from .config import (
    CURATED_APPS,
    DEFAULT_CONFIG,
    deep_merge,
    load_config as load_config_data,
    load_json_file,
    save_config as save_config_data,
)
from .docker.hub import DockerHubClient
from .docker.catalog import CatalogClient, fetch_store_catalog as catalog_fetch
from .docker.install import (
    InstallManager, InstallServices, image_repository as install_image_repository,
    compose_project_name as install_project_name,
)
from .docker.projects import ComposeProjectManager, compose_risk_report
from .docker.store import (
    dockerhub_icon_slug as store_dockerhub_icon_slug,
    dockerhub_page_url as store_dockerhub_page_url,
    dockerhub_repository_from_url as parse_dockerhub_repository_url,
    dockerhub_result_score as score_dockerhub_result,
    install_values as validate_catalog_install_values,
    normalize_image as validate_docker_image,
    normalize_port as validate_container_port,
    placeholders as catalog_placeholders,
    render_compose as render_store_compose,
    replace_placeholders as fill_catalog_placeholders,
    safe_environment_assignment as validate_environment_assignment,
    safe_volume_mapping as validate_volume_mapping,
    validate_catalog as validate_declarative_catalog,
)
from .files import browser as file_browser, trash as file_trash
from .files.copy import CopyCancelled, CopyManager
from .metrics.store import MetricStore
from .metrics.host import HostMetrics
from .samba.manager import (
    SambaManager,
    config_with_include as add_samba_include,
    parse_config as parse_samba_config_data,
    render_config as render_samba_config,
    share_payload as build_samba_share_payload,
    user_tokens as parse_samba_user_tokens,
    validate_share_name as validate_samba_name,
)
from .system.network import (
    choose_monitor_interface as select_monitor_interface,
    endpoint_address as parse_endpoint_address,
    network_device_totals as parse_network_device_totals,
    parse_ss_tcp_counters as parse_socket_tcp_counters,
    parse_udev_properties as parse_network_udev_properties,
)
from .system.network_config import (
    NetplanBackend,
    NetworkManagerBackend,
    SUPPORTED_ARCHITECTURES,
    host_architecture as detect_host_architecture,
    normalize_architecture,
    parse_nmcli_rows,
    validate_ipv4_settings as validate_network_ipv4_settings,
)
from .system import storage
from .system.disks import SmartHealthMonitor
from .system.processes import ProcessCpuTracker
from .system.power import PowerManager
from .system.webapps import NativeWebAppDiscovery
from .updates.github import GitHubReleaseClient, update_asset_version
from .updates.package import (
    TransactionalPackageUpdater,
    member_parts as package_member_parts,
    member_path as package_member_path,
    validate_manifest as validate_package_manifest,
)


MODULE_PATH = Path(__file__).resolve()
POWER_MANAGER = PowerManager()
BASE_DIR = MODULE_PATH.parents[1]
if not (BASE_DIR / "static").is_dir():
    # Compatibility bridge for installs upgraded by a pre-modular updater:
    # scripts/homestart/server.py still needs the installation root.
    BASE_DIR = MODULE_PATH.parents[2]
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "homestart.db"
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_STAGING_DIR = DATA_DIR / "restore-staging"
MAX_BACKUP_UPLOAD_SIZE = 1024 * 1024 * 1024
MAX_BACKUP_EXTRACTED_SIZE = 4 * 1024 * 1024 * 1024
BACKUP_STAGE_TTL_SECONDS = 60 * 60
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
METRIC_LAST_WRITE = 0
INSTALL_JOBS = {}
INSTALL_JOBS_LOCK = threading.Lock()
NETWORK_HISTORY_PREV = None
NETWORK_SAMPLE_LOCK = threading.Lock()
NETWORK_LATEST = {
    "timestamp": 0,
    "interface": "",
    "rx_bps": 0,
    "tx_bps": 0,
    "sample_seconds": 0,
    "rx_label": "0 B/s",
    "tx_label": "0 B/s",
}
NETWORK_INTERFACE_CACHE = {"at": 0, "items": []}
CONTAINER_NETWORK_PREV = {}
CONTAINER_NETWORK_TOP = {"download": None, "upload": None}
CONTAINER_NETWORK_TARGETS = []
CONTAINER_NETWORK_TARGETS_AT = 0
CONTAINER_NETWORK_LOCK = threading.Lock()
HOST_TCP_PREV = {}
HOST_NETWORK_TOP = {"download": None, "upload": None}
HOST_NETWORK_LOCK = threading.Lock()
HTTP_EGRESS_BYTES = {}
HTTP_EGRESS_LOCK = threading.Lock()
DOCKER_IDENTITY_CACHE = {"at": 0, "items": {}}
INTERFACE_ADDRESS_CACHE = {"at": 0, "interface": "", "items": set()}
FILE_COPY_JOBS = {}
FILE_COPY_JOBS_LOCK = threading.Lock()
METRIC_STORE = None
GITHUB_RELEASE_CLIENT = None
AUTH_MANAGER = None
LOGIN_RATE_LIMITER = LoginRateLimiter()
AUTH_UNAUTHORIZED_LOG_AT = {}
AUTH_UNAUTHORIZED_LOG_LOCK = threading.Lock()
PROCESS_CPU_TRACKER = ProcessCpuTracker()
SMART_HEALTH_MONITOR = SmartHealthMonitor()
NATIVE_WEB_APP_DISCOVERY = NativeWebAppDiscovery()
DOCKERHUB_VERIFICATION_CACHE = {}
DOCKERHUB_VERIFICATION_LOCK = threading.Lock()
DOCKER_ARCHITECTURE_CACHE = {}
STORE_CATALOG_LOCK = threading.Lock()
ICON_CACHE = {}
AUTH_COOKIE_NAME = "homestart_session"
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
        "security": config["security"],
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

    if app.get("compose_managed") and app.get("compose_project"):
        app["uninstallable"] = True
        app["uninstall_reason"] = "Removes the complete Docker Compose application."
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


def docker_port_mappings(container_name, data=None):
    data = data or docker_inspect(container_name)
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


def compose_project_manager():
    return ComposeProjectManager(COMPOSE_APP_DIR, COMPOSE_APP_DATA_DIR, run_docker_command)


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


def metrics_db():
    return metric_store().connect()


def metric_store():
    global METRIC_STORE
    if METRIC_STORE is None or METRIC_STORE.db_path != Path(DB_PATH):
        METRIC_STORE = MetricStore(DB_PATH)
    return METRIC_STORE


def record_system_metric(payload):
    global METRIC_LAST_WRITE
    captured_at = int(payload.get("timestamp") or time.time())
    if captured_at - METRIC_LAST_WRITE < 30:
        return
    METRIC_LAST_WRITE = captured_at
    metric_store().record_system(payload, captured_at)


def record_network_metric(payload):
    metric_store().record_network(payload)


def record_container_network_metrics(samples, captured_at=None):
    return metric_store().record_container_network(samples, captured_at)


def record_host_network_estimates(samples, network, container_samples, captured_at=None):
    return metric_store().record_host_estimates(
        samples, network, container_samples, captured_at,
    )


def record_http_egress(size, client_address="", local_address=""):
    global HTTP_EGRESS_BYTES
    if str(client_address or "") in {"127.0.0.1", "::1"}:
        return
    try:
        size = max(0, int(size or 0))
    except (TypeError, ValueError):
        return
    if not size:
        return
    local_address = str(local_address or "")
    with HTTP_EGRESS_LOCK:
        HTTP_EGRESS_BYTES[local_address] = (
            HTTP_EGRESS_BYTES.get(local_address, 0) + size
        )


def consume_http_egress(interface="", sample_seconds=2):
    global HTTP_EGRESS_BYTES
    with HTTP_EGRESS_LOCK:
        totals = HTTP_EGRESS_BYTES
        HTTP_EGRESS_BYTES = {}
    addresses = interface_ip_addresses(interface) if interface else set()
    transmitted = sum(
        size for address, size in totals.items()
        if not addresses or address in addresses
    )
    if not transmitted:
        return None
    sample_seconds = max(.001, float(sample_seconds or 2))
    return {
        "key": "service:homestart",
        "name": "HomeStart dashboard",
        "kind": "service",
        "confidence": "high",
        "sample_seconds": sample_seconds,
        "rx_bytes": 0,
        "tx_bytes": transmitted,
        "rx_bps": 0,
        "tx_bps": transmitted / sample_seconds,
    }


def publish_host_network_top(samples):
    download = max(samples, key=lambda item: item.get("rx_bps", 0), default=None)
    upload = max(samples, key=lambda item: item.get("tx_bps", 0), default=None)
    if download and not download.get("rx_bps"):
        download = None
    if upload and not upload.get("tx_bps"):
        upload = None
    with HOST_NETWORK_LOCK:
        HOST_NETWORK_TOP["download"] = dict(download) if download else None
        HOST_NETWORK_TOP["upload"] = dict(upload) if upload else None


def container_network_ranking(period=3600, limit=12):
    return metric_store().network_ranking(period, limit)


def metrics_history(hours=24):
    return metric_store().history(hours, default_network_interface())


def metrics_sampler():
    """Collect history independently from browser activity."""
    while True:
        started = time.monotonic()
        try:
            record_system_metric(HOST_METRICS.system_payload(None))
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
            publish_network_sample(network)
            record_network_metric({"timestamp": int(time.time()), **network})
            container_samples = update_container_network_top()
            record_container_network_metrics(container_samples)
            host_samples = update_host_network_estimates(network.get("interface", ""))
            http_sample = consume_http_egress(
                network.get("interface", ""),
                network.get("sample_seconds", 2),
            )
            if http_sample:
                host_samples.append(http_sample)
            publish_host_network_top(host_samples)
            record_host_network_estimates(host_samples, network, container_samples)
        except Exception as error:
            print(f"HomeStart network sampler: {error}", flush=True)
        elapsed = time.monotonic() - started
        time.sleep(max(.25, 2 - elapsed))


def smart_health_sampler():
    """Refresh SMART cache without ever blocking an HTTP request."""
    while True:
        started = time.monotonic()
        try:
            SMART_HEALTH_MONITOR.collect(disk_payload())
        except Exception as error:
            print(f"HomeStart SMART collector: {error}", flush=True)
        elapsed = time.monotonic() - started
        time.sleep(max(1, SMART_HEALTH_MONITOR.ttl_seconds - elapsed))


def overview_payload():
    system = HOST_METRICS.system_payload(None)
    system["network"] = latest_network_payload()
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
        smart = disk.get("smart") or {}
        effective_healthy = (
            smart.get("last_healthy")
            if smart.get("status") == "standby"
            else smart.get("healthy")
        )
        if effective_healthy is False:
            disk_name = " · ".join(
                value for value in (disk.get("model", ""), disk.get("device", ""))
                if value
            )
            alerts.append({
                "id": f"smart-{disk.get('device', 'disk')}",
                "level": "critical",
                "title": "SMART disk health warning",
                "detail": f"{disk_name or 'A physical disk'} reports a failed health assessment",
            })
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
        "uptime": HOST_METRICS.uptime_label(),
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
        if pid == os.getpid():
            continue
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
                container_name = (
                    str(item.get("Name") or "").lstrip("/")
                    or item.get("Id", "")[:12]
                )
                targets.append({
                    "key": namespace,
                    "identity_key": f"container:{container_name}",
                    "pid": pid,
                    "name": container_name,
                    "compose_project": labels.get("com.docker.compose.project", ""),
                    "compose_service": labels.get("com.docker.compose.service", ""),
                })
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
            "key": target.get("identity_key") or target["key"],
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


def publish_network_sample(payload):
    sample = {
        "timestamp": int(payload.get("timestamp") or time.time()),
        "interface": str(payload.get("interface") or ""),
        "rx_bps": max(0, round(float(payload.get("rx_bps") or 0))),
        "tx_bps": max(0, round(float(payload.get("tx_bps") or 0))),
        "sample_seconds": max(0, float(payload.get("sample_seconds") or 0)),
        "rx_label": str(payload.get("rx_label") or "0 B/s"),
        "tx_label": str(payload.get("tx_label") or "0 B/s"),
    }
    with NETWORK_SAMPLE_LOCK:
        NETWORK_LATEST.clear()
        NETWORK_LATEST.update(sample)
    return dict(sample)


def latest_network_payload():
    selected_interface = default_network_interface()
    with NETWORK_SAMPLE_LOCK:
        result = dict(NETWORK_LATEST)
    if not result.get("timestamp") or result.get("interface") != selected_interface:
        result = {
            "timestamp": int(time.time()),
            "interface": selected_interface,
            "rx_bps": 0,
            "tx_bps": 0,
            "sample_seconds": 0,
            "rx_label": "0 B/s",
            "tx_label": "0 B/s",
        }
    with CONTAINER_NETWORK_LOCK:
        result["top_consumers"] = dict(CONTAINER_NETWORK_TOP)
    with HOST_NETWORK_LOCK:
        result["top_host_consumers"] = dict(HOST_NETWORK_TOP)
    return result


def network_payload(channel="live"):
    global NETWORK_HISTORY_PREV
    if channel == "live":
        return latest_network_payload()
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
    with NETWORK_SAMPLE_LOCK:
        now = time.monotonic()
        rx_bps = tx_bps = 0
        sample_seconds = 0
        previous = NETWORK_HISTORY_PREV
        if previous and len(previous) >= 4 and previous[3] == selected_interface:
            sample_seconds = max(.001, now - previous[0])
            rx_bps = max(0, (received - previous[1]) / sample_seconds)
            tx_bps = max(0, (transmitted - previous[2]) / sample_seconds)
        NETWORK_HISTORY_PREV = (now, received, transmitted, selected_interface)
    result = {
        "timestamp": int(time.time()),
        "interface": selected_interface,
        "rx_bps": round(rx_bps),
        "tx_bps": round(tx_bps),
        "sample_seconds": sample_seconds,
        "rx_label": f"{file_browser.format_bytes(rx_bps)}/s",
        "tx_label": f"{file_browser.format_bytes(tx_bps)}/s",
    }
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


def start_copy_job(source_path, destination_path):
    FILE_BROWSER.ensure_file_operations_enabled()
    source, target = FILE_BROWSER.resolve_copy_target(source_path, destination_path)
    return COPY_MANAGER.start(source, target)


def start_move_job(source_path, destination_path):
    FILE_BROWSER.ensure_file_operations_enabled()
    source, target = FILE_BROWSER.resolve_move_target(source_path, destination_path)
    return COPY_MANAGER.start(source, target, operation="move")


def file_action(payload):
    action = payload.get("action", "")
    if action == "mkdir":
        return FILE_BROWSER.create_folder(payload.get("parent", ""), payload.get("name", ""))
    if action == "delete":
        return TRASH_MANAGER.trash_file_path(payload.get("path", ""))
    if action == "rename":
        return FILE_BROWSER.rename_file_path(payload.get("path", ""), payload.get("name", ""))
    if action == "copy":
        return FILE_BROWSER.copy_file_path(payload.get("source", ""), payload.get("destination", ""))
    if action == "copy_start":
        return start_copy_job(payload.get("source", ""), payload.get("destination", ""))
    if action == "move_start":
        return start_move_job(payload.get("source", ""), payload.get("destination", ""))
    if action == "copy_cancel":
        return COPY_MANAGER.cancel(payload.get("job_id", ""))
    if action == "upload":
        return FILE_BROWSER.upload_file(payload.get("parent", ""), payload.get("name", ""), payload.get("content", ""))
    if action == "mount_readonly":
        return STORAGE.mount_block_device_readonly(payload.get("device", ""))
    if action == "unmount":
        return STORAGE.unmount_homestart_device(payload.get("device", ""))
    raise ValueError("Invalid file action")


def samba_manager_enabled():
    return load_config_file().get("features", {}).get("samba_manager", True)


def samba_manager():
    return SambaManager(
        SAMBA_CONFIG_PATH,
        SAMBA_MANAGED_PATH,
        SAMBA_STATE_PATH,
        samba_manager_enabled,
        FILE_BROWSER.resolve_file_path,
    )


def ensure_samba_manager_enabled():
    return samba_manager().ensure_enabled()


def parse_samba_config(content):
    return parse_samba_config_data(content)


def samba_user_tokens(value):
    return parse_samba_user_tokens(value)


def samba_users():
    return samba_manager().users()


def samba_testparm(config_path=None):
    return samba_manager().testparm(config_path)


def samba_state():
    return samba_manager().state()


def samba_share_payload(name, values, state):
    return build_samba_share_payload(name, values, state)


def samba_shares_payload():
    return samba_manager().shares_payload()


def validate_samba_share_name(name):
    return validate_samba_name(name)


def render_homestart_samba_config(state):
    return render_samba_config(state)


def samba_config_with_include(content):
    return add_samba_include(content, SAMBA_MANAGED_PATH)


def reload_samba():
    return samba_manager().reload()


def save_samba_state(new_state):
    return samba_manager().save_state(new_state)


def samba_share_action(payload):
    manager = samba_manager()
    # Preserve the long-standing server-level seams used by integrations and tests.
    manager.state = samba_state
    manager.users = samba_users
    manager.shares_payload = samba_shares_payload
    manager.save_state = save_samba_state
    return manager.action(payload)


def cleanup_expired_trash(force=False):
    global TRASH_LAST_CLEANUP
    now = time.time()
    if not force and now - TRASH_LAST_CLEANUP < 3600:
        return 0
    TRASH_LAST_CLEANUP = now
    return TRASH_MANAGER.cleanup_expired_trash()


def trash_listing():
    cleanup_expired_trash(force=True)
    return TRASH_MANAGER.trash_listing()


def serve_file(handler, raw_path, include_body=True):
    target = FILE_BROWSER.resolve_file_path(raw_path)
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
    return STORAGE.disk_payload()


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
    disks = disk_payload()
    smart = SMART_HEALTH_MONITOR.snapshot(disks)
    for disk in disks:
        disk["smart"] = smart.get(disk.get("device", ""), {
            "status": "unknown",
            "healthy": None,
        })
    return {
        "disks": disks,
        "services": [service for unit in services if (service := service_status(unit))],
        "containers": APP_DISCOVERY.docker_apps(host),
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


def serve_backup_download(handler):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"homestart-backup-{stamp}.tar.gz"
    with tempfile.NamedTemporaryFile(prefix="homestart-backup-", suffix=".tar.gz", delete=False) as temporary:
        destination = Path(temporary.name)
    try:
        BACKUP_MANAGER.create_backup(destination)
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


def stage_backup_upload(handler):
    return BACKUP_MANAGER.stage_backup_upload(handler.rfile, handler.headers.get("Content-Length", "0"))


def restore_backup(name):
    source = BACKUP_MANAGER.backup_path(name)
    result = BACKUP_MANAGER.restore_backup_file(source)
    restart_service_later()
    return result


def restore_staged_backup(token):
    source = BACKUP_MANAGER.staged_backup_path(token)
    try:
        result = BACKUP_MANAGER.restore_backup_file(source, "uploaded backup")
    finally:
        source.unlink(missing_ok=True)
    restart_service_later()
    return result


def serve_download(handler, raw_path, include_body=True):
    target = FILE_BROWSER.resolve_file_path(raw_path)
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
    return install_image_repository(image)


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
    return [
        {**dict(item), **catalog_architecture_payload(item)}
        for item in CURATED_APPS
        if image_repository(item.get("image")) not in installed
    ]


def store_placeholders(value):
    return catalog_placeholders(value)


def validate_store_catalog(catalog):
    return validate_declarative_catalog(catalog)


def store_catalog_url():
    return str(load_config_file().get("app_store", {}).get("catalog_url") or STORE_CATALOG_URL).strip()


def catalog_client():
    return CatalogClient(
        STORE_CATALOG_CACHE, STORE_CATALOG_LOCK, STORE_CATALOG_TTL,
        store_catalog_url, fetch_store_catalog,
    )


def install_manager():
    services = InstallServices(
        catalog_app=store_catalog_app,
        require_catalog_architecture=require_catalog_architecture,
        render_compose=render_catalog_compose,
        verify_image=verify_docker_image_architecture,
        projects=compose_project_manager,
        run_docker=run_docker_command,
        container_exists=docker_container_exists,
        normalize_name=normalize_docker_name,
        enabled=docker_app_store_enabled,
        installed_images=installed_docker_images,
    )
    return InstallManager(services, COMPOSE_APP_DIR, INSTALL_JOBS, INSTALL_JOBS_LOCK)


def read_store_catalog_cache():
    return catalog_client().read_store_catalog_cache()


def save_store_catalog_cache(catalog):
    return catalog_client().save_store_catalog_cache(catalog)


def fetch_store_catalog(url):
    return catalog_fetch(url)


def load_store_catalog(refresh=False):
    return catalog_client().load_store_catalog(refresh)


def replace_store_placeholders(value, values):
    return fill_catalog_placeholders(value, values)


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


def host_architecture_payload():
    return detect_host_architecture()


def catalog_architecture_payload(app):
    host = host_architecture_payload()["architecture"]
    declared = list(app.get("architectures") or [])
    if not declared or host == "unknown":
        status = "unknown"
        compatible = None
    else:
        compatible = host in declared
        status = "compatible" if compatible else "incompatible"
    return {
        "host_architecture": host,
        "architectures": declared,
        "architecture_status": status,
        "architecture_compatible": compatible,
    }


def require_catalog_architecture(app):
    architecture = catalog_architecture_payload(app)
    if architecture["architecture_compatible"] is False:
        supported = ", ".join(architecture["architectures"])
        raise ValueError(
            f"{app['name']} does not declare support for this host architecture "
            f"({architecture['host_architecture']}); declared: {supported}"
        )
    return architecture


def store_templates_payload(refresh=False):
    catalog, metadata = load_store_catalog(refresh)
    if catalog is None:
        return {
            "ok": True,
            "templates": curated_store_apps(),
            "catalog": {**metadata, **host_architecture_payload()},
        }
    installed = installed_docker_images()
    installed_templates = {
        record.get("template_id")
        for record in compose_project_manager().projects().values()
        if record.get("template_id")
    }
    templates = []
    for app in catalog["apps"]:
        images = [
            image_repository(service.get("image"))
            for service in app["compose"]["services"].values()
            if service.get("image")
        ]
        if app["id"] in installed_templates or any(image in installed for image in images):
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
            "risk": compose_risk_report(app["compose"]),
            **catalog_architecture_payload(app),
        })
    return {
        "ok": True,
        "templates": templates,
        "catalog": {
            **metadata,
            "name": catalog["name"],
            "version": catalog["catalog_version"],
            "schema_version": catalog["schema_version"],
            **host_architecture_payload(),
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
    return store_dockerhub_page_url(name, official)


def dockerhub_client(verifier=None):
    return DockerHubClient(
        docker_app_store_enabled, installed_docker_images, host_architecture_payload,
        DOCKERHUB_VERIFICATION_CACHE, DOCKERHUB_VERIFICATION_LOCK, verifier=verifier,
    )


def dockerhub_verification(name, official=False):
    return dockerhub_client().dockerhub_verification(name, official)


def add_dockerhub_verification(results):
    return dockerhub_client(verifier=dockerhub_verification).add_dockerhub_verification(results)


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
    return parse_dockerhub_repository_url(value)


def dockerhub_search(query, limit=12):
    return dockerhub_client().dockerhub_search(query, limit)


def dockerhub_icon_slug(image):
    return store_dockerhub_icon_slug(image)


def dockerhub_result_score(name, description, tokens, compact_query, item):
    return score_dockerhub_result(name, description, tokens, compact_query, item)


def normalize_docker_image(image):
    return validate_docker_image(image)


def docker_manifest_architectures(image):
    image = normalize_docker_image(image)
    cached = DOCKER_ARCHITECTURE_CACHE.get(image)
    if cached and time.time() - cached[0] < 21600:
        return set(cached[1])
    try:
        payload = json.loads(
            run_docker_command(["manifest", "inspect", "--verbose", image], timeout=45)
        )
    except (ValueError, json.JSONDecodeError):
        return set()

    architectures = set()

    def collect(value):
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        if not isinstance(value, dict):
            return
        platform_value = value.get("platform") or value.get("Platform")
        if isinstance(platform_value, dict):
            operating_system = str(
                platform_value.get("os") or platform_value.get("OS") or "linux"
            ).lower()
            architecture = normalize_architecture(
                platform_value.get("architecture") or platform_value.get("Architecture")
            )
            variant = str(platform_value.get("variant") or platform_value.get("Variant") or "").lower()
            if architecture == "unknown" and str(platform_value.get("architecture") or "").startswith("arm"):
                architecture = "arm/v7" if variant == "v7" else architecture
            if operating_system == "linux" and architecture in SUPPORTED_ARCHITECTURES:
                architectures.add(architecture)
        top_architecture = normalize_architecture(value.get("Architecture"))
        if str(value.get("Os") or value.get("OS") or "linux").lower() == "linux" \
                and top_architecture in SUPPORTED_ARCHITECTURES:
            architectures.add(top_architecture)
        for key in ("manifests", "Descriptor"):
            if key in value:
                collect(value[key])

    collect(payload)
    DOCKER_ARCHITECTURE_CACHE[image] = (time.time(), sorted(architectures))
    return architectures


def verify_docker_image_architecture(image):
    host = host_architecture_payload()["architecture"]
    architectures = docker_manifest_architectures(image)
    if host != "unknown" and architectures and host not in architectures:
        supported = ", ".join(sorted(architectures))
        raise ValueError(
            f"{image} does not publish a Linux image for {host}; available: {supported}"
        )
    return {
        "host_architecture": host,
        "architectures": sorted(architectures),
        "architecture_status": (
            "compatible" if host in architectures
            else "unknown" if not architectures or host == "unknown"
            else "incompatible"
        ),
    }


def normalize_container_port(value):
    return validate_container_port(value)


def safe_env_assignment(value):
    return validate_environment_assignment(value)


def safe_volume_mapping(value):
    return validate_volume_mapping(value)


def update_install_job(job_id, **values):
    return install_manager().update_install_job(job_id, **values)


def docker_pull_with_progress(image, job_id):
    return install_manager().docker_pull_with_progress(image, job_id)


def catalog_install_values(app, supplied):
    reserved = {
        "homestart_data": str(COMPOSE_APP_DATA_DIR),
        "server_timezone": system_timezone(),
    }
    return validate_catalog_install_values(app, supplied, reserved)


def render_catalog_compose(app, supplied):
    reserved = {
        "homestart_data": str(COMPOSE_APP_DATA_DIR),
        "server_timezone": system_timezone(),
    }
    return render_store_compose(app, supplied, reserved)


def compose_project_name(app_id, instance):
    return install_project_name(app_id, instance)


def compose_command_with_progress(command, job_id, stage, start, end):
    return install_manager().compose_command_with_progress(command, job_id, stage, start, end)


def compose_store_install(payload, job_id=None):
    return install_manager().compose_store_install(payload, job_id)


def docker_store_install(payload, job_id=None):
    return install_manager().docker_store_install(payload, job_id)


def run_store_install_job(job_id, payload):
    return install_manager().run_store_install_job(job_id, payload)


def start_store_install(payload):
    return install_manager().start_store_install(payload)


def store_install_status(job_id):
    return install_manager().store_install_status(job_id)


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
    compose_project = str(payload.get("compose_project") or "").strip()

    if action in {"start", "stop", "restart", "update"}:
        if compose_project:
            if not load_config_file().get("features", {}).get("docker_actions", True):
                raise ValueError("Docker actions are disabled")
            return compose_project_manager().action(compose_project, action)
        if docker_name:
            if action not in {"stop", "restart"}:
                raise ValueError("This action is available only for managed Compose applications")
            return docker_action(docker_name, action)
        if service_name:
            if action not in {"stop", "restart"}:
                raise ValueError("This action is available only for managed Compose applications")
            return service_action(service_name, action)
        raise ValueError("No Docker container or native service is linked to this app")

    if action != "uninstall":
        raise ValueError("Invalid action")
    if not app_uninstall_enabled():
        raise ValueError("App uninstall is disabled")

    if compose_project:
        return compose_project_manager().action(
            compose_project,
            "uninstall",
            delete_data=bool(payload.get("delete_data")),
        )

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


def default_routes():
    try:
        routes = run_json(["ip", "-j", "route", "show", "default"])
    except (json.JSONDecodeError, subprocess.SubprocessError, FileNotFoundError):
        return {}
    return {route.get("dev"): route for route in routes if route.get("dev")}


def netplan_files():
    return NetplanBackend(Path("/etc/netplan"), run_netplan_command).files()


def load_netplan_file(path):
    return NetplanBackend.load(path)


def netplan_interface_config(interface):
    return NetplanBackend(Path("/etc/netplan"), run_netplan_command).interface_config(interface)


def run_netplan_command(command, timeout=20):
    return subprocess.check_output(
        command,
        text=True,
        timeout=timeout,
        stderr=subprocess.STDOUT,
    )


def nmcli_output(arguments, timeout=12):
    executable = shutil.which("nmcli")
    if not executable:
        raise FileNotFoundError("NetworkManager command nmcli is not available")
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    return subprocess.check_output(
        [executable, *arguments],
        text=True,
        timeout=timeout,
        stderr=subprocess.STDOUT,
        env=environment,
    )


def network_manager_devices():
    return NetworkManagerBackend(nmcli_output, BACKUP_DIR).devices()


def network_manager_interface_config(interface, device=None):
    return NetworkManagerBackend(nmcli_output, BACKUP_DIR).interface_config(interface, device)


def interface_configuration(interface, network_manager_device=None):
    netplan_path, netplan_config = netplan_interface_config(interface)
    if netplan_path:
        return {
            "managed_by": "netplan",
            "source": str(netplan_path),
            "connection": "",
            "mode": (
                "dhcp" if netplan_config.get("dhcp4")
                else "static" if netplan_config
                else "unknown"
            ),
            "dns": netplan_config.get("nameservers", {}).get("addresses", []),
            "editable": True,
        }
    device = network_manager_device or {}
    if device and str(device.get("state") or "").lower() != "unmanaged":
        connection, config = network_manager_interface_config(interface, device)
        return {
            "managed_by": "networkmanager",
            "source": connection,
            "connection": connection,
            "mode": config.get("mode", "unknown"),
            "dns": config.get("dns", []),
            "editable": bool(connection) or device.get("type") == "ethernet",
        }
    return {
        "managed_by": "unknown",
        "source": "",
        "connection": "",
        "mode": "unknown",
        "dns": [],
        "editable": False,
    }


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
    network_manager = network_manager_devices()
    monitor_items = monitorable_network_interfaces(refresh=True)
    hardware_by_name = {item["name"]: item for item in monitor_items}
    interfaces = []
    for item in addresses:
        if not is_physical_network_interface(item):
            continue

        name = item.get("ifname", "")
        hardware = hardware_by_name.get(name, {})
        configuration = interface_configuration(name, network_manager.get(name))
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
                "dns": configuration["dns"],
                "mode": configuration["mode"],
                "netplan_file": configuration["source"] if configuration["managed_by"] == "netplan" else "",
                "connection_name": configuration["connection"],
                "configuration_source": configuration["source"],
                "managed_by": configuration["managed_by"],
                "editable": configuration["editable"],
            }
        )

    selected = load_config_file().get("network", {}).get("monitor_interface", "auto")
    active = choose_monitor_interface(monitor_items, selected, default_route_interfaces())
    renderers = sorted({
        item["managed_by"] for item in interfaces if item["managed_by"] != "unknown"
    })
    return {
        "renderer": renderers[0] if len(renderers) == 1 else "mixed" if renderers else "unknown",
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


def validate_ipv4_settings(mode, address, gateway, dns):
    return validate_network_ipv4_settings(mode, address, gateway, dns)


def update_netplan_interface(interface, mode, address, gateway, dns):
    validate_interface_name(interface)
    return NetplanBackend(Path("/etc/netplan"), run_netplan_command).apply(
        interface, mode, address, gateway, dns,
    )


def update_network_manager_interface(interface, mode, address, gateway, dns):
    validate_interface_name(interface)
    device = network_manager_devices().get(interface)
    backend = NetworkManagerBackend(nmcli_output, BACKUP_DIR)
    profile = network_manager_interface_config(interface, device) if device else None
    return backend.apply(
        interface, mode, address, gateway, dns,
        device=device, profile=profile,
    )


def update_network_interface(interface, mode, address, gateway, dns):
    validate_interface_name(interface)
    netplan_path, _ = netplan_interface_config(interface)
    if netplan_path:
        return update_netplan_interface(interface, mode, address, gateway, dns)
    device = network_manager_devices().get(interface)
    if device and str(device.get("state") or "").lower() != "unmanaged":
        return update_network_manager_interface(interface, mode, address, gateway, dns)
    raise ValueError("No supported network configuration backend manages this interface")


def update_member_path(name):
    return package_member_path(name)


def update_member_parts(name):
    return package_member_parts(name)


def validate_update_manifest(archive):
    return validate_package_manifest(archive)


def restart_service_later():
    def restart():
        subprocess.run(
            ["systemctl", "restart", "homestart.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # Leave enough time for ThreadingHTTPServer to flush the successful update
    # response before systemd terminates this process.
    threading.Timer(3.0, restart).start()


def schedule_update_verifier(backup, version):
    verifier = BASE_DIR / "scripts" / "verify_update.py"
    systemd_run = shutil.which("systemd-run")
    if not verifier.is_file() or not systemd_run:
        return False
    try:
        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", "homestart.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if active.returncode != 0:
        return False
    unit = f"homestart-update-verify-{int(time.time())}"
    port = int(os.environ.get("PORT", "80"))
    try:
        result = subprocess.run(
            [
                systemd_run,
                "--unit", unit,
                "--collect",
                "--property", "Type=exec",
                sys.executable,
                str(verifier),
                "--install-dir", str(BASE_DIR),
                "--backup-dir", str(backup),
                "--version", str(version),
                "--port", str(port),
            ],
            text=True,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


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

    result = TransactionalPackageUpdater(BASE_DIR, BACKUP_DIR, STATIC_DIR).apply_bytes(payload)
    rollback_watch = schedule_update_verifier(result["backup"], result["manifest"]["version"])
    restart_service_later()
    return {
        "ok": True,
        "changed": result["changed"],
        "backup": result["backup"],
        "restart": True,
        "rollback_watch": rollback_watch,
        "package": result["manifest"],
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


def auth_manager():
    global AUTH_MANAGER
    if AUTH_MANAGER is None:
        AUTH_MANAGER = AuthManager(DATA_DIR)
    return AUTH_MANAGER


def request_cookie(handler, name):
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get("Cookie", ""))
    except Exception:
        return ""
    item = cookie.get(name)
    return item.value if item is not None else ""


def auth_cookie(handler, token, remember=True):
    parts = [
        f"{AUTH_COOKIE_NAME}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if remember:
        parts.append(f"Max-Age={30 * 24 * 60 * 60}")
    if handler.cookie_should_be_secure():
        parts.append("Secure")
    return "; ".join(parts)


def cleared_auth_cookie(handler):
    parts = [
        f"{AUTH_COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
    ]
    if handler.request_is_https():
        parts.append("Secure")
    return "; ".join(parts)


def auth_status(handler):
    manager = auth_manager()
    session = handler.current_auth_session()
    return {
        "ok": True,
        "setup_required": not manager.has_users(),
        "authenticated": session is not None,
        "user": session["user"] if session else None,
        "csrf_token": session["csrf_token"] if session else "",
        "expires_at": session["expires_at"] if session else 0,
    }


def auth_setup(handler, payload):
    manager = auth_manager()
    user = manager.create_initial_user(
        payload.get("setup_token", ""),
        payload.get("username", ""),
        payload.get("password", ""),
    )
    session = manager.create_session(user["id"], remember=bool(payload.get("remember", True)))
    handler.send_json(
        {
            "ok": True,
            "user": user,
            "csrf_token": session["csrf_token"],
            "expires_at": session["expires_at"],
        },
        headers={"Set-Cookie": auth_cookie(handler, session["token"], session["remember"])},
    )


def auth_login(handler, payload):
    manager = auth_manager()
    if not manager.has_users():
        raise ValueError("Initial setup is required")
    username = payload.get("username", "")
    client_ip = handler.effective_client_ip()
    retry_after = LOGIN_RATE_LIMITER.retry_after(client_ip, username)
    if retry_after:
        handler.send_json(
            {
                "ok": False,
                "error": f"Too many sign-in attempts. Try again in {retry_after} seconds.",
                "retry_after": retry_after,
            },
            HTTPStatus.TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
        )
        return
    user = manager.authenticate(username, payload.get("password", ""))
    if user is None:
        retry_after = LOGIN_RATE_LIMITER.record_failure(client_ip, username)
        response = {
            "ok": False,
            "error": "Invalid username or password",
        }
        headers = {}
        if retry_after:
            response["retry_after"] = retry_after
            headers["Retry-After"] = str(retry_after)
        handler.send_json(
            response,
            HTTPStatus.UNAUTHORIZED,
            headers=headers,
        )
        return
    LOGIN_RATE_LIMITER.record_success(client_ip, username)
    session = manager.create_session(user["id"], remember=bool(payload.get("remember", True)))
    handler.send_json(
        {
            "ok": True,
            "user": user,
            "csrf_token": session["csrf_token"],
            "expires_at": session["expires_at"],
        },
        headers={"Set-Cookie": auth_cookie(handler, session["token"], session["remember"])},
    )


def auth_logout(handler):
    token = request_cookie(handler, AUTH_COOKIE_NAME)
    auth_manager().revoke_session(token)
    handler.send_json(
        {"ok": True},
        headers={"Set-Cookie": cleared_auth_cookie(handler)},
    )


def auth_users_payload(handler):
    session = handler.require_auth_session()
    state = auth_manager().account_state(session["user"]["id"])
    return {
        "ok": True,
        **state,
        # Retained for clients from the brief multi-user release. New clients
        # use owner and legacy_users.
        "users": [
            item for item in [state["owner"], *state["legacy_users"]]
            if item
        ],
        "current_user_id": session["user"]["id"],
    }


def auth_security_payload(handler):
    handler.require_auth_session()
    config = load_config_file().get("security", {})
    try:
        mode = normalize_cookie_secure_mode(config.get("cookie_secure", "auto"))
    except ValueError:
        mode = "auto"
    try:
        proxies = normalize_trusted_proxies(config.get("trusted_proxies", []))
    except ValueError:
        proxies = []
    peer = handler.peer_ip()
    return {
        "ok": True,
        "cookie_secure": mode,
        "trusted_proxies": proxies,
        "request": {
            "peer_ip": peer,
            "effective_client_ip": handler.effective_client_ip(),
            "trusted_proxy": handler.peer_is_trusted_proxy(),
            "https": handler.request_is_https(),
            "cookie_will_be_secure": handler.cookie_should_be_secure(),
        },
    }


def auth_security_action(handler, payload):
    handler.require_auth_session()
    mode = normalize_cookie_secure_mode(payload.get("cookie_secure", "auto"))
    proxies = normalize_trusted_proxies(payload.get("trusted_proxies", []))
    config = load_config_file()
    config["security"] = deep_merge(
        config.get("security", {}),
        {
            "cookie_secure": mode,
            "trusted_proxies": proxies,
        },
    )
    save_config_file(config)
    handler.send_json(auth_security_payload(handler))


def auth_users_action(handler, payload):
    session = handler.require_auth_session()
    action = str(payload.get("action", "")).strip()
    if action == "create":
        raise ValueError("HomeStart supports one owner account")
    elif action == "delete":
        auth_manager().delete_user(
            payload.get("user_id", ""), session["user"]["id"]
        )
        handler.send_json({"ok": True})
    else:
        raise ValueError("Unknown user action")


def auth_change_password(handler, payload):
    session = handler.require_auth_session()
    auth_manager().change_password(
        session["user"]["id"],
        payload.get("current_password", ""),
        payload.get("new_password", ""),
    )
    handler.send_json(
        {
            "ok": True,
            "message": "Password changed. Sign in again on this device.",
        },
        headers={"Set-Cookie": cleared_auth_cookie(handler)},
    )


# One instance per process; providers read current configuration and drive state
# on each operation rather than capturing a Settings snapshot at startup.
FILE_BROWSER = file_browser.FileBrowser(
    lambda: load_config_file(), DEFAULT_CONFIG["file_roots"],
    lambda: STORAGE.file_sidebar_items(), lambda: STORAGE.physical_drive_entries(),
)
STORAGE = storage.StorageManager(
    FILE_BROWSER.allowed_roots, lambda: load_config_file(), FILE_MOUNT_ROOT, clamp_percent,
)
TRASH_MANAGER = file_trash.TrashManager(
    TRASH_DIR, TRASH_INDEX, FILE_BROWSER, lambda: load_config_file(),
)

COPY_MANAGER = CopyManager(FILE_COPY_JOBS, FILE_COPY_JOBS_LOCK, file_browser.path_usage)
BACKUP_MANAGER = BackupManager(
    backup_dir=BACKUP_DIR, staging_dir=BACKUP_STAGING_DIR,
    config_path=CONFIG_PATH, database_path=DB_PATH,
    icon_dir=APP_ICON_DIR, icon_index=APP_ICON_INDEX,
    auth_manager=lambda: auth_manager(), save_config=lambda config: save_config_file(config),
    max_upload_size=MAX_BACKUP_UPLOAD_SIZE,
    max_extracted_size=MAX_BACKUP_EXTRACTED_SIZE,
    stage_ttl=BACKUP_STAGE_TTL_SECONDS,
)

API_ROUTER = ApiRouter(sys.modules[__name__])


def json_response_body(payload, accept_encoding=""):
    body = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    if len(body) >= 1024 and "gzip" in str(accept_encoding or "").lower():
        compressed = gzip.compress(body, compresslevel=5)
        if len(compressed) < len(body):
            return compressed, "gzip"
    return body, ""


class CountingWriter:
    def __init__(self, writer, callback):
        self.writer = writer
        self.callback = callback

    def write(self, data):
        written = self.writer.write(data)
        self.callback(len(data) if written is None else written)
        return written

    def __getattr__(self, name):
        return getattr(self.writer, name)


class HomeStartHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
    }
    PUBLIC_GET_PATHS = {
        "/health",
        "/api/auth/status",
        "/login",
        "/login.html",
        "/login.js",
        "/manifest.webmanifest",
        "/pwa.js",
        "/service-worker.js",
        "/styles.css",
        "/visual.css",
        "/favicon.ico",
    }
    PUBLIC_GET_PREFIXES = (
        "/brand/",
        "/fonts/",
        "/icons/",
    )
    PUBLIC_POST_PATHS = {
        "/api/auth/setup",
        "/api/auth/login",
    }

    def setup(self):
        super().setup()
        client_address = self.client_address[0] if self.client_address else ""
        local_address = self.connection.getsockname()[0]
        self.wfile = CountingWriter(
            self.wfile,
            lambda size: record_http_egress(
                size, client_address, local_address,
            ),
        )

    def log_request(self, code="-", size="-"):
        if str(code) == str(HTTPStatus.UNAUTHORIZED) and urlparse(self.path).path.startswith("/api/"):
            address = self.effective_client_ip() or "unknown"
            now = time.monotonic()
            with AUTH_UNAUTHORIZED_LOG_LOCK:
                previous = AUTH_UNAUTHORIZED_LOG_AT.get(address, 0)
                if previous and now - previous < 300:
                    return
                AUTH_UNAUTHORIZED_LOG_AT[address] = now
        super().log_request(code, size)

    def __init__(self, *args, **kwargs):
        self._auth_session_loaded = False
        self._auth_session = None
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def peer_ip(self):
        return self.client_address[0] if self.client_address else ""

    def trusted_proxy_networks(self):
        values = load_config_file().get("security", {}).get("trusted_proxies", [])
        try:
            return trusted_proxy_networks(values)
        except ValueError:
            return []

    def peer_is_trusted_proxy(self):
        return address_in_networks(self.peer_ip(), self.trusted_proxy_networks())

    def effective_client_ip(self):
        return forwarded_client_ip(
            self.peer_ip(), self.headers, self.trusted_proxy_networks(),
        )

    def request_is_https(self):
        if isinstance(self.connection, ssl.SSLSocket):
            return True
        return self.peer_is_trusted_proxy() and forwarded_https(self.headers)

    def cookie_should_be_secure(self):
        try:
            mode = normalize_cookie_secure_mode(
                load_config_file().get("security", {}).get("cookie_secure", "auto")
            )
        except ValueError:
            mode = "auto"
        if mode == "always":
            return True
        if mode == "never":
            return False
        return self.request_is_https()

    def current_auth_session(self):
        if not self._auth_session_loaded:
            token = request_cookie(self, AUTH_COOKIE_NAME)
            self._auth_session = auth_manager().session(token)
            self._auth_session_loaded = True
        return self._auth_session

    def require_auth_session(self):
        session = self.current_auth_session()
        if session is None:
            raise PermissionError("Authentication required")
        return session

    def redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def reject_unauthenticated(self):
        route = urlparse(self.path).path
        if route.startswith("/api/"):
            self.send_json(
                {"ok": False, "error": "Authentication required"},
                HTTPStatus.UNAUTHORIZED,
            )
        else:
            self.redirect("/login.html")

    def public_get_route(self, route):
        return (
            route in self.PUBLIC_GET_PATHS
            or route.startswith(self.PUBLIC_GET_PREFIXES)
        )

    def do_GET(self):
        route = urlparse(self.path).path
        if route in {"/login", "/login.html"}:
            if self.current_auth_session() is not None:
                self.redirect("/")
                return
            self.path = "/login.html"
            super().do_GET()
            return
        if not self.public_get_route(route) and self.current_auth_session() is None:
            self.reject_unauthenticated()
            return
        if not API_ROUTER.get(self):
            super().do_GET()

    def do_HEAD(self):
        route = urlparse(self.path).path
        if route in {"/login", "/login.html"}:
            self.path = "/login.html"
        elif not self.public_get_route(route) and self.current_auth_session() is None:
            self.reject_unauthenticated()
            return
        if not API_ROUTER.head(self):
            super().do_HEAD()

    def do_POST(self):
        route = urlparse(self.path).path
        if route not in self.PUBLIC_POST_PATHS:
            session = self.current_auth_session()
            if session is None:
                self.reject_unauthenticated()
                return
            if not auth_manager().csrf_matches(
                session, self.headers.get("X-CSRF-Token", "")
            ):
                self.send_json(
                    {"ok": False, "error": "Invalid or missing request token"},
                    HTTPStatus.FORBIDDEN,
                )
                return
        API_ROUTER.post(self)

    def end_headers(self):
        if not getattr(self, "skip_default_cache", False):
            self.send_header("Cache-Control", "no-store")
        self.skip_default_cache = False
        super().end_headers()

    def send_json(self, payload, status=HTTPStatus.OK, headers=None):
        body, content_encoding = json_response_body(
            payload, self.headers.get("Accept-Encoding", ""),
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if content_encoding:
            self.send_header("Content-Encoding", content_encoding)
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


APP_DISCOVERY = AppDiscovery(DiscoveryServices(
    docker_inspect=lambda *args, **kwargs: docker_inspect(*args, **kwargs),
    docker_port_mappings=lambda *args, **kwargs: docker_port_mappings(*args, **kwargs),
    select_docker_web_mapping=lambda *args, **kwargs: select_docker_web_mapping(*args, **kwargs),
    docker_ports_for_display=lambda *args, **kwargs: docker_ports_for_display(*args, **kwargs),
    docker_url_from_mapping=lambda *args, **kwargs: docker_url_from_mapping(*args, **kwargs),
    with_icon=lambda *args, **kwargs: with_icon(*args, **kwargs),
    normalized_name=lambda *args, **kwargs: normalized_name(*args, **kwargs),
    compose_project_manager=lambda *args, **kwargs: compose_project_manager(*args, **kwargs),
    app_uninstall_enabled=lambda *args, **kwargs: app_uninstall_enabled(*args, **kwargs),
    apply_uninstall_metadata=lambda *args, **kwargs: apply_uninstall_metadata(*args, **kwargs),
    service_status=lambda *args, **kwargs: service_status(*args, **kwargs),
    command_available=lambda *args, **kwargs: command_available(*args, **kwargs),
    local_ip=lambda *args, **kwargs: local_ip(*args, **kwargs),
    load_config=lambda *args, **kwargs: load_config(*args, **kwargs),
    apply_app_metadata=lambda *args, **kwargs: apply_app_metadata(*args, **kwargs),
    public_app_url=lambda *args, **kwargs: public_app_url(*args, **kwargs),
    load_config_file=lambda *args, **kwargs: load_config_file(*args, **kwargs),
    check_output=lambda *args, **kwargs: subprocess.check_output(*args, **kwargs),
    service_definitions=lambda: NATIVE_SERVICE_APP_DEFINITIONS,
    listener_snapshot=lambda *args: NATIVE_WEB_APP_DISCOVERY.snapshot(*args),
))


HOST_METRICS = HostMetrics(
    clamp_percent=clamp_percent,
    process_tracker=PROCESS_CPU_TRACKER,
    process_identity=lambda pid: host_process_identity(pid, docker_identities=docker_identity_names()),
    network_payload=lambda channel: network_payload(channel),
    docker_apps=lambda: APP_DISCOVERY.docker_apps(local_ip()),
)


def main():
    if len(sys.argv) >= 3 and sys.argv[1:3] == ["auth", "reset-password"]:
        if len(sys.argv) != 4:
            raise SystemExit("Usage: app.py auth reset-password USERNAME")
        first = getpass.getpass("New HomeStart password: ")
        second = getpass.getpass("Repeat password: ")
        if first != second:
            raise SystemExit("Passwords do not match")
        user = auth_manager().reset_password(sys.argv[3], first)
        print(f"Password reset for {user['username']}. Existing sessions were closed.")
        return

    port = int(os.environ.get("PORT", "80"))
    setup_token = auth_manager().ensure_setup_token()
    if setup_token:
        print("", flush=True)
        print("HomeStart initial setup is required.", flush=True)
        print(f"Setup code: {setup_token}", flush=True)
        print(
            "Open the dashboard and enter this code to create the owner account.",
            flush=True,
        )
        print("", flush=True)
    threading.Thread(target=metrics_sampler, name="homestart-metrics", daemon=True).start()
    threading.Thread(target=network_metrics_sampler, name="homestart-network-metrics", daemon=True).start()
    threading.Thread(target=smart_health_sampler, name="homestart-smart-health", daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), HomeStartHandler)
    print(f"HomeStart listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
