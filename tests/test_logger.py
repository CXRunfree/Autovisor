import os
import re
import tempfile
import unittest
from unittest import mock

from modules.logger import Logger


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class LogFileTestCase(unittest.TestCase):
    """把日志重定向到临时文件, 便于检查真实写入格式。"""

    def setUp(self):
        self.logger = Logger()
        self.original_filename = self.logger.filename
        self.original_context = dict(self.logger._context)
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        handle.close()
        self.tmp_path = handle.name
        self.logger.filename = self.tmp_path
        self.logger._throttled.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        self.logger.filename = self.original_filename
        self.logger._context.clear()
        self.logger._context.update(self.original_context)
        self.logger._throttled.clear()
        os.unlink(self.tmp_path)

    def lines(self):
        with open(self.tmp_path, encoding="utf-8") as file:
            return file.read().splitlines()

    def text(self):
        return "\n".join(self.lines())


class DebugThrottledTests(LogFileTestCase):
    def setUp(self):
        super().setUp()
        self.written = []
        self.logger.write_log = lambda msg, **kwargs: self.written.append(msg)
        self.clock = FakeClock()
        patcher = mock.patch("modules.logger.time.monotonic", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.logger.__dict__.pop, "write_log", None)

    def test_first_message_is_written_immediately(self):
        self.logger.debug_throttled("k", "miss")
        self.assertEqual(self.written, ["miss\n"])

    def test_repeats_within_interval_are_folded(self):
        self.logger.debug_throttled("k", "miss")
        for _ in range(3):
            self.clock.advance(5)
            self.logger.debug_throttled("k", "miss")
        self.assertEqual(self.written, ["miss\n"])

        self.clock.advance(60)
        self.logger.debug_throttled("k", "miss")
        self.assertEqual(
            self.written,
            ["miss\n", "miss (期间折叠 3 次)\n"],
        )

    def test_interval_window_starts_from_last_write(self):
        self.logger.debug_throttled("k", "miss")
        self.clock.advance(59)
        self.logger.debug_throttled("k", "miss")
        self.clock.advance(2)
        self.logger.debug_throttled("k", "miss")
        self.assertEqual(
            self.written,
            ["miss\n", "miss (期间折叠 1 次)\n"],
        )

    def test_keys_are_throttled_independently(self):
        self.logger.debug_throttled("a", "miss a")
        self.logger.debug_throttled("b", "miss b")
        self.clock.advance(1)
        self.logger.debug_throttled("a", "miss a")
        self.logger.debug_throttled("b", "miss b")
        self.assertEqual(
            self.written,
            ["miss a\n", "miss b\n"],
        )

    def test_custom_interval(self):
        self.logger.debug_throttled("k", "miss", interval=5)
        self.clock.advance(5)
        self.logger.debug_throttled("k", "miss", interval=5)
        self.assertEqual(self.written, ["miss\n", "miss\n"])


class LogRecordTests(LogFileTestCase):
    def test_record_prefix_order_is_time_level_source(self):
        self.logger.debug("hello")
        line = self.lines()[-1]
        self.assertRegex(
            line,
            r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\] \[DEBUG\] "
            r"\[[\w.]*test_logger\.[\w_]+:\d+\] hello$",
        )

    def test_every_level_uses_the_same_prefix_order(self):
        self.logger.info("i", shift=True)
        self.logger.warn("w", shift=True)
        self.logger.error("e", shift=True)
        self.logger.event("ev", 键="值")
        prefixes = [
            r"\[INFO\] \[[\w.]*test_logger\.[\w_]+:\d+\] i$",
            r"\[WARN\] \[[\w.]*test_logger\.[\w_]+:\d+\] w$",
            r"\[ERROR\] \[[\w.]*test_logger\.[\w_]+:\d+\] e$",
            r"\[EVENT\] \[[\w.]*test_logger\.[\w_]+:\d+\] ev \| 键=值$",
        ]
        for line, expected in zip(self.lines(), prefixes):
            self.assertRegex(line, expected)

    def test_source_location_skips_logger_internals(self):
        self.logger.info("hello", shift=True)
        line = self.lines()[-1]
        self.assertNotIn("modules.logger.", line)
        self.assertIn("test_source_location_skips_logger_internals:", line)

    def test_event_renders_fields_and_skips_empty(self):
        self.logger.event("课时开始", 序号="1/3", 标题="第一章", 备注=None, 空="")
        line = self.lines()[-1]
        self.assertIn("[EVENT]", line)
        self.assertIn("课时开始 | 序号=1/3 标题=第一章", line)
        self.assertNotIn("备注", line)
        self.assertNotIn("空=", line)

    def test_event_interval_folds_repeats(self):
        clock = FakeClock()
        with mock.patch("modules.logger.time.monotonic", clock):
            self.logger.event("播放状态", interval=60, 进度="12%")
            for _ in range(4):
                clock.advance(1)
                self.logger.event("播放状态", interval=60, 进度="12%")
            clock.advance(60)
            self.logger.event("播放状态", interval=60, 进度="13%")
        self.assertIn("播放状态 | 进度=12%", self.text())
        self.assertIn("进度=13% 期间折叠=4", self.text())
        self.assertEqual(len([line for line in self.lines() if "播放状态" in line]), 2)

    def test_section_writes_banner(self):
        self.logger.section("运行日志")
        self.assertIn("===== 运行日志 =====", self.text())
        banner = [line for line in self.lines() if "===== 运行日志 =====" in line]
        self.assertEqual(len(banner), 1)
        self.assertRegex(banner[0], r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\] ")

    def test_context_is_attached_to_exception_log(self):
        self.logger.context(course="高数", lesson="1.1")
        try:
            raise ValueError("boom")
        except ValueError as exc:
            self.logger.log_exception("课时失败.", exc)
        text = self.text()
        self.assertIn("异常类型: ValueError", text)
        self.assertIn("异常详情: boom", text)
        self.assertIn("运行状态: course=高数 lesson=1.1", text)
        self.assertIn("Traceback (most recent call last)", text)
        self.assertEqual(text.count("运行状态:"), 1)

    def test_error_includes_run_state(self):
        self.logger.context(course="高数", lesson="1.1")
        self.logger.error("出错了")
        text = self.text()
        self.assertIn("[ERROR]", text)
        self.assertIn("出错了", text)
        self.assertIn("运行状态: course=高数 lesson=1.1", text)

    def test_error_without_context_has_no_state(self):
        self.logger.error("出错了")
        self.assertNotIn("运行状态:", self.text())

    def test_context_can_be_cleared(self):
        self.logger.context(course="高数", lesson="1.1")
        self.logger.clear_context("lesson")
        self.assertEqual(self.logger.context_text(), "course=高数")
        self.logger.clear_context()
        self.assertEqual(self.logger.context_text(), "")

    def test_no_context_line_without_context(self):
        try:
            raise ValueError("boom")
        except ValueError as exc:
            self.logger.log_exception("课时失败.", exc)
        self.assertNotIn("运行状态:", self.text())


class SummarizeExceptionTests(unittest.TestCase):
    def test_uses_first_line_only(self):
        exc = RuntimeError("first\nsecond")
        self.assertEqual(Logger.summarize_exception(exc), "RuntimeError: first")

    def test_source_location_of_unknown_frame_is_safe(self):
        self.assertTrue(re.match(r"^.+$", Logger._source_location()))


if __name__ == "__main__":
    unittest.main()
