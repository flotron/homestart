#!/usr/bin/env python3
import json
import base64
import binascii
import hashlib
import ipaddress
import mimetypes
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import yaml
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, urljoin, urlparse


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "homestart.db"
BACKUP_DIR = DATA_DIR / "backups"
APP_ICON_DIR = DATA_DIR / "app-icons"
APP_ICON_INDEX = DATA_DIR / "app-icons.json"
PACKAGE_PATH = BASE_DIR / "package.json"
FILE_MOUNT_ROOT = Path("/mnt/homestart")
CONFIG_PATH = Path(os.environ.get("HOMESTART_CONFIG", BASE_DIR / "config.json"))
CPU_PREV = None
CPU_DETAIL_PREV = None
GPU_PREV = None
ICON_CACHE = {}
APP_NAME_ALIASES = {
    "openspeedtest": "openspeedtest",
    "open speed test": "openspeedtest",
    "qbittorrent": "qbittorrent",
    "q bittorrent": "qbittorrent",
    "plex": "plex",
}
DEFAULT_CONFIG = {
    "dashboard": {
        "title": "HomeStart",
        "subtitle": "Dashboard",
        "host": "",
    },
    "apps": [],
    "native_apps": [],
    "file_roots": ["/"],
    "services": ["homestart.service", "docker.service"],
    "features": {
        "docker_actions": True,
        "file_browser": True,
        "file_operations": True,
        "file_mounts": True,
        "app_uninstall": True,
    },
    "updates": {
        "github_repo": "flotron/homestart",
    },
}
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
UPDATE_ALLOWED_PREFIXES = {"static", "scripts"}
UPDATE_ALLOWED_FILES = {
    ".gitignore",
    "README.md",
    "app.py",
    "config.example.json",
    "homestart.service.example",
    "install.sh",
    "package.json",
}
UPDATE_PRIVATE_SUFFIXES = (".db", ".sqlite", ".log")
UPDATE_PRIVATE_FRAGMENTS = (".sqlite-",)


def deep_merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config_file():
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        data = {}

    if not isinstance(data, dict):
        data = {}
    return deep_merge(DEFAULT_CONFIG, data)


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


def load_config():
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


def docker_host_mode_ports(container_name):
    data = docker_inspect(container_name)
    if not data:
        return []

    if data.get("HostConfig", {}).get("NetworkMode") != "host":
        return []

    exposed = data.get("Config", {}).get("ExposedPorts") or {}
    ports = []
    for value in exposed:
        port, _, protocol = value.partition("/")
        if protocol == "tcp" and port.isdigit() and port not in ports:
            ports.append(port)
    return sorted(ports, key=int)


def docker_published_ports(container_name):
    data = docker_inspect(container_name)
    if not data:
        return []

    ports = []
    bindings = data.get("HostConfig", {}).get("PortBindings") or {}
    for values in bindings.values():
        for item in values or []:
            port = str(item.get("HostPort", ""))
            if port.isdigit() and port not in ports:
                ports.append(port)

    network_ports = data.get("NetworkSettings", {}).get("Ports") or {}
    for values in network_ports.values():
        for item in values or []:
            port = str(item.get("HostPort", ""))
            if port.isdigit() and port not in ports:
                ports.append(port)

    return sorted(ports, key=int)


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

        ports = []
        raw_ports = item.get("Ports", "")
        for part in raw_ports.split(","):
            part = part.strip()
            if "->" not in part:
                continue
            public = part.split("->", 1)[0].rsplit(":", 1)[-1]
            if public.isdigit() and public not in ports:
                ports.append(public)

        if not ports:
            ports = docker_host_mode_ports(item.get("Names", ""))
        if not ports:
            ports = docker_published_ports(item.get("Names", ""))

        url = f"http://{host}:{ports[0]}" if ports else ""
        apps.append(
            with_icon(
                {
                    "name": item.get("Names", "Docker app"),
                    "kind": "Docker",
                    "status": item.get("Status", ""),
                    "image": item.get("Image", ""),
                    "ports": ports,
                    "url": url,
                    "source": "docker",
                    "app_type": "docker",
                    "app_type_label": "Docker",
                    "tags": ["Docker"],
                    "available": True,
                    "docker_name": item.get("Names", ""),
                }
            )
        )

    return apps


def docker_map(host):
    return {normalized_name(app["name"]): app for app in docker_apps(host)}


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


def system_payload():
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
    return {
        "timestamp": int(time.time()),
        "cpu": {"percent": cpu_percent()},
        "memory": memory_payload(),
        "gpu": gpu,
        "gpus": gpus,
    }


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
    cpu_count = max(1, os.cpu_count() or 1)
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
                "cpu_percent": clamp_percent(raw_cpu / cpu_count),
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
    return {"ok": True, "path": str(target), "action": "mkdir"}


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


