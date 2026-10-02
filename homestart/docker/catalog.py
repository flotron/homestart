"""Remote declarative catalog and validated disk cache."""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from ..config import load_json_file
from .store import validate_catalog


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
    return validate_catalog(json.loads(payload.decode("utf-8")))


class CatalogClient:
    def __init__(self, cache_path, lock, ttl, catalog_url, fetch=fetch_store_catalog):
        self._cache_path = cache_path
        self.lock = lock
        self.ttl = ttl
        self.catalog_url = catalog_url
        self.fetch = fetch

    @property
    def cache_path(self):
        value = self._cache_path
        return Path(value() if callable(value) else value)


    def read_store_catalog_cache(self):
        wrapper = load_json_file(self.cache_path, {})
        if not isinstance(wrapper.get("catalog"), dict):
            return None, 0
        try:
            return validate_catalog(wrapper["catalog"]), int(wrapper.get("fetched_at") or 0)
        except (TypeError, ValueError):
            return None, 0

    def save_store_catalog_cache(self, catalog):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"fetched_at": int(time.time()), "catalog": catalog}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.cache_path)

    def load_store_catalog(self, refresh=False):
        with self.lock:
            cached, fetched_at = self.read_store_catalog_cache()
            if cached and not refresh and time.time() - fetched_at < self.ttl:
                return cached, {"source": "cache", "stale": False, "fetched_at": fetched_at}
            url = self.catalog_url()
            if url:
                try:
                    catalog = self.fetch(url)
                    self.save_store_catalog_cache(catalog)
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
