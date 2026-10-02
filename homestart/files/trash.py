"""HomeStart trash storage and retention, independent of HTTP."""

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from ..config import load_json_file


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


class TrashManager:
    def __init__(self, directory, index_path, browser, load_config):
        self.directory = Path(directory)
        self.index_path = Path(index_path)
        self.browser = browser
        self.load_config = load_config

    def trash_file_path(self, raw_path):
        self.browser.ensure_file_operations_enabled()
        target = self.browser.resolve_file_path(raw_path)
        if target is None or not target.exists():
            raise FileNotFoundError("The file does not exist")
        if any(target == root for root in self.browser.allowed_roots()):
            raise PermissionError("Allowed roots cannot be moved to trash")
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{int(time.time())}-{uuid.uuid4().hex[:8]}-{target.name}"
        index = load_json_file(self.index_path, {})
        index[destination.name] = {"original": str(target), "name": target.name, "deleted_at": int(time.time())}
        shutil.move(str(target), destination)
        self.save_trash_index(index)
        return {"ok": True, "message": f"Moved {target.name} to HomeStart trash", "trash_path": str(destination)}

    def save_trash_index(self, index):
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.index_path)

    def resolve_trash_item(self, key):
        raw_key = str(key or "")
        clean_key = Path(raw_key).name
        if clean_key != raw_key or clean_key in {"", ".", ".."}:
            raise ValueError("Invalid trash item")
        root = self.directory.resolve()
        path = root / clean_key
        if path.parent != root:
            raise ValueError("Invalid trash item")
        return clean_key, path

    def delete_trash_item(self, key):
        key, path = self.resolve_trash_item(key)
        index = load_json_file(self.index_path, {})
        if key not in index or not path.exists():
            raise FileNotFoundError("Trash item not found")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        index.pop(key, None)
        self.save_trash_index(index)
        return {"ok": True, "deleted": key}

    def empty_trash(self):
        index = load_json_file(self.index_path, {})
        deleted = 0
        for key in list(index):
            try:
                self.delete_trash_item(key)
                deleted += 1
            except FileNotFoundError:
                index.pop(key, None)
        self.save_trash_index({})
        return {"ok": True, "deleted": deleted}

    def cleanup_expired_trash(self):
        now = time.time()
        retention = int(self.load_config().get("trash", {}).get("retention_days", 0) or 0)
        if retention <= 0:
            return 0
        cutoff = now - retention * 86400
        index = load_json_file(self.index_path, {})
        expired = [key for key, item in index.items() if float(item.get("deleted_at", 0)) < cutoff]
        deleted = 0
        for key in expired:
            try:
                self.delete_trash_item(key)
                deleted += 1
            except FileNotFoundError:
                continue
        return deleted

    def trash_listing(self):
        index = load_json_file(self.index_path, {})
        items = []
        total_size = 0
        for key, metadata in index.items():
            path = self.directory / key
            if path.exists():
                size = trash_path_size(path)
                total_size += size
                items.append({"key": key, **metadata, "size": size, "type": "directory" if path.is_dir() else "file"})
        return {
            "ok": True,
            "items": sorted(items, key=lambda item: item.get("deleted_at", 0), reverse=True),
            "total_size": total_size,
            "retention_days": int(self.load_config().get("trash", {}).get("retention_days", 0) or 0),
        }

    def restore_trash_item(self, key):
        key, source = self.resolve_trash_item(key)
        index = load_json_file(self.index_path, {})
        metadata = index.get(key)
        if not metadata or not source.exists():
            raise FileNotFoundError("Trash item not found")
        destination = self.browser.resolve_file_path(metadata["original"])
        if destination.exists():
            destination = destination.with_name(f"{destination.stem}-restored{destination.suffix}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), destination)
        index.pop(key, None)
        self.save_trash_index(index)
        return {"ok": True, "path": str(destination)}
