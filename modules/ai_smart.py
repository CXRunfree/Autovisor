import asyncio
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import Locator, Page, TimeoutError

from modules.course_runner import CourseOutcome
from modules.utils import get_video_attr


AI_SMART_HOST = "ai-smart-course-student-pro.zhihuishu.com"
KNOWLEDGE_CONTENT = ".knowledge-content"
MODULE_ITEM = ".knowledge-content > div[id^='knowledgeItem-']"
UNIT_ITEM = ":scope > .content-list > .conlist-sub-content"
SUB_ITEM = ":scope > .conlist-content-box > .item-content"
REQUIRED_SECTION_TITLE = "必学资源"
RESOURCE_CARD = ".resources-list .basic-info-video-card-container"
VIDEO_READY_TIMEOUT_MS = 15_000
RESOURCE_COMPLETE_TIMEOUT_MS = 5_000
STALL_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class AiSmartTarget:
    module: str
    unit: str
    title: str
    progress: int = 0

    @property
    def label(self) -> str:
        return f"{self.module} / {self.unit} / {self.title}"


def is_ai_smart_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return hostname == AI_SMART_HOST


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").split())


def parse_percent(value: str | None) -> int:
    matched = re.search(r"学习进度\s*(\d+(?:\.\d+)?)\s*%", value or "")
    if not matched:
        matched = re.search(r"(\d+(?:\.\d+)?)\s*%", value or "")
    if not matched:
        return 0
    try:
        number = float(matched.group(1))
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(int(number), 100))


def parse_clock(value: str | None) -> int | None:
    parts = [part.strip() for part in (value or "").split(":")]
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    return hours * 3600 + minutes * 60 + seconds


def parse_segment_range(value: str | None) -> tuple[int | None, int | None]:
    clocks = re.findall(r"\d{1,3}:\d{2}(?::\d{2})?", value or "")
    if len(clocks) < 2:
        return None, None
    return parse_clock(clocks[0]), parse_clock(clocks[1])


def build_targets(outline: dict | None) -> list[AiSmartTarget]:
    if not isinstance(outline, dict):
        return []
    targets: list[AiSmartTarget] = []
    for module in outline.get("modules") or []:
        if not isinstance(module, dict):
            continue
        module_title = normalize_text(module.get("title"))
        for unit in module.get("units") or []:
            if not isinstance(unit, dict):
                continue
            unit_title = normalize_text(unit.get("title"))
            for item in unit.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_title = normalize_text(item.get("title"))
                if not unit_title or not item_title:
                    continue
                targets.append(
                    AiSmartTarget(
                        module=module_title,
                        unit=unit_title,
                        title=item_title,
                        progress=parse_percent(item.get("progress")),
                    )
                )
    return targets


def incomplete_targets(outline: dict | None) -> list[AiSmartTarget]:
    return [target for target in build_targets(outline) if target.progress < 100]


async def extract_outline(page: Page) -> dict:
    await page.wait_for_selector(KNOWLEDGE_CONTENT, state="attached", timeout=20_000)
    await page.wait_for_selector(
        ".knowledge-content .content-list-title", state="attached", timeout=10_000
    )
    await page.wait_for_selector(
        ".knowledge-content .item-content", state="attached", timeout=10_000
    )
    return await page.evaluate(
        """() => {
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
            const modules = [...document.querySelectorAll(
                '.knowledge-content > div[id^="knowledgeItem-"]'
            )].map((moduleEl) => {
                const title = normalize(
                    moduleEl.querySelector(
                        ':scope > .content-list-title .title-left-text'
                    )?.textContent
                );
                if (!title) {
                    return null;
                }
                const units = [...moduleEl.querySelectorAll(
                    ':scope > .content-list > .conlist-sub-content'
                )].map((unitEl) => {
                    const unitTitle = normalize(
                        unitEl.querySelector(
                            ':scope > .content-list-title .title-left-sub-text'
                        )?.textContent
                    );
                    if (!unitTitle) {
                        return null;
                    }
                    const items = [...unitEl.querySelectorAll(
                        ':scope > .conlist-content-box > .item-content'
                    )].map((itemEl) => ({
                        title: normalize(itemEl.querySelector('.item-title')?.textContent),
                        progress: normalize(itemEl.innerText),
                    })).filter((item) => item.title);
                    return { title: unitTitle, items };
                }).filter(Boolean);
                return { title, units };
            }).filter(Boolean);
            return { modules };
        }"""
    )


