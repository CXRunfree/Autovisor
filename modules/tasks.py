import asyncio
import random
import time
from playwright.async_api import TimeoutError
from playwright.async_api import Page
from modules.configs import Config
from modules.utils import get_video_attr, display_window, hide_window
from playwright._impl._errors import TargetClosedError
from modules.logger import Logger

logger = Logger()

# ========== 恢复/看门狗机制 ==========

STALL_TIMEOUT = 60       # 进度冻结阈值（秒）
RECOVERY_LEVELS = ["reclick", "reload", "skip"]


async def progress_watchdog(
    page: Page,
    progress_queue: asyncio.Queue,
    recovery_event: asyncio.Event,
    stall_timeout: float = STALL_TIMEOUT,
) -> None:
    """
    进度看门狗 — 监听进度队列，如果超过 stall_timeout 秒没有任何进度变化，
    则触发 recovery_event 通知主循环执行恢复操作。

    同时监控页面异常状态（对话框/JS错误/白屏）。
    """
    last_progress = None
    last_update_time = time.monotonic()
    logger.info(f"进度看门狗已启动, 冻结阈值: {stall_timeout}s")

    while True:
        try:
            # 从队列获取进度更新，超时 = stall_timeout 秒无更新即触发恢复
            try:
                progress_val = await asyncio.wait_for(
                    progress_queue.get(), timeout=stall_timeout
                )
                if progress_val != last_progress:
                    last_progress = progress_val
                    last_update_time = time.monotonic()
                # 同一进度值连续出现不算更新
            except asyncio.TimeoutError:
                # --- 长时间无进度更新 → 触发恢复 ---
                logger.warn(
                    f"检测到进度冻结(>{stall_timeout}s 无进度变化), 准备恢复...",
                    shift=True,
                )
                recovery_event.set()
                # 等待主循环处理完恢复（最多等 20 秒）
                await asyncio.sleep(20)
                recovery_event.clear()
                # 更新基准时间，避免连环触发
                last_update_time = time.monotonic()

            # --- 额外检查：页面是否出现异常对话框 ---
            try:
                if await page.locator(".el-message-box__wrapper").is_visible(timeout=200):
                    logger.warn("检测到异常弹窗, 触发恢复流程.", shift=True)
                    recovery_event.set()
                    await asyncio.sleep(20)
                    recovery_event.clear()
                    last_update_time = time.monotonic()
            except Exception:
                pass

        except TargetClosedError:
            logger.debug("浏览器已关闭, 进度看门狗停止运行.")
            return
        except Exception as e:
            logger.log_exception("进度看门狗异常.", e)
            await asyncio.sleep(5)
            continue


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


async def play_video(page: Page, config=None) -> None:
    import random
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            # 轮询间隔拉长 — 主要靠页面内 setInterval(300ms) 自动恢复
            await asyncio.sleep(random.uniform(5.0, 8.0))
            await page.wait_for_selector("video", state="attached", timeout=1000)
            paused = await page.evaluate("document.querySelector('video').paused")
            if paused:
                logger.info("检测到视频暂停,正在尝试播放.")
                await page.wait_for_selector(".videoArea", timeout=1000)
                await page.evaluate('document.querySelector("video").play();')
                logger.debug("视频已恢复播放.")
            # 随机在视频区域移动鼠标，模拟用户活动
            try:
                elem = page.locator(".videoArea")
                box = await elem.bounding_box(timeout=500)
                if box:
                    rx = box['x'] + box['width'] * random.uniform(0.1, 0.9)
                    ry = box['y'] + box['height'] * random.uniform(0.1, 0.9)
                    await page.mouse.move(rx, ry)
            except Exception:
                pass
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
