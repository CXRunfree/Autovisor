import asyncio
from playwright.async_api import Page
from res.configs import Config
from res.utils import get_video_attr
from playwright._impl._errors import TargetClosedError

async def video_optimize(page: Page, config: Config) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(1)
            await page.wait_for_selector("video", state="attached", timeout=3000)
            if await get_video_attr(page, "volume") != 0:
                await page.evaluate(config.volume_none)
                await page.evaluate(config.set_none_icon)
                print("[Info]视频已静音.")
            if await get_video_attr(page, "playbackRate") != config.limitSpeed:
                await page.evaluate(config.revise_speed)
                await page.evaluate(config.revise_speed_name)
                print(f"[Info]视频已修改为{config.limitSpeed}倍速.")
        except TargetClosedError:
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
                print("\n[Info]检测到视频暂停,正在尝试播放...")
                await page.wait_for_selector(".videoArea", timeout=1000)
                await page.evaluate('document.querySelector("video").play();')
                print("[Info]视频已恢复播放.")
        except TargetClosedError:
            return
        except Exception as e:
            continue


async def skip_questions(page: Page, event_loop) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(0.5)
            await page.wait_for_selector(".el-dialog", state="attached", timeout=1000)
            total_ques = await page.query_selector_all(".number")
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
            return
        except Exception as e:
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
            print("\n[Warn]检测到安全验证,请手动点击完成...")
            await page.wait_for_selector(".yidun_modal__title", state="hidden", timeout=24 * 3600 * 1000)
            event_loop.set()
            print("\n[Info]安全验证已完成,继续播放...")
        except TargetClosedError:
            return
        except Exception as e:
            continue