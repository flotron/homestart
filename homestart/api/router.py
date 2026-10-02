"""Method-specific route tables with explicit endpoint response handling.

Authentication and CSRF are enforced by HomeStartHandler before dispatch.
Endpoint handlers retain their individual error and streaming behavior.
"""

import json
import subprocess
import tarfile
import urllib.error
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse


class ApiRouter:
    GET_ROUTES = {
        '/api/auth/status': '_get_api_auth_status',
        '/api/auth/users': '_get_api_auth_users',
        '/api/auth/security': '_get_api_auth_security',
        '/api/apps': '_get_api_apps',
        '/speedtest': '_get_speedtest',
        '/speedtest/': '_get_speedtest',
        '/api/icon': '_get_api_icon',
        '/api/apps/icon': '_get_api_apps_icon',
        '/api/system': '_get_api_system',
        '/api/system/power': '_get_api_system_power',
        '/api/network/live': '_get_api_network_live',
        '/api/network/ranking': '_get_api_network_ranking',
        '/api/overview': '_get_api_overview',
        '/api/metrics/history': '_get_api_metrics_history',
        '/api/settings/general': '_get_api_settings_general',
        '/api/store/templates': '_get_api_store_templates',
        '/api/store/install/status': '_get_api_store_install_status',
        '/api/docker/logs': '_get_api_docker_logs',
        '/api/backups': '_get_api_backups',
        '/api/backups/download': '_get_api_backups_download',
        '/api/trash': '_get_api_trash',
        '/api/file/download': '_get_api_file_download',
        '/api/resources': '_get_api_resources',
        '/api/speedtest/history': '_get_api_speedtest_history',
        '/api/settings/network': '_get_api_settings_network',
        '/api/update/check': '_get_api_update_check',
        '/api/store/search': '_get_api_store_search',
        '/api/status': '_get_api_status',
        '/api/files': '_get_api_files',
        '/api/file/properties': '_get_api_file_properties',
        '/api/files/copy/status': '_get_api_files_copy_status',
        '/api/samba/shares': '_get_api_samba_shares',
        '/api/file/open': '_get_api_file_open',
        '/health': '_get_health',
    }

    HEAD_ROUTES = {
        '/api/icon': '_head_api_icon',
        '/api/apps/icon': '_head_api_apps_icon',
        '/api/file/open': '_head_api_file_open',
    }

    POST_ROUTES = {
        '/api/auth/setup': '_post_api_auth_setup',
        '/api/auth/login': '_post_api_auth_login',
        '/api/auth/logout': '_post_api_auth_logout',
        '/api/auth/users': '_post_api_auth_users',
        '/api/auth/password': '_post_api_auth_password',
        '/api/auth/security': '_post_api_auth_security',
        '/api/settings/general': '_post_api_settings_general',
        '/api/system/power': '_post_api_system_power',
        '/api/backups/inspect': '_post_api_backups_inspect',
        '/api/backups/restore': '_post_api_backups_restore',
        '/api/trash/restore': '_post_api_trash_restore',
        '/api/trash/delete': '_post_api_trash_delete',
        '/api/trash/empty': '_post_api_trash_empty',
        '/api/update': '_post_api_update',
        '/api/update/github': '_post_api_update_github',
        '/api/speedtest/run': '_post_api_speedtest_run',
        '/api/settings/network': '_post_api_settings_network',
        '/api/network/monitor': '_post_api_network_monitor',
        '/api/files/action': '_post_api_files_action',
        '/api/samba/shares': '_post_api_samba_shares',
        '/api/apps/icon': '_post_api_apps_icon',
        '/api/store/install': '_post_api_store_install',
        '/api/apps/action': '_post_api_apps_action',
    }

    def __init__(self, backend):
        self.backend = backend

    @staticmethod
    def json_body(handler):
        length = int(handler.headers.get("Content-Length", "0"))
        return json.loads(handler.rfile.read(length).decode("utf-8"))

    def _dispatch(self, routes, handler):
        parsed = urlparse(handler.path)
        endpoint = routes.get(parsed.path)
        if endpoint is None:
            return False
        result = getattr(self, endpoint)(handler, parse_qs(parsed.query))
        return result is not False

    def get(self, handler):
        return self._dispatch(self.GET_ROUTES, handler)

    def head(self, handler):
        return self._dispatch(self.HEAD_ROUTES, handler)

    def post(self, handler):
        try:
            if not self._dispatch(self.POST_ROUTES, handler):
                handler.send_json({"error": "Route not found"}, HTTPStatus.NOT_FOUND)
        except json.JSONDecodeError as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
        except (ValueError, OSError, PermissionError, subprocess.SubprocessError, tarfile.TarError,
                urllib.error.URLError) as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_api_auth_status(self, handler, query):
        b = self.backend
        handler.send_json(b.auth_status(handler))

    def _get_api_auth_users(self, handler, query):
        b = self.backend
        handler.send_json(b.auth_users_payload(handler))

    def _get_api_auth_security(self, handler, query):
        b = self.backend
        handler.send_json(b.auth_security_payload(handler))

    def _get_api_apps(self, handler, query):
        b = self.backend
        handler.send_json(b.app_payload())

    def _get_speedtest(self, handler, query):
        b = self.backend
        handler.path = "/speedtest.html"
        return False

    def _get_api_icon(self, handler, query):
        b = self.backend
        b.serve_icon(handler, query.get("url", [""])[0])

    def _get_api_apps_icon(self, handler, query):
        b = self.backend
        b.serve_custom_app_icon(handler, query.get("key", [""])[0])

    def _get_api_system(self, handler, query):
        b = self.backend
        handler.send_json(b.system_payload(None))

    def _get_api_system_power(self, handler, query):
        b = self.backend
        handler.send_json(b.POWER_MANAGER.status())

    def _get_api_network_live(self, handler, query):
        b = self.backend
        handler.send_json({"ok": True, **b.latest_network_payload()})

    def _get_api_network_ranking(self, handler, query):
        b = self.backend
        try:
            handler.send_json(b.container_network_ranking(query.get("period", ["3600"])[0]))
        except ValueError as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_api_overview(self, handler, query):
        b = self.backend
        handler.send_json(b.overview_payload())

    def _get_api_metrics_history(self, handler, query):
        b = self.backend
        handler.send_json(b.metrics_history(query.get("hours", ["24"])[0]))

    def _get_api_settings_general(self, handler, query):
        b = self.backend
        handler.send_json(b.settings_payload())

    def _get_api_store_templates(self, handler, query):
        b = self.backend
        handler.send_json(b.store_templates_payload(query.get("refresh", ["0"])[0] == "1"))

    def _get_api_store_install_status(self, handler, query):
        b = self.backend
        try:
            handler.send_json(b.store_install_status(query.get("job_id", [""])[0]))
        except ValueError as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.NOT_FOUND)

    def _get_api_docker_logs(self, handler, query):
        b = self.backend
        try:
            handler.send_json(b.docker_logs(query.get("name", [""])[0], query.get("tail", ["300"])[0]))
        except ValueError as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_api_backups(self, handler, query):
        b = self.backend
        handler.send_json(b.list_backups())

    def _get_api_backups_download(self, handler, query):
        b = self.backend
        try:
            b.serve_backup_download(handler)
        except OSError as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_api_trash(self, handler, query):
        b = self.backend
        handler.send_json(b.trash_listing())

    def _get_api_file_download(self, handler, query):
        b = self.backend
        try:
            b.serve_download(handler, query.get("path", [""])[0])
        except (FileNotFoundError, PermissionError, OSError) as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_api_resources(self, handler, query):
        b = self.backend
        handler.send_json(b.resources_payload())

    def _get_api_speedtest_history(self, handler, query):
        b = self.backend
        handler.send_json(b.speedtest_history(query.get("limit", [20])[0]))

    def _get_api_settings_network(self, handler, query):
        b = self.backend
        handler.send_json(b.network_interfaces_payload())

    def _get_api_update_check(self, handler, query):
        b = self.backend
        try:
            handler.send_json(b.github_latest_update_asset())
        except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_api_store_search(self, handler, query):
        b = self.backend
        try:
            handler.send_json(b.dockerhub_search(query.get("query", [""])[0], query.get("limit", ["12"])[0]))
        except ValueError as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_api_status(self, handler, query):
        b = self.backend
        handler.send_json(b.status_payload())

    def _get_api_files(self, handler, query):
        b = self.backend
        try:
            handler.send_json(b.FILE_BROWSER.file_listing(query.get("path", [""])[0]))
        except (FileNotFoundError, NotADirectoryError, PermissionError) as error:
            handler.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_api_file_properties(self, handler, query):
        b = self.backend
        try:
            handler.send_json(b.FILE_BROWSER.file_properties(query.get("path", [""])[0]))
        except (FileNotFoundError, PermissionError, OSError, ValueError) as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_api_files_copy_status(self, handler, query):
        b = self.backend
        try:
            handler.send_json(b.copy_job_status(query.get("job_id", [""])[0]))
        except ValueError as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.NOT_FOUND)

    def _get_api_samba_shares(self, handler, query):
        b = self.backend
        try:
            handler.send_json(b.samba_shares_payload())
        except (ValueError, OSError, PermissionError) as error:
            handler.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_api_file_open(self, handler, query):
        b = self.backend
        try:
            b.serve_file(handler, query.get("path", [""])[0])
        except (FileNotFoundError, IsADirectoryError, PermissionError) as error:
            handler.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _get_health(self, handler, query):
        b = self.backend
        handler.send_json({"ok": True})

    def _head_api_icon(self, handler, query):
        b = self.backend
        b.serve_icon(handler, query.get("url", [""])[0], include_body=False)

    def _head_api_apps_icon(self, handler, query):
        b = self.backend
        b.serve_custom_app_icon(handler, query.get("key", [""])[0], include_body=False)

    def _head_api_file_open(self, handler, query):
        b = self.backend
        try:
            b.serve_file(handler, query.get("path", [""])[0], include_body=False)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            handler.send_response(HTTPStatus.BAD_REQUEST)
            handler.end_headers()

    def _post_api_auth_setup(self, handler, query):
        b = self.backend
        b.auth_setup(handler, self.json_body(handler))

    def _post_api_auth_login(self, handler, query):
        b = self.backend
        b.auth_login(handler, self.json_body(handler))

    def _post_api_auth_logout(self, handler, query):
        b = self.backend
        b.auth_logout(handler)

    def _post_api_auth_users(self, handler, query):
        b = self.backend
        b.auth_users_action(handler, self.json_body(handler))

    def _post_api_auth_password(self, handler, query):
        b = self.backend
        b.auth_change_password(handler, self.json_body(handler))

    def _post_api_auth_security(self, handler, query):
        b = self.backend
        b.auth_security_action(handler, self.json_body(handler))

    def _post_api_settings_general(self, handler, query):
        b = self.backend
        handler.send_json(b.update_settings(self.json_body(handler)))

    def _post_api_system_power(self, handler, query):
        b = self.backend
        handler.send_json(b.POWER_MANAGER.request(self.json_body(handler)), HTTPStatus.ACCEPTED)

    def _post_api_backups_inspect(self, handler, query):
        b = self.backend
        handler.send_json(b.stage_backup_upload(handler))

    def _post_api_backups_restore(self, handler, query):
        b = self.backend
        payload = self.json_body(handler)
        if payload.get("token"):
            handler.send_json(b.restore_staged_backup(payload.get("token", "")))
        else:
            handler.send_json(b.restore_backup(payload.get("name", "")))

    def _post_api_trash_restore(self, handler, query):
        b = self.backend
        payload = self.json_body(handler)
        handler.send_json(b.TRASH_MANAGER.restore_trash_item(payload.get("key", "")))

    def _post_api_trash_delete(self, handler, query):
        b = self.backend
        payload = self.json_body(handler)
        handler.send_json(b.TRASH_MANAGER.delete_trash_item(payload.get("key", "")))

    def _post_api_trash_empty(self, handler, query):
        b = self.backend
        handler.send_json(b.TRASH_MANAGER.empty_trash())

    def _post_api_update(self, handler, query):
        b = self.backend
        payload = self.json_body(handler)
        handler.send_json(b.apply_update_package(payload.get("filename", ""), payload.get("content", "")))

    def _post_api_update_github(self, handler, query):
        b = self.backend
        handler.send_json(b.apply_github_update())

    def _post_api_speedtest_run(self, handler, query):
        b = self.backend
        handler.send_json(b.speedtest_run())

    def _post_api_settings_network(self, handler, query):
        b = self.backend
        payload = self.json_body(handler)
        handler.send_json(b.update_network_interface(
            payload.get("interface", ""),
            payload.get("mode", ""),
            payload.get("address", ""),
            payload.get("gateway", ""),
            payload.get("dns", []),
        ))

    def _post_api_network_monitor(self, handler, query):
        b = self.backend
        payload = self.json_body(handler)
        requested = str(payload.get("interface") or "auto")
        available = {item["name"] for item in b.monitorable_network_interfaces(refresh=True)}
        if requested != "auto" and requested not in available:
            raise ValueError("Unknown or unavailable network interface")
        handler.send_json(b.update_settings({"network": {"monitor_interface": requested}}))

    def _post_api_files_action(self, handler, query):
        b = self.backend
        handler.send_json(b.file_action(self.json_body(handler)))

    def _post_api_samba_shares(self, handler, query):
        b = self.backend
        handler.send_json(b.samba_share_action(self.json_body(handler)))

    def _post_api_apps_icon(self, handler, query):
        b = self.backend
        handler.send_json(b.save_custom_app_icon(self.json_body(handler)))

    def _post_api_store_install(self, handler, query):
        b = self.backend
        handler.send_json(b.start_store_install(self.json_body(handler)), HTTPStatus.ACCEPTED)

    def _post_api_apps_action(self, handler, query):
        b = self.backend
        handler.send_json(b.app_action(self.json_body(handler)))
