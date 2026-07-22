import importlib.util
import json
import os
import tempfile
import io
import tarfile
import unittest
from pathlib import Path


class HomeStartSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / "config.json"
        self.config.write_text(json.dumps({"dashboard": {"title": "TestStart"}}), encoding="utf-8")
        os.environ["HOMESTART_CONFIG"] = str(self.config)
        spec = importlib.util.spec_from_file_location("homestart_app", Path(__file__).parents[1] / "app.py")
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)

    def tearDown(self):
        self.temp.cleanup()
        os.environ.pop("HOMESTART_CONFIG", None)

    def test_config_merges_defaults(self):
        config = self.app.load_config_file()
        self.assertEqual(config["dashboard"]["title"], "TestStart")
        self.assertIn("features", config)
        self.assertIn("updates", config)

    def test_percent_is_clamped(self):
        self.assertEqual(self.app.clamp_percent(110), 100)
        self.assertEqual(self.app.clamp_percent(-1), 0)

    def test_settings_update_preserves_other_sections(self):
        result = self.app.update_settings({"appearance": {"accent": "#ff0000"}})
        self.assertTrue(result["ok"])
        self.assertEqual(result["appearance"]["accent"], "#ff0000")
        self.assertIn("features", self.app.load_config_file())

    def test_backup_extraction_rejects_parent_traversal(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            info = tarfile.TarInfo("../outside")
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
        payload.seek(0)
        with tarfile.open(fileobj=payload, mode="r:gz") as archive:
            with self.assertRaises(ValueError):
                self.app.safe_extract_tar(archive, Path(self.temp.name) / "restore")

    def test_file_trash_can_be_restored(self):
        root = Path(self.temp.name) / "files"
        root.mkdir()
        source = root / "example.txt"
        source.write_text("recover me", encoding="utf-8")
        config = self.app.load_config_file()
        config["file_roots"] = [str(root)]
        self.app.save_config_file(config)
        self.app.TRASH_DIR = Path(self.temp.name) / "trash"
        self.app.TRASH_INDEX = Path(self.temp.name) / "trash.json"
        result = self.app.trash_file_path(str(source))
        self.assertTrue(result["ok"])
        self.assertFalse(source.exists())
        item = self.app.trash_listing()["items"][0]
        restored = self.app.restore_trash_item(item["key"])
        self.assertEqual(Path(restored["path"]).read_text(encoding="utf-8"), "recover me")

    def test_copy_in_same_folder_creates_copy_name(self):
        root = Path(self.temp.name) / "copy-files"
        root.mkdir()
        source = root / "manual.pdf"
        source.write_bytes(b"pdf")
        config = self.app.load_config_file()
        config["file_roots"] = [str(root)]
        self.app.save_config_file(config)
        result = self.app.copy_file_path(str(source), str(root))
        copied = Path(result["path"])
        self.assertEqual(copied.name, "manual - copy.pdf")
        self.assertEqual(copied.read_bytes(), b"pdf")


if __name__ == "__main__":
    unittest.main()
