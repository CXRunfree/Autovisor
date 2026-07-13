# encoding=utf-8
import argparse
import asyncio
import sys

from playwright.async_api import BrowserContext, Page, async_playwright
from playwright._impl._errors import TargetClosedError

from modules import installer
from modules.banner import print_banner
from modules.browser import create_browser_session
from modules.configs import Config
from modules.course_runner import (
    CourseOutcome,
    detect_catalog_after_verification,
    run_course,
)
from modules.diagnostics import check_browser, check_course
from modules.logger import Logger
from modules.slider import slider_verify
from modules.support import show_donate
from modules.tasks import (
    play_video,
    skip_questions,
    task_monitor,
    video_optimize,
    wait_for_verify,
)
from modules.utils import (
    clear_cookies,
    get_runtime_path,
    hide_window,
    import_zhihuishu_cookies,
    load_cookies,
    optimize_page,
    save_cookies,
)


event_loop_verify = asyncio.Event()
event_loop_answer = asyncio.Event()
COOKIE_PATH = get_runtime_path("res", "cookies.json")
ZHS_COOKIE_URLS = [
    "https://www.zhihuishu.com",
    "https://passport.zhihuishu.com",
    "https://onlineweb.zhihuishu.com",
    "https://studyvideoh5.zhihuishu.com",
    "https://studywisdomh5.zhihuishu.com",
    "https://fusioncourseh5.zhihuishu.com",
    "https://hike.zhihuishu.com",
]


async def persist_login_cookies(context: BrowserContext) -> None:
    cookies = await context.cookies(ZHS_COOKIE_URLS)
    if cookies:
        save_cookies(cookies, COOKIE_PATH)


async def auto_login(context: BrowserContext, page: Page, config, modules=None):
    await page.goto(config.login_url, wait_until="commit")
    if "login" not in page.url:
        logger.info("检测到已登录,跳过登录步骤.")
        await persist_login_cookies(context)
        return

    await page.wait_for_selector(".wall-main", state="attached")
    if config.username and config.password:
        await page.locator("#lUsername").fill(config.username)
        await page.locator("#lPassword").fill(config.password)
        await page.locator(".wall-sub-btn").first.click()
    if config.enableAutoCaptcha and modules:
        await slider_verify(page, modules)
    await page.wait_for_selector(".wall-main", state="hidden")
    await page.wait_for_timeout(1000)
    await persist_login_cookies(context)
    logger.info(f"已保存登录凭证到: {COOKIE_PATH},下次可免密登录.")


