import unittest

from modules import fusion_adapter
from modules.fusion_adapter import FusionAdapter
from modules.video_state import COURSE_VIDEO_SELECTOR


class FusionAdapterTests(unittest.TestCase):
    def test_submit_selector_covers_wisdom_mooc_footer_button(self):
        self.assertIn(".dialog-footer .btn", fusion_adapter._SUBMIT_SELECTOR)
        self.assertIn(".el-dialog__footer button", fusion_adapter._SUBMIT_SELECTOR)

    def test_close_selector_uses_header_icon(self):
        self.assertEqual(
            fusion_adapter._CLOSE_SELECTOR,
            ".ai-class-exercise-dialog .header-icon",
        )

    def test_resume_targets_course_video(self):
        self.assertEqual(fusion_adapter.COURSE_VIDEO_SELECTOR, COURSE_VIDEO_SELECTOR)

    def test_skip_blocking_quizzes_is_public(self):
        self.assertTrue(hasattr(FusionAdapter, "skip_blocking_quizzes"))
        self.assertTrue(hasattr(FusionAdapter, "skip_question_panel"))


if __name__ == "__main__":
    unittest.main()
