import time
from enum import Enum

from playwright.async_api import Page

from modules.course_playback import elapsed_minutes, learn_lesson, review_lesson
from modules.lesson_navigation import (
    CatalogSelectors,
    detect_catalog,
    wait_for_lesson_active,
)
from modules.tasks import has_visible_verification, wait_until_verification_hidden
from modules.utils import get_filtered_class, get_lesson_name


class CourseOutcome(Enum):
    COMPLETED = "completed"
    TIME_LIMIT = "time_limit"
    FAILED = "failed"


async def detect_catalog_after_verification(
    page: Page, course_url: str
) -> CatalogSelectors:
    deadline = time.monotonic() + 20
    while True:
        if await has_visible_verification(page):
            await wait_until_verification_hidden(page)
            deadline = time.monotonic() + 20
        remaining_ms = int(max(0, deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            raise RuntimeError("课程目录加载超时，且未检测到可处理的安全验证")
        try:
            return await detect_catalog(
                page, course_url, timeout_ms=min(1000, remaining_ms)
            )
        except RuntimeError:
            continue


async def run_course(
    page: Page,
    catalog: CatalogSelectors,
    config,
    logger,
    playback_enabled,
) -> CourseOutcome:
    await page.wait_for_selector(catalog.item, state="attached")
    to_learn = await get_filtered_class(page, catalog)
    learning = bool(to_learn)
    lessons = (
        to_learn
        if learning
        else await get_filtered_class(page, catalog, include_all=True)
    )
    if not lessons:
        logger.error("课程目录中没有可播放的视频课时.")
        return CourseOutcome.FAILED

    start_time = time.time()
    paused_time = 0.0
    for index, lesson in enumerate(lessons):
        playback_enabled.clear()
        await lesson.click()
        active = await wait_for_lesson_active(lesson, catalog)
        if not active:
            logger.warn("课时切换超时,正在重试一次.", shift=True)
            await lesson.click()
            active = await wait_for_lesson_active(lesson, catalog)
        if not active:
            logger.error(f"无法选中课时,目录类型: {catalog.name}")
            return CourseOutcome.FAILED

        await page.wait_for_timeout(1000)
        title = await get_lesson_name(page, lesson, catalog)
        logger.info(f"正在学习:{title}")
        page.set_default_timeout(10000)
        await page.wait_for_selector("video", state="attached")
        playback_enabled.set()

        if learning:
            added_pause, completed, reached_limit = await learn_lesson(
                page, start_time, paused_time, lesson, catalog, config, logger
            )
        else:
            added_pause, completed, reached_limit = await review_lesson(
                page, start_time, paused_time, config, logger
            )
        paused_time += added_pause

        if reached_limit:
            logger.info(f"当前课程已达时限:{config.limitMaxTime}min", shift=True)
            logger.info("即将进入下门课程!")
            return CourseOutcome.TIME_LIMIT
        if not completed:
            logger.warn(
                f'"{title}" 未能确认播放完成,本轮停止切换下一课.',
                shift=True,
            )
            return CourseOutcome.FAILED
        if index < len(lessons) - 1:
            logger.info(f'"{title}" 已完成!', shift=True)
            logger.info(
                f"本次课程已学习:{elapsed_minutes(start_time, paused_time):.1f} min"
            )

    if learning:
        logger.info("已学完本课程全部内容!", shift=True)
        print("==" * 10)
    else:
        logger.info(f'"{title}" 已完成!', shift=True)
    return CourseOutcome.COMPLETED
