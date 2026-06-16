import importlib
import math
import sys
import unittest


class VideoStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.pop("modules.video_state", None)
        cls.video_state = importlib.import_module("modules.video_state")

    def test_paused_video_before_end_should_resume(self):
        self.assertTrue(self.video_state.should_resume_paused_video(True, 12.0, 60.0))

    def test_paused_video_at_end_should_not_resume(self):
        self.assertFalse(self.video_state.should_resume_paused_video(True, 59.7, 60.0))

    def test_playing_video_should_not_resume(self):
        self.assertFalse(self.video_state.should_resume_paused_video(False, 12.0, 60.0))

    def test_unknown_duration_can_resume_paused_video(self):
        self.assertTrue(self.video_state.should_resume_paused_video(True, 12.0, None))

    def test_nan_duration_can_resume_paused_video(self):
        self.assertTrue(self.video_state.should_resume_paused_video(True, 12.0, math.nan))

    def test_video_near_end_is_complete(self):
        self.assertTrue(self.video_state.is_video_complete(59.5, 60.0))

    def test_video_before_end_is_not_complete(self):
        self.assertFalse(self.video_state.is_video_complete(42.0, 60.0))

    def test_nan_duration_is_not_complete(self):
        self.assertFalse(self.video_state.is_video_complete(42.0, math.nan))

    def test_invalid_duration_should_be_refreshed(self):
        self.assertTrue(self.video_state.should_refresh_video_duration(math.nan))
        self.assertTrue(self.video_state.should_refresh_video_duration(None))
        self.assertTrue(self.video_state.should_refresh_video_duration(0))
        self.assertTrue(self.video_state.should_refresh_video_duration(math.inf))

    def test_valid_duration_should_not_be_refreshed(self):
        self.assertFalse(self.video_state.should_refresh_video_duration(60.0))

    def test_nan_duration_formats_as_zero_percent(self):
        self.assertEqual(self.video_state.video_percent(42.0, math.nan), "0%")

    def test_valid_video_progress_formats_as_percent(self):
        self.assertEqual(self.video_state.video_percent(30.0, 60.0), "50%")

    def test_replay_from_near_end_keeps_a_small_tail(self):
        self.assertEqual(self.video_state.replay_from_time(60.0), 55.0)
        self.assertEqual(self.video_state.replay_from_time(3.0), 0)

    def test_sync_time_from_catalog_progress(self):
        self.assertEqual(self.video_state.time_from_percent(300.0, 13), 39.0)
        self.assertEqual(self.video_state.time_from_percent(300.0, 120), 300.0)
        self.assertEqual(self.video_state.time_from_percent(float("nan"), 13), 0)

    def test_default_completion_settle_wait_is_three_seconds(self):
        self.assertEqual(self.video_state.completion_settle_ms(), 3000)


if __name__ == "__main__":
    unittest.main()
