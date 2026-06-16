import builtins
import importlib
import sys
import types
import unittest
from unittest import mock


def install_playwright_stubs():
    playwright = types.ModuleType("playwright")
    async_api = types.ModuleType("playwright.async_api")
    impl = types.ModuleType("playwright._impl")
    errors = types.ModuleType("playwright._impl._errors")

    class Page:
        pass

    class Locator:
        pass

    class TimeoutError(Exception):
        pass

    class TargetClosedError(Exception):
        pass

    async_api.Page = Page
    async_api.Locator = Locator
    async_api.TimeoutError = TimeoutError
    errors.TargetClosedError = TargetClosedError

    sys.modules["playwright"] = playwright
    sys.modules["playwright.async_api"] = async_api
    sys.modules["playwright._impl"] = impl
    sys.modules["playwright._impl._errors"] = errors


class UtilsPlatformTests(unittest.TestCase):
    def test_utils_imports_when_pygetwindow_is_unavailable(self):
        install_playwright_stubs()
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "pygetwindow":
                raise ImportError("No module named pygetwindow")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("modules.utils", None)
        sys.modules.pop("pygetwindow", None)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            module = importlib.import_module("modules.utils")

        self.assertFalse(module.supports_window_control())


if __name__ == "__main__":
    unittest.main()
