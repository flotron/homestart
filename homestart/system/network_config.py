"""Network configuration and host architecture helpers."""

import ipaddress
import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

import yaml


ARCHITECTURE_ALIASES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv8": "arm64",
    "armv7l": "arm/v7",
    "armv7": "arm/v7",
}
SUPPORTED_ARCHITECTURES = {"amd64", "arm64", "arm/v7"}


def normalize_architecture(value):
    return ARCHITECTURE_ALIASES.get(str(value or "").strip().lower(), "unknown")


def host_architecture(machine=None):
    machine = platform.machine() if machine is None else machine
    architecture = normalize_architecture(machine)
    return {
        "machine": str(machine or ""),
        "architecture": architecture,
        "docker_platform": f"linux/{architecture}" if architecture != "unknown" else "",
    }


def split_nmcli_escaped(value, separator=":"):
    """Split a terse nmcli row while honoring backslash-escaped separators."""
    result = []
    current = []
    escaped = False
    for character in str(value or ""):
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == separator:
            result.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    result.append("".join(current))
    return result


def parse_nmcli_rows(output, columns):
    rows = []
    for raw_line in str(output or "").splitlines():
        if not raw_line.strip():
            continue
        values = split_nmcli_escaped(raw_line)
        values.extend([""] * max(0, len(columns) - len(values)))
        rows.append(dict(zip(columns, values[:len(columns)])))
    return rows


def parse_nmcli_properties(output):
    result = {}
    for raw_line in str(output or "").splitlines():
        if not raw_line.strip():
            continue
        fields = split_nmcli_escaped(raw_line)
        if len(fields) >= 2:
            result[fields[0]] = ":".join(fields[1:])
    return result


def network_manager_config(properties):
    method = str(properties.get("ipv4.method") or "").lower()
    addresses = [
        value.strip()
        for value in str(properties.get("ipv4.addresses") or "").split(",")
        if value.strip()
    ]
    dns = [
        value.strip()
        for value in str(properties.get("ipv4.dns") or "").split(",")
        if value.strip()
    ]
    return {
        "mode": "dhcp" if method == "auto" else "static" if method == "manual" else "unknown",
        "addresses": addresses,
        "gateway": str(properties.get("ipv4.gateway") or ""),
        "dns": dns,
    }


def validate_ipv4_settings(mode, address, gateway, dns):
    if mode not in {"dhcp", "static"}:
        raise ValueError("Invalid network mode")
    if mode == "dhcp":
        return "", "", []
    try:
        address = str(ipaddress.ip_interface(address))
        gateway = str(ipaddress.ip_address(gateway))
        dns_addresses = [
            str(ipaddress.ip_address(item.strip()))
            for item in dns
            if item.strip()
        ]
    except ValueError as error:
        raise ValueError(f"Invalid network value: {error}") from error
    return address, gateway, dns_addresses


