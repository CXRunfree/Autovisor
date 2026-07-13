import os
import stat
import tempfile
import unittest
from pathlib import Path

from modules.configs import Config
from modules.utils import normalize_zhihuishu_cookies, save_cookies


CONFIG = """
[user-account]
username =
password =
[browser-option]
driver = Chrome
EXE_PATH = /Applications/Google Chrome.app
attachExistingChrome = False
cdpUrl = http://127.0.0.1:9222
[script-option]
enableAutoCaptcha = False
enableHideWindow = False
showDonateCode = False
[course-option]
soundOff = True
limitMaxTime = 0
limitSpeed = 1
[course-url]
URL1 =
"""


class ConfigTests(unittest.TestCase):
    def test_macos_browser_options(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.ini"
            path.write_text(CONFIG, encoding="utf-8")
            config = Config(path)
            self.assertEqual(config.driver, "chrome")
            self.assertFalse(config.attach_existing_chrome)
            self.assertTrue(config.exe_path.endswith("Google Chrome.app"))

    @unittest.skipIf(os.name == "nt", "POSIX permission test")
    def test_saved_cookies_are_owner_only(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "cookies.json"
            save_cookies([{"name": "test", "value": "secret"}], path)
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX permission test")
    def test_cookie_overwrite_tightens_existing_permissions(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "cookies.json"
            path.write_text("{}", encoding="utf-8")
            path.chmod(0o644)
            save_cookies([{"name": "test", "value": "secret"}], path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_cookie_normalization_filters_domains_and_expiry(self):
        cookies = normalize_zhihuishu_cookies(
            [
                {"name": "ok", "value": "1", "domain": ".zhihuishu.com", "path": "/"},
                {"name": "old", "value": "2", "domain": ".zhihuishu.com", "expires": 99},
                {"name": "other", "value": "3", "domain": ".example.com"},
                {"name": "lookalike", "value": "4", "domain": ".evilzhihuishu.com"},
                {"name": "blank", "value": "4", "domain": ""},
            ],
            now=100,
        )
        self.assertEqual([cookie["name"] for cookie in cookies], ["ok"])

    def test_cookie_normalization_preserves_top_level_http_only(self):
        cookies = normalize_zhihuishu_cookies(
            [
                {
                    "name": "session",
                    "value": "secret",
                    "domain": "passport.zhihuishu.com",
                    "httpOnly": True,
                }
            ],
            now=100,
        )
        self.assertTrue(cookies[0]["httpOnly"])
