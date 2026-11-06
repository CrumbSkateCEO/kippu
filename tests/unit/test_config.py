from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from el_bienvenidor.config import load_settings
from el_bienvenidor.domain.errors import ConfigurationError


class ConfigurationTests(unittest.TestCase):
    def test_example_configuration_loads_with_paths_under_project_data(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "config"
            config_dir.mkdir()
            config = config_dir / "config.toml"
            config.write_text("[camera]\n[vision]\n[print]\n[storage]\njobs_directory = \"data/jobs\"\n[ui]\n[logging]", encoding="utf-8")
            settings = load_settings(config)
            self.assertEqual(settings.storage.jobs_directory, root / "data" / "jobs")

    def test_retention_path_cannot_escape_project_data(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "config"
            config_dir.mkdir()
            config = config_dir / "config.toml"
            config.write_text("[camera]\n[vision]\n[print]\n[storage]\njobs_directory = \"/tmp/not-kippu\"\n[ui]\n[logging]", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_settings(config)

    def test_ip_camera_configuration_valid(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "config"
            config_dir.mkdir()
            config = config_dir / "config.toml"
            config.write_text(
                "[camera]\nsource_type = \"ip\"\nip_url = \"rtsp://user:pass@192.168.1.10:554/live\"\nrtsp_transport = \"tcp\"\n"
                "[vision]\n[print]\n[storage]\njobs_directory = \"data/jobs\"\n[ui]\n[logging]",
                encoding="utf-8",
            )
            settings = load_settings(config)
            self.assertEqual(settings.camera.source_type, "ip")
            self.assertEqual(settings.camera.ip_url, "rtsp://user:pass@192.168.1.10:554/live")
            self.assertEqual(settings.camera.rtsp_transport, "tcp")
            self.assertTrue(settings.camera.low_delay)

    def test_ip_camera_configuration_missing_url(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "config"
            config_dir.mkdir()
            config = config_dir / "config.toml"
            config.write_text(
                "[camera]\nsource_type = \"ip\"\n"
                "[vision]\n[print]\n[storage]\njobs_directory = \"data/jobs\"\n[ui]\n[logging]",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigurationError):
                load_settings(config)

    def test_camera_invalid_source_type(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "config"
            config_dir.mkdir()
            config = config_dir / "config.toml"
            config.write_text(
                "[camera]\nsource_type = \"unknown_device\"\n"
                "[vision]\n[print]\n[storage]\njobs_directory = \"data/jobs\"\n[ui]\n[logging]",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigurationError):
                load_settings(config)


if __name__ == "__main__":
    unittest.main()

