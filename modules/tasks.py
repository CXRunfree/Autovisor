import asyncio
import time

from playwright.async_api import TimeoutError
from playwright.async_api import Page
from modules.configs import Config
from modules.utils import get_video_attr, display_window, hide_window, run_on
from playwright._impl._errors import TargetClosedError
from modules.logger import Logger
from modules.video_state import video_at_end

logger = Logger()

VERIFICATION_SELECTORS = (
    ".yidun_popup .yidun_modal",
    ".yidun_modal__title",
    "[id^='tcaptcha_transform']",
)

BLOCKING_OVERLAY_SELECTORS = (
    ".topic-title",
    ".ss2077-custom-dialog",
)


async def has_visible_element(page: Page, selectors: tuple[str, ...]) -> bool:
    for selector in selectors:
        try:
            visible = await page.locator(selector).evaluate_all(
                """elements => elements.some(element => {
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    const opacity = Number.parseFloat(style.opacity || "1");
                    return style.display !== "none" &&
                        style.visibility !== "hidden" &&
                        opacity > 0.05 &&
                        rect.width > 0 && rect.height > 0 &&
                        rect.bottom > 0 && rect.right > 0 &&
                        rect.top < innerHeight && rect.left < innerWidth;
                })"""
            )
            if visible:
                return True
        except TargetClosedError:
            raise
        except Exception as exc:
            logger.debug_throttled(
                "has_visible_element",
                f"可见元素检测遇到页面切换({', '.join(selectors)}): "
                f"{logger.summarize_exception(exc)}",
            )
    return False


async def has_visible_verification(page: Page) -> bool:
    return await has_visible_element(page, VERIFICATION_SELECTORS)


async def has_blocking_overlay(page: Page) -> bool:
    return await has_visible_verification(page) or await has_visible_element(
        page, BLOCKING_OVERLAY_SELECTORS
    )


async def wait_until_verification_hidden(page: Page) -> None:
    while await has_visible_verification(page):
        await asyncio.sleep(0.5)


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
            try:
                await page.wait_for_selector("video", state="attached", timeout=3000)
            except TimeoutError:
                logger.debug_throttled(
                    "video:optimize",
                    "视频调节跳过: 页面未找到元素 video",
                )
                continue
            volume = await get_video_attr(page, "volume")
            rate = await get_video_attr(page, "playbackRate")
            changes = []
            if config.soundOff and volume != 0:
                await run_on(page, "video", "(el) => { el.volume = 0; }", "设置静音")
                await run_on(
                    page,
                    ".volumeBox",
                    '(el) => el.classList.add("volumeNone")',
                    "更新静音图标",
                )
                changes.append(f"音量 {volume}->0")
            if rate != config.limitSpeed:
                await run_on(
                    page,
                    "video",
                    f"(el) => {{ el.playbackRate = {config.limitSpeed}; }}",
                    "设置倍速",
                )
                await run_on(
                    page,
                    ".speedBox span",
                    f'(el) => {{ el.innerText = "X {config.limitSpeed}"; }}',
                    "更新倍速标签",
                )
                changes.append(f"倍速 {rate}->{config.limitSpeed}")
            if changes:
                logger.event("播放器调节", 项目=", ".join(changes))
        except TargetClosedError:
            logger.debug("浏览器已关闭, 视频调节模块停止运行.")
            return
        except Exception as e:
            if is_expected_polling_error(e):
                logger.debug_throttled(
                    "video_optimize",
                    f"视频调节模块轮询未命中: {logger.summarize_exception(e)}",
                )
            else:
                logger.log_exception("视频调节模块执行失败.", e)
            continue


