import asyncio
from playwright.async_api import Page
from modules.configs import Config
from modules.utils import get_video_attr
from playwright._impl._errors import TargetClosedError
from modules.logger import Logger

logger = Logger()

async def video_optimize(page: Page, config: Config) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(2)
            await page.wait_for_selector("video", state="attached", timeout=3000)
            volume = await get_video_attr(page, "volume")
            rate = await get_video_attr(page, "playbackRate")
            if volume != 0:
                await page.evaluate(config.volume_none)
                await page.evaluate(config.set_none_icon)
            if rate != config.limitSpeed:
                await page.evaluate(config.revise_speed)
                await page.evaluate(config.revise_speed_name)
        except TargetClosedError:
            logger.write_log("浏览器已关闭,视频调节模块已下线.\n")
            return
        except Exception as e:
            continue


async def play_video(page: Page) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(1)
            await page.wait_for_selector("video", state="attached", timeout=1000)
            paused = await page.evaluate("document.querySelector('video').paused")
            if paused:
                logger.info("检测到视频暂停,正在尝试播放.")
                await page.wait_for_selector(".videoArea", timeout=1000)
                await page.evaluate('document.querySelector("video").play();')
                logger.write_log("视频已恢复播放.\n")
        except TargetClosedError:
            logger.write_log("浏览器已关闭,视频播放模块已下线.\n")
            return
        except Exception as e:
            continue


async def skip_questions(page: Page, event_loop) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(0.7)
            await page.wait_for_selector(".el-dialog", state="attached", timeout=1000)
            total_ques = await page.query_selector_all(".number")
            if total_ques:
                logger.write_log(f"检测到{len(total_ques)}道题目.\n")
            for ques in total_ques:
                await ques.click(timeout=500)
                if not await page.query_selector(".answer"):
                    choices = await page.query_selector_all(".topic-item")
                    for each in choices[:2]:
                        await each.click(timeout=500)
                        await page.wait_for_timeout(100)
            await page.press(".el-dialog", "Escape", timeout=1000)
            event_loop.set()
        except TargetClosedError:
            logger.write_log("浏览器已关闭,答题模块已下线.\n")
            return
        except Exception as e:
            if "fusioncourseh5" in page.url:
                not_finish_close = await page.query_selector(".el-dialog")
                if not_finish_close:
                    await page.press(".el-dialog", "Escape", timeout=1000)
            else:
                not_finish_close = await page.query_selector(".el-message-box__headerbtn")
                if not_finish_close:
                    await not_finish_close.click()
            continue


async def wait_for_verify(page: Page, event_loop) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(3)
            await page.wait_for_selector(".yidun_modal__title", state="attached", timeout=1000)
            logger.warn("检测到安全验证,请手动完成验证...", line_break=True)
            await page.wait_for_selector(".yidun_modal__title", state="hidden", timeout=24 * 3600 * 1000)
            event_loop.set()
            logger.info("安全验证已完成.", line_break=True)
            await asyncio.sleep(30)  # 较长时间内不会再次触发验证
        except TargetClosedError:
            logger.write_log("浏览器已关闭,安全验证模块已下线.\n")
            return
        except Exception as e:
            continue
