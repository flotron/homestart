"""Exercise backup operations without importing or starting the HTTP server."""
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock

from homestart.backup.manager import BackupManager


class BackupManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.auth = Mock(users_path=self.root / 'users.json',
                         setup_token_path=self.root / 'setup-token')
        self.save_config = Mock()
        self.manager = BackupManager(
            backup_dir=self.root / 'backups', staging_dir=self.root / 'staging',
            config_path=self.root / 'config.json', database_path=self.root / 'history.db',
            icon_dir=self.root / 'icons', icon_index=self.root / 'icons.json',
            auth_manager=lambda: self.auth, save_config=self.save_config,
            max_upload_size=1024 * 1024, max_extracted_size=4 * 1024 * 1024,
            stage_ttl=3600,
        )

    def archive(self, entries):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name, value in entries.items():
                data = json.dumps(value).encode()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return output.getvalue()

    def test_upload_restore_account_and_safety_backup(self):
        before = {'users': [{'id': 'old', 'username': 'old', 'password': 'scrypt$old'}]}
        after = {'users': [{'id': 'new', 'username': 'owner', 'password': 'scrypt$new'}]}
        self.auth.users_path.write_text(json.dumps(before))
        self.auth.setup_token_path.write_text('one-time-code')
        data = self.archive({'config.json': {'dashboard': {'title': 'Restored'}},
                             'data/auth-users.json': after})
        staged = self.manager.stage_backup_upload(io.BytesIO(data), str(len(data)))
        path = self.manager.staged_backup_path(staged['token'])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        result = self.manager.restore_backup_file(path, 'uploaded backup')
        self.assertTrue(result['session_revoked'])
        self.assertEqual(json.loads(self.auth.users_path.read_text()), after)
        self.assertEqual(self.auth.users_path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.auth.setup_token_path.exists())
        self.auth.revoke_all_sessions.assert_called_once_with()
        self.save_config.assert_called_once_with({'dashboard': {'title': 'Restored'}})
        with tarfile.open(self.manager.backup_path(result['safety_backup'])) as archive:
            self.assertEqual(json.load(archive.extractfile('data/auth-users.json')), before)

    def test_interrupted_or_invalid_upload_leaves_no_staged_archive(self):
        for data, length in [(b'broken', 20), (b'not gzip', 8)]:
            with self.subTest(data=data):
                with self.assertRaises((ValueError, tarfile.TarError)):
                    self.manager.stage_backup_upload(io.BytesIO(data), length)
                self.assertEqual(list(self.manager.staging_dir.glob('*.tar.gz')), [])
        self.save_config.assert_not_called()
        self.auth.revoke_all_sessions.assert_not_called()

    def test_expired_stage_cannot_be_restored(self):
        data = self.archive({'config.json': {}})
        staged = self.manager.stage_backup_upload(io.BytesIO(data), len(data))
        path = self.manager.staged_backup_path(staged['token'])
        os.utime(path, (1, 1))
        with self.assertRaisesRegex(FileNotFoundError, 'expired'):
            self.manager.staged_backup_path(staged['token'])
        self.assertFalse(path.exists())

    def test_rejected_archive_does_not_touch_current_data(self):
        source = self.root / 'invalid.tar.gz'
        source.write_bytes(self.archive({'../config.json': {}}))
        with self.assertRaisesRegex(ValueError, 'invalid path'):
            self.manager.restore_backup_file(source)
        self.save_config.assert_not_called()
        self.assertFalse(self.manager.backup_dir.exists())
        self.auth.revoke_all_sessions.assert_not_called()
