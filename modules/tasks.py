import asyncio
from playwright.async_api import TimeoutError
from playwright.async_api import Page
from modules.configs import Config
from modules.utils import get_video_attr, display_window, hide_window
from modules.video_state import should_resume_paused_video
from playwright._impl._errors import TargetClosedError
from modules.logger import Logger

logger = Logger()


def is_expected_polling_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    message = str(exc)
    expected_signals = [
        "waiting for locator",
        "waiting for selector",
        "ElementHandle.press",
        "No node found for selector",
        "Execution context was destroyed",
    ]
    return any(signal in message for signal in expected_signals)


async def task_monitor(tasks: list[asyncio.Task]) -> None:
    checked_tasks = set()
    logger.info("任务监控已启动.")
    while any(not task.done() for task in tasks):
        for i, task in enumerate(tasks):
            if task.done() and task not in checked_tasks:
                checked_tasks.add(task)
                exc = task.exception()
                func_name = task.get_coro().__name__
                if exc is not None:
                    logger.log_exception(f"任务函数 {func_name} 出现异常.", exc, shift=True)
        await asyncio.sleep(1)
    logger.info("任务监控已退出.", shift=True)


async def video_optimize(page: Page, config: Config) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(2)
            await page.wait_for_selector("video", state="attached", timeout=3000)
            volume = await get_video_attr(page, "volume")
            rate = await get_video_attr(page, "playbackRate")
            if config.soundOff and volume != 0:
                await page.evaluate(config.volume_none)
                await page.evaluate(config.set_none_icon)
            if rate != config.limitSpeed:
                await page.evaluate(config.revise_speed)
                await page.evaluate(config.revise_speed_name)
        except TargetClosedError:
            logger.debug("浏览器已关闭, 视频调节模块停止运行.")
            return
        except Exception as e:
            if is_expected_polling_error(e):
                logger.debug(f"视频调节模块轮询未命中: {logger.summarize_exception(e)}")
            else:
                logger.log_exception("视频调节模块执行失败.", e)
            continue


async def play_video(page: Page) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(2)
            await page.wait_for_selector("video", state="attached", timeout=1000)
            paused = await page.evaluate("document.querySelector('video').paused")
            cur_time = await get_video_attr(page, "currentTime")
            duration = await get_video_attr(page, "duration")
            if should_resume_paused_video(paused, cur_time, duration):
                logger.info("检测到视频暂停,正在尝试播放.")
                await page.wait_for_selector(".videoArea", timeout=1000)
                await page.evaluate('document.querySelector("video").play();')
                logger.debug("视频已恢复播放.")
        except TargetClosedError:
            logger.debug("浏览器已关闭, 视频播放模块停止运行.")
            return
        except Exception as e:
            if is_expected_polling_error(e):
                logger.debug(f"视频播放模块轮询未命中: {logger.summarize_exception(e)}")
            else:
                logger.log_exception("视频播放模块执行失败.", e)
            continue


async def skip_questions(page: Page, event_loop) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            if "hike.zhihuishu.com" in page.url:
                logger.warn("当前课程为新版本,不支持自动答题.", shift=True)
                return
            await asyncio.sleep(2)
            ques_element = await page.wait_for_selector(".el-scrollbar__view", state="attached", timeout=1000)
            total_ques = await ques_element.query_selector_all(".number")
            if total_ques:
                logger.debug(f"检测到{len(total_ques)}道题目.")
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
            logger.debug("浏览器已关闭, 答题模块停止运行.")
            return
        except Exception as e:
            if is_expected_polling_error(e):
                logger.debug(f"答题模块轮询未命中: {logger.summarize_exception(e)}")
            else:
                logger.log_exception("答题模块执行失败.", e)
            if "fusioncourseh5" in page.url:
                not_finish_close = await page.query_selector(".el-dialog")
                if not_finish_close:
                    await page.press(".el-dialog", "Escape", timeout=1000)
            elif "hike.zhihuishu.com" in page.url:
                logger.warn("当前课程为新版本,不支持自动答题.", shift=True)
                return
            else:
                not_finish_close = await page.query_selector(".el-message-box__headerbtn")
                if not_finish_close:
                    await not_finish_close.click()
            continue


async def wait_for_verify(page: Page, config, event_loop) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(3)
            await page.wait_for_selector(".yidun_modal__title", state="attached", timeout=1000)
            logger.warn("检测到安全验证,请手动完成验证...", shift=True)
            if config.enableHideWindow:
                await display_window(page)
            await page.wait_for_selector(".yidun_modal__title", state="hidden", timeout=24 * 3600 * 1000)
            event_loop.set()
            if config.enableHideWindow:
                await hide_window(page)
            logger.info("安全验证已完成.", shift=True)
            await asyncio.sleep(30)  # 较长时间内不会再次触发验证
        except TargetClosedError:
            logger.debug("浏览器已关闭, 安全验证模块停止运行.")
            return
        except Exception as e:
            if is_expected_polling_error(e):
                logger.debug(f"安全验证模块轮询未命中: {logger.summarize_exception(e)}")
            else:
                logger.log_exception("安全验证模块执行失败.", e)
            continue
