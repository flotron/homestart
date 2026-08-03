import tempfile
import unittest
from pathlib import Path
from unittest import mock

from homestart.system.webapps import (
    NativeWebAppDiscovery,
    display_name,
    parse_ss_listeners,
    process_details,
)


SS_OUTPUT = """\
LISTEN 0 128 0.0.0.0:8765 0.0.0.0:* users:((\"python3\",pid=321,fd=4))
LISTEN 0 4096 [::]:22 [::]:* users:((\"sshd\",pid=88,fd=3))
LISTEN 0 4096 127.0.0.1:9000 0.0.0.0:* users:((\"gunicorn\",pid=654,fd=5))
"""


class NativeWebAppDiscoveryTests(unittest.TestCase):
    def test_parse_ss_listeners_supports_ipv4_and_ipv6(self):
        listeners = parse_ss_listeners(SS_OUTPUT)
        self.assertEqual(listeners[0], {
            "address": "0.0.0.0", "port": 8765, "pid": 321, "process": "python3"
        })
        self.assertEqual(listeners[1]["address"], "::")
        self.assertEqual(listeners[1]["port"], 22)

    def test_process_details_finds_systemd_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "321"
            process.mkdir()
            (process / "comm").write_text("python3\n", encoding="utf-8")
            (process / "cmdline").write_bytes(b"python3\0/opt/scanner/app.py\0")
            (process / "cgroup").write_text(
                "0::/system.slice/lan-scanner.service\n", encoding="utf-8"
            )
            details = process_details(321, proc_root=root)
        self.assertEqual(details["unit"], "lan-scanner.service")
        self.assertEqual(details["command"], "python3 /opt/scanner/app.py")
        self.assertEqual(display_name({"port": 8765}, details), "Lan Scanner")

    def test_generic_python_process_uses_its_project_name(self):
        details = {
            "process": "python3",
            "command": "python3 /opt/my-scanner/app.py --port 8765",
            "unit": "",
        }
        self.assertEqual(display_name({"port": 8765}, details), "My Scanner")

    def test_collect_keeps_web_apps_and_filters_internal_services(self):
        discovery = NativeWebAppDiscovery(command_runner=lambda: SS_OUTPUT)
        details = {
            321: {"process": "python3", "command": "python3 app.py", "unit": "lan-scanner.service", "containerized": False},
            654: {"process": "gunicorn", "command": "gunicorn app", "unit": "private-ui.service", "containerized": False},
        }
        with mock.patch("homestart.system.webapps.process_details", side_effect=lambda pid, fallback, root: details.get(pid, {"process": fallback, "command": "", "unit": "", "containerized": False})), \
                mock.patch("homestart.system.webapps.probe_http", return_value=("http", 200)):
            apps = discovery.collect("192.168.1.10", home_port=81)
        self.assertEqual([app["name"] for app in apps], ["Lan Scanner", "Private UI"])
        self.assertEqual(apps[0]["url"], "http://192.168.1.10:8765")
        self.assertEqual(apps[1]["status"], "Detected · local only")
        self.assertEqual(apps[1]["url"], "")


if __name__ == "__main__":
    unittest.main()