async def play_video(
    page: Page, playback_enabled: asyncio.Event | None = None
) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(2)
            try:
                await page.wait_for_selector("video", state="attached", timeout=1000)
            except TimeoutError:
                logger.debug_throttled(
                    "video:play",
                    "视频播放跳过: 页面未找到元素 video",
                )
                continue
            if playback_enabled is not None and not playback_enabled.is_set():
                paused = await run_on(
                    page, "video", "(el) => el.paused", "读取视频暂停状态"
                )
                if paused is False:
                    await run_on(page, "video", "(el) => el.pause()", "暂停视频")
                continue
            state = await run_on(
                page,
                "video",
                """(el) => ({
                    paused: el.paused,
                    ended: el.ended,
                    currentTime: el.currentTime,
                    duration: el.duration,
                })""",
                "读取播放器状态",
            )
            if state is None:
                continue
            paused = state["paused"]
            blocked = await has_blocking_overlay(page)
            if blocked:
                if not paused:
                    await run_on(page, "video", "(el) => el.pause()", "遮罩层暂停视频")
                    logger.info("检测到遮罩层,已暂停视频等待处理.")
                    logger.event("遮罩层暂停", 播放器时间=round(state["currentTime"], 1))
                continue
            at_end = state["ended"] or video_at_end(
                state["currentTime"], state["duration"]
            )
            if paused and not at_end:
                logger.info("检测到视频暂停,正在尝试播放.")
                try:
                    await page.wait_for_selector(".videoArea", timeout=1000)
                except TimeoutError:
                    logger.debug_throttled(
                        "videoArea",
                        "尝试播放跳过: 页面未找到元素 .videoArea",
                    )
                    continue
                await run_on(page, "video", "(el) => el.play()", "恢复播放")
                logger.debug("视频已恢复播放.")
                logger.event(
                    "恢复播放",
                    播放器时间=round(state["currentTime"], 1),
                    总时长=round(state["duration"], 1),
                )
        except TargetClosedError:
            logger.debug("浏览器已关闭, 视频播放模块停止运行.")
            return
        except Exception as e:
            if is_expected_polling_error(e):
                logger.debug_throttled(
                    "play_video",
                    f"视频播放模块轮询未命中: {logger.summarize_exception(e)}",
                )
            else:
                logger.log_exception("视频播放模块执行失败.", e)
            continue


async def skip_questions(page: Page, event_loop) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            if "studywisdomh5.zhihuishu.com" in page.url:
                await asyncio.sleep(2)
                if not await has_visible_element(page, (".topic-title",)):
                    continue
                logger.warn("检测到新版课中弹题,请在浏览器中手动处理.", shift=True)
                logger.event("新版课中弹题", 处理方式="手动", 地址=page.url)
                while await has_visible_element(page, (".topic-title",)):
                    await asyncio.sleep(0.5)
                event_loop.set()
                continue
            if "hike.zhihuishu.com" in page.url:
                logger.warn("当前课程为新版本,不支持自动答题.", shift=True)
                logger.event("答题", 结果="跳过", 原因="课程版本不支持")
                return
            await asyncio.sleep(2)
            ques_element = await page.wait_for_selector(".el-scrollbar__view", state="attached", timeout=1000)
            total_ques = await ques_element.query_selector_all(".number")
            if total_ques:
                answered = 0
                for ques in total_ques:
                    await ques.click(timeout=500)
                    if not await page.query_selector(".answer"):
                        choices = await page.query_selector_all(".topic-item")
                        for each in choices[:2]:
                            await each.click(timeout=500)
                            await page.wait_for_timeout(100)
                        answered += 1
                logger.event("课中答题", 题目数=len(total_ques), 已作答=answered)
            await page.press(".el-dialog", "Escape", timeout=1000)
            event_loop.set()
        except TargetClosedError:
            logger.debug("浏览器已关闭, 答题模块停止运行.")
            return
        except Exception as e:
            if is_expected_polling_error(e):
                logger.debug_throttled(
                    "skip_questions",
                    f"答题模块轮询未命中(元素 .el-scrollbar__view/.el-dialog): "
                    f"{logger.summarize_exception(e)}",
                )
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
            await asyncio.sleep(2)
            if not await has_visible_verification(page):
                continue
            event_loop.clear()
            logger.warn("检测到安全验证,请手动完成验证...", shift=True)
            logger.event("安全验证", 状态="开始", 地址=page.url)
            wait_start = time.time()
            if config.enableHideWindow:
                await display_window(page)
            await wait_until_verification_hidden(page)
            event_loop.set()
            if config.enableHideWindow:
                await hide_window(page)
            logger.info("安全验证已完成.", shift=True)
            logger.event("安全验证", 状态="完成", 耗时=f"{time.time() - wait_start:.1f}s")
            await asyncio.sleep(2)
        except TargetClosedError:
            logger.debug("浏览器已关闭, 安全验证模块停止运行.")
            return
        except Exception as e:
            if is_expected_polling_error(e):
                logger.debug_throttled(
                    "wait_for_verify",
                    f"安全验证模块轮询未命中(元素 .yidun_modal/.yidun_popup/tcaptcha): "
                    f"{logger.summarize_exception(e)}",
                )
            else:
                logger.log_exception("安全验证模块执行失败.", e)
            continue
