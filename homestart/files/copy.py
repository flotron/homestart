"""Asynchronous File Browser copy jobs."""

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path


class CopyCancelled(Exception):
    """Raised when a user cancels an active copy."""


class CopyManager:
    def __init__(self, jobs, lock, path_usage, buffer_size=8 * 1024 * 1024):
        self.jobs = jobs
        self.lock = lock
        self.path_usage = path_usage
        self.buffer_size = buffer_size
        self.native_cp_cache = {"checked": False, "path": None}

    def update_job(self, job_id, **changes):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job.update(changes)
            total = max(0, int(job.get("total_bytes") or 0))
            copied = max(0, int(job.get("copied_bytes") or 0))
            now_monotonic = time.monotonic()
            last_speed_at = float(job.get("_speed_last_at") or now_monotonic)
            last_speed_bytes = max(0, int(job.get("_speed_last_bytes") or 0))
            speed_elapsed = now_monotonic - last_speed_at
            if job.get("status") == "running" and copied >= last_speed_bytes and speed_elapsed >= .25:
                current_speed = (copied - last_speed_bytes) / speed_elapsed
                previous_speed = max(0, float(job.get("speed_bps") or 0))
                job["speed_bps"] = round(
                    current_speed if not previous_speed else previous_speed * .7 + current_speed * .3
                )
                job["_speed_last_at"] = now_monotonic
                job["_speed_last_bytes"] = copied
            speed = max(0, float(job.get("speed_bps") or 0))
            job["eta_seconds"] = round((total - copied) / speed) if total > copied and speed > 0 else None
            if total:
                job["percent"] = min(100, round(copied / total * 100, 1))
            elif job.get("status") == "completed":
                job["percent"] = 100
            job["updated_at"] = int(time.time())

    def cancelled(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return bool(job and job.get("cancel_requested"))

    def native_cp_path(self):
        if self.native_cp_cache.get("checked"):
            return self.native_cp_cache.get("path")
        path = shutil.which("cp")
        if path:
            try:
                version = subprocess.check_output(
                    [path, "--version"],
                    text=True,
                    timeout=2,
                    stderr=subprocess.STDOUT,
                )
                if "GNU coreutils" not in version:
                    path = None
            except (OSError, subprocess.SubprocessError):
                path = None
        self.native_cp_cache = {"checked": True, "path": path}
        return path

    @staticmethod
    def native_cp_command(path, source, target):
        command = [
            path,
            "--reflink=auto",
            "--sparse=auto",
            "--preserve=timestamps",
        ]
        if source.is_dir():
            command.extend(["--recursive", "--dereference"])
        command.extend(["--", str(source), str(target)])
        return command

    @staticmethod
    def process_copy_bytes(pid):
        try:
            content = Path(f"/proc/{int(pid)}/io").read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None
        counters = {}
        for line in content.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                try:
                    counters[key.strip()] = max(0, int(value.strip()))
                except ValueError:
                    continue
        return counters.get("wchar") or counters.get("write_bytes")

    def native_copy_progress(self, process, source, target, total_bytes):
        copied = None
        if source.is_file() and target.exists():
            try:
                copied = target.stat().st_size
            except OSError:
                pass
        if copied is None:
            copied = self.process_copy_bytes(process.pid)
        return min(max(0, int(copied or 0)), max(0, int(total_bytes or 0)))

    @staticmethod
    def stop_native_copy(process):
        if process.poll() is not None:
            return
        try:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=3)
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def run_native_copy(self, source, target, job_id, total_bytes):
        path = self.native_cp_path()
        if not path:
            return False
        operation = self.status(job_id).get("operation", "copy")
        verb = "Moving" if operation == "move" else "Copying"
        command = self.native_cp_command(path, source, target)
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as error_file:
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=error_file,
                    text=True,
                )
            except OSError:
                return False
            self.update_job(
                job_id,
                engine="native_cp",
                engine_label="Native cp",
                current_file=source.name,
                message=f"{verb} {source.name} with native cp…",
            )
            while True:
                return_code = process.poll()
                if return_code is not None:
                    if return_code:
                        error_file.seek(0)
                        detail = error_file.read().strip()
                        raise OSError(detail[-1200:] or f"Native cp exited with status {return_code}")
                    self.update_job(job_id, copied_bytes=total_bytes)
                    return True
                if self.cancelled(job_id):
                    self.stop_native_copy(process)
                    raise CopyCancelled()
                copied = self.native_copy_progress(process, source, target, total_bytes)
                self.update_job(job_id, copied_bytes=copied)
                time.sleep(.25)

    @staticmethod
    def remove_incomplete(target):
        try:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
        except OSError:
            pass

    def copy_with_progress(self, source, target, job_id):
        operation = self.status(job_id).get("operation", "copy")
        verb = "Moving" if operation == "move" else "Copying"

        def copy_item(source_file, destination_file):
            if self.cancelled(job_id):
                raise CopyCancelled()
            Path(destination_file).parent.mkdir(parents=True, exist_ok=True)
            buffer = bytearray(self.buffer_size)
            with open(source_file, "rb", buffering=0) as input_file, open(
                destination_file, "wb", buffering=0
            ) as output_file:
                if hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_SEQUENTIAL"):
                    try:
                        os.posix_fadvise(input_file.fileno(), 0, 0, os.POSIX_FADV_SEQUENTIAL)
                    except OSError:
                        pass
                while True:
                    if self.cancelled(job_id):
                        raise CopyCancelled()
                    chunk_size = input_file.readinto(buffer)
                    if not chunk_size:
                        break
                    view = memoryview(buffer)[:chunk_size]
                    while view:
                        if self.cancelled(job_id):
                            raise CopyCancelled()
                        written = output_file.write(view)
                        if not written:
                            raise OSError("The destination stopped accepting data")
                        view = view[written:]
                    with self.lock:
                        job = self.jobs.get(job_id)
                        copied = int(job.get("copied_bytes") or 0) + chunk_size if job else chunk_size
                    self.update_job(job_id, copied_bytes=copied, current_file=Path(source_file).name)
            shutil.copystat(source_file, destination_file)
            return destination_file

        try:
            same_filesystem_move = (
                operation == "move"
                and source.stat().st_dev == target.parent.stat().st_dev
            )
            if same_filesystem_move:
                total_bytes = source.stat().st_size if source.is_file() else 0
                file_count = 1 if source.is_file() else 0
                folder_count = 1 if source.is_dir() else 0
            else:
                total_bytes, file_count, folder_count = self.path_usage(
                    source,
                    cancelled=lambda: self.cancelled(job_id),
                )
            self.update_job(
                job_id,
                total_bytes=total_bytes,
                file_count=file_count,
                folder_count=folder_count,
                status="running",
                speed_bps=0,
                eta_seconds=None,
                engine="python",
                engine_label="Python fallback",
                _speed_last_at=time.monotonic(),
                _speed_last_bytes=0,
                message=f"{verb} {source.name}…",
            )
            if same_filesystem_move:
                source.replace(target)
                self.update_job(
                    job_id,
                    copied_bytes=total_bytes,
                    engine="native_move",
                    engine_label="Native move",
                    current_file=source.name,
                )
            else:
                used_native = self.run_native_copy(source, target, job_id, total_bytes)
                if not used_native:
                    if source.is_dir():
                        shutil.copytree(source, target, copy_function=copy_item)
                    else:
                        copy_item(source, target)
                if operation == "move":
                    if source.is_dir():
                        shutil.rmtree(source)
                    else:
                        source.unlink()
            engine = self.status(job_id).get("engine_label", "Python fallback")
            self.update_job(
                job_id,
                status="completed",
                copied_bytes=total_bytes,
                path=str(target),
                message=(
                    f"Moved as {target.name} with {engine}"
                    if operation == "move"
                    else f"Pasted as {target.name} with {engine}"
                ),
                completed_at=int(time.time()),
            )
        except CopyCancelled:
            self.remove_incomplete(target)
            self.update_job(
                job_id,
                status="cancelled",
                message="Copy cancelled. The incomplete destination was removed.",
                completed_at=int(time.time()),
                speed_bps=0,
                eta_seconds=None,
            )
        except Exception as error:
            if operation == "move" and not source.exists() and target.exists():
                try:
                    target.replace(source)
                except OSError:
                    pass
            else:
                self.remove_incomplete(target)
            self.update_job(
                job_id,
                status="failed",
                error=str(error),
                message="Copy failed",
                completed_at=int(time.time()),
            )

    def start(self, source, target, operation="copy"):
        operation = "move" if operation == "move" else "copy"
        verb = "Moving" if operation == "move" else "Calculating"
        now = int(time.time())
        with self.lock:
            expired = [
                key for key, job in self.jobs.items()
                if now - int(job.get("updated_at") or now) > 3600
            ]
            for key in expired:
                self.jobs.pop(key, None)
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "preparing",
                "source": str(source),
                "destination": str(target),
                "name": source.name,
                "operation": operation,
                "copied_bytes": 0,
                "total_bytes": 0,
                "percent": 0,
                "speed_bps": 0,
                "eta_seconds": None,
                "engine": "preparing",
                "engine_label": "Selecting copy engine",
                "cancel_requested": False,
                "message": f"{verb} {source.name}…",
                "created_at": now,
                "updated_at": now,
                "_speed_last_at": time.monotonic(),
                "_speed_last_bytes": 0,
            }
        threading.Thread(
            target=self.copy_with_progress,
            args=(source, target, job_id),
            name=f"file-copy-{job_id[:8]}",
            daemon=True,
        ).start()
        return {"ok": True, "job_id": job_id, "status": "preparing", "name": source.name}

    def status(self, job_id):
        with self.lock:
            job = self.jobs.get(str(job_id or ""))
            if not job:
                raise ValueError("Copy job was not found")
            return {"ok": True, **{
                key: value for key, value in job.items()
                if not key.startswith("_")
            }}

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(str(job_id or ""))
            if not job:
                raise ValueError("Copy job was not found")
            if job.get("status") in {"completed", "failed", "cancelled"}:
                return {"ok": True, **{
                    key: value for key, value in job.items()
                    if not key.startswith("_")
                }}
            job.update({
                "cancel_requested": True,
                "status": "cancelling",
                "message": "Cancelling copy and removing incomplete data…",
                "speed_bps": 0,
                "eta_seconds": None,
                "updated_at": int(time.time()),
            })
            return {"ok": True, "job_id": job["job_id"], "status": "cancelling"}
