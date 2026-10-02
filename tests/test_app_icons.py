import base64
import io
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock
from homestart.apps.icons import AppIcons


class AppIconsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.transport = Mock()
        self.icons = AppIcons(icon_dir=lambda: self.root / 'icons',
                              index_path=lambda: self.root / 'index.json',
                              candidates=['/favicon.ico'], urlopen=self.transport)

    def upload(self, key, body=b'example', content_type='image/png'):
        return self.icons.save_custom_app_icon({'app_key': key, 'filename': 'icon',
            'content': 'data:' + content_type + ';base64,' + base64.b64encode(body).decode()})

    def test_custom_icons_persist_and_override_remote_icons(self):
        app = {'name': 'Example', 'url': 'http://host:8080'}
        key = self.icons.app_icon_key(app)
        self.upload(key)
        self.assertEqual(self.icons.custom_app_icon(key)['path'].read_bytes(), b'example')
        result = self.icons.with_icon(app.copy())
        self.assertTrue(result['custom_icon'])
        self.assertEqual(result['icon_url'], '/api/apps/icon?key=' + key)
        old = self.icons.custom_app_icon(key)['path']
        self.upload(key, b'new image', 'image/jpeg')
        self.assertFalse(old.exists())
        self.assertEqual(self.icons.custom_app_icon(key)['path'].suffix, '.jpg')
        self.transport.assert_not_called()

    def test_invalid_upload_does_not_replace_existing_icon(self):
        key = 'a' * 24
        self.upload(key)
        for body, kind in [(b'<script>alert(1)</script>', 'image/svg+xml'), (b'x' * (512*1024+1), 'image/png')]:
            with self.assertRaises(ValueError): self.upload(key, body, kind)
            self.assertEqual(self.icons.custom_app_icon(key)['path'].read_bytes(), b'example')
        with self.assertRaises(ValueError): self.upload('../invalid')

    def test_live_storage_paths_and_corrupt_index(self):
        key = 'b' * 24
        self.upload(key)
        self.root = self.root / 'other'
        self.assertIsNone(self.icons.custom_app_icon(key))
        self.upload(key, b'other')
        self.assertEqual(self.icons.custom_app_icon(key)['path'].read_bytes(), b'other')
        (self.root / 'index.json').write_text('broken')
        self.assertIsNone(self.icons.custom_app_icon(key))

    def test_remote_download_size_and_type_limits(self):
        for content_type, body, accepted in [('image/png', b'png', True), ('text/html', b'html', False), ('image/png', b'x' * (512*1024+1), False)]:
            response = io.BytesIO(body)
            response.headers = Message()
            response.headers['Content-Type'] = content_type
            self.transport.return_value = response
            result = self.icons.fetch_url('http://host/favicon.ico')
            self.assertEqual(result is not None, accepted)
            self.assertEqual(self.transport.call_args.kwargs['timeout'], 2)

    def test_remote_cache_including_missing_icons(self):
        self.icons.icon_candidates = Mock(return_value=['http://host/favicon.ico'])
        self.icons.fetch_url = Mock(return_value={'body': b'icon', 'content_type': 'image/png'})
        first = self.icons.get_icon('http://host')
        self.assertIs(self.icons.get_icon('http://host'), first)
        self.icons.fetch_url.assert_called_once()
        self.icons.fetch_url.return_value = None
        self.assertIsNone(self.icons.get_icon('http://other'))
        self.assertIsNone(self.icons.get_icon('http://other'))
        self.assertEqual(self.icons.fetch_url.call_count, 2)
