"""Storage discovery, read-only managed mounts and disk usage presentation."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from ..files import browser as file_browser


def browsable_filesystem(node):
    """Container signatures are not filesystems mount(8) can browse."""
    filesystem = str(node.get("fstype") or "").lower()
    return bool(filesystem) and filesystem not in {
        "lvm2_member", "crypto_luks", "swap", "zfs_member",
    } and not filesystem.endswith("raid_member")


def normalized_mountpoints(node):
    mountpoints = node.get("mountpoints") or []
    if isinstance(mountpoints, str):
        mountpoints = [mountpoints]
    return [str(item) for item in mountpoints if item]


def iter_block_nodes(payload):
    def visit(node, parent_disk=None):
        disk = node if node.get("type") == "disk" else parent_disk
        yield node, disk
        for child in node.get("children") or []:
            yield from visit(child, disk)

    for device in payload.get("blockdevices") or []:
        yield from visit(device)


class StorageManager:
    def __init__(self, allowed_roots, load_config, mount_root, clamp_percent):
        self.allowed_roots = allowed_roots
        self.load_config = load_config
        self.mount_root = Path(mount_root)
        self.clamp_percent = clamp_percent

    def discovered_mount_roots(self, roots):
        if not roots:
            return []

        mounts = []
        ignored_prefixes = (
            "/dev",
            "/proc",
            "/run/docker",
            "/sys",
            "/var/lib/containerd",
            "/var/lib/docker",
        )
        try:
            lines = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

        for line in lines:
            parts = line.split()
            if len(parts) < 3:
                continue
            source, target, fstype = parts[:3]
            if not source.startswith("/dev/"):
                continue
            if fstype in {"autofs", "devtmpfs", "overlay", "proc", "sysfs", "tmpfs"}:
                continue
            if target == "/" or target.startswith(ignored_prefixes):
                continue
            try:
                mount = Path(target.replace("\\040", " ")).resolve()
            except OSError:
                continue
            if mount.exists() and file_browser.path_is_allowed(mount, roots):
                mounts.append(mount)
        return mounts

    def file_sidebar_roots(self):
        roots = self.allowed_roots()
        combined = []
        seen = set()
        for root in roots + self.discovered_mount_roots(roots):
            key = str(root)
            if key not in seen:
                seen.add(key)
                combined.append(root)
        return combined

    def lsblk_payload(self):
        try:
            result = subprocess.run(
                ["lsblk", "-J", "-o", "NAME,PATH,TYPE,TRAN,FSTYPE,LABEL,MOUNTPOINTS,SIZE,MODEL"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            return {}
        if result.returncode != 0:
            return {}
        try:
            return json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return {}

    def block_node_by_path(self, device_path):
        clean_path = str(device_path or "").strip()
        if not re.fullmatch(r"/dev/[A-Za-z0-9_./+-]+", clean_path):
            raise ValueError("Invalid block device path")
        payload = self.lsblk_payload()
        for node, disk in iter_block_nodes(payload):
            if node.get("path") == clean_path:
                return node, disk or node
        raise FileNotFoundError("Block device was not found")

    def homestart_mountpoint(self, device_path):
        name = Path(device_path).name
        safe_name = re.sub(r"[^A-Za-z0-9_.+-]+", "-", name).strip("-")
        if not safe_name:
            raise ValueError("Invalid block device name")
        return self.mount_root / safe_name

    def mountpoint_allowed(self, path):
        roots = self.allowed_roots()
        return bool(roots) and file_browser.path_is_allowed(path, roots)

    def mount_block_device_readonly(self, device_path):
        self.ensure_file_mounts_enabled()
        node, _disk = self.block_node_by_path(device_path)
        device_type = node.get("type") or ""
        filesystem = node.get("fstype") or ""
        if device_type not in {"part", "lvm", "crypt", "rom"}:
            raise ValueError("Only partitions and volumes can be mounted from HomeStart")
        if not browsable_filesystem(node):
            raise ValueError("This device is a storage container or has no browsable filesystem; open its volume instead")
        mounts = normalized_mountpoints(node)
        if mounts:
            mount = Path(mounts[0]).resolve()
            if not self.mountpoint_allowed(mount):
                raise PermissionError("Mounted path is outside the allowed file roots")
            return {"ok": True, "action": "mount_readonly", "path": str(mount), "already_mounted": True}

        target = self.homestart_mountpoint(device_path).resolve()
        if not self.mountpoint_allowed(target):
            raise PermissionError("HomeStart mount path is outside the allowed file roots")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(exist_ok=True)
        if target.is_symlink():
            raise PermissionError("Mount point cannot be a symlink")
        if os.path.ismount(target):
            return {"ok": True, "action": "mount_readonly", "path": str(target), "already_mounted": True}

        options = "ro,nosuid,nodev,noexec"
        command = ["mount", "-o", options, str(device_path), str(target)]
        try:
            subprocess.check_output(command, text=True, timeout=20, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as error:
            output = (error.output or "").strip()
            raise ValueError(output or "Could not mount the device read-only") from error
        return {"ok": True, "action": "mount_readonly", "path": str(target), "readonly": True}

    def unmount_homestart_device(self, device_path):
        self.ensure_file_mounts_enabled()
        node, _disk = self.block_node_by_path(device_path)
        target = self.homestart_mountpoint(device_path).resolve()
        mounts = [Path(item).resolve() for item in normalized_mountpoints(node)]
        if target not in mounts and not os.path.ismount(target):
            raise ValueError("This device is not mounted by HomeStart")
        if not file_browser.path_is_allowed(target, [self.mount_root.resolve()]):
            raise PermissionError("Only HomeStart-managed mounts can be unmounted here")
        try:
            subprocess.check_output(["umount", str(target)], text=True, timeout=15, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as error:
            output = (error.output or "").strip()
            raise ValueError(output or "Could not unmount the device") from error
        try:
            target.rmdir()
        except OSError:
            pass
        return {"ok": True, "action": "unmount", "path": str(target)}

    def block_mount_metadata(self):
        metadata = {}
        payload = self.lsblk_payload()
        if not payload:
            return metadata

        def visit(node, parent_disk=None):
            device_type = node.get("type") or ""
            disk = node if device_type == "disk" else parent_disk
            for mountpoint in normalized_mountpoints(node):
                try:
                    mount = str(Path(mountpoint).resolve())
                except OSError:
                    mount = str(mountpoint)
                disk_info = disk or node
                transport = disk_info.get("tran") or node.get("tran") or ""
                metadata[mount] = {
                    "device": node.get("path") or node.get("name") or "",
                    "disk": disk_info.get("path") or disk_info.get("name") or "",
                    "filesystem": node.get("fstype") or "",
                    "label": node.get("label") or disk_info.get("label") or "",
                    "model": disk_info.get("model") or "",
                    "size": node.get("size") or disk_info.get("size") or "",
                    "transport": transport,
                    "kind": "usb" if str(transport).lower() == "usb" else "disk",
                }
            for child in node.get("children") or []:
                visit(child, disk)

        for device in payload.get("blockdevices") or []:
            visit(device)
        return metadata

    def physical_drive_entries(self):
        payload = self.lsblk_payload()
        roots = self.allowed_roots()
        entries = []

        def location_payload(node, disk, depth=0):
            mounts = []
            for mountpoint in normalized_mountpoints(node):
                try:
                    mount = str(Path(mountpoint).resolve())
                except OSError:
                    mount = mountpoint
                mounts.append(
                    {
                        "path": mount,
                        "allowed": file_browser.path_is_allowed(Path(mount), roots),
                    }
                )
            transport = disk.get("tran") or node.get("tran") or ""
            device_path = node.get("path") or ""
            mount_target = self.homestart_mountpoint(device_path) if device_path else None
            mounted_by_homestart = any(
                file_browser.path_is_allowed(Path(mount["path"]).resolve(), [self.mount_root.resolve()])
                for mount in mounts
            )
            can_mount = (
                self.file_mounts_enabled()
                and device_path
                and node.get("type") in {"part", "lvm", "crypt", "rom"}
                and browsable_filesystem(node)
                and not mounts
                and mount_target is not None
                and self.mountpoint_allowed(mount_target.resolve())
            )
            return {
                "name": node.get("name") or node.get("path") or "",
                "path": device_path,
                "type": node.get("type") or "",
                "kind": "usb" if str(transport).lower() == "usb" else "disk",
                "transport": transport,
                "filesystem": node.get("fstype") or "",
                "label": node.get("label") or "",
                "size": node.get("size") or "",
                "model": node.get("model") or "",
                "mountpoints": mounts,
                "mount_target": str(mount_target) if mount_target else "",
                "can_mount": bool(can_mount),
                "can_unmount": bool(mounted_by_homestart),
                "mounted_by_homestart": bool(mounted_by_homestart),
                "depth": depth,
            }

        def visit_children(node, disk, depth):
            children = []
            for child in node.get("children") or []:
                item = location_payload(child, disk, depth)
                item["children"] = visit_children(child, disk, depth + 1)
                children.append(item)
            return children

        for disk in payload.get("blockdevices") or []:
            if disk.get("type") != "disk":
                continue
            item = location_payload(disk, disk, 0)
            item["children"] = visit_children(disk, disk, 1)
            entries.append(item)
        return entries

    def file_sidebar_items(self):
        roots = self.file_sidebar_roots()
        disk_metadata = self.block_mount_metadata()
        items = []
        for root in roots:
            root_path = str(root)
            meta = disk_metadata.get(root_path, {})
            name = meta.get("label") or ("Root" if root_path == "/" else Path(root_path).name or root_path)
            kind = meta.get("kind") or ("root" if root_path == "/" else "folder")
            items.append(
                {
                    "path": root_path,
                    "name": name,
                    "kind": kind,
                    "device": meta.get("device", ""),
                    "disk": meta.get("disk", ""),
                    "filesystem": meta.get("filesystem", ""),
                    "label": meta.get("label", ""),
                    "model": meta.get("model", ""),
                    "size": meta.get("size", ""),
                    "transport": meta.get("transport", ""),
                }
            )
        return items

    def file_mounts_enabled(self):
        features = self.load_config().get("features", {})
        return features.get("file_operations", True) and features.get("file_mounts", True)

    def ensure_file_mounts_enabled(self):
        if not self.file_mounts_enabled():
            raise PermissionError("File disk mounting is disabled")

    def disk_payload(self):
        try:
            output = subprocess.check_output(
                [
                    "lsblk",
                    "-J",
                    "-b",
                    "-o",
                    "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL,TRAN",
                ],
                text=True,
                timeout=3,
            )
            devices = json.loads(output).get("blockdevices", [])
        except (json.JSONDecodeError, subprocess.SubprocessError, FileNotFoundError):
            return []

        disks = []
        for device in devices:
            if device.get("type") != "disk":
                continue

            mountpoints = []
            filesystems = []
            used_total = 0
            mounted_total = 0
            seen_mounts = set()
            for child in device.get("children", []):
                if child.get("fstype"):
                    filesystems.append(child["fstype"])

                child_mounts = [
                    mountpoint
                    for mountpoint in (child.get("mountpoints") or [])
                    if mountpoint and mountpoint not in seen_mounts
                ]
                mountpoints.extend(child_mounts)
                seen_mounts.update(child_mounts)
                if not child_mounts:
                    continue

                try:
                    usage = shutil.disk_usage(child_mounts[0])
                except OSError:
                    continue

                used_total += usage.used
                mounted_total += usage.total

            disk_size = int(device.get("size") or 0)
            percent = used_total / mounted_total * 100 if mounted_total else 0
            disks.append(
                {
                    "name": device.get("name", ""),
                    "device": f"/dev/{device.get('name', '')}",
                    "model": (device.get("model") or "").strip(),
                    "serial": device.get("serial") or "",
                    "transport": device.get("tran") or "",
                    "filesystems": sorted(set(filesystems)),
                    "mountpoints": mountpoints,
                    "mountpoint": ", ".join(mountpoints) if mountpoints else "Not mounted",
                    "used": used_total,
                    "total": disk_size,
                    "mounted_total": mounted_total,
                    "free": max(0, mounted_total - used_total),
                    "used_label": file_browser.format_bytes(used_total),
                    "total_label": file_browser.format_bytes(disk_size),
                    "free_label": file_browser.format_bytes(max(0, mounted_total - used_total)),
                    "percent": self.clamp_percent(percent),
                }
            )

        return sorted(disks, key=lambda disk: disk["device"])
