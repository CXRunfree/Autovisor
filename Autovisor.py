# encoding=utf-8
import asyncio
import os
import time
import traceback
import sys
from playwright.async_api import async_playwright, Playwright, Page, BrowserContext
from playwright.async_api import TimeoutError
from playwright._impl._errors import TargetClosedError
from modules.logger import Logger
from modules.configs import Config
from modules.progress import get_course_progress, show_course_progress
from modules.support import show_donate
from modules.utils import optimize_page, get_lesson_name, get_filtered_class, get_video_attr, get_optional_text, hide_window, \
     save_cookies, load_cookies, clear_cookies, get_runtime_path
from modules.slider import slider_verify
from modules.tasks import video_optimize, play_video, skip_questions, wait_for_verify, task_monitor
from modules import installer
from modules.banner import print_banner
from modules.browser import get_effective_driver, resolve_browser_channel, resolve_executable_path
from modules.lesson_navigation import course_is_complete, get_active_class, get_catalog_selectors, has_class, is_finished, \
     next_lesson_index, parse_progress_value
from modules.video_state import completion_settle_ms, is_video_complete, replay_from_time, should_refresh_video_duration, \
     time_from_percent, video_percent

# 获取全局事件循环
event_loop_verify = asyncio.Event()
event_loop_answer = asyncio.Event()
COOKIE_PATH = get_runtime_path("res", "cookies.json")


async def wait_for_interruption(event_loop: asyncio.Event) -> float:
    event_loop.clear()
    wait_start = time.time()
    await event_loop.wait()
    return time.time() - wait_start


def cal_time_period(start_time: float, paused_time: float) -> float:
    return max(0.0, time.time() - start_time - paused_time)


async def init_page(p: Playwright, cookies) -> tuple[Page, BrowserContext]:
    driver = get_effective_driver(config.driver)
    browser_channel = resolve_browser_channel(driver)
    logger.info(f"正在启动{driver}浏览器...")
    launch_args = {
        "headless": False,
        "executable_path": resolve_executable_path(driver, config.exe_path),
        "args": [
            f'--window-size={1600},{900}',
            '--window-position=100,100',  # 窗口位置
        ],
    }
    if browser_channel:
        launch_args["channel"] = browser_channel
    try:
        browser = await p.chromium.launch(**launch_args)
    except TargetClosedError as e:
        logger.log_exception("首次启动浏览器失败,准备重试.", e)
        logger.info("检测到浏览器首次启动失败,正在重试...")
        await asyncio.sleep(1)
        browser = await p.chromium.launch(**launch_args)
    context = await browser.new_context()
    # 加载 Cookies
    if cookies:
        await context.add_cookies(cookies)
        logger.info("已加载 Cookies!")
    else:
        logger.info("未找到 Cookies,将跳转至登录页.")
    page = await context.new_page()
    logger.debug(f"{config.driver}浏览器启动完成.")
    #抹去特征
    with open('res/stealth.min.js', 'r') as f:
        js = f.read()
    await page.add_init_script(js)
    logger.debug("stealth.js执行完成.")
    page.set_default_timeout(24 * 3600 * 1000)

    return page, context

async def auto_login(context: BrowserContext, page: Page, modules=None):
    cookie_saved = False

    async def request_handler(request):
        nonlocal cookie_saved
        if cookie_saved:
            return
        if "https://www.zhihuishu.com" in request.url:
            cookies = await context.cookies()
            save_cookies(cookies, COOKIE_PATH)
            logger.info(f"已保存登录凭证到: {COOKIE_PATH},下次可免密登录.")
            cookie_saved = True

    await page.goto(config.login_url, wait_until="commit")
    if "login" not in page.url:
        logger.info("检测到已登录,跳过登录步骤.")
        return
    await page.wait_for_selector(".wall-main", state='attached')  # 等待登陆界面加载
    page.on('request', request_handler)
    if config.username and config.password:
        await page.wait_for_selector("#lUsername", state="attached")
        await page.wait_for_selector("#lPassword", state="attached")
        await page.locator('#lUsername').fill(config.username)
        await page.locator('#lPassword').fill(config.password)
        await page.wait_for_selector(".wall-sub-btn", state="attached")
        await page.wait_for_timeout(500)
        await page.locator(".wall-sub-btn").first.click()
    if config.enableAutoCaptcha and modules:
        await slider_verify(page, modules)
    await page.wait_for_selector(".wall-main", state='hidden')


