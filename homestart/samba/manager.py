"""Samba configuration parsing and transactional share management."""

import json
import os
import pwd
import re
import subprocess
from pathlib import Path


RESERVED_SHARES = {"global", "homes", "printers", "print$"}


def parse_config(content):
    sections = {}
    current = None
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        match = re.fullmatch(r"\[([^\]]+)\]", line)
        if match:
            current = match.group(1).strip()
            sections[current] = {}
            continue
        if current and "=" in line:
            key, value = line.split("=", 1)
            sections[current][key.strip().lower()] = value.strip()
    return sections


def user_tokens(value):
    return [item for item in re.split(r"[\s,]+", str(value or "").strip()) if item]


def share_payload(name, values, state):
    return {
        "name": name,
        "path": values.get("path", ""),
        "enabled": str(values.get("available", "yes")).lower() not in {"no", "false", "0"},
        "browseable": str(values.get("browseable", values.get("browsable", "yes"))).lower()
        not in {"no", "false", "0"},
        "read_only": str(values.get("read only", "yes")).lower() not in {"no", "false", "0"},
        "guest_ok": str(values.get("guest ok", "no")).lower() in {"yes", "true", "1"},
        "valid_users": user_tokens(values.get("valid users", "")),
        "write_users": user_tokens(values.get("write list", "")),
        "read_users": user_tokens(values.get("read list", "")),
        "force_user": values.get("force user", ""),
        "managed": name in state["shares"],
        "disabled_by_homestart": name in state["disabled"],
    }


def validate_share_name(name):
    clean = str(name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}", clean):
        raise ValueError("Share name contains unsupported characters")
    if clean.lower() in RESERVED_SHARES:
        raise ValueError("This Samba share name is reserved")
    return clean


def render_config(state):
    lines = [
        "# Managed by HomeStart. Runtime server data is not included in HomeStart releases.",
        "",
    ]
    for name, share in sorted(state["shares"].items(), key=lambda item: item[0].lower()):
        lines.extend(
            [
                f"[{name}]",
                f"    path = {share['path']}",
                f"    available = {'no' if name in state['disabled'] else 'yes'}",
                f"    browseable = {'yes' if share.get('browseable', True) else 'no'}",
                f"    read only = {'yes' if share.get('read_only', True) else 'no'}",
                f"    guest ok = {'yes' if share.get('guest_ok', False) else 'no'}",
            ]
        )
        users = share.get("valid_users") or []
        if users:
            lines.append(f"    valid users = {' '.join(users)}")
        if share.get("force_user"):
            lines.extend(
                [
                    f"    force user = {share['force_user']}",
                    "    create mask = 0664",
                    "    directory mask = 0775",
                    "    force create mode = 0660",
                    "    force directory mode = 0770",
                ]
            )
        lines.extend(["", ""])
    for name in sorted(set(state["disabled"]), key=str.lower):
        if name not in state["shares"]:
            lines.extend([f"[{name}]", "    available = no", "", ""])
    return "\n".join(lines).rstrip() + "\n"


def config_with_include(content, managed_path):
    include_line = f"    include = {managed_path}"
    if re.search(rf"(?im)^\s*include\s*=\s*{re.escape(str(managed_path))}\s*$", content):
        return content
    match = re.search(r"(?im)^\s*\[global\]\s*$", content)
    if not match:
        raise ValueError("Samba configuration does not contain a [global] section")
    return content[: match.end()] + "\n" + include_line + content[match.end() :]


