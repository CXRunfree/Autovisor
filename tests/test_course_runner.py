import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from playwright.async_api import TimeoutError

from modules.course_runner import CourseOutcome, run_course
from modules.lesson_navigation import LEGACY_CATALOG


class CourseRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_restored_catalog_and_skips_late_completed_lesson(self):
        ready = False
        page = Mock()

        async def wait_for_selector(selector, **kwargs):
            nonlocal ready
            if selector == LEGACY_CATALOG.active:
                ready = True

        page.wait_for_selector = AsyncMock(side_effect=wait_for_selector)
        page.wait_for_timeout = AsyncMock()
        finished = Mock(click=AsyncMock())
        pending = Mock(click=AsyncMock())

        async def filtered(*args, **kwargs):
            self.assertTrue(ready, "Filtering must wait for restored progress")
            # A lesson can become complete after the initial catalog scan.
            return [finished, pending]

        async def progress(lesson, catalog):
            return 100 if lesson is finished else 50

        with (
            patch("modules.course_runner.get_filtered_class", side_effect=filtered),
            patch("modules.course_runner.lesson_progress", side_effect=progress),
            patch(
                "modules.course_runner.get_lesson_name",
                AsyncMock(return_value="Pending"),
            ),
            patch(
                "modules.course_runner.wait_for_lesson_active",
                AsyncMock(return_value=True),
            ),
            patch(
                "modules.course_runner.learn_lesson",
                AsyncMock(return_value=(0, True, False)),
            ) as learn,
        ):
            result = await run_course(
                page, LEGACY_CATALOG, Mock(), Mock(), asyncio.Event()
            )

        self.assertIs(result, CourseOutcome.COMPLETED)
        finished.click.assert_not_awaited()
        pending.click.assert_awaited_once()
        learn.assert_awaited_once()

    async def test_unrestored_catalog_does_not_start_switching_lessons(self):
        page = Mock()
        page.wait_for_selector = AsyncMock(
            side_effect=[None, TimeoutError("Catalog did not restore selection")]
        )
        with patch("modules.course_runner.get_filtered_class", AsyncMock()) as filtered:
            result = await run_course(
                page, LEGACY_CATALOG, Mock(), Mock(), asyncio.Event()
            )

        self.assertIs(result, CourseOutcome.FAILED)
        filtered.assert_not_awaited()

    async def test_review_mode_still_plays_completed_lessons(self):
        page = Mock()
        page.wait_for_selector = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        lesson = Mock(click=AsyncMock())
        with (
            patch(
                "modules.course_runner.get_filtered_class",
                AsyncMock(side_effect=[[], [lesson]]),
            ),
            patch("modules.course_runner.lesson_progress", AsyncMock(return_value=100)),
            patch(
                "modules.course_runner.get_lesson_name",
                AsyncMock(return_value="Completed"),
            ),
            patch(
                "modules.course_runner.wait_for_lesson_active",
                AsyncMock(return_value=True),
            ),
            patch(
                "modules.course_runner.review_lesson",
                AsyncMock(return_value=(0, True, False)),
            ) as review,
        ):
            result = await run_course(
                page, LEGACY_CATALOG, Mock(), Mock(), asyncio.Event()
            )

        self.assertIs(result, CourseOutcome.COMPLETED)
        lesson.click.assert_awaited_once()
        review.assert_awaited_once()
