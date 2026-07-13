import math
import unittest

from modules.video_state import (
    has_valid_duration,
    tail_retry_time,
    time_for_percent,
    video_at_end,
)


class VideoStateTests(unittest.TestCase):
    def test_video_end_uses_small_tolerance(self):
        self.assertTrue(video_at_end(59.4, 60.0))
        self.assertFalse(video_at_end(58.0, 60.0))

    def test_invalid_duration_is_rejected(self):
        for value in (None, 0, -1, math.nan, math.inf):
            with self.subTest(value=value):
                self.assertFalse(has_valid_duration(value))

    def test_platform_percent_maps_back_to_video_time(self):
        self.assertEqual(time_for_percent(300, 25), 75)
        self.assertEqual(time_for_percent(300, 120), 300)
        self.assertEqual(time_for_percent(math.nan, 25), 0)

    def test_tail_retry_never_goes_negative(self):
        self.assertEqual(tail_retry_time(60), 55)
        self.assertEqual(tail_retry_time(3), 0)


if __name__ == "__main__":
    unittest.main()
