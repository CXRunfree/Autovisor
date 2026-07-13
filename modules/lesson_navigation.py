import asyncio
import math
from dataclasses import dataclass

from playwright.async_api import Locator, Page, TimeoutError


@dataclass(frozen=True)
class CatalogSelectors:
    name: str
    item: str
    active: str
    finish: str
    title: str
    active_class: str
    progress: str | None = None
    progress_attribute: str | None = None
    course_title: str | None = None


WISDOM_CATALOG = CatalogSelectors(
    name="wisdom",
    item=".child-info.hasvideo",
    active=".child-info.hasvideo.current",
    finish=".child-check",
    title=".child-name",
    active_class="current",
    progress="[role='progressbar'][aria-valuenow]",
    progress_attribute="aria-valuenow",
    course_title=".course-name",
)

FUSION_CATALOG = CatalogSelectors(
    name="fusion",
    item=".chapter-content-second",
    active=".chapter-content-second.current",
    finish=".finish-icon",
    title=".item-name",
    active_class="current",
)

HIKE_CATALOG = CatalogSelectors(
    name="hike",
    item=".file-item",
    active=".file-item.active",
    finish=".icon-finish",
    title="span[title]",
    active_class="active",
    progress=".rate",
    course_title=".course-name",
)

LEGACY_CATALOG = CatalogSelectors(
    name="legacy",
    item=".clearfix.video",
    active=".clearfix.video.current_play",
    finish=".time_icofinish",
    title="#lessonOrder",
    active_class="current_play",
    progress=".progress-num",
    course_title=".source-name",
)

CATALOGS = (WISDOM_CATALOG, FUSION_CATALOG, HIKE_CATALOG, LEGACY_CATALOG)


def parse_progress_value(value) -> int:
    if isinstance(value, str):
        value = value.strip().removesuffix("%")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(number):
        return 0
    return max(0, min(int(number), 100))


def has_class(class_attr: str | None, class_name: str) -> bool:
    return class_name in (class_attr or "").split()


def catalog_candidates(course_url: str) -> tuple[CatalogSelectors, ...]:
    if "hike.zhihuishu.com" in course_url:
        return (HIKE_CATALOG,)
    if "fusioncourseh5" in course_url:
        return (FUSION_CATALOG, WISDOM_CATALOG, LEGACY_CATALOG)
    return (WISDOM_CATALOG, LEGACY_CATALOG, FUSION_CATALOG)


async def detect_catalog(
    page: Page, course_url: str = "", timeout_ms: int = 20_000
) -> CatalogSelectors:
    candidates = catalog_candidates(course_url or page.url)
    selector = ", ".join(catalog.item for catalog in candidates)
    try:
        await page.wait_for_selector(selector, state="attached", timeout=timeout_ms)
    except TimeoutError as exc:
        raise RuntimeError(
            "课程目录加载超时，未识别到新版、旧版或翻转课目录"
        ) from exc

    for catalog in candidates:
        if await page.locator(catalog.item).count() > 0:
            return catalog
    raise RuntimeError("课程目录结构无法识别")


async def lesson_progress(lesson: Locator, catalog: CatalogSelectors) -> int:
    if await lesson.locator(catalog.finish).count() > 0:
        return 100
    if not catalog.progress:
        return 0

    progress = lesson.locator(catalog.progress).first
    if await progress.count() == 0:
        return 0
    if catalog.progress_attribute:
        value = await progress.get_attribute(catalog.progress_attribute)
    else:
        value = await progress.text_content()
    return parse_progress_value(value)


async def lesson_is_complete(lesson: Locator, catalog: CatalogSelectors) -> bool:
    return await lesson_progress(lesson, catalog) >= 100


async def wait_for_lesson_completion(
    lesson: Locator, catalog: CatalogSelectors, timeout_ms: int = 5_000
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        if await lesson_is_complete(lesson, catalog):
            return True
        await asyncio.sleep(0.25)
    return False


async def wait_for_lesson_active(
    lesson: Locator, catalog: CatalogSelectors, timeout_ms: int = 8_000
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        if has_class(await lesson.get_attribute("class"), catalog.active_class):
            return True
        await asyncio.sleep(0.2)
    return False


async def get_lesson_title(
    page: Page, lesson: Locator, catalog: CatalogSelectors
) -> str:
    scoped = lesson.locator(catalog.title).first
    title_element = scoped if await scoped.count() else page.locator(catalog.title).first
    if await title_element.count():
        title = await title_element.get_attribute("title")
        if title:
            return title.strip()
        text = await title_element.text_content()
        if text:
            return " ".join(text.split())

    text = await lesson.text_content()
    return " ".join((text or "当前课时").split())
