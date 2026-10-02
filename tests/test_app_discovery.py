"""Discovery contracts independent of the HTTP server and host services."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from homestart.apps.discovery import AppDiscovery, DiscoveryServices


def discovery():
    values = {name: Mock() for name in DiscoveryServices.__dataclass_fields__}
    values.update(
        with_icon=lambda app: app,
        normalized_name=lambda name: name.lower().replace(' ', ''),
        local_ip=lambda: 'host',
        load_config=Mock(return_value=[]),
        load_config_file=Mock(return_value={'dashboard': {'title': 'First'}, 'features': {}}),
        public_app_url=lambda url, host: url.replace('localhost', host),
        service_definitions=lambda: [],
        listener_snapshot=Mock(return_value=[]),
    )
    return AppDiscovery(DiscoveryServices(**values))


class AppDiscoveryTests(unittest.TestCase):
    def test_missing_docker_and_malformed_output(self):
        d = discovery()
        d.services.check_output.side_effect = FileNotFoundError()
        self.assertEqual(d.docker_apps('host'), [])
        d.services.check_output.side_effect = None
        d.services.check_output.return_value = 'bad json\n' + json.dumps({'Names': 'web', 'State': 'running'})
        d.services.docker_inspect.return_value = {'Config': {'Labels': {'com.docker.compose.project': 'stack'}}}
        d.services.docker_port_mappings.return_value = []
        d.services.select_docker_web_mapping.return_value = None
        d.services.docker_ports_for_display.return_value = []
        d.services.docker_url_from_mapping.return_value = ''
        app, = d.docker_apps('host', all_containers=False)
        self.assertTrue(app['docker_running'])
        self.assertEqual(app['compose_project'], 'stack')
        self.assertNotIn('-a', d.services.check_output.call_args.args[0])

    def test_native_root_validation_and_url(self):
        d = discovery()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'my-app' / 'public'
            root.mkdir(parents=True)
            app = d.detected_native_web_app(root, '8443', 'host', 'Nginx', True)
            self.assertEqual(app['name'], 'My App')
            self.assertEqual(app['url'], 'https://host:8443')
            self.assertEqual(app['description'], str(root))
            self.assertIsNone(d.detected_native_web_app(root / 'missing', '80', 'host'))
        self.assertIsNone(d.detected_native_web_app('/', '80', 'host'))

    def test_listener_cache_and_current_port_are_used_without_starting_another_scanner(self):
        d = discovery()
        d.services.listener_snapshot.return_value = [{'name': 'Web'}]
        for port, expected in [('8080', 8080), ('invalid', 80)]:
            with patch.dict(os.environ, {'PORT': port}):
                self.assertEqual(d.native_listener_apps('host'), [{'name': 'Web'}])
            d.services.listener_snapshot.assert_called_with('host', expected)

    def test_payload_precedence_and_live_configuration(self):
        d = discovery()
        configured = {'name': 'Plex', 'url': 'http://localhost:32400'}
        container = {'name': 'plex', 'docker_name': 'plex', 'status': 'Up', 'image': 'plex:latest', 'url': 'http://host:32400'}
        d.services.load_config.return_value = [configured]
        d.docker_apps = Mock(return_value=[container])
        d.managed_compose_apps = Mock(return_value=[container, {'name': 'Stack', 'url': 'http://host:8080'}])
        d.native_web_apps = Mock(return_value=[{'name': 'Duplicate', 'url': 'http://host:8080'}, {'name': 'Site', 'url': 'http://host:9000'}])
        d.native_listener_apps = Mock(return_value=[{'name': 'Site', 'url': 'http://host:9000'}, {'name': 'Other', 'url': 'http://host:9100'}])
        d.native_service_apps = Mock(return_value=[{'name': 'Other'}, {'name': 'VPN'}])
        result = d.app_payload()
        self.assertEqual([a['name'] for a in result['apps']], ['Plex', 'Stack', 'Site', 'Other', 'VPN'])
        self.assertEqual(result['apps'][0]['url'], 'http://host:32400')
        self.assertEqual(result['apps'][0]['status'], 'Up')
        d.services.load_config_file.return_value = {'dashboard': {'title': 'Changed'}, 'features': {'app_uninstall': False}}
        result = d.app_payload()
        self.assertEqual(result['dashboard']['title'], 'Changed')
        self.assertFalse(result['features']['app_uninstall'])

    def test_native_service_availability(self):
        d = discovery()
        services = dict(vars(d.services))
        services['service_definitions'] = lambda: [{'name': 'VPN', 'service': 'vpn.service', 'command': 'vpn'}]
        d = AppDiscovery(DiscoveryServices(**services))
        d.services.service_status.return_value = None
        d.services.command_available.return_value = False
        self.assertEqual(d.native_service_apps(), [])
        d.services.command_available.return_value = True
        app, = d.native_service_apps()
        self.assertEqual(app['status'], 'Command installed')
        self.assertTrue(app['available'])
        self.assertFalse(app['service_actionable'])
