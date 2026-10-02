"""App icon lookup, bounded downloads and custom icon persistence."""
import base64
import binascii
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse


class AppIcons:
    def __init__(self, *, icon_dir, index_path, candidates, urlopen):
        self.icon_dir = icon_dir
        self.index_path = index_path
        self.candidates = tuple(candidates)
        self.urlopen = urlopen
        self.cache = {}

    def with_icon(self, app):
        key = self.app_icon_key(app)
        app["icon_key"] = key
        custom_icon = self.custom_app_icon_url(key)
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

    def fetch_url(self, url):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "HomeStart/1.0",
                "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*,*/*;q=0.8",
            },
        )
        with self.urlopen(request, timeout=2) as response:
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

    def fetch_html_icon_urls(self, app_url):
        request = urllib.request.Request(
            app_url,
            headers={
                "User-Agent": "HomeStart/1.0",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with self.urlopen(request, timeout=2) as response:
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

    def icon_candidates(self, app_url):
        parsed = urlparse(app_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return []

        base = f"{parsed.scheme}://{parsed.netloc}"
        candidates = [f"{base}{path}" for path in self.candidates]
        if parsed.path and parsed.path != "/":
            parent = parsed.path.rsplit("/", 1)[0] or ""
            candidates.extend(f"{base}{parent}{path}" for path in self.candidates)

        try:
            candidates.extend(self.fetch_html_icon_urls(app_url))
        except (urllib.error.URLError, TimeoutError, OSError):
            pass

        return candidates

    def get_icon(self, app_url):
        if app_url in self.cache:
            return self.cache[app_url]

        for candidate in self.icon_candidates(app_url):
            try:
                icon = self.fetch_url(candidate)
            except (urllib.error.URLError, TimeoutError, OSError):
                continue

            if icon:
                self.cache[app_url] = icon
                return icon

        self.cache[app_url] = None
        return None

    def app_icon_key(self, app):
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

    def load_app_icon_index(self):
        try:
            data = json.loads(self.index_path().read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
        return data if isinstance(data, dict) else {}

    def save_app_icon_index(self, data):
        self.index_path().parent.mkdir(parents=True, exist_ok=True)
        self.index_path().write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def custom_app_icon(self, app_key):
        item = self.load_app_icon_index().get(str(app_key or ""))
        if not isinstance(item, dict):
            return None
        filename = item.get("filename", "")
        if not re.fullmatch(r"[a-f0-9]{24}\.(png|jpg|jpeg|gif|webp|svg)", filename):
            return None
        path = self.icon_dir() / filename
        if not path.is_file():
            return None
        return {
            "path": path,
            "content_type": item.get("content_type", "image/png"),
        }

    def custom_app_icon_url(self, app_key):
        return f"/api/apps/icon?key={quote(str(app_key), safe='')}" if self.custom_app_icon(app_key) else ""

    def save_custom_app_icon(self, payload):
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

        self.icon_dir().mkdir(parents=True, exist_ok=True)
        index = self.load_app_icon_index()
        old = self.custom_app_icon(app_key)
        if old:
            old["path"].unlink(missing_ok=True)

        filename = f"{app_key}.{extension}"
        path = self.icon_dir() / filename
        path.write_bytes(body)
        index[app_key] = {
            "filename": filename,
            "content_type": content_type,
            "original_name": name[:120],
            "updated_at": int(time.time()),
        }
        self.save_app_icon_index(index)
        return {
            "ok": True,
            "icon_url": self.custom_app_icon_url(app_key),
        }

