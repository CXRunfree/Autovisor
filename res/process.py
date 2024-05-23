# encoding=utf-8
from playwright._impl._errors import TimeoutError
from playwright.sync_api import Page


def move_mouse(page: Page):
    try:
        page.wait_for_selector(".videoArea", state="attached", timeout=5000)
        elem = page.locator(".videoArea")
        elem.hover(timeout=4000)
        pos = elem.bounding_box()
        if not pos:
            return
        # 计算移动的目标位置
        target_x = pos['x'] + 30
        target_y = pos['y'] + 30
        page.mouse.move(target_x, target_y)
    except TimeoutError:
        return


def get_progress(page: Page):
    def parse_time(h, m, s):
        return int(h) * 3600 + int(m) * 60 + int(s)

    curtime = "0%"
    move_mouse(page)
    cur_play = page.query_selector(".current_play")
    progress = cur_play.query_selector(".progress-num")
    total_time_str = cur_play.query_selector(".time.fl").text_content()
    total_time = parse_time(*total_time_str.split(":"))
    if not progress:
        finish = cur_play.query_selector(".time_icofinish")
        if finish:
            curtime = "100%"
    else:
        curtime = progress.text_content()

    return curtime, total_time


def show_progress(desc, cur_str=None, enableRepeat=False):
    percent = int(cur_str.split("%")[0])
    if percent >= 80 and not enableRepeat:  # 学习模式下,80%进度即为完成
        percent = 100
    length = int(percent * 30 // 100)
    progress = ("█" * length).ljust(30, " ")
    percent = str(percent) + "%"
    print(f"\r{desc} |{progress}| {percent}\t", end="", flush=True)
