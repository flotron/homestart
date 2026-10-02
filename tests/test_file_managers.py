"""File domain tests using temporary storage without the HTTP server."""
import base64
import json
from pathlib import Path
import tempfile
import time
import unittest

from homestart.files.browser import FileBrowser, path_usage
from homestart.files.copy import CopyCancelled
from homestart.files.trash import TrashManager


class FileManagerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = self.root / 'files'
        self.files.mkdir()
        self.config = {'file_roots': [str(self.files)], 'features': {}, 'trash': {}}
        self.browser = FileBrowser(lambda: self.config, ['/'], lambda: [], lambda: [])
        self.trash = TrashManager(self.root / 'trash', self.root / 'trash.json',
                                  self.browser, lambda: self.config)

    def test_paths_and_symlinks_cannot_escape_roots(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.files / 'escape').symlink_to(outside, target_is_directory=True)
        for path in (outside, self.files / '../outside', self.files / 'escape'):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                self.browser.resolve_file_path(str(path))
        with self.assertRaises(PermissionError):
            self.browser.resolve_new_child(str(self.files), 'escape')
        with self.assertRaises(PermissionError):
            self.trash.trash_file_path(str(self.files))
        self.assertTrue(self.files.exists())

    def test_upload_listing_copy_and_rename(self):
        uploaded = self.browser.upload_file(str(self.files), 'example.txt',
                                             base64.b64encode(b'hello').decode())
        copied = self.browser.copy_file_path(uploaded['path'], str(self.files))
        self.assertEqual(Path(copied['path']).name, 'example - copy.txt')
        renamed = self.browser.rename_file_path(copied['path'], 'renamed.txt')
        self.assertEqual(Path(renamed['path']).read_bytes(), b'hello')
        listing = self.browser.file_listing(str(self.files))
        self.assertEqual([x['name'] for x in listing['entries']], ['example.txt', 'renamed.txt'])
        self.assertEqual(self.browser.file_properties(renamed['path'])['size_bytes'], 5)
        with self.assertRaises(ValueError):
            self.browser.resolve_move_target(uploaded['path'], str(self.files))

    def test_disabled_operations_do_not_change_files(self):
        self.config['features']['file_operations'] = False
        source = self.files / 'keep.txt'
        source.write_text('keep')
        operations = [lambda: self.browser.create_folder(str(self.files), 'new'),
                      lambda: self.browser.delete_file_path(str(source)),
                      lambda: self.trash.trash_file_path(str(source))]
        for operation in operations:
            with self.assertRaises(PermissionError):
                operation()
        self.assertEqual(source.read_text(), 'keep')
        self.assertFalse((self.files / 'new').exists())

    def test_trash_restore_preserves_existing_file(self):
        source = self.files / 'report.txt'
        source.write_text('original')
        self.trash.trash_file_path(str(source))
        item = self.trash.trash_listing()['items'][0]
        source.write_text('replacement')
        restored = self.trash.restore_trash_item(item['key'])
        self.assertEqual(Path(restored['path']).read_text(), 'original')
        self.assertEqual(source.read_text(), 'replacement')
        self.assertEqual(self.trash.trash_listing()['items'], [])

    def test_retention_deletes_only_expired_items(self):
        for name in ('old.txt', 'recent.txt'):
            source = self.files / name
            source.write_text(name)
            self.trash.trash_file_path(str(source))
        index = json.loads(self.trash.index_path.read_text())
        for metadata in index.values():
            if metadata['name'] == 'old.txt':
                metadata['deleted_at'] = time.time() - 3 * 86400
        self.trash.save_trash_index(index)
        self.config['trash']['retention_days'] = 1
        self.assertEqual(self.trash.cleanup_expired_trash(), 1)
        self.assertEqual([x['name'] for x in self.trash.trash_listing()['items']], ['recent.txt'])
        with self.assertRaises(ValueError):
            self.trash.delete_trash_item('../files')

    def test_size_scan_still_supports_cancellation(self):
        with self.assertRaises(CopyCancelled):
            path_usage(self.files, cancelled=lambda: True)
