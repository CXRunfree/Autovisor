import unittest
from unittest import mock

from playwright._impl._errors import TargetClosedError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from modules import utils


class _Logger:
    def __init__(self):
        self.throttled = []
        self.exceptions = []

    def debug_throttled(self, key, msg, interval=60):
        self.throttled.append((key, msg))

    def debug(self, msg):
        pass

    def log_exception(self, msg, exc=None, shift=False):
        self.exceptions.append((msg, exc))


class _Page:
    def __init__(self, result=None, error=None, wait_error=None):
        self.result = result
        self.error = error
        self.wait_error = wait_error
        self.scripts = []
        self.evaluate_calls = 0

    async def evaluate(self, script, arg=None):
        self.evaluate_calls += 1
        self.scripts.append(script)
        if self.error:
            raise self.error
        return self.result

    async def wait_for_selector(self, selector, state=None, timeout=None):
        if self.wait_error:
            raise self.wait_error


class LoggerPatchMixin(unittest.TestCase):
    def setUp(self):
        self.logger = _Logger()
        patcher = mock.patch.object(utils, "logger", self.logger)
        patcher.start()
        self.addCleanup(patcher.stop)


class RunOnTests(LoggerPatchMixin, unittest.IsolatedAsyncioTestCase):
    async def test_returns_value_and_builds_guarded_script(self):
        page = _Page(result=True)
        result = await utils.run_on(
            page, "video", "(el) => el.paused", "读取视频暂停状态"
        )
        self.assertIs(result, True)
        self.assertIn("'video'", page.scripts[0])
        self.assertIn("(el) => el.paused", page.scripts[0])
        self.assertIn("if (!el) return", page.scripts[0])

    async def test_missing_element_returns_none_and_names_selector(self):
        page = _Page(result=utils._MISSING)
        result = await utils.run_on(
            page, ".videoArea", "(el) => el.click()", "点击播放区"
        )
        self.assertIsNone(result)
        self.assertEqual(self.logger.exceptions, [])
        self.assertEqual(len(self.logger.throttled), 1)
        key, msg = self.logger.throttled[0]
        self.assertEqual(key, "run_on:.videoArea")
        self.assertIn("点击播放区", msg)
        self.assertIn(".videoArea", msg)

    async def test_script_error_reports_selector_and_returns_none(self):
        page = _Page(error=RuntimeError("boom"))
        result = await utils.run_on(page, "video", "(el) => el.play()", "恢复播放")
        self.assertIsNone(result)
        self.assertEqual(self.logger.throttled, [])
        self.assertEqual(len(self.logger.exceptions), 1)
        msg, exc = self.logger.exceptions[0]
        self.assertIn("恢复播放失败", msg)
        self.assertIn("video", msg)
        self.assertIsInstance(exc, RuntimeError)

    async def test_target_closed_is_reraised(self):
        page = _Page(error=TargetClosedError("closed"))
        with self.assertRaises(TargetClosedError):
            await utils.run_on(page, "video", "(el) => el.play()", "恢复播放")


class GetVideoAttrTests(LoggerPatchMixin, unittest.IsolatedAsyncioTestCase):
    async def test_returns_none_when_element_not_ready(self):
        page = _Page(wait_error=PlaywrightTimeoutError("not attached"))
        self.assertIsNone(await utils.get_video_attr(page, "duration"))
        self.assertEqual(page.evaluate_calls, 0)
        self.assertEqual(len(self.logger.throttled), 1)
        self.assertIn("duration", self.logger.throttled[0][1])

    async def test_reads_property_without_null_deref(self):
        page = _Page(result=72.5)
        self.assertEqual(await utils.get_video_attr(page, "duration"), 72.5)
        self.assertIn("['duration']", page.scripts[0])

    async def test_missing_video_after_wait_returns_none(self):
        page = _Page(result=utils._MISSING)
        self.assertIsNone(await utils.get_video_attr(page, "paused"))
        self.assertEqual(len(self.logger.throttled), 1)
        self.assertIn("video", self.logger.throttled[0][1])


if __name__ == "__main__":
    unittest.main()
