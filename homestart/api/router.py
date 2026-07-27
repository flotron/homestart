"""HTTP route dispatch separated from the host/domain implementation."""

import json
import subprocess
import tarfile
import time
import urllib.error
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse


class ApiRouter:
    def __init__(self, backend):
        self.backend = backend

    @staticmethod
    def json_body(handler):
        length = int(handler.headers.get("Content-Length", "0"))
        return json.loads(handler.rfile.read(length).decode("utf-8"))

    def get(self, handler):
        b = self.backend
        parsed = urlparse(handler.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        if route == "/api/auth/status":
            handler.send_json(b.auth_status(handler))
        elif route == "/api/auth/users":
            handler.send_json(b.auth_users_payload(handler))
        elif route == "/api/apps":
            handler.send_json(b.app_payload())
        elif route in {"/speedtest", "/speedtest/"}:
            handler.path = "/speedtest.html"
            return False
        elif route == "/api/icon":
            b.serve_icon(handler, query.get("url", [""])[0])
        elif route == "/api/apps/icon":
            b.serve_custom_app_icon(handler, query.get("key", [""])[0])
        elif route == "/api/system":
            handler.send_json(b.system_payload(None))
        elif route == "/api/network/live":
            handler.send_json({"ok": True, **b.latest_network_payload()})
        elif route == "/api/network/ranking":
            try:
                handler.send_json(b.container_network_ranking(query.get("period", ["3600"])[0]))
            except ValueError as error:
                handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif route == "/api/overview":
            handler.send_json(b.overview_payload())
        elif route == "/api/metrics/history":
            handler.send_json(b.metrics_history(query.get("hours", ["24"])[0]))
        elif route == "/api/settings/general":
            handler.send_json(b.settings_payload())
        elif route == "/api/store/templates":
            handler.send_json(b.store_templates_payload(query.get("refresh", ["0"])[0] == "1"))
        elif route == "/api/store/install/status":
            try:
                handler.send_json(b.store_install_status(query.get("job_id", [""])[0]))
            except ValueError as error:
                handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.NOT_FOUND)
        elif route == "/api/docker/logs":
            try:
                handler.send_json(b.docker_logs(query.get("name", [""])[0], query.get("tail", ["300"])[0]))
            except ValueError as error:
                handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif route == "/api/backups":
            handler.send_json(b.list_backups())
        elif route == "/api/backups/download":
            try:
                b.serve_backup_download(handler)
            except OSError as error:
                handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif route == "/api/trash":
            handler.send_json(b.trash_listing())
        elif route == "/api/file/download":
            try:
                b.serve_download(handler, query.get("path", [""])[0])
            except (FileNotFoundError, PermissionError, OSError) as error:
                handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif route == "/api/resources":
            handler.send_json(b.resources_payload())
        elif route == "/api/speedtest/history":
            handler.send_json(b.speedtest_history(query.get("limit", [20])[0]))
        elif route == "/api/settings/network":
            handler.send_json(b.network_interfaces_payload())
        elif route == "/api/update/check":
            try:
                handler.send_json(b.github_latest_update_asset())
            except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as error:
                handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif route == "/api/store/search":
            try:
                handler.send_json(b.dockerhub_search(query.get("query", [""])[0], query.get("limit", ["12"])[0]))
            except ValueError as error:
                handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif route == "/api/status":
            handler.send_json(b.status_payload())
        elif route == "/api/files":
            try:
                handler.send_json(b.file_listing(query.get("path", [""])[0]))
            except (FileNotFoundError, NotADirectoryError, PermissionError) as error:
                handler.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif route == "/api/file/properties":
            try:
                handler.send_json(b.file_properties(query.get("path", [""])[0]))
            except (FileNotFoundError, PermissionError, OSError, ValueError) as error:
                handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif route == "/api/files/copy/status":
            try:
                handler.send_json(b.copy_job_status(query.get("job_id", [""])[0]))
            except ValueError as error:
                handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.NOT_FOUND)
        elif route == "/api/samba/shares":
            try:
                handler.send_json(b.samba_shares_payload())
            except (ValueError, OSError, PermissionError) as error:
                handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif route == "/api/file/open":
            try:
                b.serve_file(handler, query.get("path", [""])[0])
            except (FileNotFoundError, IsADirectoryError, PermissionError) as error:
                handler.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        elif route == "/health":
            handler.send_json({"ok": True})
        else:
            return False
        return True

    def head(self, handler):
        b = self.backend
        parsed = urlparse(handler.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/icon":
            b.serve_icon(handler, query.get("url", [""])[0], include_body=False)
        elif parsed.path == "/api/apps/icon":
            b.serve_custom_app_icon(handler, query.get("key", [""])[0], include_body=False)
        elif parsed.path == "/api/file/open":
            try:
                b.serve_file(handler, query.get("path", [""])[0], include_body=False)
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                handler.send_response(HTTPStatus.BAD_REQUEST)
                handler.end_headers()
        else:
            return False
        return True

    def post(self, handler):
        b = self.backend
        route = urlparse(handler.path).path
        try:
            if route == "/api/auth/setup":
                b.auth_setup(handler, self.json_body(handler))
            elif route == "/api/auth/login":
                b.auth_login(handler, self.json_body(handler))
            elif route == "/api/auth/logout":
                b.auth_logout(handler)
            elif route == "/api/auth/users":
                b.auth_users_action(handler, self.json_body(handler))
            elif route == "/api/auth/password":
                b.auth_change_password(handler, self.json_body(handler))
            elif route == "/api/settings/general":
                handler.send_json(b.update_settings(self.json_body(handler)))
            elif route == "/api/backups/restore":
                payload = self.json_body(handler)
                handler.send_json(b.restore_backup(payload.get("name", "")))
            elif route == "/api/trash/restore":
                payload = self.json_body(handler)
                handler.send_json(b.restore_trash_item(payload.get("key", "")))
            elif route == "/api/trash/delete":
                payload = self.json_body(handler)
                handler.send_json(b.delete_trash_item(payload.get("key", "")))
            elif route == "/api/trash/empty":
                handler.send_json(b.empty_trash())
            elif route == "/api/update":
                payload = self.json_body(handler)
                handler.send_json(b.apply_update_package(payload.get("filename", ""), payload.get("content", "")))
            elif route == "/api/update/github":
                handler.send_json(b.apply_github_update())
            elif route == "/api/speedtest/run":
                handler.send_json(b.speedtest_run())
            elif route == "/api/settings/network":
                payload = self.json_body(handler)
                handler.send_json(b.update_network_interface(
                    payload.get("interface", ""),
                    payload.get("mode", ""),
                    payload.get("address", ""),
                    payload.get("gateway", ""),
                    payload.get("dns", []),
                ))
            elif route == "/api/network/monitor":
                payload = self.json_body(handler)
                requested = str(payload.get("interface") or "auto")
                available = {item["name"] for item in b.monitorable_network_interfaces(refresh=True)}
                if requested != "auto" and requested not in available:
                    raise ValueError("Unknown or unavailable network interface")
                handler.send_json(b.update_settings({"network": {"monitor_interface": requested}}))
            elif route == "/api/files/action":
                handler.send_json(b.file_action(self.json_body(handler)))
            elif route == "/api/samba/shares":
                handler.send_json(b.samba_share_action(self.json_body(handler)))
            elif route == "/api/apps/icon":
                handler.send_json(b.save_custom_app_icon(self.json_body(handler)))
            elif route == "/api/store/install":
                handler.send_json(b.start_store_install(self.json_body(handler)), HTTPStatus.ACCEPTED)
            elif route == "/api/apps/action":
                handler.send_json(b.app_action(self.json_body(handler)))
            else:
                handler.send_json({"error": "Route not found"}, HTTPStatus.NOT_FOUND)
            return
        except json.JSONDecodeError as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        except (ValueError, OSError, PermissionError, subprocess.SubprocessError, tarfile.TarError,
                urllib.error.URLError) as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
