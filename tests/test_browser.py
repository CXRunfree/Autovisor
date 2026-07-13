import tempfile
import unittest
from pathlib import Path

from modules.browser import (
    BrowserSession,
    create_browser_session,
    get_effective_driver,
    is_loopback_cdp_endpoint,
    resolve_browser_channel,
    resolve_cdp_endpoint,
    resolve_executable_path,
)


class BrowserResolutionTests(unittest.TestCase):
    def test_driver_environment_override(self):
        self.assertEqual(get_effective_driver("edge", {"AUTOVISOR_DRIVER": " chrome "}), "chrome")

    def test_channels(self):
        self.assertEqual(resolve_browser_channel("edge"), "msedge")
        self.assertEqual(resolve_browser_channel("chrome"), "chrome")
        self.assertIsNone(resolve_browser_channel("chromium"))

    def test_macos_app_path(self):
        self.assertEqual(
            resolve_executable_path("chrome", "/Applications/Google Chrome.app"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )

    def test_devtools_active_port_endpoint(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "DevToolsActivePort"
            path.write_text("9222\n/devtools/browser/test-id\n", encoding="utf-8")
            self.assertEqual(
                resolve_cdp_endpoint("http://127.0.0.1:9222", {}, path),
                "ws://127.0.0.1:9222/devtools/browser/test-id",
            )

    def test_cdp_endpoint_must_be_local(self):
        self.assertTrue(is_loopback_cdp_endpoint("ws://127.0.0.1:9222/devtools/browser/x"))
        self.assertTrue(is_loopback_cdp_endpoint("http://localhost:9222"))
        self.assertFalse(is_loopback_cdp_endpoint("ws://example.com:9222/devtools/browser/x"))


class _Page:
    def __init__(self):
        self.closed = False
        self.timeout = None

    async def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed

    async def add_init_script(self, **_kwargs):
        pass

    def set_default_timeout(self, timeout):
        self.timeout = timeout


class _Context:
    def __init__(self):
        self.page = _Page()

    async def new_page(self):
        return self.page


class _Browser:
    def __init__(self):
        self.contexts = [_Context()]
        self.closed = False

    async def close(self):
        self.closed = True


class _Chromium:
    def __init__(self):
        self.browser = _Browser()
        self.cdp_url = None

    async def connect_over_cdp(self, url):
        self.cdp_url = url
        return self.browser


class _Playwright:
    def __init__(self):
        self.chromium = _Chromium()


class _Config:
    attach_existing_chrome = True
    cdp_url = "http://127.0.0.1:9222"
    driver = "chrome"
    exe_path = ""


class _Logger:
    def __init__(self, root):
        self.runtime_root = root

    def info(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass


class BrowserSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_attached_session_closes_only_its_page(self):
        with tempfile.TemporaryDirectory() as root:
            playwright = _Playwright()
            session = await create_browser_session(
                playwright, _Config(), None, _Logger(root)
            )
            self.assertTrue(session.attached)
            await session.close()
            self.assertTrue(session.page.closed)
            self.assertFalse(session.browser.closed)

    async def test_owned_session_closes_browser(self):
        browser = _Browser()
        session = BrowserSession(browser, browser.contexts[0], _Page(), False)
        await session.close()
        self.assertTrue(browser.closed)
