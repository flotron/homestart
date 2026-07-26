"""Transactional HomeStart update package validation and installation."""

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath


EXCLUDED_NAMES = {
    "config.json",
    "data",
    ".git",
    "__pycache__",
    "dist",
    "backups",
    ".env",
    "homestart.service",
}
ALLOWED_PREFIXES = {"static", "scripts", "docs", "homestart"}
ALLOWED_FILES = {
    ".gitignore",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "VERSION",
    "app.py",
    "config.example.json",
    "homestart.service.example",
    "install.sh",
    "package.json",
}
PRIVATE_SUFFIXES = (".db", ".sqlite", ".log")
PRIVATE_FRAGMENTS = (".sqlite-",)


def member_parts(name):
    path = PurePosixPath(name)
    parts = [part for part in path.parts if part not in {"", "."}]
    if parts and parts[0] in {"homestart", "package"}:
        parts = parts[1:]
    return parts


def member_path(name):
    parts = member_parts(name)
    if not parts or any(part == ".." for part in parts):
        return None
    lower_parts = [part.lower() for part in parts]
    if any(part in EXCLUDED_NAMES for part in lower_parts):
        raise ValueError(f"Update package contains protected entry: {name}")
    if any(part.endswith(PRIVATE_SUFFIXES) for part in lower_parts):
        raise ValueError(f"Update package contains private data file: {name}")
    if any(fragment in part for part in lower_parts for fragment in PRIVATE_FRAGMENTS):
        raise ValueError(f"Update package contains private data file: {name}")
    if parts[0] in ALLOWED_PREFIXES or parts[0] in ALLOWED_FILES:
        return Path(*parts)
    return None


def validate_manifest(archive):
    manifest_member = None
    for member in archive.getmembers():
        if member_parts(member.name) == ["package.json"]:
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
    version = str(manifest.get("version") or "").strip()
    if not version or len(version) > 80:
        raise ValueError("Update package version is invalid")
    return manifest


class TransactionalPackageUpdater:
    def __init__(self, base_dir, backup_dir, static_dir):
        self.base_dir = Path(base_dir)
        self.backup_dir = Path(backup_dir)
        self.static_dir = Path(static_dir)

    @staticmethod
    def _atomic_copy(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.homestart-update-{uuid.uuid4().hex}.tmp"
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_json(path, value):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _extract_stage(self, archive, stage_root):
        manifest = validate_manifest(archive)
        members = []
        for member in archive.getmembers():
            relative_target = member_path(member.name)
            if relative_target is None or member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"Unsupported package entry: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Could not read package entry: {member.name}")
            staged = stage_root / relative_target
            staged.parent.mkdir(parents=True, exist_ok=True)
            with staged.open("wb") as output:
                shutil.copyfileobj(source, output)
            mode = member.mode & 0o777
            if mode:
                staged.chmod(mode)
            members.append(relative_target)
        if not members:
            raise ValueError("No updatable files found in package")
        return manifest, members

    @staticmethod
    def _preflight(stage_root, manifest):
        version_path = stage_root / "VERSION"
        if not version_path.is_file() or version_path.read_text(encoding="utf-8").strip() != manifest["version"]:
            raise ValueError("Update VERSION does not match package metadata")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(stage_root)
        environment["HOMESTART_CONFIG"] = str(stage_root / "preflight-config.json")
        command = (
            "import compileall; "
            "assert compileall.compile_dir('homestart', quiet=1); "
            "import app; "
            "assert callable(app.main)"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-c", command],
                cwd=stage_root,
                env=environment,
                text=True,
                capture_output=True,
                timeout=45,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError(f"Update preflight could not run: {error}") from error
        if result.returncode:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            raise ValueError(
                f"Update preflight failed: {detail[-1] if detail else 'Python import failed'}"
            )

    def _rollback(self, transaction):
        for value in reversed(transaction.get("created", [])):
            target = self.base_dir / value
            if target.is_file() or target.is_symlink():
                target.unlink()
        for value in transaction.get("replaced", []) + transaction.get("removed", []):
            backup = Path(transaction["backup_root"]) / value
            if backup.is_file():
                self._atomic_copy(backup, self.base_dir / value)

    def apply_bytes(self, payload):
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="homestart-update-stage-") as temporary:
            temporary_root = Path(temporary)
            archive_path = temporary_root / "update.tar.gz"
            archive_path.write_bytes(payload)
            stage_root = temporary_root / "staged"
            stage_root.mkdir()
            try:
                with tarfile.open(archive_path, "r:gz") as archive:
                    manifest, members = self._extract_stage(archive, stage_root)
            except tarfile.TarError as error:
                raise ValueError("Update package archive is invalid") from error
            self._preflight(stage_root, manifest)

            timestamp = time.strftime("%Y%m%d-%H%M%S")
            backup_root = self.backup_dir / f"update-{timestamp}-{uuid.uuid4().hex[:6]}"
            backup_root.mkdir(parents=True)
            transaction = {
                "schema_version": 1,
                "version": manifest["version"],
                "backup_root": str(backup_root),
                "replaced": [],
                "created": [],
                "removed": [],
                "changed": [],
            }
            packaged_static = {
                value for value in members if value.parts and value.parts[0] == "static"
            }
            stale_static = []
            if packaged_static and self.static_dir.is_dir():
                stale_static = [
                    path.relative_to(self.base_dir)
                    for path in self.static_dir.rglob("*")
                    if path.is_file() and path.relative_to(self.base_dir) not in packaged_static
                ]

            try:
                for relative_target in members:
                    target = self.base_dir / relative_target
                    if target.exists():
                        backup_target = backup_root / relative_target
                        backup_target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, backup_target)
                        transaction["replaced"].append(str(relative_target))
                    else:
                        transaction["created"].append(str(relative_target))
                    self._atomic_copy(stage_root / relative_target, target)
                    transaction["changed"].append(str(relative_target))

                for relative_existing in stale_static:
                    existing = self.base_dir / relative_existing
                    backup_target = backup_root / relative_existing
                    backup_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(existing, backup_target)
                    existing.unlink()
                    transaction["removed"].append(str(relative_existing))
                    transaction["changed"].append(f"removed {relative_existing}")
            except Exception:
                self._rollback(transaction)
                raise

            self._write_json(backup_root / "transaction.json", transaction)
            return {
                "manifest": manifest,
                "backup": str(backup_root),
                "changed": transaction["changed"],
                "transaction": transaction,
            }
