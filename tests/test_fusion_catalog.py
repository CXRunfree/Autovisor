"""Chrome DOM regression tests: AUTOVISOR_BROWSER_TESTS=1 enables these tests."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from playwright.async_api import async_playwright

from modules.course_runner import CourseOutcome, run_course
from modules.lesson_navigation import FUSION_CATALOG, get_lesson_title, lesson_progress
from modules.utils import get_filtered_class


def video(number, *, child=False, complete=False):
    css = "chapter-content-second" if child else "chapter-item"
    status = '<i class="finish-icon"></i>' if complete else (
        '<div class="el-progress" aria-valuenow="25"></div>'
    )
    return (
        f'<div class="{css}">{status}'
        f'<div class="item-name">{number}</div></div>'
    )


FIXTURE = (
    video("1.1", complete=True)
    + '<div class="chapter-item"><div class="item-box">'
    '<div class="item-name">2.1 group</div></div>'
    + video("2.1.1", child=True, complete=True)
    + video("2.1.2", child=True)
    + video("2.1.3", child=True)
    + "</div>"
    + video("2.2")
    + '<div class="chapter-item"><div class="item-box">3.1 group</div>'
    + video("3.1.1", child=True)
    + video("3.1.2", child=True)
    + "</div>"
    + video("3.3", complete=True)
    + "<video></video>"
)
ALL = ["1.1", "2.1.1", "2.1.2", "2.1.3", "2.2", "3.1.1", "3.1.2", "3.3"]
PENDING = ["2.1.2", "2.1.3", "2.2", "3.1.1", "3.1.2"]


@unittest.skipUnless(
    os.environ.get("AUTOVISOR_BROWSER_TESTS") == "1",
    "requires Chrome and AUTOVISOR_BROWSER_TESTS=1",
)
class FusionCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        self.browser = await self.playwright.chromium.launch(channel="chrome")
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.set_content(FIXTURE)
        await self.page.evaluate("""() => {
            document.querySelectorAll('.chapter-item, .chapter-content-second')
                .forEach(el => el.addEventListener('click', event => {
                    event.stopPropagation();
                    document.querySelectorAll('.current').forEach(
                        node => node.classList.remove('current'));
                    el.classList.add('current');
                }));
        }""")

    async def titles(self, lessons):
        return [await get_lesson_title(self.page, lesson, FUSION_CATALOG)
                for lesson in lessons]

    async def test_all_leaf_videos_in_document_order_without_group_duplicates(self):
        lessons = await get_filtered_class(self.page, FUSION_CATALOG, include_all=True)
        self.assertEqual(await self.titles(lessons), ALL)

    async def test_completed_sibling_does_not_hide_pending_children(self):
        lessons = await get_filtered_class(self.page, FUSION_CATALOG)
        self.assertEqual(await self.titles(lessons), PENDING)
        self.assertEqual([await lesson_progress(el, FUSION_CATALOG)
                          for el in lessons], [25] * len(PENDING))

    async def run_catalog(self, *, review=False):
        visited = []

        async def finish(*args):
            current = self.page.locator(FUSION_CATALOG.active)
            visited.append(await get_lesson_title(self.page, current, FUSION_CATALOG))
            await current.evaluate("el => el.insertAdjacentHTML('beforeend', "
                                   "'<i class=\"finish-icon\"></i>')")
            return 0, True, False

        with patch("modules.course_runner.learn_lesson", AsyncMock(side_effect=finish)), \
             patch("modules.course_runner.review_lesson", AsyncMock(side_effect=finish)), \
             patch.object(self.page, "wait_for_timeout", AsyncMock()):
            result = await run_course(
                self.page, FUSION_CATALOG, SimpleNamespace(limitMaxTime=0),
                Mock(), asyncio.Event(),
            )
        self.assertIs(result, CourseOutcome.COMPLETED)
        self.assertEqual(visited, ALL if review else PENDING)

    async def test_learning_visits_every_pending_child(self):
        await self.run_catalog()

    async def test_review_visits_every_leaf_when_all_are_complete(self):
        await self.page.locator(FUSION_CATALOG.item).evaluate_all("""nodes => {
            nodes.forEach(el => el.insertAdjacentHTML(
                'beforeend', '<i class="finish-icon"></i>'));
        }""")
        await self.run_catalog(review=True)
