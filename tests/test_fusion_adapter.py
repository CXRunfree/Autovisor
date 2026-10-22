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

    def test_select_script_answers_each_question_item(self):
        self.assertIn(".ques-list .item", fusion_adapter._SELECT_EACH_QUESTION_JS)
        self.assertIn(".class-question-select.isSelect", fusion_adapter._SELECT_EACH_QUESTION_JS)

    def test_skip_docstring_mentions_multi_question(self):
        self.assertIn("每道题", FusionAdapter.skip_ai_exercise.__doc__)


if __name__ == "__main__":
    unittest.main()
