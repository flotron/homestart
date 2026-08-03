"""Discovery of useful native web applications listening on the host."""

from __future__ import annotations

import http.client
import re
import shlex
import ssl
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


EXCLUDED_PORTS = {
    22, 25, 53, 67, 68, 69, 111, 123, 137, 138, 139, 161, 162, 389, 445,
    465, 514, 587, 636, 873, 989, 990, 993, 995, 2049, 2375, 2376, 3306,
    3389, 5432, 5900, 6379, 27017,
}
EXCLUDED_PROCESSES = {
    "containerd", "docker-proxy", "dockerd", "rootlesskit", "sshd",
    "smbd", "nmbd", "winbindd", "systemd-resolve", "rpcbind",
    "nginx", "apache2", "httpd", "caddy", "traefik",
}
TLS_PORTS = {443, 4443, 8443, 9443, 10443}
LISTENER_RE = re.compile(
    r"^LISTEN\s+\d+\s+\d+\s+(?P<address>\S+)\s+\S+(?:\s+users:\(\(\"(?P<process>[^\"]+)\",pid=(?P<pid>\d+),.*)?$"
)


def split_endpoint(endpoint):
    endpoint = str(endpoint or "").strip()
    if endpoint.startswith("[") and "]:" in endpoint:
        host, port = endpoint[1:].rsplit("]:", 1)
    elif ":" in endpoint:
        host, port = endpoint.rsplit(":", 1)
    else:
        return "", None
    try:
        return host, int(port)
    except ValueError:
        return "", None


def parse_ss_listeners(output):
    listeners = []
    seen = set()
    for raw_line in str(output or "").splitlines():
        match = LISTENER_RE.match(raw_line.strip())
        if not match:
            continue
        address, port = split_endpoint(match.group("address"))
        if port is None:
            continue
        pid = int(match.group("pid")) if match.group("pid") else None
        key = (address, port, pid)
        if key in seen:
            continue
        seen.add(key)
        listeners.append({
            "address": address,
            "port": port,
            "pid": pid,
            "process": match.group("process") or "",
        })
    return listeners


