# encoding=utf-8
import random
from playwright.async_api import Page, TimeoutError
from modules.lesson_navigation import (
    CatalogSelectors,
    lesson_progress,
    parse_progress_value,
)
from modules.logger import Logger

logger = Logger()


# 视频区域内移动鼠标
async def move_mouse(page: Page):
    try:
        await page.wait_for_selector(".videoArea", state="attached", timeout=5000)
        elem = page.locator(".videoArea")
        await elem.hover(timeout=4000)
        pos = await elem.bounding_box()
        if not pos:
            return
        # Calculate the target position to move the mouse
        target_x = pos['x'] + random.uniform(-10, 10)
        target_y = pos['y'] + random.uniform(-10, 10)
        await page.mouse.move(target_x, target_y)
    except TimeoutError:
        return


# 获取课程进度
async def get_course_progress(page: Page, catalog: CatalogSelectors) -> str:
    await move_mouse(page)
    current_lesson = page.locator(catalog.active).first
    if await current_lesson.count() == 0:
        return "0%"
    return f"{await lesson_progress(current_lesson, catalog)}%"


# 打印课程播放进度
def show_course_progress(desc, cur_time=None, limit_time=0):
    assert limit_time >= 0, "limit_time 必须为非负数!"
    if limit_time == 0:
        cur_time = "0%" if cur_time == '' or cur_time is None else cur_time
        percent = parse_progress_value(str(cur_time).rstrip("%"))
        length = int(percent * 30 // 100)
        progress = ("█" * length).ljust(30, " ")
        print(f"\r{desc} |{progress}| {percent}%\t".ljust(50), end="", flush=True)
    else:
        cur_time = 0 if cur_time == '' or cur_time is None else cur_time
        if isinstance(cur_time, str):
            cur_time = 0
        left_time = round(limit_time - cur_time, 1)
        percent = int(cur_time / limit_time * 100)
        if left_time <= 0:
            percent = 100
        percent = max(0, min(percent, 100))
        length = int(percent * 20 // 100)
        progress = ("█" * length).ljust(20, " ")
        print(f"\r{desc} |{progress}| {percent}%\t剩余 {left_time} min\t".ljust(50), end="", flush=True)


# 打印通用版进度条
def show_progress(desc, current, total, suffix="", width=30):
    percent = int(current / total * 100)
    length = int(percent * width // 100)
    progress = ("█" * length).ljust(width, " ")
    print(f"\r{desc} |{progress}| {percent}%\t{suffix}".ljust(50), end="", flush=True)
