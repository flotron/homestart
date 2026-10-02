"""Live providers and shared state after removing server forwarding adapters."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from homestart.samba.manager import SambaManager
from homestart.docker.catalog import CatalogClient
from homestart.docker.install import InstallManager, InstallServices


class ServiceLifetimeTests(unittest.TestCase):
    def test_samba_reuses_service_with_live_paths_and_permissions(self):
        root = Path('/first')
        enabled = True
        manager = SambaManager(lambda: root / 'smb.conf', lambda: root / 'managed.conf',
                               lambda: root / 'state.json', lambda: enabled, lambda p: p)
        self.assertEqual(manager.config_path, Path('/first/smb.conf'))
        root = Path('/second')
        self.assertEqual(manager.config_path, Path('/second/smb.conf'))
        self.assertEqual(manager.managed_path, Path('/second/managed.conf'))
        self.assertEqual(manager.state_path, Path('/second/state.json'))
        manager.ensure_enabled()
        enabled = False
        with self.assertRaises(PermissionError): manager.ensure_enabled()

    def test_catalog_persistence_tracks_current_storage_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'first'
            client = CatalogClient(lambda: root / 'cache.json', threading.Lock(), 60, lambda: 'https://example.invalid')
            client.save_store_catalog_cache({'apps': []})
            self.assertTrue((root / 'cache.json').is_file())
            root = Path(tmp) / 'second'
            self.assertEqual(client.read_store_catalog_cache(), (None, 0))
            client.save_store_catalog_cache({'apps': []})
            self.assertTrue((root / 'cache.json').is_file())

    def test_install_progress_stays_shared_when_project_path_changes(self):
        root = Path('/first')
        jobs = {'job': {'id': 'job', 'progress': 0}}
        services = InstallServices(**{key: Mock() for key in InstallServices.__dataclass_fields__})
        manager = InstallManager(services, lambda: root, jobs, threading.Lock())
        manager.update_install_job('job', progress=35)
        root = Path('/second')
        self.assertEqual(manager.project_dir, root)
        self.assertEqual(manager.store_install_status('job')['progress'], 35)
        self.assertEqual(jobs['job']['progress'], 35)
