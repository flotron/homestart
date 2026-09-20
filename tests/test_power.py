import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from homestart.system.power import PowerManager


class PowerTests(unittest.TestCase):
    def setUp(self):
        self.manager = PowerManager()
        self.available = {'ok': True, 'hostname': 'test-host', 'available': True,
                          'reason': '', 'boot_id': 'boot-1', 'pending': None}
        self.payload = {'action': 'reboot', 'confirmation': 'reboot', 'hostname': 'test-host'}

    def test_rejects_missing_confirmation_wrong_host_and_commands(self):
        with patch.object(self.manager, 'status', return_value=self.available), patch('homestart.system.power.subprocess.run') as run:
            for payload in [None, [], {}, {'action': ['reboot']},
                            {**self.payload, 'confirmation': True},
                            {**self.payload, 'hostname': 'other-host'},
                            {**self.payload, 'action': 'reboot; id'},
                            {**self.payload, 'action': 'halt'}]:
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    self.manager.request(payload)
            run.assert_not_called()

    def test_systemd_accepts_each_allowlisted_action_without_shell_or_force(self):
        for action in ('reboot', 'poweroff'):
            manager = PowerManager()
            with patch.object(manager, 'status', return_value=self.available), patch('homestart.system.power.shutil.which', side_effect=lambda name: '/usr/bin/' + name), patch('homestart.system.power.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
                result = manager.request({**self.payload, 'action': action, 'confirmation': action})
                self.assertTrue(result['accepted'])
                self.assertEqual(result['pending']['action'], action)
                argv = run.call_args.args[0]
                self.assertEqual(argv[-1], action)
                self.assertIn('--on-active=5s', argv)
                self.assertIn('--unit=homestart-host-power', argv)
                self.assertNotIn('--force', argv)
                self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_duplicate_concurrent_requests_schedule_only_once(self):
        with patch.object(self.manager, 'status', return_value=self.available), patch('homestart.system.power.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            def request():
                try:
                    return self.manager.request(self.payload)['accepted']
                except ValueError:
                    return False
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(sum(pool.map(lambda _: request(), range(4))), 1)
            self.assertEqual(run.call_count, 1)

    def test_failure_or_timeout_does_not_report_acceptance(self):
        with patch.object(self.manager, 'status', return_value=self.available):
            with patch('homestart.system.power.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'Access denied')):
                with self.assertRaisesRegex(ValueError, 'Access denied'):
                    self.manager.request(self.payload)
                self.assertIsNone(self.manager.pending)
            with patch('homestart.system.power.subprocess.run', side_effect=subprocess.TimeoutExpired('systemd-run', 10)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    self.manager.request(self.payload)
                self.assertIsNone(self.manager.pending)

    def test_unavailable_host_is_not_modified(self):
        with patch.object(self.manager, 'status', return_value={**self.available, 'available': False, 'reason': 'Unavailable in a container'}), patch('homestart.system.power.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'container'):
                self.manager.request(self.payload)
            run.assert_not_called()

    def test_capability_explains_containers_and_missing_privileges(self):
        with patch('homestart.system.power.Path.exists', return_value=True):
            self.assertIn('container', self.manager.status()['reason'])
        with patch('homestart.system.power.Path.exists', return_value=False), patch('homestart.system.power.Path.is_dir', return_value=True), patch('homestart.system.power.os.geteuid', return_value=1000):
            self.assertIn('root', self.manager.status()['reason'])
        with patch('homestart.system.power.Path.exists', return_value=False), patch('homestart.system.power.Path.is_dir', return_value=False):
            self.assertIn('systemd', self.manager.status()['reason'])
