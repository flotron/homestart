"""Catalog and installation behavior without the HTTP server or Docker daemon."""
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from homestart.docker.catalog import CatalogClient, fetch_store_catalog
from homestart.docker.install import InstallManager, InstallServices
from homestart.docker.store import validate_catalog


class StoreManagerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.services = InstallServices(
            catalog_app=Mock(), require_catalog_architecture=Mock(),
            render_compose=Mock(), verify_image=Mock(), projects=Mock(),
            run_docker=Mock(return_value='abcdef1234567890'),
            container_exists=Mock(return_value=False), normalize_name=lambda x: x,
            enabled=Mock(return_value=True), installed_images=Mock(return_value={}),
        )
        self.jobs = {'job': {'status': 'running', 'progress': 3}}
        self.manager = InstallManager(self.services, self.root / 'projects',
                                      self.jobs, threading.Lock())

    def test_container_install_preserves_run_options(self):
        result = self.manager.docker_store_install({
            'image': 'example/app:latest', 'name': 'sample',
            'host_port': '8080', 'container_port': '80',
            'env': ['MODE=production'], 'volumes': ['/tmp/data:/data'],
        })
        self.assertEqual(result['container_id'], 'abcdef123456')
        command = self.services.run_docker.call_args_list[-1].args[0]
        self.assertEqual(command, ['run', '-d', '--name', 'sample', '--restart',
                                  'unless-stopped', '-p', '8080:80', '-e',
                                  'MODE=production', '-v', '/tmp/data:/data',
                                  'example/app:latest'])

    def test_architecture_failure_stops_before_pull(self):
        self.services.verify_image.side_effect = ValueError('incompatible architecture')
        self.manager.run_store_install_job('job', {'image': 'example/app'})
        status = self.manager.store_install_status('job')
        self.assertEqual(status['status'], 'failed')
        self.assertIn('incompatible', status['error'])
        self.services.run_docker.assert_not_called()

    def test_failed_pull_is_reported_without_creating_container(self):
        process = Mock(stdout=io.StringIO('layer: Downloading\nnetwork failed\n'))
        process.wait.return_value = 1
        with patch('homestart.docker.install.subprocess.Popen', return_value=process):
            self.manager.run_store_install_job('job', {'image': 'example/app'})
        status = self.manager.store_install_status('job')
        self.assertEqual(status['status'], 'failed')
        self.assertEqual(status['error'], 'network failed')
        self.assertIn('network failed', status['log'])
        self.services.run_docker.assert_not_called()

    def test_successful_job_reaches_completed_status(self):
        process = Mock(stdout=io.StringIO('layer: Pull complete\n'))
        process.wait.return_value = 0
        self.services.run_docker.side_effect = ['abcdef1234567890', 'running']
        with patch('homestart.docker.install.subprocess.Popen', return_value=process):
            self.manager.run_store_install_job('job', {'image': 'example/app'})
        status = self.manager.store_install_status('job')
        self.assertEqual((status['status'], status['progress']), ('completed', 100))
        self.assertEqual(status['result']['state'], 'running')

    def test_disabled_store_cannot_install(self):
        self.services.enabled.return_value = False
        with self.assertRaisesRegex(ValueError, 'disabled'):
            self.manager.docker_store_install({'image': 'example/app'})
        self.services.run_docker.assert_not_called()

    def test_catalog_cache_refresh_and_offline_fallback(self):
        catalog = validate_catalog({'schema_version': 1, 'catalog_version': '1',
                                    'name': 'Test', 'apps': []})
        fetch = Mock(return_value=catalog)
        client = CatalogClient(self.root / 'catalog.json', threading.Lock(), 900,
                               lambda: 'https://example.com/catalog.json', fetch)
        loaded, metadata = client.load_store_catalog()
        self.assertEqual(metadata['source'], 'remote')
        self.assertEqual(loaded, catalog)
        client.load_store_catalog()
        fetch.assert_called_once()
        fetch.side_effect = OSError('offline')
        loaded, metadata = client.load_store_catalog(refresh=True)
        self.assertEqual(loaded, catalog)
        self.assertTrue(metadata['stale'])
        self.assertIn('offline', metadata['warning'])

    def test_insecure_catalog_url_is_rejected_before_network_access(self):
        with patch('homestart.docker.catalog.urllib.request.urlopen') as request:
            with self.assertRaisesRegex(ValueError, 'HTTPS'):
                fetch_store_catalog('http://example.com/catalog.json')
            request.assert_not_called()