async def ensure_login(
    context: BrowserContext, page: Page, cookies, config, modules=None
) -> None:
    if cookies:
        logger.info("正在校验 Cookies 登录状态...")
        await page.goto(config.login_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        if "login" not in page.url:
            logger.info("使用Cookies登录成功!")
            await persist_login_cookies(context)
            return
        logger.warn("检测到 Cookies 已失效, 将重新登录.", shift=True)
        clear_cookies(COOKIE_PATH)

    if not config.username or not config.password:
        logger.info("请手动填写账号密码...")
    logger.info("正在等待登录完成...")
    await auto_login(context, page, config, modules)
    logger.info("登录成功!")


async def main(config) -> bool:
    modules, tasks = [], []
    playback_enabled = asyncio.Event()
    all_courses_complete = True
    run_ok = True
    if config.enableAutoCaptcha:
        print("===== Install Log =====")
        logger.info("正在检查依赖库...")
        modules = installer.start()
        logger.info("所有依赖库安装完成!")

    print("====== Login Log ======")
    async with async_playwright() as playwright:
        cookies = None if config.attach_existing_chrome else load_cookies(COOKIE_PATH)
        session = await asyncio.wait_for(
            create_browser_session(playwright, config, cookies, logger), timeout=45
        )
        page, context = session.page, session.context
        monitor_task = None
        try:
            await ensure_login(context, page, cookies, config, modules)
            tasks.extend(
                [
                    asyncio.create_task(
                        wait_for_verify(page, config, event_loop_verify)
                    ),
                    asyncio.create_task(video_optimize(page, config)),
                    asyncio.create_task(skip_questions(page, event_loop_answer)),
                    asyncio.create_task(play_video(page, playback_enabled)),
                ]
            )
            if config.enableHideWindow:
                await hide_window(page)
            monitor_task = asyncio.create_task(task_monitor(tasks))

            for course_url in config.course_urls:
                print("===== Runtime Log =====")
                logger.info("正在加载播放页...")
                await page.goto(course_url, wait_until="commit")
                await page.wait_for_timeout(1500)
                if "login" in page.url:
                    logger.warn(
                        "播放页跳转到登录页, 当前登录状态已失效, 正在重新登录.",
                        shift=True,
                    )
                    clear_cookies(COOKIE_PATH)
                    await ensure_login(context, page, None, config, modules)
                    logger.info("重新进入播放页...")
                    await page.goto(course_url, wait_until="commit")
                    await page.wait_for_timeout(1500)

                catalog = await detect_catalog_after_verification(page, page.url)
                logger.info(f"检测到 {catalog.name} 课程目录.")
                await optimize_page(page, config, catalog)
                logger.info("页面优化完成!")
                if catalog.course_title:
                    title_element = page.locator(catalog.course_title).first
                    if await title_element.count():
                        title = " ".join(
                            (await title_element.text_content() or "").split()
                        )
                        if title:
                            logger.info(f"当前课程:<<{title}>>")

                playback_enabled.clear()
                outcome = await run_course(
                    page, catalog, config, logger, playback_enabled
                )
                playback_enabled.clear()
                if outcome is CourseOutcome.FAILED:
                    logger.warn("课程未确认完成,已停止本轮运行.", shift=True)
                    run_ok = False
                    break
                if outcome is CourseOutcome.TIME_LIMIT:
                    all_courses_complete = False
        finally:
            for task in tasks:
                task.cancel()
            if monitor_task:
                monitor_task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if monitor_task:
                await asyncio.gather(monitor_task, return_exceptions=True)
            try:
                if not session.attached:
                    await persist_login_cookies(context)
            except Exception as exc:
                logger.log_exception("刷新登录 Cookies 失败.", exc)
            finally:
                await session.close()

    print("===== Task Finished =====")
    if not run_ok:
        logger.warn("本轮因课时进度未确认而停止.", shift=True)
        return False
    if all_courses_complete:
        logger.info("所有课程已学习完毕!")
    else:
        logger.info("本轮已按每门课程时限结束,仍有课程未完成.", shift=True)
    show_donate("res/QRcode.jpg", show=config.showDonateCode)
    return True


def parse_args():
    parser = argparse.ArgumentParser(description="Autovisor")
    parser.add_argument("--config", default="configs.ini", help="配置文件路径")
    parser.add_argument(
        "--check-browser",
        action="store_true",
        help="只检查 Chrome 启动和智慧树登录状态",
    )
    parser.add_argument(
        "--check-course",
        metavar="URL",
        help="阻止进度上报和自动播放,只检查课程目录选择器",
    )
    parser.add_argument(
        "--import-cookies",
        metavar="PATH",
        help="从 Requests CookieJar JSON 安全导入未过期的智慧树 Cookie",
    )
    return parser.parse_args()


def cli() -> int:
    global logger
    args = parse_args()
    print_banner()
    logger = Logger()
    exit_code = 0
    try:
        print("====== Init Log ======")
        logger.info("程序启动中...")
        config = Config(args.config)
        if args.import_cookies:
            count = import_zhihuishu_cookies(args.import_cookies, COOKIE_PATH)
            logger.info(f"已安全导入 {count} 条智慧树 Cookie.", shift=True)
            return 0
        if args.check_browser:
            return asyncio.run(check_browser(config, logger, COOKIE_PATH))
        if args.check_course:
            return asyncio.run(
                check_course(args.check_course, config, logger, COOKIE_PATH)
            )
        if not config.course_urls:
            logger.error("未检测到有效网址或不支持此类网页,请检查配置文件!")
            return 2
        if not asyncio.run(main(config)):
            exit_code = 1
    except TargetClosedError as exc:
        if "BrowserType.launch" in repr(exc):
            logger.log_exception("浏览器相关流程异常结束.", exc)
            logger.error("浏览器启动失败,请检查 Chrome 或 CDP 配置!")
        else:
            logger.debug(f"浏览器关闭结束运行: {logger.summarize_exception(exc)}")
        exit_code = 1
    except Exception as exc:
        logger.log_exception("程序运行时出现未处理异常.", exc, shift=True)
        if isinstance(exc, KeyError):
            logger.error("配置文件错误!")
        elif isinstance(exc, FileNotFoundError):
            logger.error(f"依赖文件缺失: {exc.filename},请重新安装程序!")
        elif isinstance(exc, UnicodeDecodeError):
            logger.error("配置文件编码错误,保存时请选择UTF-8或GBK编码!")
        else:
            logger.error("系统出错,请检查后重新启动!")
        exit_code = 1
    finally:
        logger.save()
        if getattr(sys, "frozen", False) and sys.stdin.isatty():
            input("程序已结束,按Enter退出...")
    return exit_code


if __name__ == "__main__":
    sys.exit(cli())
