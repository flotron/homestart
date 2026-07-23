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

    def test_network_settings_include_runtime_hardware_metadata(self):
        address = {
            "ifname": "enp69s0f0",
            "link_type": "ether",
            "operstate": "UP",
            "address": "00:11:22:33:44:55",
            "addr_info": [{"family": "inet", "local": "192.168.0.32", "prefixlen": 24}],
        }
        hardware = {
            "name": "enp69s0f0",
            "label": "Example Networks Fast Adapter",
            "vendor": "Example Networks",
            "model": "Fast Adapter",
            "driver": "example",
            "kind": "ethernet",
            "carrier": True,
            "speed_mbps": 10000,
            "duplex": "full",
        }
        with mock.patch.object(self.app, "run_json", return_value=[address]), \
                mock.patch.object(self.app, "is_physical_network_interface", return_value=True), \
                mock.patch.object(self.app, "monitorable_network_interfaces", return_value=[hardware]), \
                mock.patch.object(self.app, "default_routes", return_value={}), \
                mock.patch.object(self.app, "netplan_interface_config", return_value=(None, {})), \
                mock.patch.object(self.app, "default_route_interfaces", return_value=["enp69s0f0"]):
            interface = self.app.network_interfaces_payload()["interfaces"][0]
        self.assertEqual(interface["label"], "Example Networks Fast Adapter")
        self.assertEqual(interface["speed_mbps"], 10000)

    def test_samba_config_parser_and_share_payload(self):
        parsed = self.app.parse_samba_config(
            "[global]\n workgroup = WORKGROUP\n[Documents]\n"
            " path = /srv/documents\n read only = no\n valid users = mariano, @office\n"
        )
        share = self.app.samba_share_payload("Documents", parsed["Documents"], {"shares": {}, "disabled": []})
        self.assertEqual(share["path"], "/srv/documents")
        self.assertFalse(share["read_only"])
        self.assertEqual(share["valid_users"], ["mariano", "@office"])

    def test_managed_samba_config_can_disable_share_reversibly(self):
        state = {
            "shares": {
                "Media": {
                    "path": "/srv/media", "browseable": True, "read_only": False,
                    "guest_ok": True, "valid_users": [], "force_user": "mediauser",
                }
            },
            "disabled": ["Media", "Legacy"],
        }
        rendered = self.app.render_homestart_samba_config(state)
        self.assertIn("[Media]\n    path = /srv/media\n    available = no", rendered)
        self.assertIn("[Legacy]\n    available = no", rendered)
        self.assertIn("force user = mediauser", rendered)
        self.assertIn("force directory mode = 0770", rendered)

    def test_guest_writable_share_uses_non_root_folder_owner(self):
        root = Path(self.temp.name) / "guest-share"
        root.mkdir()
        config = self.app.load_config_file()
        config["file_roots"] = [str(root)]
        self.app.save_config_file(config)
        state = {"shares": {}, "disabled": []}
        detected = {"ok": True, "shares": [], "users": []}
        with mock.patch.object(self.app, "samba_state", return_value=state), \
                mock.patch.object(self.app, "samba_shares_payload", return_value=detected), \
                mock.patch.object(self.app.subprocess, "check_output", return_value="1000\n"), \
                mock.patch.object(self.app.os, "chown") as chown, \
                mock.patch.object(self.app, "save_samba_state", side_effect=lambda value: value):
            result = self.app.samba_share_action({
                "action": "create", "name": "GuestFiles", "path": str(root),
                "guest_ok": True, "read_only": False, "browseable": True,
                "force_user": "operator",
            })
        self.assertEqual(result["shares"]["GuestFiles"]["force_user"], "operator")
        chown.assert_called_once_with(root, 1000, -1)

    def test_file_browser_content_inherits_parent_owner(self):
        root = Path(self.temp.name) / "owned-files"
        root.mkdir()
        config = self.app.load_config_file()
        config["file_roots"] = [str(root)]
        self.app.save_config_file(config)
        with mock.patch.object(self.app.os, "chown") as chown:
            result = self.app.create_folder(str(root), "child")
        parent_stat = root.stat()
        chown.assert_called_once_with(Path(result["path"]), parent_stat.st_uid, parent_stat.st_gid)

    def test_samba_include_is_added_inside_global_section(self):
        with mock.patch.object(self.app, "SAMBA_MANAGED_PATH", Path("/etc/samba/homestart-shares.conf")):
            rendered = self.app.samba_config_with_include("[global]\nworkgroup = WORKGROUP\n[Data]\npath = /srv/data\n")
        self.assertIn("[global]\n    include = /etc/samba/homestart-shares.conf", rendered)

    def test_samba_password_is_passed_only_to_smbpasswd_stdin(self):
        with mock.patch.object(self.app, "samba_manager_enabled", return_value=True), \
                mock.patch.object(self.app.subprocess, "check_output", return_value="1000\n"), \
                mock.patch.object(self.app.subprocess, "run") as run, \
                mock.patch.object(self.app, "samba_shares_payload", return_value={"ok": True}):
            result = self.app.samba_share_action({
                "action": "set_password", "username": "operator", "password": "secret-password",
            })
        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.args[0], ["smbpasswd", "-s", "-a", "operator"])
        self.assertEqual(run.call_args.kwargs["input"], "secret-password\nsecret-password\n")

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
