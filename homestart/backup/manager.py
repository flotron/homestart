"""Backup archives, inspection, staging and restoration, independent of HTTP.

Paths and application services are injected; this module never imports server.
The caller owns authentication, HTTP responses and service restarts.
"""

import json
import os
import re
import shutil
import tarfile
import tempfile
import time
import uuid
from pathlib import Path


def safe_extract_tar(archive, destination):
    destination = destination.resolve()
    for member in archive.getmembers():
        member_path = (destination / member.name).resolve()
        if destination != member_path and destination not in member_path.parents:
            raise ValueError("Backup contains an invalid path")
        if member.issym() or member.islnk() or member.isdev():
            raise ValueError("Backup contains an unsupported entry")
    archive.extractall(destination)


def atomic_restore_file(source, destination, mode=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.restore-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        if mode is not None:
            temporary.chmod(mode)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


class BackupManager:
    """Operate on one installation's backups with explicit dependencies."""

    def __init__(self, *, backup_dir, staging_dir, config_path, database_path,
                 icon_dir, icon_index, auth_manager, save_config,
                 max_upload_size, max_extracted_size, stage_ttl):
        self.backup_dir = Path(backup_dir)
        self.staging_dir = Path(staging_dir)
        self.config_path = Path(config_path)
        self.database_path = Path(database_path)
        self.icon_dir = Path(icon_dir)
        self.icon_index = Path(icon_index)
        self.auth_manager = auth_manager
        self.save_config = save_config
        self.max_upload_size = max_upload_size
        self.max_extracted_size = max_extracted_size
        self.stage_ttl = stage_ttl

    def create_backup(self, destination=None):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if destination is None:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            destination = self.backup_dir / f"homestart-backup-{stamp}.tar.gz"
        else:
            destination = Path(destination)
        # Metrics history can make this archive large. Level 1 keeps the portable
        # .tar.gz format while avoiding long CPU-bound waits on homelab hardware.
        with tarfile.open(destination, "w:gz", compresslevel=1) as archive:
            if self.config_path.exists():
                archive.add(self.config_path, arcname="config.json")
            if self.database_path.exists():
                archive.add(self.database_path, arcname="data/homestart.db")
            users_path = self.auth_manager().users_path
            if users_path.exists():
                archive.add(users_path, arcname="data/auth-users.json")
            if self.icon_dir.exists():
                archive.add(self.icon_dir, arcname="data/app-icons")
            if self.icon_index.exists():
                archive.add(self.icon_index, arcname="data/app-icons.json")
        destination.chmod(0o600)
        return {"ok": True, "name": destination.name, "size": destination.stat().st_size, "created_at": int(destination.stat().st_mtime)}

    def list_backups(self):
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        items = [{"name": item.name, "size": item.stat().st_size, "created_at": int(item.stat().st_mtime)} for item in self.backup_dir.glob("homestart-backup-*.tar.gz")]
        return {"ok": True, "backups": sorted(items, key=lambda item: item["created_at"], reverse=True)}

    def backup_path(self, name):
        clean = Path(str(name or "")).name
        target = self.backup_dir / clean
        if not clean.startswith("homestart-backup-") or not clean.endswith(".tar.gz") or not target.is_file():
            raise FileNotFoundError("Backup not found")
        return target

    def cleanup_staged_backups(self):
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - self.stage_ttl
        for item in self.staging_dir.glob("*.tar.gz"):
            try:
                if item.stat().st_mtime < cutoff:
                    item.unlink(missing_ok=True)
            except OSError:
                continue

    def inspect_backup_archive(self, source):
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError("Backup not found")
        if source.stat().st_size > self.max_upload_size:
            raise ValueError("Backup is larger than the 1 GB upload limit")

        allowed_files = {
            "config.json": "HomeStart settings",
            "data/homestart.db": "Metrics and Speedtest history",
            "data/auth-users.json": "Owner account",
            "data/app-icons.json": "Custom app icon index",
        }
        components = []
        seen_components = set()
        extracted_size = 0
        member_count = 0
        with tarfile.open(source, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                member_count += 1
                if member_count > 10000:
                    raise ValueError("Backup contains too many entries")
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Backup contains an invalid path")
                if member.issym() or member.islnk() or member.isdev():
                    raise ValueError("Backup contains an unsupported entry")
                if member.isfile():
                    extracted_size += max(0, member.size)
                    if extracted_size > self.max_extracted_size:
                        raise ValueError("Backup expands beyond the 4 GB safety limit")
                    name = path.as_posix()
                    if name in allowed_files:
                        component = allowed_files[name]
                    elif name.startswith("data/app-icons/"):
                        component = "Custom app icons"
                    else:
                        raise ValueError(f"Backup contains an unsupported file: {name}")
                    if component not in seen_components:
                        seen_components.add(component)
                        components.append(component)

            if not components:
                raise ValueError("The archive does not contain a HomeStart backup")

            for name in ("config.json", "data/auth-users.json", "data/app-icons.json"):
                try:
                    member = archive.getmember(name)
                except KeyError:
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"Backup entry cannot be read: {name}")
                try:
                    payload = json.load(stream)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError(f"Backup contains invalid JSON in {name}") from error
                if not isinstance(payload, dict):
                    raise ValueError(f"Backup contains invalid data in {name}")
                if name == "data/auth-users.json":
                    users = payload.get("users")
                    if not isinstance(users, list) or not users:
                        raise ValueError("Backup does not contain a valid owner account")
                    owner = users[0]
                    if (
                        not isinstance(owner, dict)
                        or not str(owner.get("id") or "").strip()
                        or not str(owner.get("username") or "").strip()
                        or not str(owner.get("password") or "").startswith("scrypt$")
                    ):
                        raise ValueError("Backup does not contain a valid owner account")

            try:
                database_member = archive.getmember("data/homestart.db")
            except KeyError:
                database_member = None
            if database_member is not None:
                stream = archive.extractfile(database_member)
                if stream is None or stream.read(16) != b"SQLite format 3\x00":
                    raise ValueError("Backup contains an invalid HomeStart database")

        return {
            "ok": True,
            "size": source.stat().st_size,
            "extracted_size": extracted_size,
            "components": components,
        }

    def stage_backup_upload(self, stream, content_length):
        try:
            length = int(content_length)
        except ValueError as error:
            raise ValueError("Invalid backup upload size") from error
        if length <= 0:
            raise ValueError("Choose a HomeStart backup file")
        if length > self.max_upload_size:
            raise ValueError("Backup is larger than the 1 GB upload limit")

        self.cleanup_staged_backups()
        token = uuid.uuid4().hex
        destination = self.staging_dir / f"{token}.tar.gz"
        remaining = length
        try:
            with destination.open("wb") as output:
                destination.chmod(0o600)
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Backup upload ended unexpectedly")
                    output.write(chunk)
                    remaining -= len(chunk)
            inspection = self.inspect_backup_archive(destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {**inspection, "token": token}

    def staged_backup_path(self, token):
        clean = str(token or "").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", clean):
            raise ValueError("Invalid or expired restore request")
        self.cleanup_staged_backups()
        target = self.staging_dir / f"{clean}.tar.gz"
        if not target.is_file():
            raise FileNotFoundError("The inspected backup expired; choose it again")
        return target

    def restore_backup_file(self, source, display_name=None):
        source = Path(source)
        inspection = self.inspect_backup_archive(source)
        safety_backup = self.create_backup()
        with tempfile.TemporaryDirectory(prefix="homestart-restore-") as directory:
            target = Path(directory)
            with tarfile.open(source, "r:gz") as archive:
                safe_extract_tar(archive, target)
            restored = []
            config = target / "config.json"
            if config.exists():
                self.save_config(json.loads(config.read_text(encoding="utf-8")))
                restored.append("config.json")
            database = target / "data/homestart.db"
            if database.exists():
                atomic_restore_file(database, self.database_path)
                restored.append("data/homestart.db")
            users = target / "data/auth-users.json"
            if users.exists():
                manager = self.auth_manager()
                atomic_restore_file(users, manager.users_path, 0o600)
                manager.setup_token_path.unlink(missing_ok=True)
                manager.revoke_all_sessions()
                restored.append("data/auth-users.json")
            icons = target / "data/app-icons"
            if icons.exists():
                if self.icon_dir.exists():
                    shutil.rmtree(self.icon_dir)
                shutil.copytree(icons, self.icon_dir)
                restored.append("data/app-icons")
            index = target / "data/app-icons.json"
            if index.exists():
                atomic_restore_file(index, self.icon_index)
                restored.append("data/app-icons.json")
        return {
            "ok": True,
            "restored": restored,
            "components": inspection["components"],
            "safety_backup": safety_backup["name"],
            "session_revoked": "data/auth-users.json" in restored,
            "restart": True,
            "message": f"Restored {display_name or source.name}",
        }
