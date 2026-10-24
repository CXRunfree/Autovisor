import os
import tempfile
import unittest
from unittest import mock

import Autovisor


class _Logger:
    def __init__(self):
        self.events = []
        self.exceptions = []

    def event(self, name, interval=None, **fields):
        self.events.append((name, fields))

    def log_exception(self, msg, exc=None, shift=False):
        self.exceptions.append(msg)


class _Context:
    def __init__(self, cookies):
        self.cookies_payload = cookies

    async def cookies(self):
        return self.cookies_payload


def _cookie(name, value="v1"):
    return {"name": name, "domain": ".zhihuishu.com", "path": "/", "value": value}


class CookiePersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = _Logger()
        self.logger_patch = mock.patch.object(
            Autovisor, "logger", self.logger, create=True
        )
        self.save_patch = mock.patch.object(Autovisor, "save_cookies")
        self.logger_patch.start()
        self.save_cookies = self.save_patch.start()
        self.addCleanup(self.logger_patch.stop)
        self.addCleanup(self.save_patch.stop)
        Autovisor.remember_login_cookies(None)

    async def test_saves_on_first_change(self):
        await Autovisor.persist_login_cookies(_Context([_cookie("a")]))
        self.assertEqual(self.save_cookies.call_count, 1)
        self.assertEqual(
            self.logger.events,
            [("保存登录凭证", {"条数": 1, "文件": Autovisor.COOKIE_PATH})],
        )

    async def test_skips_unchanged_cookies(self):
        context = _Context([_cookie("a")])
        await Autovisor.persist_login_cookies(context)
        await Autovisor.persist_login_cookies(context)
        self.assertEqual(self.save_cookies.call_count, 1)

    async def test_saves_again_after_cookie_refresh(self):
        context = _Context([_cookie("a", "v1")])
        await Autovisor.persist_login_cookies(context)
        context.cookies_payload = [_cookie("a", "v2")]
        await Autovisor.persist_login_cookies(context)
        self.assertEqual(self.save_cookies.call_count, 2)

    async def test_remembers_loaded_cookies_without_rewrite(self):
        cookies = [_cookie("a")]
        Autovisor.remember_login_cookies(cookies)
        await Autovisor.persist_login_cookies(_Context(cookies))
        self.assertEqual(self.save_cookies.call_count, 0)

    async def test_ignores_empty_cookies(self):
        await Autovisor.persist_login_cookies(_Context([]))
        await Autovisor.persist_login_cookies(_Context(None))
        self.assertEqual(self.save_cookies.call_count, 0)
        self.assertEqual(self.logger.events, [])

    async def test_save_failure_is_logged_and_not_raised(self):
        self.save_cookies.side_effect = OSError("disk full")
        await Autovisor.persist_login_cookies(_Context([_cookie("a")]))
        self.assertEqual(self.logger.exceptions, ["保存登录 Cookies 失败."])

    async def test_retries_after_save_failure(self):
        self.save_cookies.side_effect = [OSError("disk full"), None]
        context = _Context([_cookie("a")])
        await Autovisor.persist_login_cookies(context)
        await Autovisor.persist_login_cookies(context)
        self.assertEqual(self.save_cookies.call_count, 2)
        self.assertEqual(len(self.logger.events), 1)

    async def test_filters_out_third_party_and_expired_cookies(self):
        context = _Context(
            [
                _cookie("a"),
                {"name": "track", "domain": ".example.com", "path": "/", "value": "x"},
                {"name": "old", "domain": ".zhihuishu.com", "path": "/", "value": "x", "expires": 1},
            ]
        )
        await Autovisor.persist_login_cookies(context)
        self.assertEqual(self.save_cookies.call_count, 1)
        saved = self.save_cookies.call_args[0][0]
        self.assertEqual([cookie["name"] for cookie in saved], ["a"])
        self.assertEqual(self.logger.events[0][1]["条数"], 1)

    async def test_all_cookies_filtered_out_does_not_wipe_file(self):
        context = _Context([{"name": "track", "domain": ".example.com", "path": "/", "value": "x"}])
        await Autovisor.persist_login_cookies(context)
        self.assertEqual(self.save_cookies.call_count, 0)
        self.assertEqual(self.logger.events, [])


class SaveCredentialsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_path = os.path.join(self._tmpdir.name, "config.ini")

    def _write(self, text, encoding="utf-8"):
        with open(self.config_path, "w", encoding=encoding) as file:
            file.write(text)

    def _read(self, encoding="utf-8"):
        with open(self.config_path, "r", encoding=encoding) as file:
            return file.read()

    def test_fills_empty_fields_and_keeps_comments(self):
        self._write(
            "[user-account]\n;配置账号密码，留空则打开网页后需手动登录\nusername =\npassword =\n\n[browser-option]\n;配置浏览器\ndriver = Edge\n"
        )
        self.assertTrue(
            Autovisor.save_credentials_to_config(self.config_path, "13800000000", "secret")
        )
        content = self._read()
        self.assertIn("username =13800000000", content)
        self.assertIn("password =secret", content)
        self.assertIn(";配置账号密码，留空则打开网页后需手动登录", content)
        self.assertIn("driver = Edge", content)

    def test_overwrites_existing_credentials(self):
        self._write("[user-account]\nusername = old\npassword = oldpwd\n")
        self.assertTrue(
            Autovisor.save_credentials_to_config(self.config_path, "new", "newpwd")
        )
        content = self._read()
        self.assertIn("username = new", content)
        self.assertIn("password = newpwd", content)
        self.assertNotIn("old", content)

    def test_appends_missing_fields_under_user_account(self):
        self._write("[user-account]\n")
        self.assertTrue(Autovisor.save_credentials_to_config(self.config_path, "u", "p"))
        content = self._read()
        self.assertEqual(content.count("[user-account]"), 1)
        self.assertIn("username = u", content)
        self.assertIn("password = p", content)

    def test_reads_and_writes_gbk_files_unchanged_in_gbk(self):
        self._write("[user-account]\n;中文注释\nusername =\npassword =\n", encoding="gbk")
        self.assertTrue(Autovisor.save_credentials_to_config(self.config_path, "u", "p"))
        content = self._read(encoding="gbk")
        self.assertIn("username =u", content)
        self.assertIn(";中文注释", content)


if __name__ == "__main__":
    unittest.main()
