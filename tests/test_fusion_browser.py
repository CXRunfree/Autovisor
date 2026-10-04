"""Offline DOM checks; set AUTOVISOR_TEST_BROWSER to use a system Chromium.

Without that variable, use Playwright's installed Chromium and skip if absent.
No local account configuration, login, course requests or progress reports.
"""
import os
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import asyncio
from playwright.async_api import async_playwright
from playwright._impl._errors import Error
from modules.lesson_navigation import FUSION_CATALOG, lesson_progress, wait_for_lesson_active
from modules.utils import get_filtered_class


class FusionBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        executable = os.environ.get('AUTOVISOR_TEST_BROWSER')
        try:
            self.browser = await self.playwright.chromium.launch(
                executable_path=executable, headless=True)
        except Error as exc:
            await self.playwright.stop()
            if not executable and 'Executable doesn\'t exist' in str(exc):
                self.skipTest('Install Chromium with: python -m playwright install chromium')
            raise
        self.page = await self.browser.new_page()

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def test_nested_chapter_keeps_each_video_and_its_own_progress(self):
        await self.page.set_content('''
            <section class="chapter-item" id="chapter-1">
              <header class="item-name">第一章</header>
              <div class="chapter-content-second" id="a">
                <span class="item-name">第一节</span><i class="finish-icon"></i>
                <span class="el-progress" aria-valuenow="100"></span>
              </div>
              <div class="chapter-content-second" id="b">
                <span class="item-name">第二节</span>
                <span class="el-progress" aria-valuenow="12"></span>
              </div>
            </section>
            <div class="chapter-item" id="c">
              <span class="item-name">第二章第一节</span>
              <span class="el-progress" aria-valuenow="0"></span>
            </div>''')
        rows = await get_filtered_class(self.page, FUSION_CATALOG, include_all=True)
        self.assertEqual([await row.get_attribute('id') for row in rows], ['a', 'b', 'c'])
        pending = await get_filtered_class(self.page, FUSION_CATALOG)
        self.assertEqual([await row.get_attribute('id') for row in pending], ['b', 'c'])
        self.assertEqual(await lesson_progress(rows[1], FUSION_CATALOG), 12)

    async def test_flat_catalog_preserves_all_lessons(self):
        await self.page.set_content(''.join(
            f'<div class="chapter-item {"current" if i == 1 else ""}" id="flat-{i}">'
            f'<span class="item-name">第{i}节</span>'
            '<span class="el-progress" aria-valuenow="0"></span></div>' for i in range(46)))
        rows = await get_filtered_class(self.page, FUSION_CATALOG, include_all=True)
        self.assertEqual(len(rows), 46)
        self.assertTrue(await wait_for_lesson_active(rows[1], FUSION_CATALOG, timeout_ms=500))

    async def test_exact_title_click_activates_same_leaf_and_manual_switch_is_detected(self):
        from modules.lesson_navigation import click_lesson, lesson_key, ensure_lesson_unchanged, LessonChanged
        await self.page.set_content('''
          <section class="chapter-item"><header>一整章</header>
            <div class="chapter-content-second" id="a"><span class="item-name">第一节</span></div>
            <div class="chapter-content-second" id="b"><span class="item-name">第二节</span></div>
          </section>
          <script>
          document.querySelectorAll('.item-name').forEach(title => title.onclick = () => {
            document.querySelectorAll('.current').forEach(row => row.classList.remove('current'));
            title.parentElement.classList.add('current');
          });
          </script>''')
        rows = await get_filtered_class(self.page, FUSION_CATALOG, include_all=True)
        await click_lesson(rows[0], FUSION_CATALOG, 1000)
        self.assertTrue(await wait_for_lesson_active(rows[0], FUSION_CATALOG, timeout_ms=500))
        old = await lesson_key(rows[0], FUSION_CATALOG)
        await click_lesson(rows[1], FUSION_CATALOG, 1000)
        with self.assertRaises(LessonChanged):
            await ensure_lesson_unchanged(self.page, FUSION_CATALOG, old)

    async def test_normal_entry_finishes_small_lesson_before_next_chapter(self):
        from modules.course_runner import run_course, CourseOutcome
        await self.page.set_content('''
          <section class="chapter-item" id="chapter-1"><header class="item-name">第一章</header>
            <div class="chapter-content-second" id="a"><span class="item-name">第一节</span><i class="finish-icon"></i></div>
            <div class="chapter-content-second" id="b"><span class="item-name">第二节</span><span class="el-progress" aria-valuenow="12"></span></div>
          </section>
          <div class="chapter-item" id="c"><span class="item-name">第二章第一节</span><span class="el-progress" aria-valuenow="0"></span></div>
          <video></video>
          <script>
          ['a', 'b', 'c'].forEach(id => document.getElementById(id).onclick = event => {
            event.stopPropagation();
            document.querySelectorAll('.current').forEach(row => row.classList.remove('current'));
            document.getElementById(id).classList.add('current');
          });
          </script>''')
        learned = []
        async def finish(_page, _start, _pause, lesson, *_args):
            learned.append(await lesson.get_attribute('id'))
            await lesson.evaluate("el => el.insertAdjacentHTML('beforeend', '<i class=finish-icon></i>')")
            return 0, True, False
        with patch('modules.course_runner.learn_lesson', finish):
            result = await run_course(self.page, FUSION_CATALOG, SimpleNamespace(limitMaxTime=0), Mock(), asyncio.Event())
        self.assertIs(result, CourseOutcome.COMPLETED)
        self.assertEqual(learned, ['b', 'c'])


if __name__ == '__main__':
    unittest.main()