def copy_file_path(source_path, destination_path):
    ensure_file_operations_enabled()
    source = resolve_file_path(source_path)
    destination = resolve_file_path(destination_path)
    if source is None or destination is None:
        raise ValueError("Source and destination are required")
    if not source.exists():
        raise FileNotFoundError("The source path does not exist")

    target = destination / source.name if destination.exists() and destination.is_dir() else destination
    resolve_file_path(str(target))
    if source.resolve() == target.resolve():
        raise ValueError("Source and destination are the same")
    if source.is_dir() and (target == source or source in target.parents):
        raise ValueError("A folder cannot be copied into itself")
    if target.exists():
        raise FileExistsError("The destination already exists")
    if not target.parent.exists() or not target.parent.is_dir():
        raise NotADirectoryError("Destination parent folder does not exist")

    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)
    return {"ok": True, "path": str(target), "action": "copy"}


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
        return delete_file_path(payload.get("path", ""))
    if action == "copy":
        return copy_file_path(payload.get("source", ""), payload.get("destination", ""))
    if action == "upload":
        return upload_file(payload.get("parent", ""), payload.get("name", ""), payload.get("content", ""))
    if action == "mount_readonly":
        return mount_block_device_readonly(payload.get("device", ""))
    if action == "unmount":
        return unmount_homestart_device(payload.get("device", ""))
    raise ValueError("Invalid file action")


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


def docker_action(name, action):
    if not load_config_file().get("features", {}).get("docker_actions", True):
        raise ValueError("Docker actions are disabled")

    docker_name = name.strip()
    if action not in {"stop", "restart"}:
        raise ValueError("Invalid action")
    if not re.match(r"^[A-Za-z0-9_.-]+$", docker_name):
        raise ValueError("Invalid container name")

    subprocess.check_output(
        ["docker", action, docker_name],
        text=True,
        timeout=30,
        stderr=subprocess.STDOUT,
    )
    return {"ok": True, "container": docker_name, "action": action}


def configured_app(name):
    target = normalized_name(name)
    for app in load_config():
        if normalized_name(app.get("name", "")) == target:
            return app
    return None