async def ensure_login(context: BrowserContext, page: Page, cookies, modules=None):
    if cookies:
        logger.info("正在校验 Cookies 登录状态...")
        await page.goto(config.login_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        if "login" not in page.url:
            logger.info("使用Cookies登录成功!")
            return True
        logger.warn("检测到 Cookies 已失效, 将重新登录.", shift=True)
        clear_cookies(COOKIE_PATH)
        cookies = None

    if not config.username or not config.password:
        logger.info("请手动填写账号密码...")
    logger.info("正在等待登录完成...")
    await auto_login(context, page, modules)
    logger.info("登录成功!")
    return False


async def learning_loop(page: Page, start_time, is_new_version=False, is_hike_class=False, current_lesson=None):
    paused_time = 0.0
    if is_new_version:
        total_time = await get_video_attr(page, "duration")
        synced_to_catalog = False
        while True:
            try:
                limit_time = config.limitMaxTime
                time_period = cal_time_period(start_time, paused_time) / 60
                if 0 < limit_time <= time_period:
                    break
                cur_video_time = await get_video_attr(page, "currentTime")
                if should_refresh_video_duration(total_time):
                    total_time = await get_video_attr(page, "duration")
                catalog_percent = None
                if current_lesson is not None:
                    if not synced_to_catalog:
                        catalog_percent = await sync_video_to_catalog_progress(
                            page, current_lesson, total_time, cur_video_time
                        )
                        synced_to_catalog = True
                        cur_video_time = await get_video_attr(page, "currentTime")
                    else:
                        catalog_percent = await get_lesson_catalog_progress(current_lesson)
                    if catalog_percent >= 100 or await lesson_has_finish_marker(current_lesson, is_new_version=True):
                        await page.wait_for_timeout(completion_settle_ms())
                        break
                if is_video_complete(cur_video_time, total_time):
                    if current_lesson is not None and (catalog_percent is None or catalog_percent < 100):
                        replay_time = time_from_percent(total_time, catalog_percent or 0)
                        logger.warn(
                            f"视频已到末尾,但平台记录仅 {catalog_percent or 0}%,将回到该进度继续播放.",
                            shift=True,
                        )
                        await page.evaluate(
                            """time => {
                                const video = document.querySelector('video');
                                if (!video) return;
                                video.currentTime = time;
                                video.play();
                            }""",
                            replay_time,
                        )
                        await asyncio.sleep(1)
                        continue
                    await page.wait_for_timeout(completion_settle_ms())
                    break
                if catalog_percent is None:
                    show_course_progress(desc="视频播放进度:", cur_time=video_percent(cur_video_time, total_time))
                else:
                    show_course_progress(desc="平台记录进度:", cur_time=f"{catalog_percent}%")
                await asyncio.sleep(0.5)
            except TargetClosedError:
                return paused_time
            except TimeoutError as e:
                if await page.query_selector(".yidun_modal__title"):
                    paused_time += await wait_for_interruption(event_loop_verify)
                elif await page.query_selector(".topic-title"):
                    paused_time += await wait_for_interruption(event_loop_answer)
                else:
                    logger.debug(f"新版学习进度轮询未命中: {logger.summarize_exception(e)}")
        return paused_time
    try:
        cur_time = await get_course_progress(page, is_new_version, is_hike_class)
    except TargetClosedError:
        return paused_time
    while cur_time != "100%":
        try:
            limit_time = config.limitMaxTime
            time_period = cal_time_period(start_time, paused_time) / 60
            if 0 < limit_time <= time_period:
                break
            cur_time = await get_course_progress(page, is_new_version, is_hike_class)
            show_course_progress(desc="完成进度:", cur_time=cur_time)
            await asyncio.sleep(0.5)
        except TargetClosedError:
            return paused_time
        except TimeoutError as e:
            if await page.query_selector(".yidun_modal__title"):
                paused_time += await wait_for_interruption(event_loop_verify)
            elif await page.query_selector(".topic-title"):
                paused_time += await wait_for_interruption(event_loop_answer)
            else:
                logger.debug(f"学习进度轮询未命中: {logger.summarize_exception(e)}")
    return paused_time


async def get_lesson_catalog_progress(lesson) -> int:
    progress = lesson.locator(".el-progress[role='progressbar']").first
    if await progress.count() == 0:
        return 100 if await lesson_has_finish_marker(lesson, is_new_version=True) else 0
    value = await progress.get_attribute("aria-valuenow")
    return parse_progress_value(value)


async def sync_video_to_catalog_progress(page: Page, lesson, total_time, cur_video_time) -> int:
    catalog_percent = await get_lesson_catalog_progress(lesson)
    if catalog_percent >= 100:
        return catalog_percent
    if should_refresh_video_duration(total_time) or should_refresh_video_duration(cur_video_time):
        return catalog_percent
    expected_time = time_from_percent(total_time, catalog_percent)
    if cur_video_time > expected_time + 15:
        logger.warn(f"检测到播放器进度快于平台记录,已按目录进度 {catalog_percent}% 重新同步视频位置.", shift=True)
        await page.evaluate(
            """time => {
                const video = document.querySelector('video');
                if (!video) return;
                video.currentTime = time;
                video.play();
            }""",
            expected_time,
        )
    return catalog_percent


async def wait_current_lesson_active(lesson, is_new_version=False, is_hike_class=False, timeout_ms=8000) -> bool:
    active_class = get_active_class(is_new_version, is_hike_class)
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        class_name = await lesson.get_attribute("class")
        if has_class(class_name, active_class):
            return True
        await asyncio.sleep(0.2)
    return False


async def lesson_has_finish_marker(lesson, is_new_version=False, is_hike_class=False) -> bool:
    selectors = get_catalog_selectors(is_new_version, is_hike_class)
    return await lesson.locator(selectors.finish).count() > 0


async def wait_for_lesson_finish_marker(page: Page, lesson, total_time, title: str, timeout_ms=30000) -> bool:
    if await lesson_has_finish_marker(lesson, is_new_version=True):
        return True
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        await page.wait_for_timeout(1000)
        if await lesson_has_finish_marker(lesson, is_new_version=True):
            return True
    logger.warn(f"\"{title}\" 视频已到末尾,但目录尚未打完成标记,回退几秒重播以触发进度上报.", shift=True)
    await page.evaluate(
        """time => {
            const video = document.querySelector('video');
            if (!video) return;
            video.currentTime = time;
            video.play();
        }""",
        replay_from_time(total_time),
    )
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        await page.wait_for_timeout(1000)
        if await lesson_has_finish_marker(lesson, is_new_version=True):
            return True
    logger.warn(f"\"{title}\" 仍未出现完成标记,本轮暂不进入下一课.", shift=True)
    return False


async def review_loop(page: Page, start_time, is_hike_class=False):
    paused_time = 0.0
    total_time = await get_video_attr(page, "duration")
    if total_time is None:
        return paused_time
    try:
        await page.evaluate(config.reset_curtime)  # 重置视频播放时间
    except TargetClosedError:
        return paused_time
    while True:
        try:
            limit_time = config.limitMaxTime
            cur_time = await get_video_attr(page, "currentTime")
            if cur_time is None or cur_time >= total_time:
                break
            time_period = cal_time_period(start_time, paused_time) / 60
            if 0 < limit_time <= time_period:
                break
            show_course_progress(desc="完成进度:", cur_time=time_period, limit_time=limit_time)
            await asyncio.sleep(0.5)
        except TargetClosedError:
            return paused_time
        except TimeoutError as e:
            if await page.query_selector(".yidun_modal__title"):
                paused_time += await wait_for_interruption(event_loop_verify)
            elif await page.query_selector(".topic-title"):
                paused_time += await wait_for_interruption(event_loop_answer)
            else:
                logger.debug(f"复习进度轮询未命中: {logger.summarize_exception(e)}")
    return paused_time


async def working_loop(page: Page, is_new_version=False, is_hike_class=False):
    # 获取所有课程元素
    selectors = get_catalog_selectors(is_new_version, is_hike_class)
    await page.wait_for_selector(selectors.item, state="attached")
    to_learn_class = await get_filtered_class(page, is_new_version, is_hike_class)
    learning = True if len(to_learn_class) > 0 else False
    if learning:
        all_class = to_learn_class
    else:
        all_class = await get_filtered_class(page, is_new_version, is_hike_class, include_all=True)
    start_time = time.time()
    paused_time = 0.0
    cur_index = 0
    last_lesson_completed = not learning

    while cur_index < len(all_class):
        current_lesson = all_class[cur_index]
        await current_lesson.click()
        active = await wait_current_lesson_active(current_lesson, is_new_version, is_hike_class)
        if not active:
            logger.warn("等待当前课时切换超时,将重新点击一次当前课时.", shift=True)
            await current_lesson.click()
            active = await wait_current_lesson_active(current_lesson, is_new_version, is_hike_class)
        if not active:
            logger.debug(f"等待当前课时选中状态超时,继续检测视频. Selector: {selectors.active}")
        await page.wait_for_timeout(1000)
        title = await get_lesson_name(page, is_hike_class, is_new_version)
        logger.info(f"正在学习:{title}")
        page.set_default_timeout(10000)
        # 移除视频暂停功能
        await page.wait_for_selector("video", state="attached")
        await page.evaluate(config.remove_pause)
        lesson_completed = True
        if learning:
            paused_time += await learning_loop(page, start_time, is_new_version, is_hike_class, current_lesson)
            if is_new_version:
                total_time = await get_video_attr(page, "duration")
                lesson_completed = await wait_for_lesson_finish_marker(page, current_lesson, total_time, title)
        else:
            paused_time += await review_loop(page, start_time, is_hike_class)
        last_lesson_completed = lesson_completed
        cur_index = next_lesson_index(cur_index, len(all_class), lesson_completed=lesson_completed)
        reachTimeLimit = await check_time_limit(
            page,
            start_time,
            paused_time,
            all_class,
            title,
            is_hike_class,
            cur_index,
            lesson_completed,
        )
        if reachTimeLimit:
            return False
        if not lesson_completed:
            return False
    return course_is_complete(last_lesson_completed)


async def check_time_limit(page: Page, start_time, paused_time, all_class, title, is_hike_class, cur_index,
                           lesson_completed=True) -> bool:
    reachTimeLimit = False
    page.set_default_timeout(24 * 3600 * 1000)
    time_period = cal_time_period(start_time, paused_time) / 60
    if 0 < config.limitMaxTime <= time_period:
        logger.info(f"当前课程已达时限:{config.limitMaxTime}min", shift=True)
        logger.info("即将进入下门课程!")
        reachTimeLimit = True
    else:
        if not lesson_completed:
            logger.warn(f"\"{title}\" 未确认完成,下次启动会重新从该课时检查.", shift=True)
        elif is_finished(cur_index, len(all_class)):
            logger.info("已学完本课程全部内容!", shift=True)
            print("==" * 10)
        else:
            logger.info(f"\"{title}\" 已完成!", shift=True)
            logger.info(f"本次课程已学习:{time_period:.1f} min")
    return reachTimeLimit


async def main():
    modules, tasks = [], []
    if config.enableAutoCaptcha:
        print("===== Install Log =====")
        logger.info("正在检查依赖库...")
        modules = installer.start()
        logger.info("所有依赖库安装完成!")
    print("====== Login Log ======")
    async with async_playwright() as p:
        cookies = load_cookies(COOKIE_PATH)
        page, context = await init_page(p, cookies)

        await ensure_login(context, page, cookies, modules)

        # 先启动人机验证协程
        verify_task = asyncio.create_task(wait_for_verify(page, config, event_loop_verify))

        # 启动协程任务
        video_optimize_task = asyncio.create_task(video_optimize(page, config))
        skip_ques_task = asyncio.create_task(skip_questions(page, event_loop_answer))
        play_video_task = asyncio.create_task(play_video(page))
        tasks.extend([verify_task, video_optimize_task, skip_ques_task, play_video_task])

        # 隐藏窗口
        if config.enableHideWindow:
            await hide_window(page)

        # 任务监视器
        monitor_task = asyncio.create_task(task_monitor(tasks))

        # 遍历所有课程,加载网页
        for course_url in config.course_urls:
            print("===== Runtime Log =====")
            is_new_version = "fusioncourseh5" in course_url
            is_hike_class = "hike.zhihuishu.com" in course_url  # 判断是否为翻转课
            logger.info("正在加载播放页...")
            await page.goto(course_url, wait_until="commit")
            await page.wait_for_timeout(1500)
            if "login" in page.url:
                logger.warn("播放页跳转到登录页, 当前登录状态已失效, 正在重新登录.", shift=True)
                clear_cookies(COOKIE_PATH)
                await ensure_login(context, page, None, modules)
                logger.info("重新进入播放页...")
                await page.goto(course_url, wait_until="commit")
                await page.wait_for_timeout(1500)
            # 关闭弹窗,优化页面结构
            await optimize_page(page, config, is_new_version, is_hike_class)
            logger.info("页面优化完成!")
            if not is_new_version and await page.locator(".chapter-content-second").count() > 0:
                is_new_version = True
                logger.info("检测到新版课程目录,启用新版课时选择器.")
            # 获取课程标题
            if not is_new_version and is_hike_class is False:
                course_title = await get_optional_text(page, ".source-name")
                if course_title:
                    logger.info(f"当前课程:<<{course_title}>>")
            if is_hike_class:
                course_title = await get_optional_text(page, ".course-name")
                if course_title:
                    logger.info(f"当前课程:<<{course_title}>>， 是翻转课哎")
            # 启动课程主循环
            course_completed = await working_loop(page, is_new_version=is_new_version, is_hike_class=is_hike_class)
            if not course_completed:
                logger.warn("存在未确认完成的课时,已停止本轮运行.", shift=True)
                return
    print("===== Task Finished =====")
    logger.info("所有课程已学习完毕!")
    show_donate("res/QRcode.jpg", show=config.showDonateCode)
    # 结束所有协程任务
    await asyncio.gather(*tasks, return_exceptions=True) if tasks else None
    await monitor_task


if __name__ == "__main__":
    print_banner()
    logger = Logger()
    try:
        print("====== Init Log ======")
        logger.info("程序启动中...")
        config = Config("configs.ini")
        if not config.course_urls:
            logger.error("未检测到有效网址或不支持此类网页,请检查配置文件!")
            time.sleep(2)
            sys.exit(-1)
        asyncio.run(main())
    except TargetClosedError as e:
        if "BrowserType.launch" in repr(e):
            logger.log_exception("浏览器相关流程异常结束.", e)
            logger.error("浏览器启动失败,请尝试重新启动!")
            logger.info("如果仍然无法启动,请修改配置文件并使用Chrome浏览器")
        else:
            logger.debug(f"浏览器关闭结束运行: {logger.summarize_exception(e)}")
    except Exception as e:
        logger.log_exception("程序运行时出现未处理异常.", e, shift=True)
        if isinstance(e, KeyError):
            logger.error(f"配置文件错误!")
        elif isinstance(e, FileNotFoundError):
            logger.error(f"依赖文件缺失: {e.filename},请重新安装程序!")
        elif isinstance(e, UnicodeDecodeError):
            logger.error("配置文件编码错误,保存时请选择UTF-8或GBK编码!")
        else:
            logger.error("系统出错,请检查后重新启动!")
    except KeyboardInterrupt:
        logger.warn("检测到用户中断,程序即将退出.", shift=True)
    finally:
        logger.save()
        try:
            input("程序已结束,按Enter退出...")
        except EOFError:
            pass
