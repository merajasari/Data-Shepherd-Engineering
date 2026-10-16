import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ml import linux_scheduler_adapter as adapter


class LinuxSchedulerAdapterTests(unittest.TestCase):
    def _write_units(self, root: Path, kind: str):
        config = adapter.CONTRACTS[kind]

        service = root / config["service"]
        timer = root / config["timer"]

        service.write_text(
            "[Service]\n"
            "User=ubuntu\n"
            f"WorkingDirectory={adapter.PROJECT_ROOT}\n"
            "ExecStart="
            f"{adapter.PROJECT_ROOT}/.venv/bin/python "
            f"-u -m ml.linux_scheduler_adapter {kind}\n",
            encoding="utf-8",
        )

        timer.write_text(
            "[Timer]\n"
            f"OnUnitActiveSec=300s\n"
            f"Unit={config['service']}\n",
            encoding="utf-8",
        )

    def test_v8_systemd_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_units(root, "v8")

            ok, detail = adapter.scheduler_contract_safe(
                "v8",
                unit_root=root,
            )

            self.assertTrue(ok, detail)

    def test_v10_systemd_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_units(root, "v10")

            ok, detail = adapter.scheduler_contract_safe(
                "v10",
                unit_root=root,
            )

            self.assertTrue(ok, detail)

    def test_contract_fails_closed_when_unit_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            ok, detail = adapter.scheduler_contract_safe(
                "v8",
                unit_root=Path(directory),
            )

            self.assertFalse(ok)
            self.assertIn("missing unit file", detail)

    @patch.object(adapter, "_systemctl")
    def test_loaded_requires_active_and_enabled_timer(self, systemctl):
        active = unittest.mock.Mock(
            returncode=0,
            stdout="active\n",
            stderr="",
        )
        enabled = unittest.mock.Mock(
            returncode=0,
            stdout="enabled\n",
            stderr="",
        )
        systemctl.side_effect = [active, enabled]

        loaded, detail = adapter.scheduler_loaded("v8")

        self.assertTrue(loaded, detail)
        self.assertEqual(
            systemctl.call_args_list[0].args,
            ("is-active", "datashepherd-v8paper.timer"),
        )
        self.assertEqual(
            systemctl.call_args_list[1].args,
            ("is-enabled", "datashepherd-v8paper.timer"),
        )

    @patch.object(adapter, "_systemctl")
    def test_loaded_fails_closed_if_timer_not_active(self, systemctl):
        inactive = unittest.mock.Mock(
            returncode=3,
            stdout="inactive\n",
            stderr="",
        )
        enabled = unittest.mock.Mock(
            returncode=0,
            stdout="enabled\n",
            stderr="",
        )
        systemctl.side_effect = [inactive, enabled]

        loaded, _ = adapter.scheduler_loaded("v10")

        self.assertFalse(loaded)

    def test_adapter_is_outside_frozen_manifests(self):
        manifests = (
            Path("ml/v8/operational_lock_manifest.json"),
            Path("ml/v10/cycle3_operational_lock_manifest.json"),
        )

        for path in manifests:
            payload = json.loads(path.read_text(encoding="utf-8"))
            protected = {
                item["path"]
                for item in payload["protected_files"]
            }

            self.assertNotIn(
                "ml/linux_scheduler_adapter.py",
                protected,
            )


if __name__ == "__main__":
    unittest.main()