class NetplanBackend:
    def __init__(self, root, run):
        self.root = Path(root)
        self.run = run

    def files(self):
        if not self.root.exists():
            return []
        return sorted([*self.root.glob("*.yaml"), *self.root.glob("*.yml")])

    @staticmethod
    def load(path):
        try:
            with Path(path).open("r", encoding="utf-8") as file:
                return yaml.safe_load(file) or {}
        except (OSError, yaml.YAMLError):
            return {}

    def interface_config(self, interface):
        for path in self.files():
            data = self.load(path)
            network = data.get("network", {})
            for section in ("ethernets", "wifis"):
                interfaces = network.get(section, {})
                if interface in interfaces:
                    return path, interfaces[interface]
        return None, {}

    def apply(self, interface, mode, address, gateway, dns):
        address, gateway, dns_addresses = validate_ipv4_settings(
            mode, address, gateway, dns,
        )
        target_file, _ = self.interface_config(interface)
        if target_file is None:
            target_file = self.root / f"90-homestart-{interface}.yaml"
            section = "wifis" if interface.startswith("wl") else "ethernets"
            data = {"network": {"version": 2, "renderer": "networkd", section: {}}}
        else:
            data = self.load(target_file)
            network = data.setdefault("network", {})
            network.setdefault("version", 2)
            network.setdefault("renderer", "networkd")
            section = "ethernets" if interface in network.get("ethernets", {}) else "wifis"
            network.setdefault(section, {})

        network = data.setdefault("network", {})
        interface_config = network.setdefault(section, {}).setdefault(interface, {})
        interface_config.clear()
        if mode == "dhcp":
            interface_config["dhcp4"] = True
        else:
            interface_config["dhcp4"] = False
            interface_config["addresses"] = [address]
            interface_config["routes"] = [{"to": "default", "via": gateway}]
            if dns_addresses:
                interface_config["nameservers"] = {"addresses": dns_addresses}

        target_file.parent.mkdir(parents=True, exist_ok=True)
        backup = target_file.with_suffix(target_file.suffix + f".bak-{int(time.time())}")
        if target_file.exists():
            shutil.copy2(target_file, backup)
        temporary = target_file.with_suffix(target_file.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            yaml.safe_dump(data, file, sort_keys=False)
        temporary.replace(target_file)

        self.run(["netplan", "generate"], timeout=10)
        self.run(["netplan", "apply"], timeout=20)
        return {
            "ok": True,
            "interface": interface,
            "mode": mode,
            "backup": str(backup) if backup.exists() else "",
            "managed_by": "netplan",
        }


class NetworkManagerBackend:
    def __init__(self, run, backup_root):
        self.run = run
        self.backup_root = Path(backup_root)

    def devices(self):
        try:
            output = self.run([
                "--terse", "--escape", "yes",
                "--fields", "DEVICE,TYPE,STATE,CONNECTION",
                "device", "status",
            ])
        except (OSError, subprocess.SubprocessError):
            return {}
        rows = parse_nmcli_rows(output, ("device", "type", "state", "connection"))
        return {
            row["device"]: row
            for row in rows
            if row.get("device") and row.get("type") in {"ethernet", "wifi"}
        }

    def interface_config(self, interface, device=None):
        device = device or self.devices().get(interface, {})
        if str(device.get("state") or "").lower() == "unmanaged":
            return "", {}
        connection = str(device.get("connection") or "").strip()
        if not connection or connection == "--":
            return "", {}
        try:
            output = self.run([
                "--terse", "--escape", "yes",
                "--fields", "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns",
                "connection", "show", connection,
            ])
        except (OSError, subprocess.SubprocessError):
            return connection, {}
        return connection, network_manager_config(parse_nmcli_properties(output))

    def apply(self, interface, mode, address, gateway, dns, device=None, profile=None):
        address, gateway, dns_addresses = validate_ipv4_settings(
            mode, address, gateway, dns,
        )
        device = device or self.devices().get(interface)
        if not device or str(device.get("state") or "").lower() == "unmanaged":
            raise ValueError("This interface is not managed by NetworkManager")
        connection, current = (
            profile if profile is not None
            else self.interface_config(interface, device)
        )
        created = False
        if not connection:
            if device.get("type") != "ethernet":
                raise ValueError("Connect this Wi-Fi interface before changing its IPv4 settings")
            connection = f"homestart-{interface}"
            self.run([
                "connection", "add", "type", "ethernet",
                "ifname", interface, "con-name", connection,
            ], timeout=20)
            created = True

        self.backup_root.mkdir(parents=True, exist_ok=True)
        backup = self.backup_root / f"networkmanager-{interface}-{int(time.time())}.json"
        backup.write_text(
            json.dumps({
                "interface": interface,
                "connection": connection,
                "created_by_homestart": created,
                "configuration": current,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        backup.chmod(0o600)

        values = (
            [
                "ipv4.method", "auto",
                "ipv4.addresses", "",
                "ipv4.gateway", "",
                "ipv4.dns", "",
            ]
            if mode == "dhcp"
            else [
                "ipv4.method", "manual",
                "ipv4.addresses", address,
                "ipv4.gateway", gateway,
                "ipv4.dns", ",".join(dns_addresses),
            ]
        )
        self.run(["connection", "modify", connection, *values], timeout=20)
        self.run(["connection", "up", connection, "ifname", interface], timeout=30)
        return {
            "ok": True,
            "interface": interface,
            "mode": mode,
            "backup": str(backup),
            "managed_by": "networkmanager",
            "connection": connection,
        }
