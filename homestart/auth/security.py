"""Login throttling and reverse-proxy aware request security helpers."""

import hashlib
import ipaddress
import math
import threading
import time


COOKIE_SECURE_MODES = {"auto", "always", "never"}
ACCOUNT_DELAYS = (0, 0, 0, 0, 2, 5, 15, 30, 60)
CLIENT_DELAYS = (0,) * 19 + (2, 5, 15, 30, 60)


def normalize_cookie_secure_mode(value):
    mode = str(value or "auto").strip().lower()
    if mode not in COOKIE_SECURE_MODES:
        raise ValueError("Cookie security must be automatic, always secure or never secure")
    return mode


def normalize_trusted_proxies(values):
    if values is None:
        return []
    if isinstance(values, str):
        values = values.replace(",", "\n").splitlines()
    if not isinstance(values, (list, tuple)):
        raise ValueError("Trusted proxies must be a list of IP addresses or networks")
    normalized = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError as error:
            raise ValueError(f"Invalid trusted proxy address or network: {text}") from error
        canonical = str(network)
        if canonical not in normalized:
            normalized.append(canonical)
    if len(normalized) > 64:
        raise ValueError("At most 64 trusted proxy addresses or networks are allowed")
    return normalized


def trusted_proxy_networks(values):
    return [
        ipaddress.ip_network(value, strict=False)
        for value in normalize_trusted_proxies(values)
    ]


def address_in_networks(address, networks):
    try:
        candidate = ipaddress.ip_address(str(address or "").strip())
    except ValueError:
        return False
    return any(candidate.version == network.version and candidate in network for network in networks)


def forwarded_https(headers):
    forwarded = str(headers.get("Forwarded", "") or "")
    if forwarded:
        first_hop = forwarded.split(",", 1)[0]
        for parameter in first_hop.split(";"):
            name, separator, value = parameter.partition("=")
            if separator and name.strip().lower() == "proto":
                return value.strip().strip('"').lower() == "https"
    forwarded_proto = str(headers.get("X-Forwarded-Proto", "") or "")
    if forwarded_proto:
        return forwarded_proto.split(",", 1)[0].strip().lower() == "https"
    return False


def effective_client_ip(peer_ip, headers, trusted_networks):
    if not address_in_networks(peer_ip, trusted_networks):
        return str(peer_ip or "")
    chain = []
    for value in str(headers.get("X-Forwarded-For", "") or "").split(","):
        value = value.strip()
        try:
            chain.append(str(ipaddress.ip_address(value)))
        except ValueError:
            continue
    chain.append(str(peer_ip or ""))
    for address in reversed(chain):
        if not address_in_networks(address, trusted_networks):
            return address
    return chain[0] if chain else str(peer_ip or "")


class LoginRateLimiter:
    """In-memory progressive limiter without permanent account lockouts."""

    def __init__(self, clock=None, window_seconds=15 * 60, max_entries=4096):
        self.clock = clock or time.monotonic
        self.window_seconds = int(window_seconds)
        self.max_entries = int(max_entries)
        self.entries = {}
        self.lock = threading.Lock()

    @staticmethod
    def _account_key(username):
        normalized = str(username or "").strip().casefold()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return ("account", digest)

    @staticmethod
    def _client_key(client_ip):
        return ("client", str(client_ip or "unknown"))

    @staticmethod
    def _delay(schedule, failures):
        if failures <= 0:
            return 0
        return schedule[min(failures, len(schedule)) - 1]

    def _cleanup(self, now):
        expired = [
            key for key, entry in self.entries.items()
            if now - entry["last_failure"] >= self.window_seconds
        ]
        for key in expired:
            self.entries.pop(key, None)
        if len(self.entries) <= self.max_entries:
            return
        oldest = sorted(
            self.entries, key=lambda key: self.entries[key]["last_failure"]
        )
        for key in oldest[:len(self.entries) - self.max_entries]:
            self.entries.pop(key, None)

    def _keys(self, client_ip, username):
        return self._account_key(username), self._client_key(client_ip)

    def retry_after(self, client_ip, username):
        now = self.clock()
        with self.lock:
            self._cleanup(now)
            waits = [
                max(0, self.entries.get(key, {}).get("blocked_until", 0) - now)
                for key in self._keys(client_ip, username)
            ]
        return int(math.ceil(max(waits, default=0)))

    def record_failure(self, client_ip, username):
        now = self.clock()
        account_key, client_key = self._keys(client_ip, username)
        with self.lock:
            self._cleanup(now)
            for key, schedule in (
                (account_key, ACCOUNT_DELAYS),
                (client_key, CLIENT_DELAYS),
            ):
                entry = self.entries.get(key)
                if entry is None or now - entry["last_failure"] >= self.window_seconds:
                    entry = {"failures": 0, "last_failure": now, "blocked_until": 0}
                entry["failures"] += 1
                entry["last_failure"] = now
                delay = self._delay(schedule, entry["failures"])
                entry["blocked_until"] = max(entry["blocked_until"], now + delay)
                self.entries[key] = entry
            wait = max(
                self.entries[account_key]["blocked_until"],
                self.entries[client_key]["blocked_until"],
            ) - now
        return int(math.ceil(max(0, wait)))

    def record_success(self, client_ip, username):
        with self.lock:
            self.entries.pop(self._account_key(username), None)

