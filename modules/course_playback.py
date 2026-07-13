import asyncio
import time

from playwright.async_api import Page, TimeoutError
from playwright._impl._errors import TargetClosedError

from modules.lesson_navigation import (
    CatalogSelectors,
    lesson_progress,
    wait_for_lesson_completion,
)
from modules.progress import show_course_progress
from modules.tasks import (
    has_visible_element,
    has_visible_verification,
    wait_until_verification_hidden,
)
from modules.utils import get_video_attr
from modules.video_state import (
    has_valid_duration,
    tail_retry_time,
    time_for_percent,
    video_at_end,
)

METADATA_TIMEOUT_SECONDS = 30
STALL_TIMEOUT_SECONDS = 120


def elapsed_minutes(start_time: float, paused_time: float) -> float:
    return max(0.0, time.time() - start_time - paused_time) / 60


async def _wait_for_topic_hidden(page: Page) -> float:
    wait_start = time.time()
    while await has_visible_element(page, (".topic-title",)):
        await asyncio.sleep(0.5)
    return time.time() - wait_start


async def _wait_for_duration(page: Page):
    deadline = time.monotonic() + METADATA_TIMEOUT_SECONDS
    paused_time = 0.0
    while time.monotonic() < deadline and not page.is_closed():
        if await has_visible_verification(page):
            wait_start = time.monotonic()
            await wait_until_verification_hidden(page)
            waited = time.monotonic() - wait_start
            deadline += waited
            paused_time += waited
            continue
        if await has_visible_element(page, (".topic-title",)):
            wait_start = time.monotonic()
            await _wait_for_topic_hidden(page)
            waited = time.monotonic() - wait_start
            deadline += waited
            paused_time += waited
            continue
        duration = await get_video_attr(page, "duration")
        if has_valid_duration(duration):
            return duration, paused_time
        await asyncio.sleep(0.5)
    return None, paused_time


async def learn_lesson(
    page: Page,
    start_time: float,
    paused_before: float,
    current_lesson,
    catalog: CatalogSelectors,
    config,
    logger,
) -> tuple[float, bool, bool]:
    total_time, paused_time = await _wait_for_duration(page)
    if not has_valid_duration(total_time):
        logger.warn("视频元数据加载超时,停止当前课时.", shift=True)
        return paused_time, False, False
    synced_to_catalog = False
    retry_count = 0
    last_catalog_progress = -1
    last_video_time = -1.0
    last_activity = time.monotonic()

    while True:
        try:
            if await has_visible_verification(page):
                wait_start = time.time()
                await wait_until_verification_hidden(page)
                paused_time += time.time() - wait_start
                synced_to_catalog = False
                last_activity = time.monotonic()
                continue
            if await has_visible_element(page, (".topic-title",)):
                paused_time += await _wait_for_topic_hidden(page)
                last_activity = time.monotonic()
                continue

            if 0 < config.limitMaxTime <= elapsed_minutes(
                start_time, paused_before + paused_time
            ):
                return paused_time, False, True

            catalog_progress = await lesson_progress(current_lesson, catalog)
            if catalog_progress >= 100:
                await page.wait_for_timeout(2000)
                completed = await wait_for_lesson_completion(
                    current_lesson, catalog, timeout_ms=5000
                )
                return paused_time, completed, False

            if catalog_progress > last_catalog_progress:
                last_catalog_progress = catalog_progress
                retry_count = 0
                last_activity = time.monotonic()

            current_time = await get_video_attr(page, "currentTime")
            if isinstance(current_time, (int, float)) and current_time > last_video_time + 0.25:
                last_video_time = current_time
                last_activity = time.monotonic()
            if time.monotonic() - last_activity >= STALL_TIMEOUT_SECONDS:
                logger.warn("视频和平台进度连续 120 秒未推进,停止当前课时.", shift=True)
                return paused_time, False, False

            if has_valid_duration(total_time) and isinstance(
                current_time, (int, float)
            ):
                expected_time = time_for_percent(total_time, catalog_progress)
                if (
                    not synced_to_catalog
                    and catalog.progress
                    and current_time > expected_time + 15
                ):
                    logger.warn(
                        f"播放器进度快于平台记录,回到 {catalog_progress}% 继续.",
                        shift=True,
                    )
                    await page.evaluate(
                        """time => {
                            const video = document.querySelector('video');
                            if (!video) return;
                            video.currentTime = time;
                            video.play();
                        }""",
                        expected_time,
                    )
                    current_time = expected_time
                    last_video_time = expected_time
                    last_activity = time.monotonic()
                synced_to_catalog = True

                if video_at_end(current_time, total_time):
                    await page.wait_for_timeout(3000)
                    if await has_visible_verification(page):
                        wait_start = time.time()
                        await wait_until_verification_hidden(page)
                        paused_time += time.time() - wait_start
                        retry_count = 0
                        synced_to_catalog = False
                        last_activity = time.monotonic()
                        continue
                    if await has_visible_element(page, (".topic-title",)):
                        paused_time += await _wait_for_topic_hidden(page)
                        retry_count = 0
                        last_activity = time.monotonic()
                        continue
                    refreshed = await lesson_progress(current_lesson, catalog)
                    if refreshed >= 100:
                        return paused_time, True, False
                    if retry_count >= 2:
                        logger.warn(
                            f"视频已结束但平台进度停在 {refreshed}%,停止自动重试.",
                            shift=True,
                        )
                        return paused_time, False, False
                    retry_time = (
                        time_for_percent(total_time, refreshed)
                        if catalog.progress
                        else tail_retry_time(total_time)
                    )
                    logger.warn(
                        f"视频已结束但平台仅记录 {refreshed}%,回退后重试上报.",
                        shift=True,
                    )
                    await page.evaluate(
                        """time => {
                            const video = document.querySelector('video');
                            if (!video) return;
                            video.currentTime = time;
                            video.play();
                        }""",
                        retry_time,
                    )
                    retry_count += 1
                    last_video_time = retry_time
                    last_activity = time.monotonic()
                    await asyncio.sleep(1)
                    continue

            show_course_progress(
                desc="平台记录进度:", cur_time=f"{catalog_progress}%"
            )
            await asyncio.sleep(0.5)
        except TargetClosedError:
            return paused_time, False, False
        except TimeoutError as exc:
            if await has_visible_verification(page):
                wait_start = time.time()
                await wait_until_verification_hidden(page)
                paused_time += time.time() - wait_start
            else:
                logger.debug(
                    f"学习进度轮询未命中: {logger.summarize_exception(exc)}"
                )


