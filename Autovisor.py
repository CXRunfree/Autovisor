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
from modules.utils import optimize_page, get_lesson_name, get_filtered_class, get_video_attr, hide_window, \
     save_cookies, load_cookies, clear_cookies, get_runtime_path
from modules.slider import slider_verify
from modules.tasks import video_optimize, play_video, skip_questions, wait_for_verify, task_monitor, \
     progress_watchdog
from modules import installer
from modules.banner import print_banner

# 获取全局事件循环
event_loop_verify = asyncio.Event()
event_loop_answer = asyncio.Event()
event_recovery = asyncio.Event()
progress_queue: asyncio.Queue = None
RECOVERY_LEVELS = ["reclick", "reload", "skip"]
COOKIE_PATH = get_runtime_path("res", "cookies.json")


async def wait_for_interruption(event_loop: asyncio.Event) -> float:
    event_loop.clear()
    wait_start = time.time()
    await event_loop.wait()
    return time.time() - wait_start


def cal_time_period(start_time: float, paused_time: float) -> float:
    return max(0.0, time.time() - start_time - paused_time)


async def recovery_handler(page: Page, config, level: int,
                           all_class=None, cur_index=None) -> str:
    """
    渐进式恢复处理。
    level 0: 重新点击当前课程 + 重新注入脚本
    level 1: 刷新页面
    level 2: 跳过当前课程
    返回: "ok" / "skipped" / "failed"
    """
    logger.warn(f"恢复处理: 执行级别 {level} ({RECOVERY_LEVELS[level]})", shift=True)

    try:
        if level == 0:  # reclick — 重新点击当前视频
            if all_class and cur_index is not None and cur_index < len(all_class):
                await all_class[cur_index].click(timeout=3000)
                await page.wait_for_timeout(1000)
            # 重新注入脚本
            await page.evaluate(config.remove_pause)
            await page.evaluate('document.querySelector("video")?.play()')
            logger.info("恢复级别0完成: 已重新点击并注入脚本.", shift=True)
            return "ok"

        elif level == 1:  # reload — 刷新页面
            url = page.url
            await page.goto(url, wait_until="commit")
            await page.wait_for_timeout(2000)
            await page.evaluate(config.remove_pause)
            logger.info("恢复级别1完成: 页面已刷新.", shift=True)
            return "ok"

        elif level == 2:  # skip — 跳过当前课程
            logger.info("恢复级别2: 跳过当前课程.", shift=True)
            return "skipped"

    except Exception as e:
        logger.log_exception(f"恢复级别{level}执行失败.", e)

    return "failed"

async def init_page(p: Playwright, cookies) -> tuple[Page, BrowserContext]:
    driver = "msedge" if config.driver == "edge" else config.driver
    logger.info(f"正在启动{config.driver}浏览器...")
    launch_args = {
        "channel": driver,
        "headless": False,
        "executable_path": config.exe_path if config.exe_path else None,
        "args": [
            f'--window-size={1600},{900}',
            '--window-position=100,100',  # 窗口位置
        ],
    }
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


