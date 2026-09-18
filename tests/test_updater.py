import os
import re
import unittest

import requests

from modules import updater
from modules.version import __version__

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RELEASE_PAGE = "https://github.com/CXRunfree/Autovisor/releases/tag/x"
ASSET_URL = (
    "https://github.com/CXRunfree/Autovisor/releases/download/3.19.0/"
    "Autovisor-3.19.0-windows-amd64.zip"
)


class FakeLogger:
    def __init__(self):
        self.records = []

    def _record(self, level, msg, shift=False):
        self.records.append((level, msg))

    def debug(self, msg):
        self._record("DEBUG", msg)

    def info(self, msg, shift=False):
        self._record("INFO", msg)

    def warn(self, msg, shift=False):
        self._record("WARN", msg)

    def event(self, name, interval=None, **fields):
        details = " ".join(f"{key}={value}" for key, value in fields.items())
        self._record("EVENT", f"{name} | {details}" if details else name)

    def text(self, level=None):
        return "\n".join(msg for lvl, msg in self.records if level is None or lvl == level)

    def summarize_exception(self, exc):
        return f"{type(exc).__name__}: {exc}"


class FakeResponse:
    def __init__(self, payload, error=None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []
        self.kwargs = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        self.kwargs.append(kwargs)
        if self.error:
            raise self.error
        return self.response or FakeResponse({})


class RetrySession(FakeSession):
    """首次抛错, 之后正常返回, 用于验证降级重试。"""

    def get(self, url, **kwargs):
        self.calls.append(url)
        self.kwargs.append(kwargs)
        if len(self.calls) == 1:
            raise self.error
        return self.response


def release_payload(name, html_url, assets=()):
    return {
        "name": name,
        "tag_name": "2026/9/15",
        "html_url": html_url,
        "assets": list(assets),
    }


class ParseVersionTests(unittest.TestCase):
    def test_extracts_version_from_release_name(self):
        self.assertEqual(updater.parse_version("Autovisor-3.18.0"), (3, 18, 0))

    def test_ignores_date_style_tag(self):
        self.assertIsNone(updater.parse_version("2026/9/15"))

    def test_ignores_empty_and_none(self):
        self.assertIsNone(updater.parse_version(""))
        self.assertIsNone(updater.parse_version(None))


class IsNewerTests(unittest.TestCase):
    def test_newer_patch_and_minor(self):
        self.assertTrue(updater.is_newer((3, 18, 1), (3, 18, 0)))
        self.assertTrue(updater.is_newer((3, 19, 0), (3, 18, 9)))

    def test_same_or_older(self):
        self.assertFalse(updater.is_newer((3, 18, 0), (3, 18, 0)))
        self.assertFalse(updater.is_newer((3, 17, 9), (3, 18, 0)))

    def test_unparsable_is_not_newer(self):
        self.assertFalse(updater.is_newer(None, (3, 18, 0)))
        self.assertFalse(updater.is_newer((3, 19, 0), None))


class CheckForUpdateTests(unittest.TestCase):
    def test_prompts_when_release_is_newer(self):
        logger = FakeLogger()
        session = FakeSession(
            FakeResponse(release_payload("Autovisor-3.19.0", RELEASE_PAGE))
        )
        url = updater.check_for_update(logger, current_version="3.18.1", session=session)
        self.assertEqual(url, RELEASE_PAGE)
        self.assertIn("3.19.0", logger.text("INFO"))
        self.assertIn(RELEASE_PAGE, logger.text("INFO"))
        self.assertEqual(logger.text("WARN"), "")

    def test_uses_tag_when_tag_is_a_version(self):
        logger = FakeLogger()
        payload = release_payload("Autovisor", RELEASE_PAGE)
        payload["tag_name"] = "3.19.0"
        session = FakeSession(FakeResponse(payload))
        url = updater.check_for_update(logger, current_version="3.18.1", session=session)
        self.assertEqual(url, RELEASE_PAGE)
        self.assertIn("3.19.0", logger.text("INFO"))

    def test_reports_up_to_date(self):
        logger = FakeLogger()
        payload = release_payload("Autovisor-3.18.1", RELEASE_PAGE)
        payload["tag_name"] = "3.18.1"
        session = FakeSession(FakeResponse(payload))
        self.assertIsNone(
            updater.check_for_update(logger, current_version="3.18.1", session=session)
        )
        self.assertIn("当前版本3.18.1,已是最新版本.", logger.text("INFO"))
        self.assertEqual(logger.text("WARN"), "")

    def test_silent_when_release_version_unparsable(self):
        logger = FakeLogger()
        session = FakeSession(FakeResponse(release_payload("latest", RELEASE_PAGE)))
        self.assertIsNone(
            updater.check_for_update(logger, current_version="3.18.1", session=session)
        )
        self.assertEqual(logger.text("INFO"), "")

    def test_network_error_does_not_raise(self):
        logger = FakeLogger()
        session = FakeSession(error=OSError("network is unreachable"))
        self.assertIsNone(
            updater.check_for_update(logger, current_version="3.18.1", session=session)
        )
        self.assertIn("检查更新失败", logger.text("DEBUG"))
        self.assertEqual(logger.text("INFO"), "")
        self.assertEqual(len(session.calls), 1)

    def test_windows_asset_link_is_included_on_windows(self):
        if os.name != "nt":
            self.skipTest("Windows-only asset matching")
        logger = FakeLogger()
        session = FakeSession(
            FakeResponse(
                release_payload(
                    "Autovisor-3.19.0",
                    RELEASE_PAGE,
                    assets=[
                        {
                            "name": "Autovisor-3.19.0-windows-amd64.zip",
                            "browser_download_url": ASSET_URL,
                        }
                    ],
                )
            )
        )
        updater.check_for_update(logger, current_version="3.18.1", session=session)
        self.assertIn(ASSET_URL, logger.text("INFO"))


class TrustedUrlTests(unittest.TestCase):
    def test_accepts_github_hosts(self):
        self.assertTrue(updater.is_trusted_url("https://github.com/a/b"))
        self.assertTrue(updater.is_trusted_url("https://objects.githubusercontent.com/x"))
        self.assertTrue(updater.is_trusted_url("https://api.github.com/repos/x"))

    def test_rejects_other_hosts_and_schemes(self):
        self.assertFalse(updater.is_trusted_url("https://example.com/dl.zip"))
        self.assertFalse(updater.is_trusted_url("https://evilgithub.com/dl.zip"))
        self.assertFalse(updater.is_trusted_url("http://github.com/dl.zip"))
        self.assertFalse(updater.is_trusted_url(None))
        self.assertFalse(updater.is_trusted_url(""))


class SslFallbackTests(unittest.TestCase):
    def test_ssl_error_retries_without_verification(self):
        logger = FakeLogger()
        session = RetrySession(
            FakeResponse(
                release_payload(
                    "Autovisor-3.19.0",
                    RELEASE_PAGE,
                    assets=[
                        {
                            "name": "Autovisor-3.19.0-windows-amd64.zip",
                            "browser_download_url": ASSET_URL,
                        }
                    ],
                )
            ),
            error=requests.exceptions.SSLError("certificate verify failed"),
        )
        url = updater.check_for_update(logger, current_version="3.18.1", session=session)
        self.assertEqual(url, RELEASE_PAGE)
        self.assertEqual(len(session.calls), 2)
        self.assertNotIn("verify", session.kwargs[0])
        self.assertIs(session.kwargs[1]["verify"], False)
        self.assertIn("证书校验失败", logger.text("DEBUG"))
        self.assertIn("3.19.0", logger.text("INFO"))

    def test_ssl_error_on_both_attempts_is_silent(self):
        logger = FakeLogger()
        session = FakeSession(error=requests.exceptions.SSLError("certificate verify failed"))
        self.assertIsNone(
            updater.check_for_update(logger, current_version="3.18.1", session=session)
        )
        self.assertEqual(len(session.calls), 2)
        self.assertIn("检查更新失败", logger.text("DEBUG"))
        self.assertEqual(logger.text("INFO"), "")

    def test_untrusted_release_page_falls_back_to_official_page(self):
        logger = FakeLogger()
        session = FakeSession(
            FakeResponse(release_payload("Autovisor-3.19.0", "https://evil.com/update"))
        )
        url = updater.check_for_update(logger, current_version="3.18.1", session=session)
        self.assertEqual(url, updater.RELEASE_PAGE_URL)
        self.assertNotIn("evil.com", logger.text("INFO"))

    def test_untrusted_asset_url_is_ignored(self):
        if os.name != "nt":
            self.skipTest("Windows-only asset matching")
        logger = FakeLogger()
        session = FakeSession(
            FakeResponse(
                release_payload(
                    "Autovisor-3.19.0",
                    RELEASE_PAGE,
                    assets=[
                        {
                            "name": "Autovisor-3.19.0-windows-amd64.zip",
                            "browser_download_url": "https://evil.com/payload.zip",
                        }
                    ],
                )
            )
        )
        updater.check_for_update(logger, current_version="3.18.1", session=session)
        self.assertNotIn("evil.com", logger.text("INFO"))
        self.assertIn(RELEASE_PAGE, logger.text("INFO"))


class VersionSourceTests(unittest.TestCase):
    def test_pyproject_takes_version_from_code(self):
        with open(os.path.join(PROJECT_ROOT, "pyproject.toml"), "r", encoding="utf-8") as file:
            content = file.read()
        self.assertIn('dynamic = ["version"]', content)
        self.assertIn('attr = "modules.version.__version__"', content)
        self.assertIsNone(
            re.search(r'^version\s*=\s*"', content, re.MULTILINE),
            "pyproject.toml 不应再写死 version",
        )
        self.assertEqual(updater.__version__, __version__)


if __name__ == "__main__":
    unittest.main()
