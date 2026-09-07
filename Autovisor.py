# encoding=utf-8
import asyncio
import os
import time
import traceback
import sys
import ctypes
from playwright.async_api import async_playwright, Playwright, Page, BrowserContext
from playwright.async_api import TimeoutError
from playwright._impl._errors import TargetClosedError
from modules.logger import Logger
from modules.configs import Config, ConfigError
from modules.progress import get_course_progress, show_course_progress
from modules.support import show_donate
from modules.utils import optimize_page, get_lesson_name, get_filtered_class, get_video_attr, hide_window, \
     save_cookies, load_cookies, clear_cookies, get_runtime_path
from modules.slider import slider_verify
from modules.tasks import video_optimize, play_video, skip_questions, wait_for_verify, task_monitor
from modules import installer
from modules.banner import print_banner
from modules.login import (
    LOGIN_PASSWORD_SELECTOR,
    LOGIN_SUBMIT_SELECTOR,
    LOGIN_USERNAME_SELECTOR,
    accept_login_terms,
    is_login_page,
    wait_for_login_complete,
)

# 获取全局事件循环
event_loop_verify = asyncio.Event()
event_loop_answer = asyncio.Event()
COOKIE_PATH = get_runtime_path("data", "cookies.json")


async def wait_for_interruption(event_loop: asyncio.Event) -> float:
    event_loop.clear()
    wait_start = time.time()
    await event_loop.wait()
    return time.time() - wait_start


def cal_time_period(start_time: float, paused_time: float) -> float:
    return max(0.0, time.time() - start_time - paused_time)


def get_screen_size():
    if os.name == "nt":
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    return 1920, 1080


async def init_page(p: Playwright, cookies) -> tuple[Page, BrowserContext]:
    driver = "msedge" if config.driver == "edge" else config.driver
    logger.info(f"正在启动{config.driver}浏览器...")
    screen_width, screen_height = get_screen_size()
    launch_args = {
        "channel": driver,
        "headless": False,
        "executable_path": config.exe_path if config.exe_path else None,
        "args": [
            "--start-maximized",
            f"--window-size={screen_width},{screen_height}",
            "--window-position=0,0",
        ],
    }
    try:
        browser = await p.chromium.launch(**launch_args)
    except TargetClosedError as e:
        logger.log_exception("首次启动浏览器失败,准备重试.", e)
        logger.info("检测到浏览器首次启动失败,正在重试...")
        await asyncio.sleep(1)
        browser = await p.chromium.launch(**launch_args)
    # 使用真实窗口尺寸，避免 Playwright 默认 viewport 覆盖最大化窗口。
    context = await browser.new_context(viewport=None)
    # 加载 Cookies
    if cookies:
        await context.add_cookies(cookies)
        logger.info("已加载 Cookies!")
    else:
        logger.info("未找到 Cookies,将跳转至登录页.")
    page = await context.new_page()
    logger.debug(f"{config.driver}浏览器启动完成.")
    #抹去特征
    with open(get_runtime_path("resources", "stealth.min.js"), 'r') as f:
        js = f.read()
    await page.add_init_script(js)
    logger.debug("stealth.js执行完成.")
    page.set_default_timeout(24 * 3600 * 1000)

    return page, context

async def auto_login(context: BrowserContext, page: Page, modules=None):
    await page.goto(config.login_url, wait_until="commit")
    if not is_login_page(page.url):
        logger.info("检测到已登录,跳过登录步骤.")
        return

    if config.username and config.password:
        try:
            username = await page.wait_for_selector(
                LOGIN_USERNAME_SELECTOR, state="visible", timeout=30000
            )
            password = await page.wait_for_selector(
                LOGIN_PASSWORD_SELECTOR, state="visible", timeout=30000
            )
            await username.fill(config.username)
            await password.fill(config.password)
            await accept_login_terms(page)
            submit = await page.wait_for_selector(
                LOGIN_SUBMIT_SELECTOR, state="visible", timeout=30000
            )
            await page.wait_for_timeout(500)
            await submit.click()
        except TimeoutError:
            if is_login_page(page.url):
                logger.warn("未找到自动登录控件,请在浏览器中手动完成登录.", shift=True)

    captcha_task = None
    if config.enableAutoCaptcha and modules:
        captcha_task = asyncio.create_task(slider_verify(page, modules))

    try:
        await wait_for_login_complete(page)
    finally:
        if captcha_task:
            if not captcha_task.done():
                captcha_task.cancel()
            await asyncio.gather(captcha_task, return_exceptions=True)

    cookies = await context.cookies()
    save_cookies(cookies, COOKIE_PATH)
    logger.info(f"已保存登录凭证到: {COOKIE_PATH},下次可免密登录.")


