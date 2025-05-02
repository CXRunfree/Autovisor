import ctypes
import json
import os.path
import traceback
from typing import List
from playwright.async_api import Page, Locator, BrowserContext
from playwright.async_api import TimeoutError
from pygetwindow import Win32Window

from modules.configs import Config
import time
import pygetwindow as gw
from modules.logger import Logger
from preview.modules import quark

logger = Logger()


# 将python终端前置
def bring_console_to_front():
    # 获取当前控制台窗口句柄
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
        ctypes.windll.user32.SetForegroundWindow(hwnd)


async def get_quark_ticket(context: BrowserContext):
    os.makedirs("res/", exist_ok=True)
    if os.path.exists("res/userdata.json"):
        with open("res/userdata.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            ticket = data.get("service_ticket")
            if not ticket:
                ticket = await quark.login(context)
    else:
        ticket = await quark.login(context)
        data = {"service_ticket": ticket}
        with open("res/userdata.json", "w", encoding="utf-8") as f:
            json.dump(data, f)
    return ticket


async def display_window(page: Page) -> None:
    window = await get_browser_window(page)
    if window:
        window.moveTo(100, 100)
        logger.info("播放窗口已自动前置.", shift=True)
    else:
        logger.warn("未找到播放窗口!")


async def hide_window(page: Page) -> None:
    window = await get_browser_window(page)
    if window:
        window.moveTo(-3200, -3200)
        logger.info("播放窗口已自动隐藏.")
    else:
        logger.warn("未找到播放窗口!")


async def get_browser_window(page: Page) -> Win32Window | None:
    custom_title = "Autovisor - Playwright"
    await page.wait_for_load_state("domcontentloaded")
    await page.evaluate(f'document.title = "{custom_title}"')
    # 获取所有窗口并尝试匹配 Playwright 窗口
    await page.wait_for_timeout(1000)
    win_list = gw.getWindowsWithTitle(custom_title)
    if win_list:
        return win_list[0]
    else:
        return None


async def evaluate_js(page: Page, wait_selector, js: str, timeout=None, is_hike_class=False) -> None:
    try:
        if wait_selector and is_hike_class is False:
            await page.wait_for_selector(wait_selector, timeout=timeout)
        if is_hike_class is False:
            await page.evaluate(js)
    except Exception as e:
        logger.write_log(f"Exec JS failed: {js} Selector:{wait_selector} Error:{repr(e)}\n")
        logger.write_log(traceback.format_exc())
        return


async def evaluate_on_element(page: Page, selector: str, js: str, timeout: float = None,
                              is_hike_class=False) -> None:
    try:
        if selector and is_hike_class is False:
            element = page.locator(selector).first
            await element.evaluate(js, timeout=timeout)
    except Exception as e:
        logger.write_log(f"Exec JS failed: Selector:{selector} JS:{js} Error:{repr(e)}\n")
        logger.write_log(traceback.format_exc())
        return


async def optimize_page(page: Page, config: Config, is_new_version=False, is_hike_class=False) -> None:
    try:
        #await page.wait_for_load_state("domcontentloaded")
        await evaluate_js(page, ".studytime-div", config.pop_js, None, is_hike_class)
        if not is_new_version:
            if not is_hike_class:
                hour = time.localtime().tm_hour
                if hour >= 18 or hour < 7:
                    await evaluate_on_element(page, ".Patternbtn-div", "el=>el.click()", timeout=1500)
                await evaluate_on_element(page, ".exploreTip", "el=>el.remove()", timeout=1500)
                await evaluate_on_element(page, ".ai-helper-Index2", "el=>el.remove()", timeout=1500)
                await evaluate_on_element(page, ".aiMsg.once", "el=>el.remove()", timeout=1500)
                logger.info("页面优化完成!")

    except Exception as e:
        logger.write_log(f"Exec optimize_page failed. Error:{repr(e)}\n")
        logger.write_log(traceback.format_exc())
        return


async def get_video_attr(page, attr: str) -> any:
    try:
        await page.wait_for_selector("video", state="attached", timeout=1000)
        attr = await page.evaluate(f'''document.querySelector('video').{attr}''')
        return attr
    except Exception as e:
        logger.write_log(f"Exec get_video_attr failed. Error:{repr(e)}\n")
        logger.write_log(traceback.format_exc())
        return None


async def get_lesson_name(page: Page, is_hike_class=False) -> str:
    if is_hike_class:
        title_ele1 = await page.wait_for_selector("#sourceTit")
        title_ele = await page.wait_for_selector("span")
        await page.wait_for_timeout(500)
        title = await title_ele.get_attribute("title")
    else:
        title_ele = await page.wait_for_selector("#lessonOrder")
        await page.wait_for_timeout(500)
        title = await title_ele.get_attribute("title")
    return title


async def get_filtered_class(page: Page, is_new_version=False, is_hike_class=False, include_all=False) -> List[Locator]:
    try:
        if is_new_version:
            await page.wait_for_selector(".progress-num", timeout=2000)
        if is_hike_class:
            await page.wait_for_selector(".icon-finish", timeout=2000)
        else:
            await page.wait_for_selector(".time_icofinish", timeout=2000)
    except TimeoutError:
        pass

    if is_hike_class:
        all_class = await page.locator(".file-item").all()
        if include_all:
            pass
            # logger.write_log(f"Get to-review class: {len(all_class)}\n")
            # return all_class
        else:
            to_learn_class = []
            for each in all_class:
                isDone = await each.locator(".icon-finish").count()
                if not isDone:
                    to_learn_class.append(each)
            logger.write_log(f"Get to-learn class: {len(all_class)}\n")
            return to_learn_class

    else:
        all_class = await page.locator(".clearfix.video").all()
        if include_all:
            logger.write_log(f"Get to-review class: {len(all_class)}\n")
            return all_class
        else:
            to_learn_class = []
            for each in all_class:
                if is_new_version:
                    progress = await each.locator(".progress-num").text_content()
                    isDone = progress == "100%"
                else:
                    isDone = await each.locator(".time_icofinish").count()
                if not isDone:
                    to_learn_class.append(each)
            logger.write_log(f"Get to-learn class: {len(all_class)}\n")
            return to_learn_class