async def review_lesson(
    page: Page,
    start_time: float,
    paused_before: float,
    config,
    logger,
) -> tuple[float, bool, bool]:
    total_time, paused_time = await _wait_for_duration(page)
    if not has_valid_duration(total_time):
        logger.warn("视频元数据加载超时,停止当前课时.", shift=True)
        return paused_time, False, False
    try:
        await page.evaluate(config.reset_curtime)
    except TargetClosedError:
        return paused_time, False, False
    last_video_time = -1.0
    last_activity = time.monotonic()

    while True:
        try:
            if await has_visible_verification(page):
                wait_start = time.time()
                await wait_until_verification_hidden(page)
                paused_time += time.time() - wait_start
                last_activity = time.monotonic()
                continue
            if await has_visible_element(page, (".topic-title",)):
                paused_time += await _wait_for_topic_hidden(page)
                last_activity = time.monotonic()
                continue

            current_time = await get_video_attr(page, "currentTime")
            if video_at_end(current_time, total_time):
                return paused_time, True, False
            if isinstance(current_time, (int, float)) and current_time > last_video_time + 0.25:
                last_video_time = current_time
                last_activity = time.monotonic()
            if time.monotonic() - last_activity >= STALL_TIMEOUT_SECONDS:
                logger.warn("视频连续 120 秒未推进,停止当前课时.", shift=True)
                return paused_time, False, False
            if 0 < config.limitMaxTime <= elapsed_minutes(
                start_time, paused_before + paused_time
            ):
                return paused_time, False, True
            show_course_progress(
                desc="完成进度:",
                cur_time=elapsed_minutes(start_time, paused_before + paused_time),
                limit_time=config.limitMaxTime,
            )
            await asyncio.sleep(0.5)
        except TargetClosedError:
            return paused_time, False, False
        except TimeoutError as exc:
            if await has_visible_verification(page):
                wait_start = time.time()
                await wait_until_verification_hidden(page)
                paused_time += time.time() - wait_start
            else:
                logger.debug(
                    f"复习进度轮询未命中: {logger.summarize_exception(exc)}"
                )
