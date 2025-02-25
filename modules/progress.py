# encoding=utf-8
import random
from playwright.async_api import Page, TimeoutError
from modules.utils import get_video_attr


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
async def get_course_progress(page: Page, is_new_version=False):
    curtime = "0%"
    await move_mouse(page)
    cur_play = await page.query_selector(".current_play")
    progress = await cur_play.query_selector(".progress-num")
    if not progress:
        if is_new_version:
            progress_ele = await cur_play.query_selector(".progress-num")
            progress = await progress_ele.text_content()
            finish = progress == "100%"
        else:
            finish = await cur_play.query_selector(".time_icofinish")
        if finish:
            curtime = "100%"
    else:
        curtime = await progress.text_content()

    return curtime


# 打印课程播放进度
def show_course_progress(desc, cur_time=None, limit_time=0):
    assert limit_time >= 0, "limit_time 必须为非负数!"
    if limit_time == 0:
        cur_time = "0%" if cur_time == '' else cur_time
        percent = int(cur_time.split("%")[0]) + 1  # Handles a 1% rendering error
        if percent >= 80:  # In learning mode, 80% progress is considered complete
            percent = 100
        length = int(percent * 30 // 100)
        progress = ("█" * length).ljust(30, " ")
        print(f"\r{desc} |{progress}| {percent}%\t", end="", flush=True)
    else:
        cur_time = 0 if cur_time == '' else cur_time
        left_time = round(limit_time - cur_time, 1)
        percent = int(cur_time / limit_time * 100)
        if left_time <= 0:
            percent = 100
        length = int(percent * 20 // 100)
        progress = ("█" * length).ljust(20, " ")
        print(f"\r{desc} |{progress}| {percent}%\t剩余 {left_time} min\t", end="", flush=True)


# 打印通用版进度条
def show_progress(desc, current, total, suffix="", width=30):
    percent = int(current / total * 100)
    length = int(percent * width // 100)
    progress = ("█" * length).ljust(width, " ")
    print(f"\r{desc} |{progress}| {percent}%\t{suffix}", end="", flush=True)
