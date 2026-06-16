import io
import unittest
from contextlib import redirect_stdout

from modules.progress import show_course_progress


class ProgressDisplayTests(unittest.TestCase):
    def _render_progress(self, cur_time):
        output = io.StringIO()
        with redirect_stdout(output):
            show_course_progress(desc="视频播放进度:", cur_time=cur_time)
        return output.getvalue()

    def test_eighty_percent_is_not_displayed_as_complete(self):
        self.assertIn("80%", self._render_progress("80%"))
        self.assertNotIn("100%", self._render_progress("80%"))

    def test_seventy_nine_percent_is_not_displayed_as_complete(self):
        self.assertIn("79%", self._render_progress("79%"))
        self.assertNotIn("100%", self._render_progress("79%"))


if __name__ == "__main__":
    unittest.main()
