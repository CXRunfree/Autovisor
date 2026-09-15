import unittest
from unittest.mock import AsyncMock, patch

from modules.course_playback import learn_lesson, review_lesson
from modules.lesson_navigation import WISDOM_CATALOG


class _Config:
    limitMaxTime = 0
    reset_curtime = ""


class _Logger:
    def warn(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass


class CoursePlaybackTests(unittest.IsolatedAsyncioTestCase):
    @patch(
        "modules.course_playback._wait_for_duration",
        new_callable=AsyncMock,
        return_value=(None, 7.5),
    )
    async def test_invalid_metadata_fails_learning_with_three_part_result(self, _wait):
        result = await learn_lesson(
            object(), 0, 0, object(), WISDOM_CATALOG, _Config(), _Logger()
        )
        self.assertEqual(result, (7.5, False, False))

    @patch(
        "modules.course_playback._wait_for_duration",
        new_callable=AsyncMock,
        return_value=(None, 7.5),
    )
    async def test_invalid_metadata_fails_review_with_three_part_result(self, _wait):
        result = await review_lesson(object(), 0, 0, _Config(), _Logger())
        self.assertEqual(result, (7.5, False, False))


if __name__ == "__main__":
    unittest.main()
