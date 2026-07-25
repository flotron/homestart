"""GitHub release discovery and download."""

import json
import re
import urllib.error
import urllib.request


def update_asset_version(name):
    match = re.match(r"homestart-update-(.+)\.t(?:ar\.)?gz$", str(name or ""))
    return match.group(1) if match else ""


class GitHubReleaseClient:
    def __init__(self, repo_provider, package_metadata_provider):
        self.repo_provider = repo_provider
        self.package_metadata_provider = package_metadata_provider

    @staticmethod
    def fetch_json(url):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "HomeStart updater",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def latest(self):
        repo = self.repo_provider()
        current_version = self.package_metadata_provider().get("version", "")
        try:
            release = self.fetch_json(f"https://api.github.com/repos/{repo}/releases/latest")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return {
                    "ok": True,
                    "repo": repo,
                    "current_version": current_version,
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
                "current_version": current_version,
                "latest_version": release.get("tag_name", ""),
                "update_available": False,
                "release_url": release.get("html_url", ""),
                "message": "Latest GitHub release does not include a homestart-update package.",
            }

        asset = sorted(update_assets, key=lambda item: str(item.get("name", "")), reverse=True)[0]
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

    @staticmethod
    def download(url, limit=30 * 1024 * 1024):
        request = urllib.request.Request(url, headers={"User-Agent": "HomeStart updater"})
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