async def ensure_login(context: BrowserContext, page: Page, cookies, modules=None):
    if cookies:
        logger.info("正在校验 Cookies 登录状态...")
        await page.goto(config.login_url, wait_until="domcontentloaded")
        try:
            await wait_for_login_complete(page, timeout=10000)
        except TimeoutError:
            pass
        if not is_login_page(page.url):
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


async def learning_loop(page: Page, start_time, is_new_version=False, is_hike_class=False):
    paused_time = 0.0
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
    if is_hike_class:
        await page.wait_for_selector(".file-item", state="attached")
    else:
        await page.wait_for_selector(".clearfix.video", state="attached")
    to_learn_class = await get_filtered_class(page, is_new_version, is_hike_class)
    learning = True if len(to_learn_class) > 0 else False
    if learning:
        all_class = to_learn_class
    else:
        all_class = await get_filtered_class(page, is_new_version, is_hike_class, include_all=True)
    start_time = time.time()
    paused_time = 0.0
    cur_index = 0

    while cur_index < len(all_class):
        await all_class[cur_index].click()
        if is_hike_class:
            await page.wait_for_selector(".file-item.active", state="attached")
        else:
            await page.wait_for_selector(".current_play", state="attached")
        await page.wait_for_timeout(1000)
        title = await get_lesson_name(page, is_hike_class)
        logger.info(f"正在学习:{title}")
        page.set_default_timeout(10000)
        # 移除视频暂停功能
        await page.wait_for_selector("video", state="attached")
        await page.evaluate(config.remove_pause)
        if learning:
            paused_time += await learning_loop(page, start_time, is_new_version, is_hike_class)
        else:
            paused_time += await review_loop(page, start_time, is_hike_class)
        if is_hike_class is False:
            if "current_play" in await all_class[cur_index].get_attribute('class'):
                cur_index += 1
        else:
            if "active" in await all_class[cur_index].get_attribute('class'):
                cur_index += 1
        reachTimeLimit = await check_time_limit(page, start_time, paused_time, all_class, title, is_hike_class)
        if reachTimeLimit:
            return


async def check_time_limit(page: Page, start_time, paused_time, all_class, title, is_hike_class) -> bool:
    reachTimeLimit = False
    page.set_default_timeout(24 * 3600 * 1000)
    time_period = cal_time_period(start_time, paused_time) / 60
    if 0 < config.limitMaxTime <= time_period:
        logger.info(f"当前课程已达时限:{config.limitMaxTime}min", shift=True)
        logger.info("即将进入下门课程!")
        reachTimeLimit = True
    else:
        class_name = await all_class[-1].get_attribute('class')
        if is_hike_class:
            if "active" in class_name:
                logger.info("已学完本课程全部内容!", shift=True)
                print("==" * 10)
            else:
                logger.info(f"\"{title}\" 已完成!", shift=True)
                logger.info(f"本次课程已学习:{time_period:.1f} min")
        else:
            if "current_play" in class_name:
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
        modules = installer.start(config)
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
            # 获取课程标题
            if not is_new_version and is_hike_class is False:
                title_selector = await page.wait_for_selector(".source-name")
                course_title = await title_selector.text_content()
                logger.info(f"当前课程:<<{course_title}>>")
            if is_hike_class:
                title_selector = await page.wait_for_selector(".course-name")
                course_title = await title_selector.text_content()
                logger.info(f"当前课程:<<{course_title}>>， 是翻转课哎")
            # 启动课程主循环
            await working_loop(page, is_new_version=is_new_version, is_hike_class=is_hike_class)
    print("===== Task Finished =====")
    logger.info("所有课程已学习完毕!")
    show_donate(get_runtime_path("resources", "QRcode.jpg"), show=config.showDonateCode)
    # 结束所有协程任务
    await asyncio.gather(*tasks, return_exceptions=True) if tasks else None
    await monitor_task


if __name__ == "__main__":
    print_banner()
    logger = Logger()
    try:
        print("====== Init Log ======")
        logger.info("程序启动中...")
        installer.validate_python_version()
        base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "configs.ini")
        mirrors_path = os.path.join(base_dir, "data", "mirrors.json")
        config=Config(config_path, mirrors_path)
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
    except ConfigError as e:
        logger.error(f"配置文件无效: {e}", shift=True)
        logger.info("请完整解压发行包，并确保 configs.ini 与 Autovisor.exe 位于同一目录。")
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
    finally:
        logger.save()
        input("程序已结束,按Enter退出...")