async def _select_module_tab(page: Page, module_name: str) -> None:
    if not module_name:
        return
    tabs = await page.locator(".ant-tabs-tab-btn").all()
    for tab in tabs:
        if normalize_text(await tab.text_content()) == normalize_text(module_name):
            await tab.click()
            await page.wait_for_timeout(500)
            return


async def _find_target_item(page: Page, target: AiSmartTarget) -> Locator | None:
    modules = await page.locator(MODULE_ITEM).all()
    for module in modules:
        module_title = normalize_text(
            await module.locator(":scope > .content-list-title .title-left-text")
            .first.text_content()
        )
        if target.module and module_title != normalize_text(target.module):
            continue
        units = await module.locator(UNIT_ITEM).all()
        for unit in units:
            unit_title = normalize_text(
                await unit.locator(":scope > .content-list-title .title-left-sub-text")
                .first.text_content()
            )
            if target.unit and unit_title != normalize_text(target.unit):
                continue
            items = await unit.locator(SUB_ITEM).all()
            for item in items:
                item_title = normalize_text(
                    await item.locator(".item-title").first.text_content()
                )
                if item_title == normalize_text(target.title):
                    return item
    return None


async def open_target(page: Page, target: AiSmartTarget) -> bool:
    await _select_module_tab(page, target.module)
    item = await _find_target_item(page, target)
    if item is None:
        return False
    await item.scroll_into_view_if_needed()
    await item.click()
    try:
        await page.wait_for_selector(".resources-section", state="attached", timeout=15_000)
    except TimeoutError:
        return False
    return True


async def get_required_section(page: Page) -> Locator:
    await page.wait_for_selector(".resources-section", state="attached", timeout=10_000)
    sections = page.locator(".resources-section")
    for index in range(await sections.count()):
        section = sections.nth(index)
        title = await section.locator(".resources-detail-title").first.text_content()
        if normalize_text(title) == REQUIRED_SECTION_TITLE:
            return section
    raise RuntimeError("未找到必学资源区域")


async def list_required_resources(page: Page) -> list[Locator]:
    section = await get_required_section(page)
    return await section.locator(RESOURCE_CARD).all()


async def resource_title(resource: Locator) -> str:
    return normalize_text(await resource.locator(".video-title").first.text_content())


async def resource_type(resource: Locator) -> str:
    icon_class = await resource.locator(".icon-box").first.get_attribute("class") or ""
    if "video" in icon_class:
        return "video"
    if "book" in icon_class:
        return "book"
    return "other"


async def is_resource_completed(resource: Locator) -> bool:
    try:
        text = await resource.inner_text()
    except Exception:
        text = await resource.text_content()
    return "已完成" in normalize_text(text)


async def wait_for_resource_active(
    page: Page, resource: Locator, timeout_ms: int = 10_000
) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        class_name = await resource.get_attribute("class") or ""
        if "active" in class_name.split():
            return True
        await page.wait_for_timeout(200)
    return False


async def activate_resource(page: Page, resource: Locator) -> bool:
    await resource.scroll_into_view_if_needed()
    await resource.click()
    return await wait_for_resource_active(page, resource)


async def get_segment_range(page: Page) -> tuple[int | None, int | None]:
    try:
        text = await page.locator(".resources-talk .segment-btn").first.text_content(
            timeout=1000
        )
    except Exception:
        return None, None
    return parse_segment_range(text)


