import json
import os
import os.path
import platform
from typing import List
from playwright.async_api import Page, Locator
from playwright.async_api import TimeoutError
from playwright._impl._errors import TargetClosedError

from modules.configs import Config
from modules.lesson_navigation import get_catalog_selectors
import time
from modules.logger import Logger

logger = Logger()

try:
    import ctypes
except ImportError:
    ctypes = None

try:
    import pygetwindow as gw
    from pygetwindow import Win32Window
except ImportError:
    gw = None
    Win32Window = object


def get_runtime_root():
    return logger.runtime_root


def get_runtime_path(*parts):
    return os.path.join(get_runtime_root(), *parts)


def supports_window_control():
    return platform.system() == "Windows" and gw is not None

def save_cookies(cookies, filename="cookies.json"):
    """保存登录Cookies到文件"""
    with open(filename, 'w') as f:
        json.dump(cookies, f)

def load_cookies(filename="cookies.json"):
    """从文件加载 Cookies"""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def clear_cookies(filename="cookies.json"):
    if os.path.exists(filename):
        os.remove(filename)

# 将python终端前置
def bring_console_to_front():
    if not supports_window_control() or ctypes is None or not hasattr(ctypes, "windll"):
        logger.warn("当前系统不支持自动前置控制台窗口,已跳过.")
        return
    # 获取当前控制台窗口句柄
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
        ctypes.windll.user32.SetForegroundWindow(hwnd)


async def display_window(page: Page) -> None:
    if not supports_window_control():
        logger.warn("当前系统不支持自动显示播放窗口,请手动切换到浏览器.")
        return
    window = await get_browser_window(page)
    if window:
        window.show()
        window.restore()
        window.moveTo(100, 100)
        logger.info("播放窗口已自动前置.", shift=True)
    else:
        logger.warn("未找到播放窗口!")


async def hide_window(page: Page) -> None:
    if not supports_window_control():
        logger.warn("当前系统不支持自动隐藏播放窗口,已跳过.")
        return
    window = await get_browser_window(page)
    if window:
        window.hide()
        logger.info("播放窗口已自动隐藏,将在需要安全验证时显示.")
    else:
        logger.warn("未找到播放窗口!")


async def get_browser_window(page: Page) -> Win32Window | None:
    if not supports_window_control():
        return None
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
    except TargetClosedError as e:
        logger.debug(f"浏览器关闭时停止执行页面脚本: {logger.summarize_exception(e)}")
        return
    except TimeoutError as e:
        logger.debug(f"页面脚本等待选择器超时,已跳过. Selector: {wait_selector} {logger.summarize_exception(e)}")
        return
    except Exception as e:
        logger.log_exception(f"执行页面脚本失败. Selector: {wait_selector} JS: {js}", e)
        return


async def evaluate_on_element(page: Page, selector: str, js: str, timeout: float = None,
                              is_hike_class=False) -> None:
    try:
        if selector and is_hike_class is False:
            element = page.locator(selector).first
            await element.evaluate(js, timeout=timeout)
    except TargetClosedError as e:
        logger.debug(f"浏览器关闭时停止执行元素脚本: {logger.summarize_exception(e)}")
        return
    except TimeoutError as e:
        logger.debug(f"元素脚本等待选择器超时,已跳过. Selector: {selector} {logger.summarize_exception(e)}")
        return
    except Exception as e:
        logger.log_exception(f"执行元素脚本失败. Selector: {selector} JS: {js}", e)
        return


async def optimize_page(page: Page, config: Config, is_new_version=False, is_hike_class=False) -> None:
    try:
        #await page.wait_for_load_state("domcontentloaded")
        await evaluate_js(page, ".studytime-div", config.pop_js, 1500, is_hike_class)
        if not is_new_version:
            if not is_hike_class:
                hour = time.localtime().tm_hour
                if hour >= 18 or hour < 7:
                    await evaluate_on_element(page, ".Patternbtn-div", "el=>el.click()", timeout=1500)
                await evaluate_on_element(page, ".exploreTip", "el=>el.remove()", timeout=1500)
                await evaluate_on_element(page, ".ai-helper-Index2", "el=>el.remove()", timeout=1500)
                await evaluate_on_element(page, ".aiMsg.once", "el=>el.remove()", timeout=1500)
                logger.info("页面优化完成!")

    except TargetClosedError as e:
        logger.debug(f"浏览器关闭时停止页面优化: {logger.summarize_exception(e)}")
        return
    except Exception as e:
        logger.log_exception("页面优化失败.", e)
        return


async def get_video_attr(page, attr: str) -> any:
    try:
        await page.wait_for_selector("video", state="attached", timeout=1000)
        attr = await page.evaluate(f'''document.querySelector('video').{attr}''')
        return attr
    except TargetClosedError as e:
        logger.debug(f"浏览器关闭时停止读取视频属性 {attr}: {logger.summarize_exception(e)}")
        return None
    except Exception as e:
        logger.log_exception(f"读取视频属性失败. attr: {attr}", e)
        return None


async def get_optional_text(page: Page, selector: str, timeout=2000) -> str | None:
    try:
        element = await page.wait_for_selector(selector, timeout=timeout)
        return await element.text_content()
    except TimeoutError:
        logger.debug(f"读取可选文本超时,已跳过. Selector: {selector}")
        return None
    except TargetClosedError as e:
        logger.debug(f"浏览器关闭时停止读取可选文本: {logger.summarize_exception(e)}")
        return None
    except Exception as e:
        logger.log_exception(f"读取可选文本失败. Selector: {selector}", e)
        return None


async def get_lesson_name(page: Page, is_hike_class=False, is_new_version=False) -> str:
    if is_new_version:
        title = await get_optional_text(page, ".chapter-content-second.current .item-name", timeout=1000)
        if title:
            return title.strip()
        title = await get_optional_text(page, ".chapter-content-second.current", timeout=1000)
        if title:
            return " ".join(title.split())
        return "当前课时"
    if is_hike_class:
        #title_ele1 = await page.wait_for_selector("#sourceTit")
        title_ele = await page.wait_for_selector("span")
        await page.wait_for_timeout(500)
        title = await title_ele.get_attribute("title")
    else:
        title_ele = await page.wait_for_selector("#lessonOrder")
        await page.wait_for_timeout(500)
        title = await title_ele.get_attribute("title")
    return title


async def get_filtered_class(page: Page, is_new_version=False, is_hike_class=False, include_all=False) -> List[Locator]:
    selectors = get_catalog_selectors(is_new_version, is_hike_class)
    try:
        await page.wait_for_selector(selectors.item, timeout=2000)
    except TimeoutError:
        pass

    if is_hike_class:
        all_class = await page.locator(selectors.item).all()
        if include_all:
            pass
            # logger.debug(f"Get to-review class: {len(all_class)}")
            # return all_class
        else:
            to_learn_class = []
            for each in all_class:
                isDone = await each.locator(selectors.finish).count()
                if not isDone:
                    to_learn_class.append(each)
            logger.debug(f"Get to-learn class: {len(to_learn_class)}")
            return to_learn_class

    else:
        all_class = await page.locator(selectors.item).all()
        if include_all:
            logger.debug(f"Get to-review class: {len(all_class)}")
            return all_class
        else:
            to_learn_class = []
            for each in all_class:
                if is_new_version and not await each.is_visible():
                    continue
                if is_new_version:
                    isDone = await each.locator(selectors.finish).count()
                else:
                    isDone = await each.locator(selectors.finish).count()
                if not isDone:
                    to_learn_class.append(each)
            logger.debug(f"Get to-learn class: {len(to_learn_class)}")
            return to_learn_class