def app_action(payload):
    action = payload.get("action", "")
    docker_name = payload.get("docker_name", "")

    if action in {"stop", "restart"}:
        return docker_action(docker_name, action)

    if action != "uninstall":
        raise ValueError("Invalid action")
    if not app_uninstall_enabled():
        raise ValueError("App uninstall is disabled")

    docker_name = docker_name.strip()
    if docker_name:
        if not re.match(r"^[A-Za-z0-9_.-]+$", docker_name):
            raise ValueError("Invalid container name")
        subprocess.check_output(
            ["docker", "rm", "-f", docker_name],
            text=True,
            timeout=60,
            stderr=subprocess.STDOUT,
        )
        return {
            "ok": True,
            "container": docker_name,
            "action": action,
            "message": "Container removed. Docker images and volumes were preserved.",
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
    discovered = [
        app for app in containers.values() if normalized_name(app.get("name", "")) not in seen
    ]
    for app in discovered:
        apply_uninstall_metadata(app)

    return {
        "dashboard": load_config_file().get("dashboard", {}),
        "host": host,
        "apps": configured + discovered,
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
    return True


def network_interfaces_payload():
    try:
        addresses = run_json(["ip", "-j", "addr", "show"])
    except (json.JSONDecodeError, subprocess.SubprocessError, FileNotFoundError):
        addresses = []

    routes = default_routes()
    interfaces = []
    for item in addresses:
        if not is_physical_network_interface(item):
            continue

        name = item.get("ifname", "")
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

    return {
        "renderer": "netplan",
        "interfaces": interfaces,
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

    threading.Timer(1.0, restart).start()


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


def fetch_github_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "HomeStart updater",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def update_asset_version(name):
    match = re.match(r"homestart-update-(.+)\.t(?:ar\.)?gz$", name)
    return match.group(1) if match else ""


def github_latest_update_asset():
    repo = github_update_repo()
    try:
        release = fetch_github_json(f"https://api.github.com/repos/{repo}/releases/latest")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {
                "ok": True,
                "repo": repo,
                "current_version": installed_package_metadata().get("version", ""),
                "latest_version": "",
                "update_available": False,
                "message": "No GitHub release was found for this repository.",
            }
        raise

    assets = release.get("assets") or []
    update_assets = [
        asset
        for asset in assets
        if update_asset_version(str(asset.get("name", ""))) and asset.get("browser_download_url")
    ]
    if not update_assets:
        return {
            "ok": True,
            "repo": repo,
            "current_version": installed_package_metadata().get("version", ""),
            "latest_version": release.get("tag_name", ""),
            "update_available": False,
            "release_url": release.get("html_url", ""),
            "message": "Latest GitHub release does not include a homestart-update package.",
        }

    asset = sorted(update_assets, key=lambda item: str(item.get("name", "")), reverse=True)[0]
    current_version = installed_package_metadata().get("version", "")
    latest_version = update_asset_version(str(asset.get("name", ""))) or str(release.get("tag_name", ""))
    return {
        "ok": True,
        "repo": repo,
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": latest_version != current_version,
        "asset_name": asset.get("name", ""),
        "asset_size": asset.get("size", 0),
        "published_at": release.get("published_at", ""),
        "release_url": release.get("html_url", ""),
        "download_url": asset.get("browser_download_url", ""),
        "message": "Update available." if latest_version != current_version else "HomeStart is up to date.",
    }


def download_update_asset(url):
    request = urllib.request.Request(url, headers={"User-Agent": "HomeStart updater"})
    limit = 30 * 1024 * 1024
    payload = bytearray()
    with urllib.request.urlopen(request, timeout=30) as response:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > limit:
                raise ValueError("Update package is too large")
    return bytes(payload)


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


class HomeStartHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/api/apps":
            self.send_json(app_payload())
            return


        if route in {"/speedtest", "/speedtest/"}:
            self.path = "/speedtest.html"
            super().do_GET()
            return

        if route == "/api/icon":
            query = parse_qs(parsed.query)
            serve_icon(self, query.get("url", [""])[0])
            return

        if route == "/api/apps/icon":
            query = parse_qs(parsed.query)
            serve_custom_app_icon(self, query.get("key", [""])[0])
            return

        if route == "/api/system":
            self.send_json(system_payload())
            return

        if route == "/api/resources":
            self.send_json(resources_payload())
            return

        if route == "/api/speedtest/history":
            query = parse_qs(parsed.query)
            self.send_json(speedtest_history(query.get("limit", [20])[0]))
            return

        if route == "/api/settings/network":
            self.send_json(network_interfaces_payload())
            return

        if route == "/api/update/check":
            try:
                self.send_json(github_latest_update_asset())
            except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as error:
                self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/status":
            self.send_json(status_payload())
            return

        if route == "/api/files":
            query = parse_qs(parsed.query)
            try:
                self.send_json(file_listing(query.get("path", [""])[0]))
            except (FileNotFoundError, NotADirectoryError, PermissionError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/file/open":
            query = parse_qs(parsed.query)
            try:
                serve_file(self, query.get("path", [""])[0])
            except (FileNotFoundError, IsADirectoryError, PermissionError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/health":
            self.send_json({"ok": True})
            return

        super().do_GET()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/icon":
            query = parse_qs(parsed.query)
            serve_icon(self, query.get("url", [""])[0], include_body=False)
            return

        if parsed.path == "/api/apps/icon":
            query = parse_qs(parsed.query)
            serve_custom_app_icon(self, query.get("key", [""])[0], include_body=False)
            return

        if parsed.path == "/api/file/open":
            query = parse_qs(parsed.query)
            try:
                serve_file(self, query.get("path", [""])[0], include_body=False)
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.end_headers()
            return

        super().do_HEAD()

    def do_POST(self):
        route = urlparse(self.path).path
        if route == "/api/update":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self.send_json(apply_update_package(payload.get("filename", ""), payload.get("content", "")))
            except (json.JSONDecodeError, ValueError, OSError, tarfile.TarError) as error:
                self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/update/github":
            try:
                self.send_json(apply_github_update())
            except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError, tarfile.TarError) as error:
                self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/speedtest/run":
            try:
                self.send_json(speedtest_run())
            except (ValueError, subprocess.SubprocessError, subprocess.TimeoutExpired) as error:
                self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/settings/network":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                result = update_netplan_interface(
                    payload.get("interface", ""),
                    payload.get("mode", ""),
                    payload.get("address", ""),
                    payload.get("gateway", ""),
                    payload.get("dns", []),
                )
                self.send_json(result)
            except (json.JSONDecodeError, ValueError, subprocess.SubprocessError, OSError) as error:
                self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/files/action":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self.send_json(file_action(payload))
            except (json.JSONDecodeError, ValueError, OSError, PermissionError) as error:
                self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/apps/icon":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self.send_json(save_custom_app_icon(payload))
            except (json.JSONDecodeError, ValueError, OSError) as error:
                self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        if route != "/api/apps/action":
            self.send_json({"error": "Route not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            result = app_action(payload)
            self.send_json(result)
        except (json.JSONDecodeError, ValueError, subprocess.SubprocessError) as error:
            self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

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


def main():
    port = int(os.environ.get("PORT", "80"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HomeStartHandler)
    print(f"HomeStart listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()


