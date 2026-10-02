import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from homestart.system.storage import StorageManager


class StorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = {'features': {}}
        self.manager = StorageManager(lambda: [self.root], lambda: self.config,
                                      self.root / 'mounts', lambda x: max(0, min(100, x)))
        self.devices = {'blockdevices': [{'name': 'sdb', 'path': '/dev/sdb',
            'type': 'disk', 'tran': 'usb', 'children': [
                {'name': 'sdb1', 'path': '/dev/sdb1', 'type': 'part',
                 'fstype': 'ext4', 'mountpoints': []}]}]}
        self.manager.lsblk_payload = Mock(return_value=self.devices)

    def test_mount_command_keeps_readonly_and_security_options(self):
        with patch('homestart.system.storage.subprocess.check_output') as command:
            result = self.manager.mount_block_device_readonly('/dev/sdb1')
        self.assertTrue(result['readonly'])
        self.assertEqual(command.call_args.args[0], ['mount', '-o', 'ro,nosuid,nodev,noexec',
                                                     '/dev/sdb1', str(self.root / 'mounts/sdb1')])

    def test_disabled_mounts_and_raw_disks_are_rejected(self):
        with patch('homestart.system.storage.subprocess.check_output') as command:
            with self.assertRaisesRegex(ValueError, 'partitions and volumes'):
                self.manager.mount_block_device_readonly('/dev/sdb')
            self.config['features']['file_mounts'] = False
            with self.assertRaises(PermissionError):
                self.manager.mount_block_device_readonly('/dev/sdb1')
            command.assert_not_called()

    def test_unmount_cannot_target_external_mount(self):
        self.devices['blockdevices'][0]['children'][0]['mountpoints'] = ['/elsewhere']
        with patch('homestart.system.storage.subprocess.check_output') as command:
            with self.assertRaisesRegex(ValueError, 'not mounted by HomeStart'):
                self.manager.unmount_homestart_device('/dev/sdb1')
            command.assert_not_called()

    def test_drive_tree_uses_live_mount_permissions(self):
        partition = self.manager.physical_drive_entries()[0]['children'][0]
        self.assertEqual(partition['kind'], 'usb')
        self.assertTrue(partition['can_mount'])
        self.config['features']['file_operations'] = False
        partition = self.manager.physical_drive_entries()[0]['children'][0]
        self.assertFalse(partition['can_mount'])