class SambaManager:
    def __init__(self, config_path, managed_path, state_path, enabled, resolve_path):
        self.config_path = Path(config_path)
        self.managed_path = Path(managed_path)
        self.state_path = Path(state_path)
        self.enabled = enabled
        self.resolve_path = resolve_path

    def ensure_enabled(self):
        if not self.enabled():
            raise PermissionError("Samba Share Manager is disabled")

    def users(self):
        try:
            output = subprocess.check_output(
                ["pdbedit", "-L"], text=True, timeout=8, stderr=subprocess.DEVNULL
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return []
        users = []
        for line in output.splitlines():
            name, separator, description = line.partition(":")
            if separator and name.strip():
                users.append(
                    {
                        "name": name.strip(),
                        "description": description.rsplit(":", 1)[-1].strip(),
                    }
                )
        return sorted(users, key=lambda item: item["name"].lower())

    def testparm(self, config_path=None):
        try:
            return subprocess.check_output(
                ["testparm", "-s", str(config_path or self.config_path)],
                text=True,
                timeout=10,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as error:
            raise FileNotFoundError("Samba testparm is not installed") from error
        except subprocess.CalledProcessError as error:
            raise ValueError("Samba configuration validation failed") from error

    def state(self):
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            state = {"shares": {}, "disabled": []}
        if not isinstance(state, dict):
            state = {"shares": {}, "disabled": []}
        state.setdefault("shares", {})
        state.setdefault("disabled", [])
        return state

    def shares_payload(self):
        self.ensure_enabled()
        if not self.config_path.exists():
            return {
                "ok": True,
                "available": False,
                "shares": [],
                "users": [],
                "message": f"Samba configuration was not found at {self.config_path}",
            }
        try:
            effective = parse_config(self.testparm())
        except FileNotFoundError as error:
            return {
                "ok": True,
                "available": False,
                "shares": [],
                "users": [],
                "message": str(error),
            }
        state = self.state()
        shares = [
            share_payload(name, values, state)
            for name, values in effective.items()
            if name.lower() not in RESERVED_SHARES and values.get("path")
        ]
        shares.sort(key=lambda item: item["name"].lower())
        return {
            "ok": True,
            "available": True,
            "shares": shares,
            "users": self.users(),
            "passwords_readable": False,
            "message": "Samba passwords are stored as non-reversible hashes and cannot be displayed.",
        }

    def reload(self):
        commands = [
            ["smbcontrol", "all", "reload-config"],
            ["systemctl", "reload", "smbd"],
            ["systemctl", "reload", "smb"],
        ]
        for command in commands:
            try:
                subprocess.check_output(
                    command, text=True, timeout=15, stderr=subprocess.STDOUT
                )
                return
            except (FileNotFoundError, subprocess.SubprocessError):
                continue
        raise ValueError("The Samba configuration is valid, but Samba could not be reloaded")

    def save_state(self, new_state):
        self.ensure_enabled()
        original_main = self.config_path.read_text(encoding="utf-8")
        original_managed = (
            self.managed_path.read_text(encoding="utf-8")
            if self.managed_path.exists()
            else None
        )
        new_main = config_with_include(original_main, self.managed_path)
        self.managed_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.config_path.write_text(new_main, encoding="utf-8")
            self.managed_path.write_text(render_config(new_state), encoding="utf-8")
            self.testparm()
            self.reload()
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(new_state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.state_path)
        except Exception:
            self.config_path.write_text(original_main, encoding="utf-8")
            if original_managed is None:
                try:
                    self.managed_path.unlink()
                except FileNotFoundError:
                    pass
            else:
                self.managed_path.write_text(original_managed, encoding="utf-8")
            try:
                self.reload()
            except (ValueError, OSError):
                pass
            raise
        return self.shares_payload()

    def set_password(self, username, password):
        username = str(username or "").strip()
        password = str(password or "")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}", username):
            raise ValueError("Invalid Linux username")
        if not 4 <= len(password) <= 128:
            raise ValueError("Samba password must contain between 4 and 128 characters")
        try:
            subprocess.check_output(
                ["id", "-u", username],
                text=True,
                timeout=5,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as error:
            raise ValueError("The user must already exist as a Linux account") from error
        try:
            subprocess.run(
                ["smbpasswd", "-s", "-a", username],
                input=f"{password}\n{password}\n",
                text=True,
                capture_output=True,
                check=True,
                timeout=12,
            )
        except FileNotFoundError as error:
            raise FileNotFoundError("smbpasswd is not installed") from error
        except subprocess.CalledProcessError as error:
            raise ValueError(
                (error.stderr or "").strip() or "Could not update the Samba password"
            ) from error
        return self.shares_payload()

    def action(self, payload):
        self.ensure_enabled()
        action = str(payload.get("action") or "")
        if action == "set_password":
            return self.set_password(payload.get("username"), payload.get("password"))
        state = self.state()
        if action in {"create", "update"}:
            name = validate_share_name(payload.get("name"))
            if action == "update" and name not in state["shares"]:
                raise PermissionError("Only shares created by HomeStart can be edited")
            target = self.resolve_path(payload.get("path", ""))
            if target is None or not target.exists() or not target.is_dir():
                raise NotADirectoryError(
                    "Select an existing folder inside the allowed File Browser roots"
                )
            current_names = {
                item["name"].lower() for item in self.shares_payload().get("shares", [])
            }
            if action == "create" and name.lower() in current_names:
                raise FileExistsError("A Samba share with this name already exists")
            requested_users = payload.get("valid_users") or []
            if isinstance(requested_users, str):
                requested_users = user_tokens(requested_users)
            known_users = {item["name"] for item in self.users()}
            unknown = [
                user
                for user in requested_users
                if not user.startswith("@") and user not in known_users
            ]
            if unknown:
                raise ValueError(f"Unknown Samba user: {', '.join(unknown)}")
            if not payload.get("guest_ok") and not requested_users:
                raise ValueError("Choose at least one Samba user or enable guest access")
            guest_ok = bool(payload.get("guest_ok", False))
            read_only = bool(payload.get("read_only", True))
            force_user = ""
            ownership_before = None
            if guest_ok and not read_only:
                force_user = str(payload.get("force_user") or "").strip()
                if not force_user:
                    for candidate in (target, *target.parents):
                        try:
                            owner = pwd.getpwuid(candidate.stat().st_uid)
                        except (KeyError, OSError):
                            continue
                        if owner.pw_uid != 0:
                            force_user = owner.pw_name
                            break
                    if not force_user:
                        raise ValueError(
                            "Could not find a non-root Linux owner; enter a Linux write user"
                        )
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}", force_user):
                    raise ValueError("Invalid Linux write user")
                try:
                    uid = int(
                        subprocess.check_output(
                            ["id", "-u", force_user],
                            text=True,
                            timeout=5,
                            stderr=subprocess.DEVNULL,
                        ).strip()
                    )
                except (
                    FileNotFoundError,
                    subprocess.SubprocessError,
                    ValueError,
                ) as error:
                    raise ValueError(
                        "Guest write user must be an existing Linux account"
                    ) from error
                if uid == 0:
                    raise PermissionError(
                        "Guest shares cannot write as root; choose a non-root Linux user"
                    )
                target_stat = target.stat()
                if target_stat.st_uid != uid:
                    ownership_before = (target_stat.st_uid, target_stat.st_gid)
                    try:
                        os.chown(target, uid, -1)
                    except OSError as error:
                        raise PermissionError(
                            f"Could not grant folder ownership to {force_user}"
                        ) from error
            state["shares"][name] = {
                "path": str(target),
                "browseable": bool(payload.get("browseable", True)),
                "read_only": read_only,
                "guest_ok": guest_ok,
                "valid_users": requested_users,
                "force_user": force_user,
            }
            state["disabled"] = [item for item in state["disabled"] if item != name]
            try:
                return self.save_state(state)
            except Exception:
                if ownership_before:
                    try:
                        os.chown(target, ownership_before[0], ownership_before[1])
                    except OSError:
                        pass
                raise
        if action in {"disable", "enable", "delete"}:
            name = validate_share_name(payload.get("name"))
            if action == "disable":
                if name not in state["disabled"]:
                    state["disabled"].append(name)
            elif action == "enable":
                state["disabled"] = [item for item in state["disabled"] if item != name]
            elif name in state["shares"]:
                del state["shares"][name]
                state["disabled"] = [item for item in state["disabled"] if item != name]
            else:
                raise PermissionError(
                    "Existing Samba shares can be disabled but not deleted by HomeStart"
                )
            return self.save_state(state)
        raise ValueError("Invalid Samba share action")
