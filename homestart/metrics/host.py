"""Host resource collectors with process-local sampling state.

Network sampling and app discovery are injected; this module never imports server.
"""
import json
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from ..files import browser as file_browser

GPU_VENDOR_NAMES = {"0x10de": "NVIDIA", "0x8086": "Intel", "0x1002": "AMD"}

class HostMetrics:
    def __init__(self, *, clamp_percent, process_tracker, process_identity,
                 network_payload, docker_apps):
        self.clamp_percent = clamp_percent
        self.process_tracker = process_tracker
        self.process_identity = process_identity
        self.network_payload = network_payload
        self.docker_apps = docker_apps
        self.cpu_prev = None
        self.cpu_detail_prev = None
        self.gpu_prev = None

    def read_cpu_times(self):
        with Path("/proc/stat").open("r", encoding="utf-8") as file:
            fields = file.readline().split()[1:]

        values = [int(value) for value in fields]
        idle = values[3] + values[4]
        total = sum(values)
        return total, idle

    def read_cpu_counters(self):
        with Path("/proc/stat").open("r", encoding="utf-8") as file:
            fields = [int(value) for value in file.readline().split()[1:]]

        names = ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "guest", "guest_nice"]
        return dict(zip(names, fields + [0] * (len(names) - len(fields))))

    def cpu_percent(self):
        current = self.read_cpu_times()
        if self.cpu_prev is None:
            self.cpu_prev = current
            return None

        total_delta = current[0] - self.cpu_prev[0]
        idle_delta = current[1] - self.cpu_prev[1]
        self.cpu_prev = current
        if total_delta <= 0:
            return None

        return self.clamp_percent((1 - (idle_delta / total_delta)) * 100)

    def cpu_detail_payload(self):
        current = self.read_cpu_counters()
        if self.cpu_detail_prev is None:
            self.cpu_detail_prev = current
            return {
                "user": None,
                "system": None,
                "iowait": None,
                "idle": None,
            }

        delta = {key: current.get(key, 0) - self.cpu_detail_prev.get(key, 0) for key in current}
        self.cpu_detail_prev = current
        total = sum(max(0, value) for value in delta.values())
        if total <= 0:
            return {
                "user": None,
                "system": None,
                "iowait": None,
                "idle": None,
            }

        user = delta.get("user", 0) + delta.get("nice", 0)
        system = delta.get("system", 0) + delta.get("irq", 0) + delta.get("softirq", 0)
        return {
            "user": self.clamp_percent(user / total * 100),
            "system": self.clamp_percent(system / total * 100),
            "iowait": self.clamp_percent(delta.get("iowait", 0) / total * 100),
            "idle": self.clamp_percent(delta.get("idle", 0) / total * 100),
        }

    def memory_payload(self):
        values = {}
        with Path("/proc/meminfo").open("r", encoding="utf-8") as file:
            for line in file:
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0]) * 1024

        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        used = max(0, total - available)
        percent = (used / total * 100) if total else None
        return {
            "used_bytes": used,
            "total_bytes": total,
            "free_bytes": values.get("MemFree", 0),
            "available_bytes": available,
            "used_label": file_browser.format_bytes(used),
            "total_label": file_browser.format_bytes(total),
            "free_label": file_browser.format_bytes(values.get("MemFree", 0)),
            "available_label": file_browser.format_bytes(available),
            "percent": self.clamp_percent(percent),
        }

    def read_first_match(self, paths, pattern):
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            match = re.search(pattern, text, re.MULTILINE)
            if match:
                return match.group(1), str(path)
        return None, None

    def gpu_debug_paths(self, filename):
        root = Path("/sys/kernel/debug/dri")
        if not root.exists():
            return []
        return sorted(root.glob(f"*/{filename}"))

    def gpu_frequency(self):
        raw, source = self.read_first_match(
            self.gpu_debug_paths("i915_frequency_info"),
            r"Actual freq:\s+(\d+)\s+MHz",
        )
        if raw is None:
            return None, None
        return int(raw), source

    def gpu_busy_percent(self):
        paths = self.gpu_debug_paths("i915_engine_info")
        engine_runtime = {}

        for path in paths:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue

            engine = None
            for line in lines:
                stripped = line.strip()
                if stripped and not line.startswith("\t") and re.match(r"^[a-z]+[0-9]+$", stripped):
                    engine = stripped
                    continue

                if engine and stripped.startswith("Runtime:"):
                    match = re.search(r"Runtime:\s+(\d+)ms", stripped)
                    if match:
                        engine_runtime[engine] = int(match.group(1))
                    engine = None

        if not engine_runtime:
            return None

        now = time.monotonic()
        current = (now, engine_runtime)
        if self.gpu_prev is None:
            self.gpu_prev = current
            return None

        elapsed_ms = max(1, (now - self.gpu_prev[0]) * 1000)
        previous = self.gpu_prev[1]
        self.gpu_prev = current

        deltas = [
            max(0, runtime - previous.get(engine, runtime))
            for engine, runtime in engine_runtime.items()
        ]
        if not deltas:
            return None

        return self.clamp_percent((sum(deltas) / (elapsed_ms * max(1, len(deltas)))) * 100)

    def nvidia_gpus_payload(self):
        command = shutil.which("nvidia-smi")
        if not command:
            return []
        try:
            output = subprocess.check_output(
                [
                    command,
                    "--query-gpu=index,name,utilization.gpu,clocks.gr,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=2,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

        gpus = []
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 6:
                continue
            try:
                index = int(parts[0])
            except ValueError:
                index = len(gpus)
            try:
                percent = float(parts[2])
            except ValueError:
                percent = None
            try:
                frequency = int(float(parts[3]))
            except ValueError:
                frequency = None
            try:
                memory_used = int(float(parts[4])) * 1024 * 1024
                memory_total = int(float(parts[5])) * 1024 * 1024
            except ValueError:
                memory_used = 0
                memory_total = 0
            gpus.append(
                {
                    "index": index,
                    "name": parts[1] or f"NVIDIA GPU {index}",
                    "percent": self.clamp_percent(percent),
                    "frequency_mhz": frequency,
                    "memory_used_bytes": memory_used,
                    "memory_total_bytes": memory_total,
                    "memory_used_label": file_browser.format_bytes(memory_used),
                    "memory_total_label": file_browser.format_bytes(memory_total),
                    "memory_percent": self.clamp_percent((memory_used / memory_total * 100) if memory_total else None),
                    "available": percent is not None or frequency is not None,
                    "source": "nvidia-smi",
                }
            )
        return gpus

    def detected_gpu_vendors(self, drm_root=Path("/sys/class/drm")):
        vendors = []
        try:
            cards = sorted(drm_root.glob("card[0-9]*"))
        except OSError:
            return vendors
        for card in cards:
            try:
                vendor_id = (card / "device" / "vendor").read_text(
                    encoding="utf-8", errors="replace",
                ).strip().lower()
            except OSError:
                continue
            vendor = GPU_VENDOR_NAMES.get(vendor_id)
            if vendor and vendor not in vendors:
                vendors.append(vendor)
        return vendors

    def nvidia_driver_branch(self, version_path=Path("/proc/driver/nvidia/version")):
        try:
            text = version_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        match = re.search(r"(?:Kernel Module|NVRM version:.*?Kernel Module)\s+(\d+)", text)
        return match.group(1) if match else None

    def gpu_monitor_hint(self, vendors=None):
        vendors = vendors if vendors is not None else self.detected_gpu_vendors()
        if "NVIDIA" in vendors:
            if shutil.which("nvidia-smi"):
                return {
                    "vendor": "NVIDIA",
                    "title": "NVIDIA counter unavailable",
                    "message": "nvidia-smi is installed but cannot read the GPU. Check that the NVIDIA driver and userspace libraries use the same version.",
                    "command": "nvidia-smi",
                }
            branch = self.nvidia_driver_branch()
            if branch:
                command = f"sudo apt install nvidia-utils-{branch}"
                message = f"Install the NVIDIA {branch} monitoring utilities, then restart HomeStart."
            else:
                command = "sudo ubuntu-drivers install"
                message = "Install the recommended NVIDIA driver and its nvidia-smi utility, then restart the server."
            return {
                "vendor": "NVIDIA",
                "title": "NVIDIA monitoring utility missing",
                "message": message,
                "command": command,
            }
        if "Intel" in vendors:
            return {
                "vendor": "Intel",
                "title": "Intel counter unavailable",
                "message": "HomeStart reads Intel i915 counters directly. Check that the i915 driver and debugfs are available; intel-gpu-tools can help diagnose the GPU.",
                "command": "sudo apt install intel-gpu-tools",
            }
        if "AMD" in vendors:
            return {
                "vendor": "AMD",
                "title": "AMD counter unavailable",
                "message": "HomeStart needs utilization counters exposed by the amdgpu kernel driver. radeontop can help verify that the GPU is reporting activity.",
                "command": "sudo apt install radeontop",
            }
        return {
            "vendor": "",
            "title": "No GPU counter detected",
            "message": "No supported GPU monitoring interface was found. NVIDIA requires nvidia-smi; Intel uses the built-in i915 counters; AMD requires amdgpu counters.",
            "command": "",
        }

    def summarize_gpus(self, gpus):
        available = [gpu for gpu in gpus if gpu.get("available")]
        if not available:
            return {
                "name": "GPU",
                "count": 0,
                "percent": None,
                "frequency_mhz": None,
                "available": False,
                "source": "",
            }

        percents = [gpu["percent"] for gpu in available if gpu.get("percent") is not None]
        frequencies = [gpu["frequency_mhz"] for gpu in available if gpu.get("frequency_mhz")]
        return {
            "name": f"{len(gpus)} GPUs" if len(gpus) > 1 else available[0].get("name", "GPU"),
            "count": len(gpus),
            "percent": max(percents) if percents else None,
            "frequency_mhz": max(frequencies) if frequencies else None,
            "available": True,
            "source": available[0].get("source", ""),
        }

    def system_payload(self, network_channel=None):
        gpus = self.nvidia_gpus_payload()
        if gpus:
            gpu = self.summarize_gpus(gpus)
        else:
            gpu_freq, gpu_source = self.gpu_frequency()
            gpu_busy = self.gpu_busy_percent()
            intel_gpu = {
                "index": 0,
                "name": "Intel GPU",
                "percent": gpu_busy,
                "frequency_mhz": gpu_freq,
                "available": gpu_busy is not None or gpu_freq is not None,
                "source": gpu_source,
            }
            gpus = [intel_gpu] if intel_gpu["available"] else []
            gpu = self.summarize_gpus(gpus)
        if not gpu.get("available"):
            gpu["monitor_hint"] = self.gpu_monitor_hint()
        payload = {
            "timestamp": int(time.time()),
            "cpu": {
                "percent": self.cpu_percent(),
                "top": self.process_tracker.top(
                    self.process_identity
                ),
            },
            "memory": self.memory_payload(),
            "gpu": gpu,
            "gpus": gpus,
            "network": self.network_payload(network_channel) if network_channel else {},
            "temperature": self.temperature_payload(),
        }
        return payload

    def temperature_payload(self):
        values = []
        for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            try:
                value = float(path.read_text().strip())
                values.append(value / 1000 if value > 1000 else value)
            except (OSError, ValueError):
                continue
        celsius = max(values) if values else None
        return {"celsius": round(celsius, 1) if celsius is not None else None, "available": celsius is not None}

    def uptime_label(self):
        try:
            seconds = int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
        except (OSError, ValueError, IndexError):
            return "unknown"

        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if days:
            return f"{days} days, {hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def task_summary(self):
        total = 0
        threads = 0
        running = 0
        sleeping = 0
        other = 0
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue

            total += 1
            try:
                stat = entry.joinpath("stat").read_text(encoding="utf-8", errors="replace").split()
                status = entry.joinpath("status").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            state = stat[2] if len(stat) > 2 else ""
            if state == "R":
                running += 1
            elif state in {"S", "I"}:
                sleeping += 1
            else:
                other += 1

            match = re.search(r"^Threads:\s+(\d+)$", status, flags=re.MULTILINE)
            if match:
                threads += int(match.group(1))

        return {
            "total": total,
            "threads": threads,
            "running": running,
            "sleeping": sleeping,
            "other": other,
        }

    def process_payload(self, limit=12):
        try:
            output = subprocess.check_output(
                ["ps", "-eo", "pid,user,pcpu,pmem,rss,args", "--sort=-pcpu"],
                text=True,
                timeout=3,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

        processes = []
        for line in output.splitlines()[1:]:
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue

            pid, user, cpu, memory, rss, command = parts
            if "ps -eo pid,user,pcpu,pmem,rss,args" in command or "docker stats --no-stream" in command:
                continue
            try:
                rss_bytes = int(rss) * 1024
                raw_cpu = float(cpu)
                memory_percent = float(memory)
            except ValueError:
                rss_bytes = 0
                raw_cpu = 0
                memory_percent = 0

            processes.append(
                {
                    "pid": pid,
                    "user": user,
                    "cpu_percent": self.clamp_percent(raw_cpu),
                    "cpu_raw_percent": raw_cpu,
                    "memory_percent": memory_percent,
                    "memory": file_browser.format_bytes(rss_bytes),
                    "command": command,
                }
            )
            if len(processes) >= limit:
                break
        return processes

    def docker_stats_payload(self):
        try:
            output = subprocess.check_output(
                ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
                text=True,
                timeout=5,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return {}

        stats = {}
        for line in output.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = item.get("Name", "")
            if name:
                stats[name] = item
        return stats

    def container_resources_payload(self):
        stats = self.docker_stats_payload()
        containers = []
        for app in self.docker_apps():
            name = app.get("docker_name") or app.get("name")
            stat = stats.get(name, {})
            containers.append(
                {
                    "name": name,
                    "status": app.get("status", ""),
                    "cpu": stat.get("CPUPerc", "0%"),
                    "memory": stat.get("MemUsage", ""),
                    "memory_percent": stat.get("MemPerc", ""),
                    "ports": app.get("ports", []),
                }
            )
        return containers

    def resources_payload(self):
        memory = self.memory_payload()
        return {
            "hostname": socket.gethostname(),
            "uptime": self.uptime_label(),
            "cpu": self.cpu_detail_payload(),
            "memory": memory,
            "containers": self.container_resources_payload(),
            "tasks": self.task_summary(),
            "processes": self.process_payload(),
        }

