import asyncio
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from modules.course_playback import learn_lesson, review_lesson
from modules.course_runner import CourseOutcome, run_course
from modules.lesson_navigation import WISDOM_CATALOG, LessonChanged


class Clock:
    now = 0.0

    def read(self):
        return self.now

    async def sleep(self, seconds):
        self.now += max(seconds, 30)


class PlaybackRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def playback(self, times, progresses, review=False, limit=0):
        clock = Clock()
        page = SimpleNamespace(wait_for_timeout=AsyncMock(), evaluate=AsyncMock())
        logger = Mock()
        with ExitStack() as stack:
            for name, replacement in {
                '_wait_for_duration': AsyncMock(return_value=(534.8, 0)),
                'lesson_key': AsyncMock(return_value='original'),
                'ensure_lesson_unchanged': AsyncMock(),
                'has_visible_verification': AsyncMock(return_value=False),
                'has_visible_element': AsyncMock(return_value=False),
                'get_video_attr': AsyncMock(side_effect=times),
                'lesson_progress': AsyncMock(side_effect=progresses),
                'wait_for_lesson_completion': AsyncMock(return_value=True),
                'show_course_progress': Mock(),
                'run_on': AsyncMock(),
            }.items():
                stack.enter_context(patch('modules.course_playback.' + name, replacement))
            stack.enter_context(patch('modules.course_playback.time.monotonic', clock.read))
            stack.enter_context(patch('modules.course_playback.time.time', clock.read))
            stack.enter_context(patch('modules.course_playback.asyncio.sleep', clock.sleep))
            config = SimpleNamespace(limitMaxTime=limit)
            if review:
                result = await review_lesson(page, 0, 0, config, logger)
            else:
                result = await learn_lesson(page, 0, 0, object(), WISDOM_CATALOG, config, logger)
        return result, logger

    async def test_rewind_does_not_need_to_reach_old_high_water_mark(self):
        result, logger = await self.playback([308, 52, 106, 160, 225, 280], [60] * 6 + [100])
        self.assertTrue(result[1])
        self.assertFalse(any('连续 120 秒' in str(call) for call in logger.warn.call_args_list))

    async def test_real_stall_waits_and_can_finish_after_platform_recovers(self):
        result, logger = await self.playback([150] * 6, [60] * 6 + [100])
        self.assertTrue(result[1])
        self.assertTrue(any('等待恢复' in str(call) for call in logger.warn.call_args_list))

    async def test_configured_time_limit_still_stops_stalled_lesson(self):
        result, _ = await self.playback([150] * 6, [60] * 6, limit=1)
        self.assertEqual(result, (0, False, True))

    async def test_review_rewind_is_not_a_stall(self):
        result, logger = await self.playback([308, 52, 106, 160, 225, 280, 534.8], [], review=True)
        self.assertTrue(result[1])
        self.assertFalse(any('连续 120 秒' in str(call) for call in logger.warn.call_args_list))

    async def test_tail_retry_exhaustion_keeps_page_waiting_for_confirmation(self):
        result, logger = await self.playback([534.8] * 5, [60] * 9 + [100])
        self.assertTrue(result[1])
        self.assertTrue(any('等待平台确认' in str(call) for call in logger.warn.call_args_list))

    async def test_manual_switch_is_reported_before_reading_old_lesson_progress(self):
        logger = Mock()
        with patch('modules.course_playback._wait_for_duration', AsyncMock(return_value=(535, 7))), \
             patch('modules.course_playback.lesson_key', AsyncMock(return_value='old')), \
             patch('modules.course_playback.ensure_lesson_unchanged', AsyncMock(side_effect=LessonChanged)), \
             patch('modules.course_playback.lesson_progress', AsyncMock()) as progress:
            with self.assertRaises(LessonChanged) as caught:
                await learn_lesson(object(), 0, 0, object(), WISDOM_CATALOG, SimpleNamespace(limitMaxTime=0), logger)
            self.assertEqual(caught.exception.paused_time, 7)
            progress.assert_not_awaited()


class RunnerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_temporarily_empty_catalog_is_not_reported_as_completed(self):
        row = SimpleNamespace(key='a')
        done = False
        page = SimpleNamespace(is_closed=lambda: False, wait_for_selector=AsyncMock(),
                               wait_for_timeout=AsyncMock(), set_default_timeout=Mock())
        async def learn(*_args):
            nonlocal done
            done = True
            return 0, True, False
        with ExitStack() as stack:
            replacements = {
                'get_filtered_class': AsyncMock(side_effect=[[row], [], [row], [row]]),
                'lesson_key': AsyncMock(return_value='a'),
                'lesson_progress': AsyncMock(side_effect=lambda *_: 100 if done else 0),
                'active_lesson': AsyncMock(return_value=row),
                'click_lesson': AsyncMock(),
                'wait_for_lesson_active': AsyncMock(return_value=True),
                'get_lesson_name': AsyncMock(return_value='a'),
                'learn_lesson': learn,
                'asyncio.sleep': AsyncMock(),
            }
            for name, replacement in replacements.items():
                stack.enter_context(patch('modules.course_runner.' + name, replacement))
            result = await run_course(page, WISDOM_CATALOG, SimpleNamespace(limitMaxTime=0), Mock(), asyncio.Event())
        self.assertIs(result, CourseOutcome.COMPLETED)
        self.assertTrue(done)
        replacements['click_lesson'].assert_awaited_once()

    async def test_metadata_failure_waits_and_resumes_same_lesson(self):
        row = SimpleNamespace(key='a')
        done = False
        calls = 0
        page = SimpleNamespace(is_closed=lambda: False, wait_for_selector=AsyncMock(),
                               wait_for_timeout=AsyncMock(), set_default_timeout=Mock())
        async def learn(*_args):
            nonlocal done, calls
            calls += 1
            done = calls == 2
            return 0, done, False
        with ExitStack() as stack:
            replacements = {
                'get_filtered_class': AsyncMock(return_value=[row]),
                'lesson_key': AsyncMock(return_value='a'),
                'lesson_progress': AsyncMock(side_effect=lambda *_: 100 if done else 0),
                'active_lesson': AsyncMock(return_value=row),
                'click_lesson': AsyncMock(),
                'wait_for_lesson_active': AsyncMock(return_value=True),
                'get_lesson_name': AsyncMock(return_value='a'),
                'get_video_attr': AsyncMock(return_value=535),
                'has_visible_verification': AsyncMock(return_value=False),
                'learn_lesson': learn,
            }
            for name, replacement in replacements.items():
                stack.enter_context(patch('modules.course_runner.' + name, replacement))
            result = await run_course(page, WISDOM_CATALOG, SimpleNamespace(limitMaxTime=0), Mock(), asyncio.Event())
        self.assertIs(result, CourseOutcome.COMPLETED)
        self.assertEqual(calls, 2)
        replacements['click_lesson'].assert_awaited_once()

    async def test_activation_failure_allows_manual_selection_and_playback(self):
        row = SimpleNamespace(key='a')
        done = False
        gate = asyncio.Event()
        page = SimpleNamespace(is_closed=lambda: False, wait_for_selector=AsyncMock(),
                               wait_for_timeout=AsyncMock(), set_default_timeout=Mock())
        async def learn(*_args):
            nonlocal done
            done = True
            self.assertTrue(gate.is_set())
            return 0, True, False
        with ExitStack() as stack:
            replacements = {
                'get_filtered_class': AsyncMock(return_value=[row]),
                'lesson_key': AsyncMock(return_value='a'),
                'lesson_progress': AsyncMock(side_effect=lambda *_: 100 if done else 0),
                'active_lesson': AsyncMock(side_effect=[None, row]),
                'click_lesson': AsyncMock(),
                'wait_for_lesson_active': AsyncMock(return_value=False),
                'get_lesson_name': AsyncMock(return_value='a'),
                'has_visible_verification': AsyncMock(return_value=False),
                'learn_lesson': learn,
            }
            for name, replacement in replacements.items():
                stack.enter_context(patch('modules.course_runner.' + name, replacement))
            result = await run_course(page, WISDOM_CATALOG, SimpleNamespace(limitMaxTime=0), Mock(), gate)
        self.assertIs(result, CourseOutcome.COMPLETED)
        self.assertEqual(replacements['click_lesson'].await_count, 2)

    async def test_manual_switch_is_adopted_and_unfinished_lesson_is_not_lost(self):
        rows = [SimpleNamespace(key=key) for key in ('a', 'b', 'c')]
        done = set()
        calls, clicks = [], []
        selected = rows[0]
        page = SimpleNamespace(is_closed=lambda: False, wait_for_selector=AsyncMock(),
                               wait_for_timeout=AsyncMock(), set_default_timeout=Mock())
        async def filtered(_page, _catalog, include_all=False):
            return rows if include_all else [row for row in rows if row.key not in done]
        async def click(row, *_args):
            nonlocal selected
            selected = row
            clicks.append(row.key)
        async def learn(_page, _start, _pause, row, *_args):
            nonlocal selected
            calls.append(row.key)
            if len(calls) == 1:
                selected = rows[1]
                exc = LessonChanged()
                exc.paused_time = 4
                raise exc
            done.add(row.key)
            return 0, True, False
        with ExitStack() as stack:
            replacements = {
                'get_filtered_class': filtered,
                'lesson_key': AsyncMock(side_effect=lambda row, _: row.key),
                'lesson_progress': AsyncMock(side_effect=lambda row, _: 100 if row.key in done else 0),
                'active_lesson': AsyncMock(side_effect=lambda *_: selected),
                'click_lesson': click,
                'wait_for_lesson_active': AsyncMock(return_value=True),
                'get_lesson_name': AsyncMock(side_effect=lambda _page, row, _: row.key),
                'learn_lesson': learn,
            }
            for name, replacement in replacements.items():
                stack.enter_context(patch('modules.course_runner.' + name, replacement))
            result = await run_course(page, WISDOM_CATALOG, SimpleNamespace(limitMaxTime=0), Mock(), asyncio.Event())
        self.assertIs(result, CourseOutcome.COMPLETED)
        self.assertEqual(calls, ['a', 'b', 'c', 'a'])
        self.assertEqual(clicks, ['a', 'c', 'a'])
        self.assertEqual(done, {'a', 'b', 'c'})


if __name__ == '__main__':
    unittest.main()
