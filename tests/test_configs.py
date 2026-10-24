import json
import os
import tempfile
import unittest
from unittest.mock import patch

from modules.configs import Config, ConfigError, ensure_config_files


class ConfigTests(unittest.TestCase):
    def test_reports_missing_config_file(self):
        with self.assertRaisesRegex(ConfigError, "未找到配置文件"):
            Config("missing-config.ini")

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


    def test_reads_config_with_utf8_bom(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", delete=False) as file:
            file.write(
                "[user-account]\nusername=\npassword=\n"
                "[browser-option]\ndriver=edge\nEXE_PATH=\n"
                "[script-option]\nenableAutoCaptcha=false\nenableHideWindow=false\nshowDonateCode=false\n"
                "[course-option]\nsoundOff=true\n"
                "[course-url]\nURL1=\n"
            )
            path = file.name
        mirrors_path = path + ".json"
        with open(mirrors_path, "w", encoding="utf-8") as file:
            file.write('{"primary": "https://mirror.example/simple"}')
        try:
            self.assertEqual(Config(path, mirrors_path).driver, "edge")
        finally:
            os.remove(path)
            os.remove(mirrors_path)

    def test_reads_mirrors_with_utf8_bom(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
            file.write(
                "[user-account]\nusername=\npassword=\n"
                "[browser-option]\ndriver=edge\nEXE_PATH=\n"
                "[script-option]\nenableAutoCaptcha=false\nenableHideWindow=false\nshowDonateCode=false\n"
                "[course-option]\nsoundOff=true\n"
                "[course-url]\nURL1=\n"
            )
            path = file.name
        mirrors_path = path + ".json"
        with open(mirrors_path, "w", encoding="utf-8-sig") as file:
            file.write('{"primary": "https://mirror.example/simple"}')
        try:
            self.assertEqual(
                Config(path, mirrors_path).mirrors,
                {"primary": "https://mirror.example/simple"},
            )
        finally:
            os.remove(path)
            os.remove(mirrors_path)



class EnsureConfigFilesTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher = patch("modules.configs._runtime_root", return_value=self._tmpdir.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _config_path(self):
        return os.path.join(self._tmpdir.name, "config.ini")

    def test_generates_missing_files_and_returns_created_list(self):
        created = ensure_config_files(self._config_path())
        names = sorted(os.path.basename(path) for path in created)
        self.assertEqual(names, ["config.ini", "llm.json", "mirrors.json"])
        self.assertTrue(os.path.isfile(self._config_path()))
        self.assertTrue(os.path.isfile(os.path.join(self._tmpdir.name, "data", "llm.json")))
        self.assertTrue(os.path.isfile(os.path.join(self._tmpdir.name, "data", "mirrors.json")))

    def test_never_overwrites_existing_files(self):
        config_path = self._config_path()
        custom = "[user-account]\nusername = kept\n"
        with open(config_path, "w", encoding="utf-8") as file:
            file.write(custom)
        llm_path = os.path.join(self._tmpdir.name, "data", "llm.json")
        os.mkdir(os.path.join(self._tmpdir.name, "data"))
        with open(llm_path, "w", encoding="utf-8") as file:
            file.write('{"api_key": "mine"}')
        created = ensure_config_files(config_path)
        self.assertEqual([os.path.basename(path) for path in created], ["mirrors.json"])
        with open(config_path, "r", encoding="utf-8") as file:
            self.assertEqual(file.read(), custom)
        with open(llm_path, "r", encoding="utf-8") as file:
            self.assertEqual(json.load(file), {"api_key": "mine"})

    def test_generated_config_is_loadable_by_config(self):
        config_path = self._config_path()
        ensure_config_files(config_path)
        config = Config(config_path, os.path.join(self._tmpdir.name, "data", "mirrors.json"))
        self.assertEqual(config.course_urls, [])
        self.assertEqual(config.driver, "edge")

    def test_generated_llm_json_has_expected_keys(self):
        ensure_config_files(self._config_path())
        with open(os.path.join(self._tmpdir.name, "data", "llm.json"), encoding="utf-8") as file:
            data = json.load(file)
        self.assertEqual(
            sorted(data),
            ["api_base", "api_key", "auto_submit", "model"],
        )
        self.assertEqual(data["api_key"], "")


if __name__ == "__main__":
    unittest.main()
