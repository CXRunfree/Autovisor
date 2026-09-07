import os
import tempfile
import unittest
from unittest.mock import patch

from modules.configs import Config, ConfigError


class ConfigTests(unittest.TestCase):
    def test_reports_missing_config_file(self):
        with self.assertRaisesRegex(ConfigError, "未找到配置文件"):
            Config("missing-configs.ini")

    def test_reports_missing_required_sections(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
            file.write("[user-account]\nusername =\n")
            path = file.name
        try:
            with self.assertRaisesRegex(ConfigError, "缺少必要配置段"):
                Config(path)
        finally:
            os.remove(path)

    def test_reads_configured_mirrors(self):
        mirrors_path = None
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
            file.write(
                "[user-account]\nusername=\npassword=\n"
                "[browser-option]\ndriver=edge\nEXE_PATH=\n"
                "[script-option]\nenableAutoCaptcha=true\nenableHideWindow=false\nshowDonateCode=true\n"
                "[course-option]\nsoundOff=true\n"
                "[course-url]\nURL1=\n"
                "[mirrors]\nprimary=https://mirror.example/simple\n"
            )
            path = file.name
        mirrors_path = path + ".json"
        with open(mirrors_path, "w", encoding="utf-8") as file:
            file.write('{"primary": "https://mirror.example/simple"}')
        try:
            self.assertEqual(
                Config(path, mirrors_path).mirrors,
                {"primary": "https://mirror.example/simple"},
            )
        finally:
            os.remove(path)
            os.remove(mirrors_path)

    def test_frozen_default_mirrors_path_is_next_to_executable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = os.path.join(temp_dir, "data")
            os.mkdir(data_dir)
            mirrors_path = os.path.join(data_dir, "mirrors.json")
            with open(mirrors_path, "w", encoding="utf-8") as file:
                file.write('{"primary": "https://mirror.example/simple"}')
            with patch("modules.configs.sys.frozen", True, create=True), \
                    patch("modules.configs.sys.executable", os.path.join(temp_dir, "Autovisor.exe")):
                self.assertEqual(
                    Config().mirrors,
                    {"primary": "https://mirror.example/simple"},
                )


if __name__ == "__main__":
    unittest.main()
