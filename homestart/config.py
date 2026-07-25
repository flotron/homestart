"""Configuration defaults and file persistence."""

import json
import os
from pathlib import Path


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
        "native_service_actions": True,
        "file_browser": True,
        "file_operations": True,
        "file_mounts": True,
        "samba_manager": True,
        "app_uninstall": True,
        "docker_app_store": True,
    },
    "updates": {
        "github_repo": "flotron/homestart",
    },
    "app_store": {
        "catalog_url": os.environ.get(
            "HOMESTART_APP_CATALOG_URL",
            "https://raw.githubusercontent.com/flotron/homestart-apps/main/dist/catalog.json",
        ),
    },
    "appearance": {"theme": "dark", "accent": "#38bdf8", "density": "comfortable"},
    "alerts": {"cpu_percent": 90, "memory_percent": 90, "disk_percent": 90, "temperature_c": 85},
    "network": {"monitor_interface": "auto"},
    "time": {"timezone": "UTC"},
    "trash": {"retention_days": 0},
}


CURATED_APPS = [
    {"name": "Uptime Kuma", "image": "louislam/uptime-kuma:1", "page_url": "https://hub.docker.com/r/louislam/uptime-kuma", "container_port": 3001, "host_port": 3001, "description": "Self-hosted uptime monitoring", "volume": "/opt/uptime-kuma:/app/data"},
    {"name": "Home Assistant", "image": "ghcr.io/home-assistant/home-assistant:stable", "page_url": "https://github.com/home-assistant/core/pkgs/container/home-assistant", "link_label": "GHCR", "container_port": 8123, "host_port": 8123, "description": "Open source home automation", "volume": "/opt/homeassistant:/config"},
    {"name": "Jellyfin", "image": "jellyfin/jellyfin:latest", "page_url": "https://hub.docker.com/r/jellyfin/jellyfin", "container_port": 8096, "host_port": 8096, "description": "Personal media server", "volume": "/opt/jellyfin:/config"},
    {"name": "Nginx Proxy Manager", "image": "jc21/nginx-proxy-manager:latest", "page_url": "https://hub.docker.com/r/jc21/nginx-proxy-manager", "container_port": 81, "host_port": 81, "description": "Visual reverse proxy manager", "volume": "/opt/nginx-proxy-manager:/data"},
    {"name": "Grafana", "image": "grafana/grafana:latest", "page_url": "https://hub.docker.com/r/grafana/grafana", "container_port": 3000, "host_port": 3000, "description": "Metrics dashboards and visualization", "volume": "/opt/grafana:/var/lib/grafana"},
    {"name": "Forgejo", "image": "codeberg.org/forgejo/forgejo:latest", "page_url": "https://codeberg.org/forgejo/forgejo", "link_label": "Codeberg", "container_port": 3000, "host_port": 3000, "description": "Lightweight Git service", "volume": "/opt/forgejo:/data"},
]


def deep_merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_json_file(path, fallback):
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, type(fallback)) else fallback
    except (OSError, json.JSONDecodeError):
        return fallback


def load_config(path):
    data = load_json_file(path, {})
    return deep_merge(DEFAULT_CONFIG, data)


def save_config(path, config):
    if not isinstance(config, dict):
        raise ValueError("Invalid configuration")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return load_config(path)