def systemd_unit_for_pid(pid, proc_root=Path("/proc")):
    if not pid:
        return ""
    try:
        cgroup = (proc_root / str(pid) / "cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    matches = re.findall(r"(?:^|/)([A-Za-z0-9_.@:-]+\.service)(?:/|$)", cgroup, re.MULTILINE)
    return matches[-1] if matches else ""


def process_details(pid, fallback="", proc_root=Path("/proc")):
    details = {"process": fallback or "", "command": "", "unit": "", "containerized": False}
    if not pid:
        return details
    root = proc_root / str(pid)
    try:
        details["process"] = (root / "comm").read_text(encoding="utf-8", errors="replace").strip() or details["process"]
    except OSError:
        pass
    try:
        cmdline = (root / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        details["command"] = cmdline[:500]
    except OSError:
        pass
    try:
        cgroup = (root / "cgroup").read_text(encoding="utf-8", errors="replace")
        details["containerized"] = bool(re.search(r"/(?:docker|libpod|containerd)[-/]?[0-9a-f]{12,}", cgroup))
    except OSError:
        pass
    details["unit"] = systemd_unit_for_pid(pid, proc_root)
    return details


def display_name(listener, details):
    unit = details.get("unit", "")
    process = details.get("process", "")
    raw = unit.removesuffix(".service") if unit else process
    if not unit and process.lower().startswith(("python", "node")):
        try:
            arguments = shlex.split(details.get("command", ""))[1:]
        except ValueError:
            arguments = []
        script = next((Path(value) for value in arguments if not value.startswith("-") and Path(value).suffix in {".py", ".js", ".mjs", ".cjs"}), None)
        if script:
            raw = script.parent.name if script.stem.lower() in {"app", "main", "server", "index"} else script.stem
    if not raw:
        raw = f"Web app {listener['port']}"
    raw = re.sub(r"[@_.-]+", " ", raw).strip()
    acronyms = {"api", "http", "https", "ip", "nas", "ui", "vpn"}
    return " ".join(word.upper() if word.lower() in acronyms else word.capitalize() for word in raw.split())


def probe_target(listener):
    address = listener.get("address", "")
    if address in {"", "*", "0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    if address.startswith("::ffff:"):
        return address.split("::ffff:", 1)[1]
    return address.split("%", 1)[0]


def probe_http(listener, timeout=0.25):
    host = probe_target(listener)
    port = listener["port"]
    schemes = ("https", "http") if port in TLS_PORTS else ("http", "https")
    for scheme in schemes:
        connection = None
        try:
            if scheme == "https":
                context = ssl._create_unverified_context()
                connection = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
            else:
                connection = http.client.HTTPConnection(host, port, timeout=timeout)
            connection.request("HEAD", "/", headers={"User-Agent": "HomeStart discovery"})
            response = connection.getresponse()
            response.read(256)
            return scheme, int(response.status)
        except (OSError, http.client.HTTPException, ssl.SSLError):
            pass
        finally:
            if connection:
                connection.close()
    return None


class NativeWebAppDiscovery:
    """Collect native web listeners once, then serve a short-lived cache."""

    def __init__(self, ttl=60, command_runner=None, proc_root=Path("/proc")):
        self.ttl = max(10, int(ttl))
        self.command_runner = command_runner or self._run_ss
        self.proc_root = Path(proc_root)
        self._lock = threading.Lock()
        self._apps = []
        self._collected_at = 0.0
        self._refreshing = False

    @staticmethod
    def _run_ss():
        return subprocess.check_output(
            ["ss", "-H", "-lntp"], text=True, timeout=4, stderr=subprocess.DEVNULL
        )

    def _candidate(self, listener, home_port):
        if listener["port"] in EXCLUDED_PORTS or listener["port"] == home_port:
            return None
        details = process_details(listener.get("pid"), listener.get("process", ""), self.proc_root)
        if details["process"].lower() in EXCLUDED_PROCESSES or details["containerized"]:
            return None
        return listener, details

    def collect(self, public_host, home_port=80):
        try:
            listeners = parse_ss_listeners(self.command_runner())
        except (OSError, subprocess.SubprocessError):
            listeners = []
        candidates = [item for listener in listeners if (item := self._candidate(listener, home_port))]
        # Keep a cold-cache request bounded even on hosts exposing many sockets.
        candidates = candidates[:32]
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(candidates)))) as executor:
            probes = list(executor.map(lambda item: probe_http(item[0]), candidates))

        apps = []
        seen_ports = set()
        seen_processes = set()
        for (listener, details), probe in zip(candidates, probes):
            if not probe or listener["port"] in seen_ports:
                continue
            identity = details.get("unit") or listener.get("pid") or (details.get("process"), listener["port"])
            if identity in seen_processes:
                continue
            seen_ports.add(listener["port"])
            seen_processes.add(identity)
            scheme, status_code = probe
            local_only = listener["address"] in {"127.0.0.1", "::1", "[::1]"}
            url_host = "127.0.0.1" if local_only else public_host
            default_port = (scheme == "http" and listener["port"] == 80) or (scheme == "https" and listener["port"] == 443)
            port_suffix = "" if default_port else f":{listener['port']}"
            description_parts = []
            if details.get("unit"):
                description_parts.append(details["unit"])
            if details.get("process"):
                description_parts.append(f"process: {details['process']}")
            description_parts.append(f"HTTP {status_code}")
            apps.append({
                "name": display_name(listener, details),
                "kind": "Native web app",
                "status": "Detected · local only" if local_only else "Listening",
                "description": " · ".join(description_parts),
                "url": "" if local_only else f"{scheme}://{url_host}{port_suffix}",
                "source": "native-port-discovery",
                "app_type": "native",
                "app_type_label": "Native Linux",
                "tags": ["Native Linux", "Auto-detected", "Web"],
                "available": True,
                "service_name": details.get("unit", ""),
                "service_actionable": False,
                "ports": [str(listener["port"])],
                "process_name": details.get("process", ""),
                "local_only": local_only,
            })
        return apps

    def _background_collect(self, public_host, home_port):
        try:
            apps = self.collect(public_host, home_port)
            with self._lock:
                self._apps = apps
                self._collected_at = time.monotonic()
        finally:
            with self._lock:
                self._refreshing = False

    def snapshot(self, public_host, home_port=80):
        now = time.monotonic()
        with self._lock:
            has_cache = bool(self._collected_at)
            fresh = has_cache and now - self._collected_at < self.ttl
            cached = [dict(app) for app in self._apps]
            if fresh:
                return cached
            if has_cache:
                if not self._refreshing:
                    self._refreshing = True
                    threading.Thread(
                        target=self._background_collect,
                        args=(public_host, home_port),
                        name="native-web-discovery",
                        daemon=True,
                    ).start()
                return cached

        apps = self.collect(public_host, home_port)
        with self._lock:
            self._apps = apps
            self._collected_at = time.monotonic()
        return [dict(app) for app in apps]
