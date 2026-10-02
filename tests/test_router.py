"""HTTP dispatch contracts; authentication/CSRF integration lives in test_smoke."""
import io
import json
import unittest
from http import HTTPStatus
from unittest.mock import Mock
from homestart.api.router import ApiRouter


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.router = ApiRouter(self.backend)
        self.handler = Mock()

    def request(self, path, payload=None):
        data = json.dumps(payload or {}).encode()
        self.handler.path = path
        self.handler.headers = {'Content-Length': str(len(data))}
        self.handler.rfile = io.BytesIO(data)
        return self.handler

    def test_apps_uses_persistent_discovery(self):
        self.router.get(self.request('/api/apps'))
        self.backend.APP_DISCOVERY.app_payload.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(self.backend.APP_DISCOVERY.app_payload.return_value)

    def test_wrong_method_never_invokes_power_action(self):
        self.assertFalse(self.router.head(self.request('/api/system/power')))
        self.router.get(self.request('/api/system/power'))
        self.backend.POWER_MANAGER.status.assert_called_once_with()
        self.backend.POWER_MANAGER.request.assert_not_called()

    def test_accepted_status_for_background_actions(self):
        for path, action in [('/api/system/power', self.backend.POWER_MANAGER.request),
                             ('/api/store/install', self.backend.start_store_install)]:
            with self.subTest(path=path):
                self.handler.reset_mock()
                self.router.post(self.request(path, {'action': 'reboot'}))
                action.assert_called_once_with({'action': 'reboot'})
                self.handler.send_json.assert_called_once_with(action.return_value, HTTPStatus.ACCEPTED)

    def test_binary_backup_upload_bypasses_json_parser(self):
        handler = self.request('/api/backups/inspect')
        handler.rfile = io.BytesIO(b'not-json')
        self.router.post(handler)
        self.backend.stage_backup_upload.assert_called_once_with(handler)

    def test_get_error_shapes_and_missing_jobs_are_preserved(self):
        self.backend.FILE_BROWSER.file_listing.side_effect = PermissionError('denied')
        self.router.get(self.request('/api/files?path=%2Fprivate'))
        self.handler.send_json.assert_called_with({'error': 'denied'}, HTTPStatus.BAD_REQUEST)
        self.backend.FILE_BROWSER.file_listing.assert_called_once_with('/private')
        self.backend.COPY_MANAGER.status.side_effect = ValueError('missing')
        self.router.get(self.request('/api/files/copy/status?job_id=abc'))
        self.handler.send_json.assert_called_with({'ok': False, 'error': 'missing'}, HTTPStatus.NOT_FOUND)

    def test_head_stream_omits_body_and_errors_have_no_json(self):
        self.router.head(self.request('/api/file/open?path=%2Ffile.txt'))
        self.backend.serve_file.assert_called_once_with(self.handler, '/file.txt', include_body=False)
        self.backend.serve_file.side_effect = PermissionError('denied')
        self.router.head(self.request('/api/file/open'))
        self.handler.send_response.assert_called_once_with(HTTPStatus.BAD_REQUEST)
        self.handler.end_headers.assert_called_once_with()
        self.handler.send_json.assert_not_called()

    def test_unknown_routes_and_static_alias(self):
        self.assertFalse(self.router.get(self.request('/unknown')))
        self.assertFalse(self.router.head(self.request('/unknown')))
        self.router.post(self.request('/unknown'))
        self.handler.send_json.assert_called_once_with({'error': 'Route not found'}, HTTPStatus.NOT_FOUND)
        self.assertFalse(self.router.get(self.request('/speedtest/')))
        self.assertEqual(self.handler.path, '/speedtest.html')
        self.assertEqual(self.backend.mock_calls, [])

    def test_invalid_json_is_rejected_before_backend_action(self):
        handler = self.request('/api/files/action')
        handler.rfile = io.BytesIO(b'!!')
        self.router.post(handler)
        self.backend.file_action.assert_not_called()
        self.assertEqual(handler.send_json.call_args.args[1], HTTPStatus.BAD_REQUEST)
        self.assertFalse(handler.send_json.call_args.args[0]['ok'])

    def test_backup_restore_selects_uploaded_token_or_stored_name(self):
        self.router.post(self.request('/api/backups/restore', {'token': 'abc', 'name': 'ignored'}))
        self.backend.restore_staged_backup.assert_called_once_with('abc')
        self.backend.restore_backup.assert_not_called()
        self.router.post(self.request('/api/backups/restore', {'name': 'saved.tar.gz'}))
        self.backend.restore_backup.assert_called_once_with('saved.tar.gz')
