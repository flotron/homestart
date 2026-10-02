"""Docker Hub search and publisher verification with shared cache state."""
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode
from .install import image_repository
from .store import (dockerhub_page_url, dockerhub_repository_from_url,
                    dockerhub_icon_slug, dockerhub_result_score)


class DockerHubClient:
    def __init__(self, enabled, installed_images, host_architecture, cache, lock,
                 opener=None, verifier=None):
        self.enabled = enabled
        self.installed_images = installed_images
        self.host_architecture = host_architecture
        self.cache = cache
        self.lock = lock
        self.opener = opener or urllib.request.urlopen
        self.verifier = verifier or self.dockerhub_verification

    def dockerhub_verification(self, name, official=False):
        if official:
            return {"verified": True, "verification_label": "Docker Official Image", "trusted_rank": 3}
        key = str(name or "").strip().lower()
        now = time.time()
        with self.lock:
            cached = self.cache.get(key)
            if cached and now - cached[0] < 21600:
                return dict(cached[1])
        result = {"verified": False, "verification_label": "", "trusted_rank": 0}
        try:
            request = urllib.request.Request(dockerhub_page_url(key), headers={"User-Agent": "HomeStart/1.0"})
            with self.opener(request, timeout=6) as response:
                page = response.read(1_500_000).decode("utf-8", errors="ignore")
            if "Verified Publisher" in page:
                result = {"verified": True, "verification_label": "Verified Publisher", "trusted_rank": 2}
            elif "Docker-Sponsored Open Source" in page:
                result = {"verified": True, "verification_label": "Docker-Sponsored Open Source", "trusted_rank": 1}
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        with self.lock:
            self.cache[key] = (now, result)
        return dict(result)

    def add_dockerhub_verification(self, results):
        pending = [item for item in results if not item.get("official")]
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(pending)))) as executor:
            checks = list(executor.map(lambda item: self.verifier(item.get("name")), pending))
        for item in results:
            if item.get("official"):
                item.update(self.verifier(item.get("name"), True))
        for item, verification in zip(pending, checks):
            item.update(verification)
        return results

    def dockerhub_search(self, query, limit=12):
        if not self.enabled():
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
            with self.opener(request, timeout=10) as response:
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
        installed = self.installed_images()
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
                    "host_architecture": self.host_architecture()["architecture"],
                    "architectures": [],
                    "architecture_status": "unknown",
                    "architecture_compatible": None,
                }
            )
        self.add_dockerhub_verification(results)
        results.sort(key=lambda item: (item.get("trusted_rank", 0), item["relevance"], item["pulls"], item["stars"]), reverse=True)
        return {
            "ok": True,
            "results": results,
            **self.host_architecture(),
        }
