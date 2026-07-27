"""Single-owner account and opaque server-side sessions.

HomeStart deliberately keeps authentication separate from Linux and Samba
accounts. The owner retains the same complete dashboard capabilities as the
service had before authentication was introduced. Accounts created by the
short-lived multi-user release remain usable until the owner removes them.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
PASSWORD_MIN_LENGTH = 6
SESSION_SECONDS = 12 * 60 * 60
REMEMBERED_SESSION_SECONDS = 30 * 24 * 60 * 60
SCRYPT_N = 2 ** 16
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 128 * 1024 * 1024


class AuthManager:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.users_path = self.data_dir / "auth-users.json"
        self.sessions_path = self.data_dir / "auth-sessions.db"
        self.setup_token_path = self.data_dir / "setup-token"
        self.lock = threading.RLock()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_sessions()

    @staticmethod
    def _secure_mode(path):
        try:
            Path(path).chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def normalize_username(value):
        username = str(value or "").strip()
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValueError(
                "Username must be 3–64 characters using letters, numbers, dot, dash or underscore"
            )
        return username

    @staticmethod
    def validate_password(value):
        password = str(value or "")
        if len(password) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"Password must contain at least {PASSWORD_MIN_LENGTH} characters")
        if len(password) > 1024:
            raise ValueError("Password is too long")
        return password

    @staticmethod
    def _password_hash(password):
        salt = secrets.token_bytes(16)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            maxmem=SCRYPT_MAXMEM,
            dklen=SCRYPT_DKLEN,
        )
        return "$".join([
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            salt.hex(),
            derived.hex(),
        ])

    @staticmethod
    def _password_matches(password, encoded):
        try:
            algorithm, n, r, p, salt, expected = str(encoded).split("$", 5)
            if algorithm != "scrypt":
                return False
            derived = hashlib.scrypt(
                str(password).encode("utf-8"),
                salt=bytes.fromhex(salt),
                n=int(n),
                r=int(r),
                p=int(p),
                maxmem=SCRYPT_MAXMEM,
                dklen=len(bytes.fromhex(expected)),
            )
            return hmac.compare_digest(derived, bytes.fromhex(expected))
        except (TypeError, ValueError):
            return False

    def _read_users(self):
        try:
            payload = json.loads(self.users_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": 1, "users": []}
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("HomeStart user database could not be read") from error
        users = payload.get("users", []) if isinstance(payload, dict) else []
        if not isinstance(payload, dict) or not isinstance(users, list):
            raise RuntimeError("HomeStart user database is invalid")
        return {
            "schema_version": 1,
            "users": [item for item in users if isinstance(item, dict)],
        }

    def _write_users(self, payload):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.users_path.with_suffix(".json.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.users_path)
            self._secure_mode(self.users_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _initialize_sessions(self):
        with self._connect() as database:
            database.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    csrf_token TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            database.execute(
                "CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at)"
            )
        self._secure_mode(self.sessions_path)

    def _connect(self):
        database = sqlite3.connect(self.sessions_path, timeout=10)
        database.row_factory = sqlite3.Row
        return database

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def has_users(self):
        with self.lock:
            return bool(self._read_users()["users"])

    def ensure_setup_token(self):
        with self.lock:
            if self.has_users():
                self.setup_token_path.unlink(missing_ok=True)
                return ""
            try:
                token = self.setup_token_path.read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
            if len(token) < 24:
                token = secrets.token_urlsafe(24)
                descriptor = os.open(
                    self.setup_token_path,
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                    0o600,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    output.write(token + "\n")
                self._secure_mode(self.setup_token_path)
            return token

    def create_initial_user(self, setup_token, username, password):
        with self.lock:
            if self.has_users():
                raise ValueError("Initial setup has already been completed")
            expected = self.ensure_setup_token()
            if not expected or not hmac.compare_digest(
                str(setup_token or "").strip(), expected
            ):
                raise ValueError("Invalid setup code")
            user = self._new_user(username, password)
            self._write_users({"schema_version": 1, "users": [user]})
            self.setup_token_path.unlink(missing_ok=True)
            return self._public_user(user)

    def _new_user(self, username, password):
        username = self.normalize_username(username)
        password = self.validate_password(password)
        return {
            "id": uuid.uuid4().hex,
            "username": username,
            "username_key": username.casefold(),
            "password": self._password_hash(password),
            "created_at": int(time.time()),
        }

    @staticmethod
    def _public_user(user):
        return {
            "id": user.get("id", ""),
            "username": user.get("username", ""),
            "created_at": int(user.get("created_at", 0) or 0),
        }

    def list_users(self):
        with self.lock:
            return [
                self._public_user(item)
                for item in self._read_users()["users"]
            ]

    def account_state(self, current_user_id=""):
        with self.lock:
            users = [
                self._public_user(item)
                for item in self._read_users()["users"]
            ]
        owner = users[0] if users else None
        return {
            "owner": owner,
            "legacy_users": users[1:],
            "current_user_id": str(current_user_id or ""),
            "current_is_owner": bool(
                owner and owner["id"] == str(current_user_id or "")
            ),
        }

    def create_user(self, username, password):
        raise ValueError("HomeStart supports one owner account")

    def delete_user(self, user_id, current_user_id=""):
        with self.lock:
            payload = self._read_users()
            if len(payload["users"]) <= 1:
                raise ValueError("There are no legacy accounts to remove")
            owner_id = str(payload["users"][0].get("id", ""))
            if owner_id != str(current_user_id or ""):
                raise ValueError("Only the owner account can remove legacy accounts")
            if str(user_id or "") == owner_id:
                raise ValueError("The owner account cannot be deleted")
            remaining = [
                item for item in payload["users"]
                if str(item.get("id", "")) != str(user_id or "")
            ]
            if len(remaining) == len(payload["users"]):
                raise ValueError("User not found")
            self._write_users({"schema_version": 1, "users": remaining})
            self.revoke_user_sessions(user_id)
            return True

    def authenticate(self, username, password):
        key = str(username or "").strip().casefold()
        with self.lock:
            users = self._read_users()["users"]
            user = next(
                (
                    item for item in users
                    if item.get("username_key", str(item.get("username", "")).casefold())
                    == key
                ),
                None,
            )
        comparison_hash = (
            user.get("password", "")
            if user is not None
            else users[0].get("password", "") if users else ""
        )
        password_matches = self._password_matches(password, comparison_hash)
        if user is None or not password_matches:
            return None
        return self._public_user(user)

    def change_password(self, user_id, current_password, new_password):
        new_password = self.validate_password(new_password)
        with self.lock:
            payload = self._read_users()
            user = next(
                (item for item in payload["users"] if item.get("id") == user_id),
                None,
            )
            if user is None or not self._password_matches(
                current_password, user.get("password", "")
            ):
                raise ValueError("Current password is incorrect")
            user["password"] = self._password_hash(new_password)
            self._write_users(payload)
            self.revoke_user_sessions(user_id)
            return True

    def create_session(self, user_id, remember=True):
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        now = int(time.time())
        duration = REMEMBERED_SESSION_SECONDS if remember else SESSION_SECONDS
        expires_at = now + duration
        with self._connect() as database:
            database.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            database.execute(
                """
                INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (self._token_hash(token), user_id, csrf_token, now, expires_at),
            )
        return {
            "token": token,
            "csrf_token": csrf_token,
            "expires_at": expires_at,
            "remember": bool(remember),
        }

    def session(self, token):
        if not token:
            return None
        now = int(time.time())
        with self._connect() as database:
            database.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            row = database.execute(
                """
                SELECT token_hash, user_id, csrf_token, created_at, expires_at
                FROM sessions WHERE token_hash = ? AND expires_at > ?
                """,
                (self._token_hash(token), now),
            ).fetchone()
        if row is None:
            return None
        with self.lock:
            user = next(
                (
                    item for item in self._read_users()["users"]
                    if item.get("id") == row["user_id"]
                ),
                None,
            )
        if user is None:
            self.revoke_session(token)
            return None
        return {
            "user": self._public_user(user),
            "csrf_token": row["csrf_token"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }

    def csrf_matches(self, session, provided):
        expected = str((session or {}).get("csrf_token", ""))
        return bool(expected) and hmac.compare_digest(expected, str(provided or ""))

    def revoke_session(self, token):
        if not token:
            return
        with self._connect() as database:
            database.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (self._token_hash(token),),
            )

    def revoke_user_sessions(self, user_id):
        with self._connect() as database:
            database.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def revoke_all_sessions(self):
        with self._connect() as database:
            database.execute("DELETE FROM sessions")

    def reset_password(self, username, new_password):
        new_password = self.validate_password(new_password)
        key = str(username or "").strip().casefold()
        with self.lock:
            payload = self._read_users()
            user = next(
                (
                    item for item in payload["users"]
                    if item.get("username_key", str(item.get("username", "")).casefold())
                    == key
                ),
                None,
            )
            if user is None:
                raise ValueError("User not found")
            user["password"] = self._password_hash(new_password)
            self._write_users(payload)
            self.revoke_user_sessions(user["id"])
            return self._public_user(user)
