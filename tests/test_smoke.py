import importlib.util
import json
import os
import tempfile
import io
import tarfile
import unittest
from unittest import mock
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

    def test_docker_image_matching_ignores_registry_tag(self):
        self.assertEqual(self.app.image_repository("docker.io/library/redis:7"), "redis")
        self.assertEqual(self.app.image_repository("jellyfin/jellyfin:latest"), "jellyfin/jellyfin")

    def test_installed_recommended_images_are_hidden(self):
        with mock.patch.object(self.app, "installed_docker_images", return_value={"jellyfin/jellyfin": ["media"]}):
            images = [item["image"] for item in self.app.curated_store_apps()]
        self.assertNotIn("jellyfin/jellyfin:latest", images)
        self.assertIn("grafana/grafana:latest", images)

    def test_dockerhub_direct_links_are_parsed(self):
        self.assertEqual(
            self.app.dockerhub_repository_from_url("https://hub.docker.com/r/kasmweb/workspaces"),
            "kasmweb/workspaces",
        )
        self.assertEqual(self.app.dockerhub_repository_from_url("https://hub.docker.com/_/nginx"), "nginx")
        self.assertEqual(self.app.dockerhub_repository_from_url("https://example.com/r/kasmweb/workspaces"), "")

    def test_verified_store_results_are_prioritized(self):
        results = [
            {"name": "community/app", "official": False, "relevance": 100, "pulls": 1000, "stars": 10},
            {"name": "trusted/app", "official": False, "relevance": 10, "pulls": 10, "stars": 1},
        ]
        checks = {
            "community/app": {"verified": False, "verification_label": "", "trusted_rank": 0},
            "trusted/app": {"verified": True, "verification_label": "Verified Publisher", "trusted_rank": 2},
        }
        with mock.patch.object(self.app, "dockerhub_verification", side_effect=lambda name, official=False: checks[name]):
            self.app.add_dockerhub_verification(results)
        results.sort(key=lambda item: (item.get("trusted_rank", 0), item["relevance"]), reverse=True)
        self.assertEqual(results[0]["name"], "trusted/app")

    def test_metric_history_is_stored_without_browser_state(self):
        self.app.DB_PATH = Path(self.temp.name) / "metrics.db"
        self.app.METRIC_LAST_WRITE = 0
        now = int(__import__("time").time())
        self.app.record_system_metric({
            "timestamp": now,
            "cpu": {"percent": 7.5},
            "memory": {"percent": 22.0},
            "gpu": {"percent": 3.0},
            "network": {"rx_bps": 1000, "tx_bps": 500},
            "temperature": {"celsius": 48.0},
        })
        points = self.app.metrics_history(1)["points"]
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["cpu"], 7.5)
        self.assertEqual(points[0]["temperature"], 48.0)
        self.assertEqual(self.app.metrics_history("auto")["hours"], "auto")

    def test_live_and_history_network_counters_are_independent(self):
        self.app.NETWORK_LIVE_PREV = None
        self.app.NETWORK_HISTORY_PREV = None
        self.app.network_payload("live")
        self.assertIsNotNone(self.app.NETWORK_LIVE_PREV)
        self.assertIsNone(self.app.NETWORK_HISTORY_PREV)
        self.app.network_payload("history")
        self.assertIsNotNone(self.app.NETWORK_HISTORY_PREV)

    def test_monitor_selection_falls_back_when_saved_interface_disappears(self):
        items = [
            {"name": "enp2s0", "carrier": False, "state": "down"},
            {"name": "enp69s0f0", "carrier": True, "state": "up"},
        ]
        selected = self.app.choose_monitor_interface(items, "removed0", ["enp69s0f0"])
        self.assertEqual(selected, "enp69s0f0")

    def test_udev_properties_support_human_hardware_names(self):
        properties = self.app.parse_udev_properties(
            "ID_VENDOR_FROM_DATABASE=Example Networks\nID_MODEL_FROM_DATABASE=Fast Ethernet Adapter\n"
        )
        self.assertEqual(properties["ID_VENDOR_FROM_DATABASE"], "Example Networks")
        self.assertEqual(properties["ID_MODEL_FROM_DATABASE"], "Fast Ethernet Adapter")

    def test_network_device_totals_exclude_loopback(self):
        content = "Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n lo: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n eth0: 3000 0 0 0 0 0 0 0 900 0 0 0 0 0 0 0\n"
        self.assertEqual(self.app.network_device_totals(content), (3000, 900))

    def test_stopped_container_alert_lists_names(self):
        system = {
            "cpu": {"percent": 1}, "memory": {"percent": 2},
            "temperature": {"celsius": 40}, "network": {},
        }
        status = {
            "containers": [
                {"docker_name": "running-app", "docker_running": True},
                {"docker_name": "stopped-app", "docker_running": False},
            ],
            "services": [], "disks": [],
        }
        with mock.patch.object(self.app, "system_payload", return_value=system), mock.patch.object(self.app, "status_payload", return_value=status):
            alert = next(item for item in self.app.overview_payload()["alerts"] if item["id"] == "stopped-containers")
        self.assertIn("stopped-app", alert["detail"])

    def test_network_history_is_stored_separately_at_fine_resolution(self):
        self.app.DB_PATH = Path(self.temp.name) / "network-metrics.db"
        now = int(__import__("time").time())
        for offset, rx in ((-4, 5000), (-2, 6000), (0, 7000)):
            self.app.record_network_metric({"timestamp": now + offset, "rx_bps": rx, "tx_bps": 900})
        history = self.app.metrics_history(1)
        self.assertEqual(history["network_sample_seconds"], 2)
        self.assertEqual(history["retention_days"], 7)
        self.assertEqual(len(history["network_points"]), 3)
        self.assertEqual(history["network_points"][-1]["rx_bps"], 7000)


if __name__ == "__main__":
    unittest.main()
