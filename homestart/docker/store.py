"""Declarative App Store validation, rendering, and Docker Hub helpers."""

import os
import re
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..system.network_config import SUPPORTED_ARCHITECTURES, normalize_architecture


PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
INPUT_TYPES = {"text", "port", "path", "select", "timezone"}
RESERVED_VALUES = {"homestart_data", "server_timezone"}
COMPOSE_KEYS = {"services", "volumes", "networks", "configs", "secrets"}


def placeholders(value):
    if isinstance(value, dict):
        result = set()
        for key, item in value.items():
            result.update(placeholders(key))
            result.update(placeholders(item))
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result.update(placeholders(item))
        return result
    return set(PLACEHOLDER.findall(value)) if isinstance(value, str) else set()


def replace_placeholders(value, values):
    if isinstance(value, dict):
        return {
            replace_placeholders(key, values): replace_placeholders(item, values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [replace_placeholders(item, values) for item in value]
    if not isinstance(value, str):
        return value
    return PLACEHOLDER.sub(lambda match: str(values[match.group(1)]), value)


def validate_catalog(catalog):
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
        if not isinstance(compose, dict) or set(compose) - COMPOSE_KEYS:
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
            if input_type not in INPUT_TYPES or "default" not in item:
                raise ValueError(f"{app_id}: unsupported input {input_id}")
            label = str(item.get("label") or "").strip()
            if not label or len(label) > 100:
                raise ValueError(f"{app_id}: invalid label for {input_id}")
            clean = {
                "id": input_id,
                "label": label,
                "type": input_type,
                "default": item["default"],
            }
            if placeholders(item["default"]) - RESERVED_VALUES:
                raise ValueError(
                    f"{app_id}: input defaults may only use reserved placeholders"
                )
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
        unknown = placeholders(compose) - input_ids - RESERVED_VALUES
        if unknown:
            raise ValueError(f"{app_id}: undeclared Compose placeholders")
        for service_name, service in services.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(service_name)) or not isinstance(
                service, dict
            ):
                raise ValueError(f"{app_id}: invalid Compose service")
            if (
                not isinstance(service.get("image"), str)
                or not service["image"].strip()
                or "build" in service
            ):
                raise ValueError(
                    f"{app_id}: every Compose service needs a fixed image"
                )
        architectures = source.get("architectures", [])
        if architectures is None:
            architectures = []
        if not isinstance(architectures, list) or len(architectures) > len(
            SUPPORTED_ARCHITECTURES
        ):
            raise ValueError(f"{app_id}: invalid architectures")
        clean_architectures = []
        for value in architectures:
            architecture = normalize_architecture(value)
            if architecture not in SUPPORTED_ARCHITECTURES:
                raise ValueError(f"{app_id}: unsupported architecture {value}")
            if architecture not in clean_architectures:
                clean_architectures.append(architecture)
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
            "architectures": clean_architectures,
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


def normalize_image(image):
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


def normalize_port(value):
    port = str(value or "").strip()
    if not port:
        return ""
    if not port.isdigit():
        raise ValueError("Ports must be numeric")
    number = int(port)
    if number < 1 or number > 65535:
        raise ValueError("Ports must be between 1 and 65535")
    return str(number)


def safe_environment_assignment(value):
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


def install_values(app, supplied, reserved):
    supplied = {} if supplied is None else supplied
    if not isinstance(supplied, dict):
        raise ValueError("Invalid app settings")
    declared = {item["id"] for item in app["inputs"]}
    if set(supplied) - declared:
        raise ValueError("Unknown app setting")
    values = {}
    for item in app["inputs"]:
        input_id = item["id"]
        default = replace_placeholders(item["default"], reserved)
        value = str(supplied.get(input_id, default)).strip()
        if not value or len(value) > 2048 or "\x00" in value or "\n" in value:
            raise ValueError(f"{item['label']} is invalid")
        input_type = item["type"]
        if input_type == "port":
            value = normalize_port(value)
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


def render_compose(app, supplied, reserved):
    values = install_values(app, supplied, reserved)
    compose = replace_placeholders(app["compose"], values)
    if placeholders(compose):
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
        labels.update(
            {
                "com.homestart.managed": "true",
                "com.homestart.template": app["id"],
            }
        )
        service["labels"] = labels
    compose["name"] = ""
    return compose, values


def dockerhub_page_url(name, official=False):
    clean = str(name or "").strip()
    if official and "/" not in clean:
        return f"https://hub.docker.com/_/{quote(clean)}"
    return f"https://hub.docker.com/r/{quote(clean, safe='/')}"


def dockerhub_repository_from_url(value):
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "hub.docker.com",
        "www.hub.docker.com",
    }:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "r":
        repository = "/".join(parts[1:3])
    elif len(parts) >= 2 and parts[0] == "_":
        repository = parts[1]
    else:
        return ""
    pattern = r"^[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)?$"
    return repository if re.match(pattern, repository, re.I) else ""


def dockerhub_icon_slug(image):
    _, _, repo = str(image or "").rpartition("/")
    repo = (repo or str(image or "")).split(":", 1)[0].lower()
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
    return re.sub(r"[^a-z0-9]+", "", repo)[:48]


def dockerhub_result_score(name, description, tokens, compact_query, item):
    normalized_name = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
    normalized_description = re.sub(
        r"[^a-z0-9]+", "", str(description or "").lower()
    )
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
    score += min(80, int(item.get("pull_count") or 0).bit_length() * 4)
    score += min(40, int(item.get("star_count") or 0).bit_length() * 3)
    return score
