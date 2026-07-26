import importlib
import json
import os
import signal
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
        self.app = importlib.reload(importlib.import_module("homestart.server"))

    def tearDown(self):
        self.temp.cleanup()
        os.environ.pop("HOMESTART_CONFIG", None)

    def test_config_merges_defaults(self):
        config = self.app.load_config_file()
        self.assertEqual(config["dashboard"]["title"], "TestStart")
        self.assertIn("features", config)
        self.assertIn("updates", config)

    def test_modular_entry_point_and_update_paths_are_compatible(self):
        root = Path(__file__).parents[1]
        entry_point = (root / "app.py").read_text(encoding="utf-8-sig")
        self.assertIn("from homestart.server import main", entry_point)
        self.assertIn("from scripts.homestart.server import main", entry_point)
        for relative_path in (
            "homestart/server.py",
            "homestart/api/router.py",
            "homestart/config.py",
            "homestart/docker/projects.py",
            "homestart/docker/store.py",
            "homestart/files/copy.py",
            "homestart/metrics/store.py",
            "homestart/samba/manager.py",
            "homestart/system/network.py",
            "homestart/system/network_config.py",
            "homestart/updates/github.py",
        ):
            self.assertTrue((root / relative_path).is_file(), relative_path)
        self.assertEqual(
            self.app.update_member_path("homestart/homestart/api/router.py"),
            Path("homestart/api/router.py"),
        )
        package_script = (root / "scripts" / "build_package.sh").read_text(encoding="utf-8")
        self.assertIn('"$PACKAGE_DIR/scripts/homestart/"', package_script)
        self.assertIn("from app import main; assert callable(main)", package_script)

    def test_percent_is_clamped(self):
        self.assertEqual(self.app.clamp_percent(110), 100)
        self.assertEqual(self.app.clamp_percent(-1), 0)

    def test_settings_update_preserves_other_sections(self):
        result = self.app.update_settings({"appearance": {"accent": "#ff0000"}})
        self.assertTrue(result["ok"])
        self.assertEqual(result["appearance"]["accent"], "#ff0000")
        self.assertIn("features", self.app.load_config_file())

    def test_system_timezone_change_uses_timedatectl(self):
        with mock.patch.object(self.app.subprocess, "check_output", return_value="") as check_output:
            result = self.app.set_system_timezone("America/Argentina/Cordoba")
        self.assertEqual(result, "America/Argentina/Cordoba")
        check_output.assert_called_once_with(
            ["timedatectl", "set-timezone", "America/Argentina/Cordoba"],
            text=True, timeout=15, stderr=self.app.subprocess.STDOUT,
        )

    def test_timezone_regions_include_server_reported_zones(self):
        with mock.patch.object(self.app, "available_timezones", return_value={"UTC"}), \
                mock.patch.object(self.app.subprocess, "check_output", return_value="America/Argentina/Cordoba\nEurope/Madrid\n"):
            regions = self.app.timezone_regions()
        self.assertIn("America/Argentina/Cordoba", regions)
        self.assertIn("Europe/Madrid", regions)
        self.assertIn("UTC", regions)

    def test_trash_retention_accepts_supported_periods(self):
        result = self.app.update_settings({"trash": {"retention_days": 30}})
        self.assertEqual(result["trash"]["retention_days"], 30)
        with self.assertRaises(ValueError):
            self.app.update_settings({"trash": {"retention_days": 31}})

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

    def test_trash_reports_recursive_size_and_permanent_delete(self):
        self.app.TRASH_DIR = Path(self.temp.name) / "trash-size"
        self.app.TRASH_INDEX = Path(self.temp.name) / "trash-size.json"
        folder = self.app.TRASH_DIR / "item-folder"
        folder.mkdir(parents=True)
        (folder / "a.bin").write_bytes(b"a" * 10)
        (folder / "b.bin").write_bytes(b"b" * 15)
        self.app.save_trash_index({
            "item-folder": {"original": "/tmp/folder", "name": "folder", "deleted_at": int(__import__("time").time())}
        })
        with mock.patch.object(self.app, "cleanup_expired_trash", return_value=0):
            listing = self.app.trash_listing()
        self.assertEqual(listing["items"][0]["size"], 25)
        self.assertEqual(listing["total_size"], 25)
        self.app.delete_trash_item("item-folder")
        self.assertFalse(folder.exists())
        with self.assertRaises(ValueError):
            self.app.delete_trash_item("..")

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

    def test_copy_progress_reports_speed_and_eta(self):
        job_id = "speed-job"
        self.app.FILE_COPY_JOBS[job_id] = {
            "job_id": job_id,
            "status": "running",
            "total_bytes": 1000,
            "copied_bytes": 0,
            "speed_bps": 0,
            "_speed_last_at": 10,
            "_speed_last_bytes": 0,
        }
        with mock.patch.object(self.app.time, "monotonic", return_value=11):
            self.app.update_copy_job(job_id, copied_bytes=500)
        status = self.app.copy_job_status(job_id)
        self.assertEqual(status["speed_bps"], 500)
        self.assertEqual(status["eta_seconds"], 1)
        self.assertNotIn("_speed_last_at", status)

    def test_native_cp_command_uses_safe_gnu_copy_options(self):
        root = Path(self.temp.name) / "native-command"
        source = root / "source folder"
        target = root / "target folder"
        source.mkdir(parents=True)
        command = self.app.native_cp_command("/usr/bin/cp", source, target)
        self.assertIn("--reflink=auto", command)
        self.assertIn("--sparse=auto", command)
        self.assertIn("--recursive", command)
        self.assertIn("--dereference", command)
        self.assertEqual(command[-3:], ["--", str(source), str(target)])

    def test_native_cp_engine_copies_regular_file(self):
        if not self.app.native_cp_path():
            self.skipTest("GNU cp is not available")
        root = Path(self.temp.name) / "native-copy"
        root.mkdir()
        source = root / "source.bin"
        target = root / "destination.bin"
        source.write_bytes(b"native-copy" * 1000)
        job_id = "native-job"
        self.app.FILE_COPY_JOBS[job_id] = {
            "job_id": job_id,
            "status": "preparing",
            "copied_bytes": 0,
            "total_bytes": 0,
            "speed_bps": 0,
            "cancel_requested": False,
            "_speed_last_at": __import__("time").monotonic(),
            "_speed_last_bytes": 0,
        }
        self.app.copy_file_with_progress(source, target, job_id)
        status = self.app.copy_job_status(job_id)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["engine"], "native_cp")
        self.assertEqual(status["copied_bytes"], source.stat().st_size)
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_python_copy_remains_available_as_fallback(self):
        root = Path(self.temp.name) / "fallback-copy"
        root.mkdir()
        source = root / "source.bin"
        target = root / "destination.bin"
        source.write_bytes(b"fallback")
        job_id = "fallback-job"
        self.app.FILE_COPY_JOBS[job_id] = {
            "job_id": job_id,
            "status": "preparing",
            "copied_bytes": 0,
            "total_bytes": 0,
            "speed_bps": 0,
            "cancel_requested": False,
            "_speed_last_at": __import__("time").monotonic(),
            "_speed_last_bytes": 0,
        }
        with mock.patch.object(self.app.copy_manager(), "native_cp_path", return_value=None):
            self.app.copy_file_with_progress(source, target, job_id)
        status = self.app.copy_job_status(job_id)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["engine"], "python")
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_native_cp_cancellation_terminates_the_process(self):
        class FakeProcess:
            pid = 12345

            def __init__(self):
                self.signal = None
                self.return_code = None

            def poll(self):
                return self.return_code

            def send_signal(self, value):
                self.signal = value
                self.return_code = -value

            def wait(self, timeout=None):
                return self.return_code

            def kill(self):
                self.return_code = -9

        root = Path(self.temp.name) / "native-cancel"
        root.mkdir()
        source = root / "source.bin"
        target = root / "destination.bin"
        source.write_bytes(b"x" * 100)
        job_id = "native-cancel-job"
        self.app.FILE_COPY_JOBS[job_id] = {
            "job_id": job_id,
            "status": "cancelling",
            "copied_bytes": 0,
            "total_bytes": 100,
            "speed_bps": 0,
            "cancel_requested": True,
            "_speed_last_at": __import__("time").monotonic(),
            "_speed_last_bytes": 0,
        }
        process = FakeProcess()
        with mock.patch.object(self.app.copy_manager(), "native_cp_path", return_value="/usr/bin/cp"), \
                mock.patch("homestart.files.copy.subprocess.Popen", return_value=process):
            with self.assertRaises(self.app.CopyCancelled):
                self.app.run_native_copy(source, target, job_id, 100)
        self.assertEqual(process.signal, signal.SIGTERM)

    def test_cancelled_copy_removes_incomplete_destination(self):
        root = Path(self.temp.name) / "cancel-copy"
        root.mkdir()
        source = root / "source.bin"
        target = root / "destination.bin"
        source.write_bytes(b"x" * 1024)
        job_id = "cancel-job"
        self.app.FILE_COPY_JOBS[job_id] = {
            "job_id": job_id,
            "status": "cancelling",
            "copied_bytes": 0,
            "total_bytes": 0,
            "cancel_requested": True,
            "speed_bps": 0,
            "updated_at": 0,
        }
        self.app.copy_file_with_progress(source, target, job_id)
        status = self.app.copy_job_status(job_id)
        self.assertEqual(status["status"], "cancelled")
        self.assertFalse(target.exists())

    def test_file_properties_include_recursive_folder_size(self):
        root = Path(self.temp.name) / "properties"
        folder = root / "documents"
        nested = folder / "nested"
        nested.mkdir(parents=True)
        (folder / "one.bin").write_bytes(b"a" * 10)
        (nested / "two.bin").write_bytes(b"b" * 15)
        config = self.app.load_config_file()
        config["file_roots"] = [str(root)]
        self.app.save_config_file(config)
        properties = self.app.file_properties(str(folder))
        self.assertEqual(properties["size_bytes"], 25)
        self.assertEqual(properties["file_count"], 2)
        self.assertEqual(properties["folder_count"], 2)

    def test_async_copy_reports_byte_progress_and_completion(self):
        root = Path(self.temp.name) / "copy-progress"
        root.mkdir()
        source = root / "archive.bin"
        source.write_bytes(b"x" * (2 * 1024 * 1024 + 17))
        config = self.app.load_config_file()
        config["file_roots"] = [str(root)]
        self.app.save_config_file(config)
        started = self.app.start_copy_job(str(source), str(root))
        deadline = __import__("time").time() + 3
        while __import__("time").time() < deadline:
            status = self.app.copy_job_status(started["job_id"])
            if status["status"] in {"completed", "failed"}:
                break
            __import__("time").sleep(.02)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["percent"], 100)
        self.assertEqual(status["copied_bytes"], source.stat().st_size)
        self.assertEqual(Path(status["path"]).read_bytes(), source.read_bytes())

    def test_docker_image_matching_ignores_registry_tag(self):
        self.assertEqual(self.app.image_repository("docker.io/library/redis:7"), "redis")
        self.assertEqual(self.app.image_repository("jellyfin/jellyfin:latest"), "jellyfin/jellyfin")

    def test_installed_recommended_images_are_hidden(self):
        with mock.patch.object(self.app, "installed_docker_images", return_value={"jellyfin/jellyfin": ["media"]}):
            images = [item["image"] for item in self.app.curated_store_apps()]
        self.assertNotIn("jellyfin/jellyfin:latest", images)
        self.assertIn("grafana/grafana:latest", images)

    def declarative_catalog(self):
        return {
            "schema_version": 1,
            "catalog_version": "test.1",
            "name": "Test catalog",
            "apps": [{
                "id": "sample-app",
                "name": "Sample App",
                "description": "A test application",
                "category": "Testing",
                "verified": True,
                "verification_label": "Reviewed",
                "page_url": "https://example.com/sample",
                "inputs": [
                    {"id": "container_name", "label": "Container name", "type": "text",
                     "default": "sample-app", "pattern": "^[A-Za-z0-9_.-]+$"},
                    {"id": "host_port", "label": "Web port", "type": "port", "default": 8080},
                    {"id": "data_path", "label": "Data folder", "type": "path",
                     "default": "{{homestart_data}}/sample-app"},
                ],
                "compose": {"services": {"app": {
                    "image": "example/sample:latest",
                    "container_name": "{{container_name}}",
                    "ports": ["{{host_port}}:80"],
                    "volumes": ["{{data_path}}:/data"],
                    "restart": "unless-stopped",
                }}},
            }],
        }

    def test_declarative_catalog_is_validated_and_rendered(self):
        catalog = self.app.validate_store_catalog(self.declarative_catalog())
        app = catalog["apps"][0]
        self.app.COMPOSE_APP_DATA_DIR = Path(self.temp.name) / "app-data"
        with mock.patch.object(self.app, "system_timezone", return_value="UTC"):
            compose, values = self.app.render_catalog_compose(app, {
                "container_name": "sample-one",
                "host_port": "9090",
                "data_path": str(Path(self.temp.name) / "sample"),
            })
        service = compose["services"]["app"]
        self.assertEqual(service["container_name"], "sample-one")
        self.assertEqual(service["ports"], ["9090:80"])
        self.assertEqual(service["labels"]["com.homestart.template"], "sample-app")
        self.assertEqual(values["host_port"], "9090")

    def test_declarative_catalog_rejects_undeclared_placeholders(self):
        catalog = self.declarative_catalog()
        catalog["apps"][0]["compose"]["services"]["app"]["environment"] = {"SECRET": "{{not_declared}}"}
        with self.assertRaises(ValueError):
            self.app.validate_store_catalog(catalog)

    def test_catalog_architecture_is_normalized_and_blocks_explicit_mismatch(self):
        catalog = self.declarative_catalog()
        catalog["apps"][0]["architectures"] = ["x86_64", "aarch64"]
        app = self.app.validate_store_catalog(catalog)["apps"][0]
        self.assertEqual(app["architectures"], ["amd64", "arm64"])
        with mock.patch.object(
            self.app,
            "detect_host_architecture",
            return_value={"machine": "aarch64", "architecture": "arm64", "docker_platform": "linux/arm64"},
        ):
            self.assertTrue(self.app.require_catalog_architecture(app)["architecture_compatible"])
            app["architectures"] = ["amd64"]
            with self.assertRaisesRegex(ValueError, "does not declare support"):
                self.app.require_catalog_architecture(app)

    def test_docker_manifest_architecture_detects_multi_platform_images(self):
        manifest = json.dumps([
            {"Descriptor": {"platform": {"architecture": "amd64", "os": "linux"}}},
            {"Descriptor": {"platform": {"architecture": "arm64", "os": "linux"}}},
        ])
        self.app.DOCKER_ARCHITECTURE_CACHE = {}
        with mock.patch.object(self.app, "run_docker_command", return_value=manifest):
            architectures = self.app.docker_manifest_architectures("example/image:latest")
        self.assertEqual(architectures, {"amd64", "arm64"})

    def test_docker_manifest_preflight_rejects_known_host_mismatch(self):
        with mock.patch.object(
            self.app,
            "detect_host_architecture",
            return_value={"machine": "aarch64", "architecture": "arm64", "docker_platform": "linux/arm64"},
        ), mock.patch.object(
            self.app,
            "docker_manifest_architectures",
            return_value={"amd64"},
        ):
            with self.assertRaisesRegex(ValueError, "does not publish"):
                self.app.verify_docker_image_architecture("example/amd64-only:latest")

    def test_store_catalog_uses_stale_cache_when_remote_fetch_fails(self):
        self.app.STORE_CATALOG_CACHE = Path(self.temp.name) / "catalog-cache.json"
        catalog = self.app.validate_store_catalog(self.declarative_catalog())
        self.app.save_store_catalog_cache(catalog)
        wrapper = json.loads(self.app.STORE_CATALOG_CACHE.read_text(encoding="utf-8"))
        wrapper["fetched_at"] = 1
        self.app.STORE_CATALOG_CACHE.write_text(json.dumps(wrapper), encoding="utf-8")
        with mock.patch.object(self.app, "fetch_store_catalog", side_effect=OSError("offline")):
            loaded, metadata = self.app.load_store_catalog()
        self.assertEqual(loaded["apps"][0]["id"], "sample-app")
        self.assertEqual(metadata["source"], "cache")
        self.assertTrue(metadata["stale"])

    def test_compose_catalog_install_writes_project_and_runs_compose(self):
        app = self.app.validate_store_catalog(self.declarative_catalog())["apps"][0]
        self.app.COMPOSE_APP_DIR = Path(self.temp.name) / "compose-apps"
        self.app.COMPOSE_APP_DATA_DIR = Path(self.temp.name) / "app-data"
        commands = []

        def docker(command, timeout=60):
            commands.append(command)
            if command[:2] == ["ps", "-a"]:
                return ""
            if "ps" in command and "-q" in command:
                return "container-id"
            return "ok"

        values = {
            "container_name": "sample-one",
            "host_port": "9090",
            "data_path": str(Path(self.temp.name) / "sample"),
        }
        with mock.patch.object(self.app, "store_catalog_app", return_value=app), \
                mock.patch.object(self.app, "system_timezone", return_value="UTC"), \
                mock.patch.object(self.app, "docker_container_exists", return_value=False), \
                mock.patch.object(self.app, "run_docker_command", side_effect=docker):
            result = self.app.compose_store_install({"template_id": "sample-app", "values": values})
        compose_path = Path(result["compose_file"])
        self.assertTrue(compose_path.is_file())
        self.assertTrue((compose_path.parent / "project.json").is_file())
        self.assertIn("com.homestart.template: sample-app", compose_path.read_text(encoding="utf-8"))
        self.assertTrue(any(command[-1] == "pull" for command in commands))
        self.assertTrue(any(command[-2:] == ["up", "-d"] for command in commands))

    def test_compose_risk_report_flags_dangerous_permissions(self):
        report = self.app.compose_risk_report({
            "services": {
                "api": {
                    "image": "example/api",
                    "privileged": True,
                    "network_mode": "host",
                    "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
                },
                "worker": {
                    "image": "example/worker",
                    "cap_add": ["SYS_ADMIN"],
                    "volumes": ["/etc/ssl:/certificates:ro"],
                },
            },
        })
        self.assertEqual(report["level"], "critical")
        codes = {warning["code"] for warning in report["warnings"]}
        self.assertTrue({
            "privileged", "host-network", "docker-socket", "capabilities", "sensitive-bind",
        } <= codes)

    def test_compose_project_lifecycle_controls_the_complete_stack(self):
        import yaml

        self.app.COMPOSE_APP_DIR = Path(self.temp.name) / "compose-projects"
        self.app.COMPOSE_APP_DATA_DIR = Path(self.temp.name) / "app-data"
        project_dir = self.app.COMPOSE_APP_DIR / "sample"
        project_dir.mkdir(parents=True)
        managed_data = self.app.COMPOSE_APP_DATA_DIR / "sample"
        external_data = Path(self.temp.name) / "external-data"
        managed_data.mkdir(parents=True)
        external_data.mkdir()
        compose = {
            "name": "homestart-sample",
            "services": {
                "web": {
                    "image": "nginx:alpine",
                    "labels": {"com.homestart.managed": "true", "com.homestart.template": "sample"},
                    "volumes": [f"{managed_data}:/data", f"{external_data}:/external"],
                },
                "db": {
                    "image": "redis:alpine",
                    "labels": {"com.homestart.managed": "true", "com.homestart.template": "sample"},
                },
            },
            "volumes": {"database": {}},
        }
        compose_path = project_dir / "compose.yaml"
        compose_path.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
        commands = []

        def docker(command, timeout=60):
            commands.append(command)
            return "ok"

        manager = self.app.ComposeProjectManager(
            self.app.COMPOSE_APP_DIR,
            self.app.COMPOSE_APP_DATA_DIR,
            docker,
        )
        manager.record_install(compose_path, "homestart-sample", "sample", "Sample", compose)
        manager.action("homestart-sample", "stop")
        manager.action("homestart-sample", "restart")
        manager.action("homestart-sample", "update")
        preserved = manager.action("homestart-sample", "uninstall", delete_data=False)
        self.assertFalse(preserved["data_deleted"])
        self.assertTrue(project_dir.is_dir())
        self.assertTrue(managed_data.is_dir())
        self.assertTrue(external_data.is_dir())
        manager.action("homestart-sample", "start")
        removed = manager.action("homestart-sample", "uninstall", delete_data=True)
        self.assertTrue(removed["data_deleted"])
        self.assertFalse(project_dir.exists())
        self.assertFalse(managed_data.exists())
        self.assertTrue(external_data.exists())
        self.assertTrue(any(command[-1] == "stop" for command in commands))
        self.assertTrue(any(command[-1] == "restart" for command in commands))
        self.assertTrue(any(command[-1] == "pull" for command in commands))
        self.assertTrue(any(command[-2:] == ["--remove-orphans", "--volumes"] for command in commands))

    def test_managed_compose_services_are_grouped_as_one_app(self):
        import yaml

        self.app.COMPOSE_APP_DIR = Path(self.temp.name) / "grouped-projects"
        self.app.COMPOSE_APP_DATA_DIR = Path(self.temp.name) / "grouped-data"
        project_dir = self.app.COMPOSE_APP_DIR / "sample"
        project_dir.mkdir(parents=True)
        compose = {
            "name": "homestart-sample",
            "services": {
                "web": {"image": "nginx:alpine", "labels": {"com.homestart.template": "sample"}},
                "db": {"image": "redis:alpine", "labels": {"com.homestart.template": "sample"}},
            },
        }
        compose_path = project_dir / "compose.yaml"
        compose_path.write_text(yaml.safe_dump(compose), encoding="utf-8")
        self.app.compose_project_manager().record_install(
            compose_path, "homestart-sample", "sample", "Sample Stack", compose,
        )
        containers = [
            {
                "name": "sample-web", "docker_name": "sample-web", "docker_running": True,
                "status": "Up", "image": "nginx:alpine", "url": "http://host:8080", "ports": ["8080"],
                "compose_project": "homestart-sample", "compose_service": "web", "compose_managed": True,
            },
            {
                "name": "sample-db", "docker_name": "sample-db", "docker_running": True,
                "status": "Up", "image": "redis:alpine", "url": "", "ports": [],
                "compose_project": "homestart-sample", "compose_service": "db", "compose_managed": True,
            },
        ]
        apps = self.app.managed_compose_apps("host", containers)
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["name"], "Sample Stack")
        self.assertEqual(len(apps[0]["compose_services"]), 2)
        self.assertEqual(apps[0]["status"], "2/2 services running")

    def test_app_action_routes_compose_operations_to_project_manager(self):
        manager = mock.Mock()
        manager.action.side_effect = [
            {"ok": True, "action": "update"},
            {"ok": True, "action": "uninstall", "data_deleted": True},
        ]
        with mock.patch.object(self.app, "compose_project_manager", return_value=manager), \
                mock.patch.object(self.app, "load_config_file", return_value={"features": {"docker_actions": True}}), \
                mock.patch.object(self.app, "app_uninstall_enabled", return_value=True):
            updated = self.app.app_action({
                "action": "update",
                "compose_project": "homestart-sample",
            })
            removed = self.app.app_action({
                "action": "uninstall",
                "compose_project": "homestart-sample",
                "delete_data": True,
            })
        self.assertEqual(updated["action"], "update")
        self.assertTrue(removed["data_deleted"])
        manager.action.assert_has_calls([
            mock.call("homestart-sample", "update"),
            mock.call("homestart-sample", "uninstall", delete_data=True),
        ])

    def update_fixture(self, root, version="test-2", valid=True):
        package_root = Path(root) / "package"
        (package_root / "homestart").mkdir(parents=True)
        (package_root / "static").mkdir()
        (package_root / "app.py").write_text(
            "from homestart.server import main\n" if valid else "from missing_package import main\n",
            encoding="utf-8",
        )
        (package_root / "homestart" / "__init__.py").write_text("", encoding="utf-8")
        (package_root / "homestart" / "server.py").write_text(
            "def main():\n    return True\n",
            encoding="utf-8",
        )
        (package_root / "static" / "new.js").write_text("new", encoding="utf-8")
        (package_root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
        (package_root / "package.json").write_text(json.dumps({
            "name": "homestart", "version": version, "package_type": "update", "format": 1,
        }), encoding="utf-8")
        archive_path = Path(root) / "update.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(package_root, arcname="homestart")
        return archive_path.read_bytes()

    def test_transactional_update_preserves_runtime_data_and_removes_stale_static(self):
        from homestart.updates.package import TransactionalPackageUpdater

        install = Path(self.temp.name) / "transaction-install"
        backup = install / "data" / "backups"
        static = install / "static"
        static.mkdir(parents=True)
        (install / "app.py").write_text("old app", encoding="utf-8")
        (static / "old.js").write_text("old", encoding="utf-8")
        (install / "config.json").write_text('{"keep": true}', encoding="utf-8")
        (install / "data" / "history.db").parent.mkdir(parents=True, exist_ok=True)
        (install / "data" / "history.db").write_bytes(b"history")
        payload = self.update_fixture(self.temp.name)
        result = TransactionalPackageUpdater(install, backup, static).apply_bytes(payload)
        self.assertEqual(result["manifest"]["version"], "test-2")
        self.assertIn("from homestart.server", (install / "app.py").read_text(encoding="utf-8"))
        self.assertTrue((static / "new.js").is_file())
        self.assertFalse((static / "old.js").exists())
        self.assertEqual((install / "config.json").read_text(encoding="utf-8"), '{"keep": true}')
        self.assertEqual((install / "data" / "history.db").read_bytes(), b"history")
        self.assertTrue((Path(result["backup"]) / "transaction.json").is_file())

    def test_failed_update_preflight_changes_nothing(self):
        from homestart.updates.package import TransactionalPackageUpdater

        install = Path(self.temp.name) / "failed-install"
        static = install / "static"
        static.mkdir(parents=True)
        (install / "app.py").write_text("old app", encoding="utf-8")
        payload = self.update_fixture(Path(self.temp.name) / "invalid", valid=False)
        with self.assertRaisesRegex(ValueError, "preflight failed"):
            TransactionalPackageUpdater(install, install / "data" / "backups", static).apply_bytes(payload)
        self.assertEqual((install / "app.py").read_text(encoding="utf-8"), "old app")

    def test_transaction_failure_rolls_back_already_replaced_files(self):
        from homestart.updates.package import TransactionalPackageUpdater

        install = Path(self.temp.name) / "rollback-install"
        static = install / "static"
        static.mkdir(parents=True)
        (install / "app.py").write_text("old app", encoding="utf-8")
        payload = self.update_fixture(Path(self.temp.name) / "rollback-payload")
        updater = TransactionalPackageUpdater(install, install / "data" / "backups", static)
        original_copy = updater._atomic_copy

        def fail_on_static(source, target):
            if target.name == "new.js" and "staged" in source.parts:
                raise OSError("simulated disk failure")
            return original_copy(source, target)

        with mock.patch.object(updater, "_atomic_copy", side_effect=fail_on_static):
            with self.assertRaisesRegex(OSError, "simulated disk failure"):
                updater.apply_bytes(payload)
        self.assertEqual((install / "app.py").read_text(encoding="utf-8"), "old app")
        self.assertFalse((static / "new.js").exists())

    def test_post_restart_verifier_restores_transaction_backup(self):
        from scripts import verify_update

        install = Path(self.temp.name) / "verified-install"
        backup = Path(self.temp.name) / "verified-backup"
        (install / "homestart").mkdir(parents=True)
        (backup / "homestart").mkdir(parents=True)
        (install / "app.py").write_text("broken", encoding="utf-8")
        (install / "homestart" / "new.py").write_text("new", encoding="utf-8")
        (backup / "app.py").write_text("working", encoding="utf-8")
        (backup / "transaction.json").write_text(json.dumps({
            "replaced": ["app.py"],
            "created": ["homestart/new.py"],
            "removed": [],
        }), encoding="utf-8")
        with mock.patch.object(verify_update.subprocess, "run") as run:
            verify_update.rollback(install, backup)
        self.assertEqual((install / "app.py").read_text(encoding="utf-8"), "working")
        self.assertFalse((install / "homestart" / "new.py").exists())
        self.assertTrue((backup / "rollback.json").is_file())
        run.assert_called_once()

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
        self.assertIsInstance(self.app.metrics_history("auto")["server_timestamp"], int)

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

    def test_networkmanager_configuration_is_detected_and_parsed(self):
        address = {
            "ifname": "eth0",
            "link_type": "ether",
            "operstate": "UP",
            "address": "00:11:22:33:44:55",
            "addr_info": [{"family": "inet", "local": "192.168.1.20", "prefixlen": 24}],
        }
        device = {
            "device": "eth0",
            "type": "ethernet",
            "state": "connected",
            "connection": "Wired connection 1",
        }
        with mock.patch.object(self.app, "run_json", return_value=[address]), \
                mock.patch.object(self.app, "is_physical_network_interface", return_value=True), \
                mock.patch.object(self.app, "monitorable_network_interfaces", return_value=[{"name": "eth0"}]), \
                mock.patch.object(self.app, "default_routes", return_value={"eth0": {"gateway": "192.168.1.1"}}), \
                mock.patch.object(self.app, "netplan_interface_config", return_value=(None, {})), \
                mock.patch.object(self.app, "network_manager_devices", return_value={"eth0": device}), \
                mock.patch.object(
                    self.app,
                    "network_manager_interface_config",
                    return_value=("Wired connection 1", {
                        "mode": "dhcp", "addresses": ["192.168.1.20/24"],
                        "gateway": "192.168.1.1", "dns": ["192.168.1.1"],
                    }),
                ), \
                mock.patch.object(self.app, "default_route_interfaces", return_value=["eth0"]):
            payload = self.app.network_interfaces_payload()
        interface = payload["interfaces"][0]
        self.assertEqual(payload["renderer"], "networkmanager")
        self.assertEqual(interface["managed_by"], "networkmanager")
        self.assertEqual(interface["connection_name"], "Wired connection 1")
        self.assertEqual(interface["mode"], "dhcp")
        self.assertTrue(interface["editable"])

    def test_networkmanager_update_uses_existing_profile_and_writes_backup(self):
        self.app.BACKUP_DIR = Path(self.temp.name) / "backups"
        device = {
            "device": "eth0", "type": "ethernet",
            "state": "connected", "connection": "Wired connection 1",
        }
        commands = []

        def nmcli(arguments, timeout=12):
            commands.append(arguments)
            return ""

        with mock.patch.object(self.app, "validate_interface_name"), \
                mock.patch.object(self.app, "network_manager_devices", return_value={"eth0": device}), \
                mock.patch.object(
                    self.app,
                    "network_manager_interface_config",
                    return_value=("Wired connection 1", {
                        "mode": "dhcp", "addresses": [], "gateway": "", "dns": [],
                    }),
                ), \
                mock.patch.object(self.app, "nmcli_output", side_effect=nmcli):
            result = self.app.update_network_manager_interface(
                "eth0", "static", "192.168.1.20/24", "192.168.1.1", ["1.1.1.1"],
            )
        self.assertEqual(result["managed_by"], "networkmanager")
        self.assertTrue(Path(result["backup"]).is_file())
        self.assertIn(
            ["connection", "modify", "Wired connection 1",
             "ipv4.method", "manual", "ipv4.addresses", "192.168.1.20/24",
             "ipv4.gateway", "192.168.1.1", "ipv4.dns", "1.1.1.1"],
            commands,
        )
        self.assertIn(
            ["connection", "up", "Wired connection 1", "ifname", "eth0"],
            commands,
        )

    def test_network_update_prefers_netplan_and_falls_back_to_networkmanager(self):
        with mock.patch.object(self.app, "validate_interface_name"), \
                mock.patch.object(
                    self.app, "netplan_interface_config",
                    return_value=(Path("/etc/netplan/01-network.yaml"), {"dhcp4": True}),
                ), \
                mock.patch.object(
                    self.app, "update_netplan_interface",
                    return_value={"ok": True, "managed_by": "netplan"},
                ) as netplan_update, \
                mock.patch.object(self.app, "update_network_manager_interface") as nm_update:
            result = self.app.update_network_interface("eth0", "dhcp", "", "", [])
        self.assertEqual(result["managed_by"], "netplan")
        netplan_update.assert_called_once()
        nm_update.assert_not_called()

        device = {"device": "eth0", "type": "ethernet", "state": "connected"}
        with mock.patch.object(self.app, "validate_interface_name"), \
                mock.patch.object(self.app, "netplan_interface_config", return_value=(None, {})), \
                mock.patch.object(self.app, "network_manager_devices", return_value={"eth0": device}), \
                mock.patch.object(
                    self.app, "update_network_manager_interface",
                    return_value={"ok": True, "managed_by": "networkmanager"},
                ) as nm_update:
            result = self.app.update_network_interface("eth0", "dhcp", "", "", [])
        self.assertEqual(result["managed_by"], "networkmanager")
        nm_update.assert_called_once()

    def test_nmcli_terse_parser_preserves_escaped_connection_names(self):
        rows = self.app.parse_nmcli_rows(
            "eth0:ethernet:connected:Office\\: LAN\n",
            ("device", "type", "state", "connection"),
        )
        self.assertEqual(rows[0]["connection"], "Office: LAN")

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

    def test_ss_tcp_counters_include_process_and_socket_totals(self):
        output = (
            'ESTAB 0 0 192.168.0.32:443 192.168.0.10:50100 users:(("nginx",pid=123,fd=6))\n'
            " cubic wscale:7,7 bytes_sent:900 bytes_received:1200 segs_out:10 segs_in:12\n"
        )
        counters = self.app.parse_ss_tcp_counters(output)
        self.assertEqual(len(counters), 1)
        self.assertEqual(counters[0]["pid"], 123)
        self.assertEqual(counters[0]["process"], "nginx")
        self.assertEqual(counters[0]["local"], "192.168.0.32:443")
        self.assertEqual(counters[0]["rx_total"], 1200)
        self.assertEqual(counters[0]["tx_total"], 900)
        self.assertEqual(self.app.endpoint_address("[::ffff:192.168.0.32]:443"), "192.168.0.32")

    def test_host_network_estimate_uses_tcp_counter_deltas(self):
        first = [{"key": "123:a>b", "pid": 123, "process": "curl", "local": "192.168.0.32:4000",
                  "peer": "1.1.1.1:443", "rx_total": 1000, "tx_total": 500, "owner_count": 1}]
        second = [{**first[0], "rx_total": 7000, "tx_total": 2500}]
        identity = {"key": "process:curl", "name": "curl", "kind": "process", "confidence": "medium"}
        with mock.patch.object(self.app, "ss_tcp_process_counters", side_effect=[first, second]), \
                mock.patch.object(self.app, "interface_ip_addresses", return_value={"192.168.0.32"}), \
                mock.patch.object(self.app, "docker_identity_names", return_value={}), \
                mock.patch.object(self.app, "host_process_identity", return_value=identity), \
                mock.patch.object(self.app.time, "monotonic", side_effect=[100, 102]):
            self.assertEqual(self.app.update_host_network_estimates("eth0"), [])
            samples = self.app.update_host_network_estimates("eth0")
        self.assertEqual(samples[0]["name"], "curl")
        self.assertEqual(samples[0]["rx_bytes"], 6000)
        self.assertEqual(samples[0]["tx_bytes"], 2000)
        self.assertEqual(samples[0]["rx_bps"], 3000)
        self.assertEqual(samples[0]["confidence"], "medium")

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
        self.assertEqual(history["network_points"][-1]["rx_avg_bps"], 7000)
        self.assertLessEqual(history["network_status"]["last_sample_age_seconds"], 1)

    def test_network_history_buckets_preserve_short_peaks(self):
        self.app.DB_PATH = Path(self.temp.name) / "network-peak-metrics.db"
        now = int(__import__("time").time())
        for offset in range(-3599, 1):
            self.app.record_network_metric({
                "timestamp": now + offset,
                "rx_bps": 875_000_000 if offset == -1800 else 1_000,
                "tx_bps": 2_000,
            })
        history = self.app.metrics_history(1)
        peak = max(history["network_points"], key=lambda point: point["rx_bps"])
        self.assertEqual(peak["rx_bps"], 875_000_000)
        self.assertLess(peak["rx_avg_bps"], peak["rx_bps"])
        self.assertGreater(peak["sample_count"], 1)

    def test_container_network_ranking_accumulates_traffic_by_name(self):
        self.app.DB_PATH = Path(self.temp.name) / "container-network.db"
        now = int(__import__("time").time())
        self.app.record_container_network_metrics([
            {"key": "alpha-1", "name": "alpha", "rx_bps": 1000, "tx_bps": 500, "sample_seconds": 2},
            {"key": "beta-1", "name": "beta", "rx_bps": 100, "tx_bps": 50, "sample_seconds": 2},
        ], now)
        self.app.record_container_network_metrics([
            {"key": "alpha-1", "name": "alpha", "rx_bps": 2000, "tx_bps": 1000, "sample_seconds": 2},
        ], now + 1)
        ranking = self.app.container_network_ranking(60)
        self.assertEqual(ranking["items"][0]["name"], "alpha")
        self.assertEqual(ranking["items"][0]["rx_bytes"], 6000)
        self.assertEqual(ranking["items"][0]["tx_bytes"], 3000)
        self.assertEqual(ranking["items"][0]["total_bytes"], 9000)

    def test_host_network_ranking_separates_estimated_and_unattributed_traffic(self):
        self.app.DB_PATH = Path(self.temp.name) / "host-network.db"
        now = int(__import__("time").time())
        self.app.record_host_network_estimates(
            [{"key": "process:curl", "name": "curl", "kind": "process", "confidence": "medium",
              "rx_bytes": 4000, "tx_bytes": 1000, "rx_bps": 2000, "tx_bps": 500}],
            {"sample_seconds": 2, "rx_bps": 3000, "tx_bps": 1000},
            [],
            now,
        )
        ranking = self.app.container_network_ranking(60)
        self.assertEqual(ranking["items"], [])
        process = next(item for item in ranking["estimated_items"] if item["kind"] == "process")
        unattributed = next(item for item in ranking["estimated_items"] if item["kind"] == "unattributed")
        self.assertEqual(process["name"], "curl")
        self.assertEqual(process["total_bytes"], 5000)
        self.assertEqual(process["confidence"], "medium")
        self.assertEqual(unattributed["rx_bytes"], 2000)
        self.assertEqual(unattributed["tx_bytes"], 1000)
        self.assertEqual(unattributed["confidence"], "low")

    def test_history_charts_use_their_rendered_panel_width(self):
        script = (Path(__file__).parents[1] / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("responsiveChartWidth(historyChart)", script)
        self.assertIn("responsiveChartWidth(bandwidthChart)", script)
        self.assertNotIn("const width = 800;", script)

    def test_new_file_and_bandwidth_controls_are_wired(self):
        root = Path(__file__).parents[1]
        script = (root / "static" / "app.js").read_text(encoding="utf-8")
        html = (root / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('action: "copy_start"', script)
        self.assertIn("/api/file/properties", script)
        self.assertIn("/api/network/ranking", script)
        self.assertIn('data-file-context-action="properties"', html)
        self.assertIn('id="bandwidth-ranking-period"', html)
        self.assertIn('id="host-bandwidth-ranking-list"', html)
        self.assertIn('action: "copy_cancel"', script)
        self.assertIn("function formatCopySize", script)
        self.assertIn("status.engine_label", script)
        self.assertIn('id="file-copy-speed"', html)
        self.assertIn('id="file-copy-cancel"', html)
        self.assertIn('id="app-uninstall-dialog"', html)
        self.assertIn('id="store-risk"', html)
        self.assertIn('name="uninstall-data"', html)
        self.assertIn("compose_project: app.compose_project", script)
        self.assertIn("delete_data: Boolean(options.deleteData)", script)
        self.assertIn('runAppAction(app, "update")', script)
        self.assertIn("Managed by ${managerLabels", script)
        self.assertIn("architecture_compatible === false", script)


if __name__ == "__main__":
    unittest.main()
