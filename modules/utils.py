import traceback
from typing import List
from playwright.async_api import Page, Locator
from playwright.async_api import TimeoutError
from modules.configs import Config
import time
from modules.logger import Logger

logger = Logger()


async def evaluate_js(page: Page, js: str, wait_selector=None, timeout=None) -> None:
    try:
        if wait_selector:
            await page.wait_for_selector(wait_selector, timeout=timeout)
        await page.evaluate(js)
    except Exception as e:
        logger.write_log(f"Exec JS failed: {js} Selector:{wait_selector} Error:{repr(e)}\n")
        logger.write_log(traceback.format_exc())
        return


async def optimize_page(page: Page, config: Config, is_new_version=False) -> None:
    try:
        #await page.wait_for_load_state("domcontentloaded")
        await evaluate_js(page, config.pop_js, ".studytime-div", None)
        if not is_new_version:
            hour = time.localtime().tm_hour
            if hour >= 18 or hour < 7:
                await evaluate_js(page, config.night_js, ".Patternbtn-div", 1500)
            await evaluate_js(page, config.remove_assist, ".ai-show-icon.ai-icon-appear", 1500)
            await evaluate_js(page, config.no_ai_tip, ".aiMsg.once", 1500)
            await evaluate_js(page, config.no_ai_bot, ".ai-helper-Index2", 1500)
            await page.wait_for_selector(".exploreTip", timeout=1500)
            await evaluate_js(page, config.no_tip, 1500)
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


async def get_lesson_name(page: Page) -> str:
    title_ele = await page.wait_for_selector("#lessonOrder")
    await page.wait_for_timeout(500)
    title = await title_ele.get_attribute("title")
    return title


async def get_filtered_class(page: Page, is_new_version=False, include_all=False) -> List[Locator]:
    try:
        if is_new_version:
            await page.wait_for_selector(".progress-num", timeout=2000)
        else:
            await page.wait_for_selector(".time_icofinish", timeout=2000)
    except TimeoutError:
        pass
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