async def get_display_time(page: Page) -> int | None:
    try:
        text = await page.locator(".nPlayTime .currentTime").first.text_content(
            timeout=1000
        )
    except Exception:
        return None
    return parse_clock(normalize_text(text))


async def is_ai_segment_finished(page: Page, tolerance_seconds: int = 1) -> bool:
    _, segment_end = await get_segment_range(page)
    if segment_end is None:
        return False
    current_time = await get_display_time(page)
    if current_time is None:
        value = await get_video_attr(page, "currentTime")
        if not isinstance(value, (int, float)):
            return False
        current_time = int(value)
    return current_time >= segment_end - tolerance_seconds


async def _wait_for_verification(page: Page) -> bool:
    from modules.tasks import has_visible_verification, wait_until_verification_hidden

    if not await has_visible_verification(page):
        return False
    await wait_until_verification_hidden(page)
    return True


async def _play_video(page: Page) -> None:
    await page.evaluate(
        """() => {
            const video = document.querySelector('video');
            if (video && video.paused) {
                video.play().catch(() => {});
            }
        }"""
    )


def _time_limit_reached(config, started_at: float) -> bool:
    limit = getattr(config, "limitMaxTime", 0) or 0
    return 0 < limit <= (time.monotonic() - started_at) / 60


async def _wait_for_resource_completed(
    page: Page, resource: Locator, timeout_ms: int = RESOURCE_COMPLETE_TIMEOUT_MS
) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if await is_resource_completed(resource):
            return True
        await page.wait_for_timeout(250)
    return False


async def watch_video_resource(
    page: Page,
    resource: Locator,
    config,
    logger,
    started_at: float,
    playback_enabled: asyncio.Event,
) -> tuple[bool, bool]:
    await page.wait_for_selector("video", state="attached", timeout=VIDEO_READY_TIMEOUT_MS)
    playback_enabled.set()
    await _play_video(page)
    segment_start, segment_end = await get_segment_range(page)
    metadata_deadline = time.monotonic() + VIDEO_READY_TIMEOUT_MS / 1000
    while segment_end is None and time.monotonic() < metadata_deadline:
        duration = await get_video_attr(page, "duration")
        if isinstance(duration, (int, float)) and duration > 0:
            break
        await _play_video(page)
        await asyncio.sleep(0.5)
        segment_start, segment_end = await get_segment_range(page)
    logger.event(
        "ai-smart 视频分段",
        开始=segment_start,
        结束=segment_end,
    )
    last_time = -1.0
    last_activity = time.monotonic()
    metadata_deadline = last_activity + VIDEO_READY_TIMEOUT_MS / 1000
    try:
        while True:
            if _time_limit_reached(config, started_at):
                return False, True
            if await _wait_for_verification(page):
                last_activity = time.monotonic()
                metadata_deadline = last_activity + VIDEO_READY_TIMEOUT_MS / 1000
                continue

            current_time = await get_display_time(page)
            if current_time is None:
                value = await get_video_attr(page, "currentTime")
                if isinstance(value, (int, float)):
                    current_time = int(value)
            logger.event(
                "ai-smart 播放进度",
                interval=30,
                当前=current_time,
                分段结束=segment_end,
            )

            if segment_end is not None and current_time is not None:
                if current_time >= segment_end - 1:
                    if not await _wait_for_resource_completed(page, resource):
                        logger.warn("视频分段已播完, 但页面尚未标记资源完成.", shift=True)
                    return True, False
            else:
                duration = await get_video_attr(page, "duration")
                if (
                    isinstance(duration, (int, float))
                    and duration > 0
                    and current_time is not None
                    and current_time >= duration - 1
                ):
                    await _wait_for_resource_completed(page, resource)
                    return True, False
                if time.monotonic() >= metadata_deadline:
                    logger.warn("ai-smart 视频元数据加载超时.", shift=True)
                    return False, False

            paused = await get_video_attr(page, "paused")
            if paused:
                await _play_video(page)
            if current_time is not None and current_time > last_time + 0.25:
                last_time = current_time
                last_activity = time.monotonic()
            if time.monotonic() - last_activity >= STALL_TIMEOUT_SECONDS:
                logger.warn("ai-smart 视频连续 120 秒未推进.", shift=True)
                return False, False
            await asyncio.sleep(0.5)
    finally:
        playback_enabled.clear()


