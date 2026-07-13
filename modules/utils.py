import json
import os
import os.path
import sys
import tempfile
from playwright.async_api import Page, Locator
from playwright.async_api import TimeoutError
from playwright._impl._errors import TargetClosedError
from modules.configs import Config
from modules.lesson_navigation import (
    CatalogSelectors,
    get_lesson_title,
    lesson_is_complete,
)
import time
from modules.logger import Logger

if sys.platform == "win32":
    import ctypes
    import pygetwindow as gw
    from pygetwindow import Win32Window
else:
    ctypes = None
    gw = None
    Win32Window = object

logger = Logger()


def get_runtime_root():
    return logger.runtime_root


def get_runtime_path(*parts):
    return os.path.join(get_runtime_root(), *parts)

def save_cookies(cookies, filename="cookies.json"):
    """保存登录Cookies到文件"""
    filename = os.fspath(filename)
    directory = os.path.dirname(os.path.abspath(filename))
    fd, temp_path = tempfile.mkstemp(prefix=".cookies-", dir=directory)
    try:
        if os.name != "nt":
            os.chmod(temp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(cookies, file)
        os.replace(temp_path, filename)
        if os.name != "nt":
            os.chmod(filename, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

def load_cookies(filename="cookies.json"):
    """从文件加载 Cookies"""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def normalize_zhihuishu_cookies(cookies, now=None):
    now = time.time() if now is None else now
    normalized = []
    for cookie in cookies:
        domain = str(cookie.get("domain") or "").strip()
        normalized_domain = domain.lstrip(".").lower()
        name = str(cookie.get("name") or "").strip()
        valid_domain = normalized_domain == "zhihuishu.com" or normalized_domain.endswith(
            ".zhihuishu.com"
        )
        if not name or not valid_domain:
            continue
        expires = cookie.get("expires", cookie.get("expirationDate"))
        if isinstance(expires, (int, float)) and expires > 0 and expires <= now:
            continue
        item = {
            "name": name,
            "value": str(cookie.get("value") or ""),
            "domain": domain,
            "path": cookie.get("path") or "/",
            "secure": bool(cookie.get("secure", False)),
        }
        if isinstance(expires, (int, float)) and expires > now:
            item["expires"] = float(expires)
        rest = cookie.get("rest") or {}
        if rest.get("HttpOnly") is True or cookie.get("httpOnly") is True:
            item["httpOnly"] = True
        same_site = rest.get("SameSite") or cookie.get("sameSite")
        if same_site in {"Strict", "Lax", "None"}:
            item["sameSite"] = same_site
        normalized.append(item)
    return normalized


def import_zhihuishu_cookies(source, destination="cookies.json") -> int:
    with open(source, "r", encoding="utf-8") as file:
        raw = json.load(file)
    if not isinstance(raw, list):
        raise ValueError("Cookie 文件必须是列表格式")
    cookies = normalize_zhihuishu_cookies(raw)
    if not cookies:
        raise ValueError("Cookie 文件中没有可用的智慧树 Cookie")
    save_cookies(cookies, destination)
    return len(cookies)


def clear_cookies(filename="cookies.json"):
    if os.path.exists(filename):
        os.remove(filename)

# 将python终端前置
def bring_console_to_front():
    if sys.platform != "win32":
        return False
    # 获取当前控制台窗口句柄
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        return True
    return False


async def display_window(page: Page) -> None:
    if sys.platform != "win32":
        await page.bring_to_front()
        logger.info("播放标签页已前置.", shift=True)
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
    if sys.platform != "win32":
        logger.warn("macOS 不支持隐藏单个 Chrome 窗口,将保持可见以便处理验证.")
        return
    window = await get_browser_window(page)
    if window:
        window.hide()
        logger.info("播放窗口已自动隐藏,将在需要安全验证时显示.")
    else:
        logger.warn("未找到播放窗口!")


async def get_browser_window(page: Page) -> object | None:
    if sys.platform != "win32":
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
    except Exception as e:
        logger.log_exception(f"执行元素脚本失败. Selector: {selector} JS: {js}", e)
        return


async def optimize_page(
    page: Page, config: Config, catalog: CatalogSelectors
) -> None:
    try:
        preread_close = page.locator(
            ".ss2077-custom-modal .ss2077-custom-dialog:visible "
            ".ss2077-custom-title > img.icon"
        ).first
        if await preread_close.count() and await preread_close.is_visible():
            await preread_close.click(timeout=2000)
            logger.info("已关闭学前必读弹窗.")

        if catalog.name == "legacy":
            await evaluate_js(page, ".studytime-div", config.pop_js)
            hour = time.localtime().tm_hour
            if hour >= 18 or hour < 7:
                await evaluate_on_element(page, ".Patternbtn-div", "el=>el.click()", timeout=1500)
            await evaluate_on_element(page, ".exploreTip", "el=>el.remove()", timeout=1500)
            await evaluate_on_element(page, ".ai-helper-Index2", "el=>el.remove()", timeout=1500)
            await evaluate_on_element(page, ".aiMsg.once", "el=>el.remove()", timeout=1500)

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


async def get_lesson_name(
    page: Page, lesson: Locator, catalog: CatalogSelectors
) -> str:
    return await get_lesson_title(page, lesson, catalog)


async def get_filtered_class(
    page: Page, catalog: CatalogSelectors, include_all=False
) -> list[Locator]:
    try:
        await page.wait_for_selector(catalog.item, timeout=2000)
    except TimeoutError:
        pass

    all_class = await page.locator(catalog.item).all()
    if include_all:
        logger.debug(f"Get to-review class: {len(all_class)}")
        return all_class

    to_learn_class = []
    for each in all_class:
        if not await lesson_is_complete(each, catalog):
            to_learn_class.append(each)
    logger.debug(f"Get to-learn class: {len(to_learn_class)} / {len(all_class)}")
    return to_learn_class