async def learning_loop(page: Page, start_time, is_new_version=False, is_hike_class=False,
                        all_class=None, cur_index=None):
    paused_time = 0.0
    try:
        cur_time = await get_course_progress(page, is_new_version, is_hike_class)
    except TargetClosedError:
        return paused_time
    # 首次推送进度到看门狗
    if progress_queue:
        await progress_queue.put(cur_time)

    recovery_attempt = 0

    while cur_time != "100%":
        try:
            # 检查看门狗是否触发了恢复
            if event_recovery.is_set():
                event_recovery.clear()
                result = await recovery_handler(
                    page, config, recovery_attempt,
                    all_class, cur_index
                )
                if result == "ok":
                    recovery_attempt = 0
                    # 重新获取进度
                    cur_time = await get_course_progress(page, is_new_version, is_hike_class)
                    if progress_queue:
                        await progress_queue.put(cur_time)
                    continue
                elif result == "skipped":
                    return paused_time
                else:
                    recovery_attempt = min(recovery_attempt + 1, 2)
                    continue

            limit_time = config.limitMaxTime
            time_period = cal_time_period(start_time, paused_time) / 60
            if 0 < limit_time <= time_period:
                break
            cur_time = await get_course_progress(page, is_new_version, is_hike_class)
            show_course_progress(desc="完成进度:", cur_time=cur_time)
            # 推送进度到看门狗
            if progress_queue:
                await progress_queue.put(cur_time)
            await asyncio.sleep(0.5)
        except TargetClosedError:
            return paused_time
        except TimeoutError as e:
            if await page.query_selector(".yidun_modal__title"):
                paused_time += await wait_for_interruption(event_loop_verify)
                # 验证完成后重置看门狗计时
                if progress_queue:
                    await progress_queue.put(cur_time)
            elif await page.query_selector(".topic-title"):
                paused_time += await wait_for_interruption(event_loop_answer)
                if progress_queue:
                    await progress_queue.put(cur_time)
            else:
                logger.debug(f"学习进度轮询未命中: {logger.summarize_exception(e)}")
    return paused_time


async def review_loop(page: Page, start_time, is_hike_class=False,
                      all_class=None, cur_index=None):
    paused_time = 0.0
    total_time = await get_video_attr(page, "duration")
    if total_time is None:
        return paused_time
    try:
        await page.evaluate(config.reset_curtime)  # 重置视频播放时间
    except TargetClosedError:
        return paused_time

    recovery_attempt = 0

    while True:
        try:
            # 检查看门狗
            if event_recovery.is_set():
                event_recovery.clear()
                result = await recovery_handler(
                    page, config, recovery_attempt,
                    all_class, cur_index
                )
                if result == "ok":
                    recovery_attempt = 0
                    total_time = await get_video_attr(page, "duration")
                    if total_time is None:
                        return paused_time
                    continue
                elif result == "skipped":
                    return paused_time
                else:
                    recovery_attempt = min(recovery_attempt + 1, 2)
                    continue

            limit_time = config.limitMaxTime
            cur_time = await get_video_attr(page, "currentTime")
            if cur_time is None or cur_time >= total_time:
                break
            time_period = cal_time_period(start_time, paused_time) / 60
            if 0 < limit_time <= time_period:
                break
            show_course_progress(desc="完成进度:", cur_time=time_period, limit_time=limit_time)
            # 推送进度到看门狗
            if progress_queue:
                await progress_queue.put(cur_time)
            await asyncio.sleep(0.5)
        except TargetClosedError:
            return paused_time
        except TimeoutError as e:
            if await page.query_selector(".yidun_modal__title"):
                paused_time += await wait_for_interruption(event_loop_verify)
                if progress_queue:
                    await progress_queue.put(None)
            elif await page.query_selector(".topic-title"):
                paused_time += await wait_for_interruption(event_loop_answer)
                if progress_queue:
                    await progress_queue.put(None)
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
            paused_time += await learning_loop(page, start_time, is_new_version, is_hike_class,
                                                all_class, cur_index)
        else:
            paused_time += await review_loop(page, start_time, is_hike_class,
                                             all_class, cur_index)
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
    global progress_queue

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

        # 初始化看门狗队列
        progress_queue = asyncio.Queue()
        event_recovery.clear()

        # 先启动人机验证协程
        verify_task = asyncio.create_task(wait_for_verify(page, config, event_loop_verify))

        # 启动协程任务
        video_optimize_task = asyncio.create_task(video_optimize(page, config))
        skip_ques_task = asyncio.create_task(skip_questions(page, event_loop_answer))
        play_video_task = asyncio.create_task(play_video(page, config))
        # 进度看门狗 — 检测冻结和异常
        watchdog_task = asyncio.create_task(
            progress_watchdog(page, progress_queue, event_recovery)
        )
        tasks.extend([verify_task, video_optimize_task, skip_ques_task, play_video_task, watchdog_task])

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
    finally:
        logger.save()
        input("程序已结束,按Enter退出...")
