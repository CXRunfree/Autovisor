import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

from modules.browser import create_browser_session
from modules.lesson_navigation import (
    CATALOGS,
    detect_catalog,
    get_lesson_title,
    lesson_is_complete,
    lesson_progress,
)
from modules.tasks import has_visible_verification
from modules.utils import load_cookies


async def check_browser(config, logger, cookie_path: str) -> int:
    async with async_playwright() as playwright:
        cookies = None if config.attach_existing_chrome else load_cookies(cookie_path)
        session = await asyncio.wait_for(
            create_browser_session(playwright, config, cookies, logger), timeout=45
        )
        try:
            await session.page.goto(
                "https://onlineweb.zhihuishu.com/onlinestuh5",
                wait_until="commit",
                timeout=15000,
            )
            await session.page.wait_for_timeout(1000)
            if "passport.zhihuishu.com/login" in session.page.url:
                logger.warn("Chrome 已连接,但智慧树登录状态无效.", shift=True)
                return 1
            logger.info(f"浏览器检查通过: {await session.page.title()}", shift=True)
            return 0
        finally:
            await session.close()


async def check_course(course_url: str, config, logger, cookie_path: str) -> int:
    blocked_markers = (
        "saveDatabaseIntervalTime",
        "saveCacheIntervalTime",
        "saveStuStudyRecord",
        "saveLearningTime",
        "saveStudyTime",
    )
    blocked_requests = 0
    blocked_media = 0

    async def block_progress(route):
        nonlocal blocked_media, blocked_requests
        if route.request.resource_type == "media":
            blocked_media += 1
            await route.abort()
        elif any(marker in route.request.url for marker in blocked_markers):
            blocked_requests += 1
            await route.abort()
        else:
            await route.continue_()

    async with async_playwright() as playwright:
        cookies = None if config.attach_existing_chrome else load_cookies(cookie_path)
        session = await asyncio.wait_for(
            create_browser_session(playwright, config, cookies, logger), timeout=45
        )
        try:
            page = session.page
            await page.route("**/*", block_progress)
            await page.add_init_script(
                "HTMLMediaElement.prototype.play = function() { "
                "this.pause(); return Promise.resolve(); }; "
                "addEventListener('play', event => event.target.pause(), true);"
            )
            await page.goto(course_url, wait_until="commit", timeout=15000)
            await page.wait_for_timeout(10000)
            screenshot_path = Path.home() / "scratch-data" / "autovisor-course-check.png"
            html_path = Path.home() / "scratch-data" / "autovisor-course-check.html"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                screenshot_path.parent.chmod(0o700)
            try:
                catalog = await detect_catalog(page, page.url, timeout_ms=15000)
            except RuntimeError:
                await page.screenshot(path=str(screenshot_path), full_page=False)
                html_path.write_text(await page.content(), encoding="utf-8")
                if os.name != "nt":
                    screenshot_path.chmod(0o600)
                    html_path.chmod(0o600)
                body_text = await page.locator("body").inner_text(timeout=3000)
                logger.error(
                    f"目录检查失败: title={await page.title()!r}, url={page.url}, "
                    f"body_length={len(body_text)}, screenshot={screenshot_path}, "
                    f"html={html_path}"
                )
                raise
            selectors = {entry.name: entry.item for entry in CATALOGS}
            selectors["video"] = "video"
            counts = {
                name: await page.locator(selector).count()
                for name, selector in selectors.items()
            }
            lessons = await page.locator(catalog.item).all()
            completed_count = sum(
                [await lesson_is_complete(lesson, catalog) for lesson in lessons]
            )
            active = page.locator(catalog.active).first
            if await active.count():
                active_title = await get_lesson_title(page, active, catalog)
                active_progress = await lesson_progress(active, catalog)
            else:
                active_title = None
                active_progress = None
            body_text = await page.locator("body").inner_text(timeout=3000)
            verification_visible = await has_visible_verification(page)
            video_paused = await page.locator("video").evaluate_all(
                "videos => videos.map(video => video.paused)"
            )
            frame_urls = [frame.url for frame in page.frames]
            await page.screenshot(path=str(screenshot_path), full_page=False)
            html_path.write_text(await page.content(), encoding="utf-8")
            if os.name != "nt":
                screenshot_path.chmod(0o600)
                html_path.chmod(0o600)
            logger.info(
                f"课程页检查: title={await page.title()!r}, "
                f"url={page.url}, catalog={catalog.name}, selectors={counts}, "
                f"completed={completed_count}/{len(lessons)}, "
                f"active={active_title!r}, active_progress={active_progress}, "
                f"video_paused={video_paused}, blocked_media={blocked_media}, "
                f"blocked_progress={blocked_requests}, "
                f"verification_visible={verification_visible}, "
                f"body_length={len(body_text)}, frames={frame_urls}, "
                f"screenshot={screenshot_path}, html={html_path}",
                shift=True,
            )
            return 0
        finally:
            await session.close()
