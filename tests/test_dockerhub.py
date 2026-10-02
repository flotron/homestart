import io
import json
import threading
import unittest
from unittest.mock import Mock
from homestart.docker.hub import DockerHubClient


class DockerHubTests(unittest.TestCase):
    def client(self, opener):
        return DockerHubClient(lambda: True, lambda: {'nginx': ['web']},
                               lambda: {'architecture': 'amd64'}, {}, threading.Lock(),
                               opener=opener)

    def test_direct_official_link_preserves_installed_status(self):
        opener = Mock(return_value=io.BytesIO(json.dumps({'description': 'Web server'}).encode()))
        result = self.client(opener).dockerhub_search('https://hub.docker.com/_/nginx')
        item = result['results'][0]
        self.assertEqual(item['name'], 'nginx')
        self.assertTrue(item['official'])
        self.assertTrue(item['installed'])
        self.assertEqual(item['installed_containers'], ['web'])
        self.assertEqual(item['trusted_rank'], 3)
        self.assertEqual(opener.call_count, 1)
        self.assertIn('/repositories/library/nginx/', opener.call_args.args[0].full_url)

    def test_publisher_verification_is_cached(self):
        opener = Mock(return_value=io.BytesIO(b'Verified Publisher'))
        client = self.client(opener)
        self.assertEqual(client.dockerhub_verification('vendor/app')['trusted_rank'], 2)
        self.assertEqual(client.dockerhub_verification('VENDOR/APP')['trusted_rank'], 2)
        opener.assert_called_once()

    def test_offline_verification_does_not_claim_trust(self):
        opener = Mock(side_effect=OSError('offline'))
        result = self.client(opener).dockerhub_verification('vendor/app')
        self.assertFalse(result['verified'])
        self.assertEqual(result['trusted_rank'], 0)

    def test_search_error_and_short_query(self):
        import urllib.error
        opener = Mock(side_effect=urllib.error.URLError('offline'))
        client = self.client(opener)
        self.assertEqual(client.dockerhub_search('x')['results'], [])
        opener.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'Could not search Docker Hub'):
            client.dockerhub_search('nginx')
