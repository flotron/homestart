#!/usr/bin/env python3
"""Exercise clean, previous, pre-modular and data-preserving upgrades."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


REPOSITORY = "flotron/homestart"
PROJECT_ROOT = Path(__file__).parents[1]
LOCAL_DIST = PROJECT_ROOT / "dist"
LEGACY_PREFIXES = {"static", "scripts", "docs"}
LEGACY_FILES = {
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


def relative_member(member_name):
    parts = [part for part in Path(member_name).parts if part not in {"", "."}]
    if parts and parts[0] in {"homestart", "package"}:
        parts = parts[1:]
    if not parts or ".." in parts:
        return None
    return Path(*parts)


def extract_package(archive_path, destination, legacy_only=False):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            relative = relative_member(member.name)
            if relative is None or member.isdir():
                continue
            if not member.isfile():
                raise RuntimeError(f"Unsupported package entry: {member.name}")
            if legacy_only and relative.parts[0] not in LEGACY_PREFIXES | LEGACY_FILES:
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"Could not read {member.name}")
            with target.open("wb") as output:
                output.write(source.read())
            mode = member.mode & 0o777
            if mode:
                target.chmod(mode)


def run_import(install_dir):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(install_dir)
    environment["HOMESTART_CONFIG"] = str(install_dir / "config.json")
    result = subprocess.run(
        [sys.executable, "-c", "import app; assert callable(app.main)"],
        cwd=install_dir,
        env=environment,
        text=True,
        capture_output=True,
        timeout=45,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "HomeStart import failed").strip())


def release_archive(version, cache_dir):
    target = cache_dir / f"homestart-update-{version}.tar.gz"
    if target.is_file():
        return target
    local = LOCAL_DIST / target.name
    if local.is_file():
        target.write_bytes(local.read_bytes())
        return target
    url = (
        f"https://github.com/{REPOSITORY}/releases/download/"
        f"v{version}/homestart-update-{version}.tar.gz"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "HomeStart update matrix"})
    with urllib.request.urlopen(request, timeout=60) as response:
        target.write_bytes(response.read())
    return target


def seed_runtime_data(install_dir):
    files = {
        "config.json": b'{"dashboard":{"title":"Matrix HomeStart"},"file_roots":["/srv/data"]}\n',
        "data/homestart.db": b"synthetic-sqlite-history",
        "data/trash.json": b'{"item":{"original":"/srv/data/file"}}\n',
        "data/app-icons/sample.svg": b"<svg></svg>",
        "data/compose-apps/sample/project.json": b'{"project":"sample","state":"data-preserved"}\n',
        "data/app-data/sample/content.txt": b"application data",
    }
    for relative, content in files.items():
        path = install_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {
        relative: hashlib.sha256((install_dir / relative).read_bytes()).hexdigest()
        for relative in files
    }


def assert_runtime_data(install_dir, expected):
    for relative, digest in expected.items():
        path = install_dir / relative
        if not path.is_file():
            raise RuntimeError(f"Upgrade removed runtime file: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise RuntimeError(f"Upgrade changed runtime file: {relative}")


def apply_with_installed_updater(install_dir, current_archive):
    driver = r'''
import base64
import importlib.util
import json
import os
from pathlib import Path

root = Path(os.environ["MATRIX_INSTALL_DIR"])
server_path = root / "homestart" / "server.py"
if server_path.is_file():
    import homestart.server as app
else:
    spec = importlib.util.spec_from_file_location("matrix_legacy_app", root / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)

app.BASE_DIR = root
app.STATIC_DIR = root / "static"
app.DATA_DIR = root / "data"
app.DB_PATH = app.DATA_DIR / "homestart.db"
app.BACKUP_DIR = app.DATA_DIR / "backups"
app.PACKAGE_PATH = root / "package.json"
app.CONFIG_PATH = root / "config.json"
app.restart_service_later = lambda: None
if hasattr(app, "schedule_update_verifier"):
    app.schedule_update_verifier = lambda *_args, **_kwargs: False
payload = Path(os.environ["MATRIX_CURRENT_ARCHIVE"]).read_bytes()
result = app.apply_update_package(
    Path(os.environ["MATRIX_CURRENT_ARCHIVE"]).name,
    base64.b64encode(payload).decode("ascii"),
)
print(json.dumps({"ok": result.get("ok"), "version": result.get("package", {}).get("version")}))
'''
    environment = dict(os.environ)
    environment.update({
        "PYTHONPATH": str(install_dir),
        "HOMESTART_CONFIG": str(install_dir / "config.json"),
        "MATRIX_INSTALL_DIR": str(install_dir),
        "MATRIX_CURRENT_ARCHIVE": str(current_archive.resolve()),
    })
    result = subprocess.run(
        [sys.executable, "-c", driver],
        cwd=install_dir,
        env=environment,
        text=True,
        capture_output=True,
        timeout=180,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "Upgrade failed").strip())


def upgrade_scenario(name, source_archive, current_archive, work_root):
    install_dir = work_root / name
    extract_package(source_archive, install_dir)
    expected = seed_runtime_data(install_dir)
    apply_with_installed_updater(install_dir, current_archive)
    assert_runtime_data(install_dir, expected)
    run_import(install_dir)
    expected_version = (Path(__file__).parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    installed_version = (install_dir / "VERSION").read_text(encoding="utf-8").strip()
    if installed_version != expected_version:
        raise RuntimeError(f"{name} installed {installed_version}, expected {expected_version}")
    print(f"PASS {name}: {installed_version}, runtime data preserved")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", required=True, type=Path)
    parser.add_argument("--installer", type=Path)
    parser.add_argument(
        "--matrix",
        type=Path,
        default=PROJECT_ROOT / "tests" / "update-matrix.json",
    )
    args = parser.parse_args()
    if not args.update.is_file():
        raise SystemExit(f"Update archive not found: {args.update}")
    installer = args.installer or args.update
    if not installer.is_file():
        raise SystemExit(f"Installer archive not found: {installer}")
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="homestart-update-matrix-") as temporary:
        root = Path(temporary)
        clean = root / "clean"
        extract_package(installer, clean)
        run_import(clean)
        print("PASS clean install")

        legacy = root / "legacy-allowlist"
        extract_package(args.update, legacy, legacy_only=True)
        run_import(legacy)
        print("PASS legacy allowlist bridge")

        cache = root / "release-cache"
        cache.mkdir()
        previous = release_archive(matrix["previous"], cache)
        premodular = release_archive(matrix["premodular"], cache)
        upgrade_scenario("previous-to-current", previous, args.update, root)
        upgrade_scenario("premodular-to-current", premodular, args.update, root)
        for index, version in enumerate(matrix.get("additional", []), start=1):
            additional = release_archive(str(version), cache)
            upgrade_scenario(
                f"additional-{index}-to-current", additional, args.update, root
            )


if __name__ == "__main__":
    main()
