"""File browsing and operations with explicit configuration and drive providers."""

import base64
import binascii
import os
import shutil
from pathlib import Path

from .copy import CopyCancelled


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


def path_is_allowed(path, roots):
    return any(path == root or root in path.parents for root in roots)


def inherit_parent_ownership(path):
    """Avoid root-owned browser content when HomeStart runs as a system service."""
    try:
        parent_stat = path.parent.stat()
        os.chown(path, parent_stat.st_uid, parent_stat.st_gid)
    except (OSError, PermissionError):
        pass


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


def decode_data_url(content):
    value = str(content or "")
    if "," in value and value.startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid upload encoding") from error


class FileBrowser:
    """File access policy and operations; no HTTP or server globals."""

    def __init__(self, load_config, default_roots, sidebar_items, drive_entries):
        self.load_config = load_config
        self.default_roots = default_roots
        self.sidebar_items = sidebar_items
        self.drive_entries = drive_entries

    def allowed_roots(self):
        config = self.load_config()
        roots = []
        candidates = config.get("file_roots", []) or self.default_roots
        for item in candidates:
            try:
                root = Path(item).expanduser().resolve()
            except OSError:
                continue
            if root.exists():
                roots.append(root)
        return roots

    def resolve_file_path(self, raw_path):
        roots = self.allowed_roots()
        if not roots:
            raise FileNotFoundError("No file browser roots are available")

        if not raw_path:
            return None

        candidate = Path(raw_path).expanduser().resolve()
        for root in roots:
            if path_is_allowed(candidate, [root]):
                return candidate
        raise PermissionError("Path is outside the allowed roots")

    def file_listing(self, raw_path):
        roots = self.allowed_roots()
        sidebar_items = self.sidebar_items()
        target = self.resolve_file_path(raw_path)

        if target is None:
            return {
                "path": "",
                "parent": "",
                "roots": [item["path"] for item in sidebar_items],
                "root_entries": sidebar_items,
                "drive_entries": self.drive_entries(),
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

        try:
            if not target.exists():
                raise FileNotFoundError("The path does not exist or its mount is no longer available")
            if not target.is_dir():
                raise NotADirectoryError("The path is not a folder")
            target_items = list(target.iterdir())
        except PermissionError as error:
            raise PermissionError(
                f"HomeStart cannot read {target}. Check the mount owner and permissions; "
                "desktop/devmon mounts under /media may need to be remounted for the "
                "account running HomeStart or mounted persistently under /mnt."
            ) from error

        entries = []
        for item in sorted(target_items, key=lambda path: (not path.is_dir(), path.name.lower())):
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
            "drive_entries": self.drive_entries(),
            "entries": entries,
        }

    def file_operations_enabled(self):
        return self.load_config().get("features", {}).get("file_operations", True)

    def ensure_file_operations_enabled(self):
        if not self.file_operations_enabled():
            raise PermissionError("File operations are disabled")

    def resolve_new_child(self, parent_path, name):
        parent = self.resolve_file_path(parent_path)
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
        self.resolve_file_path(str(target))
        return target

    def create_folder(self, parent_path, name):
        self.ensure_file_operations_enabled()
        target = self.resolve_new_child(parent_path, name)
        if target.exists():
            raise FileExistsError("A file or folder with that name already exists")
        target.mkdir()
        inherit_parent_ownership(target)
        return {"ok": True, "path": str(target), "action": "mkdir"}

    def delete_file_path(self, raw_path):
        self.ensure_file_operations_enabled()
        target = self.resolve_file_path(raw_path)
        if target is None:
            raise ValueError("Path is required")
        roots = self.allowed_roots()
        if any(target == root for root in roots):
            raise PermissionError("Allowed roots cannot be deleted")
        if not target.exists():
            raise FileNotFoundError("The path does not exist")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"ok": True, "path": str(target), "action": "delete"}

    def file_properties(self, raw_path):
        target = self.resolve_file_path(raw_path)
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

    def resolve_copy_target(self, source_path, destination_path):
        source = self.resolve_file_path(source_path)
        destination = self.resolve_file_path(destination_path)
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
        self.resolve_file_path(str(target))
        if source.resolve() == target.resolve():
            raise ValueError("Source and destination are the same")
        if source.is_dir() and (target == source or source in target.parents):
            raise ValueError("A folder cannot be copied into itself")
        if target.exists():
            raise FileExistsError("The destination already exists")
        if not target.parent.exists() or not target.parent.is_dir():
            raise NotADirectoryError("Destination parent folder does not exist")
        return source, target

    def resolve_move_target(self, source_path, destination_path):
        source = self.resolve_file_path(source_path)
        destination = self.resolve_file_path(destination_path)
        if source is None or destination is None:
            raise ValueError("Source and destination are required")
        if not source.exists():
            raise FileNotFoundError("The source path does not exist")
        if not destination.exists() or not destination.is_dir():
            raise NotADirectoryError("Destination folder does not exist")

        target = destination / source.name
        if source.resolve() == target.resolve():
            raise ValueError("Source and destination are the same")
        if source.is_dir() and source in target.parents:
            raise ValueError("A folder cannot be moved into itself")
        if target.exists():
            raise FileExistsError("A file or folder with that name already exists")
        self.resolve_file_path(str(target))
        return source, target

    def copy_file_path(self, source_path, destination_path):
        self.ensure_file_operations_enabled()
        source, target = self.resolve_copy_target(source_path, destination_path)

        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        return {"ok": True, "path": str(target), "action": "copy", "message": f"Pasted as {target.name}"}

    def upload_file(self, parent_path, name, content):
        self.ensure_file_operations_enabled()
        target = self.resolve_new_child(parent_path, name)
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

    def rename_file_path(self, raw_path, raw_name):
        self.ensure_file_operations_enabled()
        target = self.resolve_file_path(raw_path)
        name = Path(str(raw_name or "")).name.strip()
        if not name or name in {".", ".."}:
            raise ValueError("Invalid name")
        destination = target.with_name(name)
        self.resolve_file_path(str(destination))
        if destination.exists():
            raise FileExistsError("A file with that name already exists")
        target.rename(destination)
        return {"ok": True, "path": str(destination)}
