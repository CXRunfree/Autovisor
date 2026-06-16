import importlib
import sys
import unittest


class BrowserChannelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.pop("modules.browser", None)
        cls.browser = importlib.import_module("modules.browser")

    def test_edge_uses_playwright_msedge_channel(self):
        self.assertEqual(self.browser.resolve_browser_channel("edge"), "msedge")

    def test_chromium_uses_bundled_playwright_browser(self):
        self.assertIsNone(self.browser.resolve_browser_channel("chromium"))

    def test_chrome_uses_playwright_chrome_channel(self):
        self.assertEqual(self.browser.resolve_browser_channel("chrome"), "chrome")

    def test_effective_driver_uses_config_when_env_is_absent(self):
        self.assertEqual(self.browser.get_effective_driver("Edge", {}), "edge")

    def test_effective_driver_uses_env_override(self):
        env = {"AUTOVISOR_DRIVER": " chromium "}
        self.assertEqual(self.browser.get_effective_driver("Edge", env), "chromium")

    def test_chromium_ignores_configured_executable_path(self):
        self.assertIsNone(
            self.browser.resolve_executable_path(
                "chromium",
                "'/Applications/Google Chrome.app'",
            )
        )

    def test_macos_app_path_resolves_to_inner_executable(self):
        resolved = self.browser.resolve_executable_path(
            "chrome",
            "'/Applications/Google Chrome.app'",
        )

        self.assertEqual(
            resolved,
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )


if __name__ == "__main__":
    unittest.main()