async def _load_home(page: Page, home_url: str) -> None:
    await page.goto(home_url, wait_until="domcontentloaded")
    await page.wait_for_selector(KNOWLEDGE_CONTENT, state="attached", timeout=20_000)


async def run_ai_smart_course(
    page: Page,
    home_url: str,
    config,
    logger,
    playback_enabled: asyncio.Event,
) -> CourseOutcome:
    page.set_default_timeout(10_000)
    started_at = time.monotonic()
    await _load_home(page, home_url)
    outline = await extract_outline(page)
    targets = build_targets(outline)
    pending = incomplete_targets(outline)
    logger.event(
        "ai-smart 课程大纲",
        子项目=len(targets),
        待完成=len(pending),
    )
    if not targets:
        logger.error("ai-smart 课程大纲为空, 未找到可学习的子项目.", shift=True)
        return CourseOutcome.FAILED
    if not pending:
        logger.info("ai-smart 课程全部子项目已完成!", shift=True)
        return CourseOutcome.COMPLETED

    logger.info(f"ai-smart 待完成子项目: {len(pending)} 个")
    failed: list[AiSmartTarget] = []
    for index, target in enumerate(pending, 1):
        if _time_limit_reached(config, started_at):
            return CourseOutcome.TIME_LIMIT
        playback_enabled.clear()
        logger.info(f"正在处理子项目 {index}/{len(pending)}: {target.label}")
        logger.context(子项目序号=f"{index}/{len(pending)}", 子项目名称=target.label)
        target_failed = False
        try:
            await _load_home(page, home_url)
            if not await open_target(page, target):
                logger.warn(f"未找到子项目: {target.label}", shift=True)
                failed.append(target)
                continue
            resources = await list_required_resources(page)
            if not resources:
                logger.warn(f"子项目没有必学资源: {target.label}", shift=True)
                continue
            for resource in resources:
                if _time_limit_reached(config, started_at):
                    return CourseOutcome.TIME_LIMIT
                if await is_resource_completed(resource):
                    continue
                title = await resource_title(resource)
                kind = await resource_type(resource)
                logger.info(f"正在学习资源: {title} ({kind})")
                if kind != "video":
                    await activate_resource(page, resource)
                    await page.wait_for_timeout(1500)
                    continue
                if not await activate_resource(page, resource):
                    logger.warn(f"资源无法激活: {title}", shift=True)
                    target_failed = True
                    break
                completed, reached_limit = await watch_video_resource(
                    page,
                    resource,
                    config,
                    logger,
                    started_at,
                    playback_enabled,
                )
                if reached_limit:
                    return CourseOutcome.TIME_LIMIT
                if not completed:
                    logger.warn(f"资源未完成: {title}", shift=True)
                    target_failed = True
                    break
        except Exception as exc:
            playback_enabled.clear()
            logger.log_exception(f"ai-smart 子项目处理失败: {target.label}", exc, shift=True)
            target_failed = True
        finally:
            playback_enabled.clear()
        if target_failed:
            failed.append(target)

    if failed:
        logger.warn(f"仍有 {len(failed)} 个 ai-smart 子项目未完成.", shift=True)
        for target in failed:
            logger.warn(f"- {target.label}", shift=True)
        return CourseOutcome.FAILED
    logger.info("ai-smart 课程全部必学资源已处理完成!", shift=True)
    return CourseOutcome.COMPLETED
