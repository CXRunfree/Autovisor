"""Browser regressions for nested Fusion rows, using an offline HTML fixture.

Install Chromium with ``uv run playwright install chromium``. To use an existing
Chrome installation locally, set AUTOVISOR_TEST_BROWSER_CHANNEL=chrome.
"""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from playwright.async_api import async_playwright

from modules.course_runner import CourseOutcome, run_course
from modules.lesson_navigation import (
    FUSION_CATALOG,
    WISDOM_CATALOG,
    get_lesson_title,
    lesson_progress,
    wait_for_lesson_active,
)
from modules.utils import get_filtered_class


class FusionCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        playwright = await async_playwright().start()
        self.addAsyncCleanup(playwright.stop)
        options = {"headless": True}
        channel = os.environ.get("AUTOVISOR_TEST_BROWSER_CHANNEL")
        if channel:
            options["channel"] = channel
        self.browser = await playwright.chromium.launch(**options)
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        self.page.set_default_timeout(2000)
        fixture = Path(__file__).parent / "fixtures" / "fusion_catalog.html"
        await self.page.set_content(fixture.read_text(encoding="utf-8"))

    async def row_ids(self, rows):
        return [await row.get_attribute("id") for row in rows]

    async def test_review_lists_nested_and_standalone_lessons_in_dom_order(self):
        rows = await get_filtered_class(self.page, FUSION_CATALOG, include_all=True)
        self.assertEqual(
            await self.row_ids(rows),
            ["lesson-531", "lesson-532", "lesson-533", "lesson-54"],
        )

    async def test_finished_sibling_does_not_hide_unfinished_children(self):
        rows = await get_filtered_class(self.page, FUSION_CATALOG)
        self.assertEqual(
            await self.row_ids(rows), ["lesson-532", "lesson-533", "lesson-54"]
        )
        self.assertEqual(
            [await lesson_progress(row, FUSION_CATALOG) for row in rows], [24, 0, 0]
        )
        self.assertEqual(
            await get_lesson_title(self.page, rows[0], FUSION_CATALOG),
            "5.3.2 Second lesson",
        )

    async def test_completion_moves_to_next_child_before_next_section(self):
        await self.page.locator("#lesson-532").evaluate(
            "el => el.insertAdjacentHTML('beforeend', '<span class=finish-icon></span>')"
        )
        rows = await get_filtered_class(self.page, FUSION_CATALOG)
        self.assertEqual(await self.row_ids(rows), ["lesson-533", "lesson-54"])

    async def test_fully_unfinished_group_keeps_first_child_and_individual_progress(self):
        await self.page.locator("#lesson-531 .finish-icon").evaluate("el => el.remove()")
        rows = await get_filtered_class(self.page, FUSION_CATALOG)
        self.assertEqual(
            await self.row_ids(rows),
            ["lesson-531", "lesson-532", "lesson-533", "lesson-54"],
        )
        self.assertEqual(
            [await lesson_progress(row, FUSION_CATALOG) for row in rows],
            [0, 24, 0, 0],
        )

    async def test_click_and_active_detection_target_the_exact_child(self):
        rows = await get_filtered_class(self.page, FUSION_CATALOG)
        await rows[0].click()
        self.assertTrue(await wait_for_lesson_active(rows[0], FUSION_CATALOG, 500))
        self.assertEqual(await self.page.evaluate("window.clickedLessons"), ["lesson-532"])
        self.assertEqual(
            await get_lesson_title(self.page, rows[0], FUSION_CATALOG),
            "5.3.2 Second lesson",
        )

    async def test_missing_label_does_not_use_a_title_elsewhere_on_page(self):
        await self.page.locator("#lesson-532 .item-name").evaluate(
            "el => el.replaceWith(document.createTextNode('Second lesson'))"
        )
        self.assertEqual(
            await get_lesson_title(self.page, self.page.locator("#lesson-532"), FUSION_CATALOG),
            "5.3.2 Second lesson",
        )

    async def test_existing_number_in_title_is_not_duplicated(self):
        row = self.page.locator("#lesson-531")
        await row.locator(".item-name").evaluate(
            "el => el.setAttribute('title', '5.3.1 First lesson')"
        )
        self.assertEqual(await get_lesson_title(self.page, row, FUSION_CATALOG), "5.3.1 First lesson")

    async def test_non_fusion_catalog_keeps_its_rows_and_titles(self):
        await self.page.set_content('''
            <div class="child-info hasvideo" id="done">
              <span class="child-check"></span><span class="child-name">Done</span>
            </div>
            <div class="child-info hasvideo" id="pending">
              <span class="child-name">Pending</span>
            </div>
        ''')
        rows = await get_filtered_class(self.page, WISDOM_CATALOG)
        self.assertEqual(await self.row_ids(rows), ["pending"])
        self.assertEqual(await get_lesson_title(self.page, rows[0], WISDOM_CATALOG), "Pending")

    async def test_course_runner_visits_remaining_children_before_standalone(self):
        learned = []

        async def complete_lesson(page, start, paused, lesson, catalog, config, logger):
            learned.append(await lesson.get_attribute("id"))
            await lesson.evaluate(
                "el => el.insertAdjacentHTML('beforeend', '<span class=finish-icon></span>')"
            )
            return 0.0, True, False

        with (
            patch("modules.course_runner.learn_lesson", side_effect=complete_lesson),
            patch("modules.course_runner.FusionAdapter.expand_catalog", new_callable=AsyncMock),
        ):
            result = await run_course(
                self.page, FUSION_CATALOG, SimpleNamespace(limitMaxTime=0),
                Mock(), asyncio.Event(),
            )
        self.assertEqual(result, CourseOutcome.COMPLETED)
        self.assertEqual(learned, ["lesson-532", "lesson-533", "lesson-54"])
        self.assertEqual(await self.page.evaluate("window.clickedLessons"), learned)

    async def test_all_completed_course_reviews_every_child_in_order(self):
        await self.page.locator('[id^="lesson-"]').evaluate_all(
            "rows => rows.forEach(el => el.insertAdjacentHTML("
            "'beforeend', '<span class=finish-icon></span>'))"
        )
        self.assertEqual(await get_filtered_class(self.page, FUSION_CATALOG), [])
        with (
            patch("modules.course_runner.learn_lesson", new_callable=AsyncMock) as learn,
            patch("modules.course_runner.review_lesson", new_callable=AsyncMock,
                  return_value=(0.0, True, False)) as review,
            patch("modules.course_runner.FusionAdapter.expand_catalog", new_callable=AsyncMock),
        ):
            result = await run_course(
                self.page, FUSION_CATALOG, SimpleNamespace(limitMaxTime=0),
                Mock(), asyncio.Event(),
            )
        self.assertEqual(result, CourseOutcome.COMPLETED)
        learn.assert_not_awaited()
        self.assertEqual(review.await_count, 4)
        self.assertEqual(
            await self.page.evaluate("window.clickedLessons"),
            ["lesson-531", "lesson-532", "lesson-533", "lesson-54"],
        )


if __name__ == "__main__":
    unittest.main()
