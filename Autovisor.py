# encoding=utf-8
import argparse
import asyncio
import ctypes
import getpass
import os
import platform
import re
import sys
import time

from playwright.async_api import BrowserContext, Page, Playwright, TimeoutError, async_playwright
from playwright._impl._errors import TargetClosedError

from modules import installer, quiz_page, updater
from modules.banner import print_banner
from modules.configs import Config, ConfigError, ensure_config_files
from modules.course_runner import (
    CourseOutcome,
    detect_catalog_after_verification,
    run_course,
)
from modules.diagnostics import check_browser, check_course
from modules.login import (
    describe_login_error,
    is_login_page,
    perform_password_login,
    wait_for_login_complete,
)
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
    filter_zhihuishu_cookies,
    get_runtime_path,
    hide_window,
    load_cookies,
    optimize_page,
    save_cookies,
)
from modules.version import __version__

# 获取全局事件循环
event_loop_verify = asyncio.Event()
event_loop_answer = asyncio.Event()
COOKIE_PATH = get_runtime_path("data", "cookies.json")
# 运行期间周期性落盘 Cookies 的间隔(秒): 服务器中途续期后, 崩溃/断电也不丢凭证
COOKIE_SYNC_INTERVAL_SECONDS = 300


_saved_cookies = None


def _cookies_signature(cookies):
    if not cookies:
        return None
    return frozenset(
        (
            cookie.get("name"),
            cookie.get("domain"),
            cookie.get("path"),
            cookie.get("value"),
        )
        for cookie in cookies
    )


def remember_login_cookies(cookies) -> None:
    """记录已经落盘的凭证, 用于跳过重复写入。"""
    global _saved_cookies
    _saved_cookies = _cookies_signature(cookies)


async def persist_login_cookies(context: BrowserContext) -> None:
    """凭证有变化时才写盘: 登录完成、Cookie 续期后立即保存, 中断也不丢。"""
    global _saved_cookies
    # 按域名筛选而非固定 URL 列表, 新子域下发 cookies 也能收进来
    cookies = filter_zhihuishu_cookies(await context.cookies())
    signature = _cookies_signature(cookies)
    if signature is None or signature == _saved_cookies:
        return
    try:
        save_cookies(cookies, COOKIE_PATH)
    except Exception as exc:
        logger.log_exception("保存登录 Cookies 失败.", exc)
        return
    _saved_cookies = signature
    logger.event("保存登录凭证", 条数=len(cookies), 文件=COOKIE_PATH)


async def periodic_cookie_sync(context: BrowserContext) -> None:
    """运行期间周期性落盘 Cookies, 与 persist_login_cookies 共用变更检测, 无变化时不写盘。"""
    while True:
        await asyncio.sleep(COOKIE_SYNC_INTERVAL_SECONDS)
        try:
            await persist_login_cookies(context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.log_exception("周期保存登录 Cookies 失败.", exc)


def get_screen_size():
    if os.name == "nt":
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    return 1920, 1080


async def init_page(p: Playwright, config, cookies) -> tuple[Page, BrowserContext]:
    driver = "msedge" if config.driver == "edge" else config.driver
    logger.info(f"正在启动{config.driver}浏览器...")
    screen_width, screen_height = get_screen_size()
    logger.event(
        "启动浏览器",
        驱动=config.driver,
        通道=driver,
        可执行文件=config.exe_path or "默认",
        窗口大小=f"{screen_width}x{screen_height}",
    )
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
    except TargetClosedError as exc:
        logger.log_exception("首次启动浏览器失败,准备重试.", exc)
        logger.info("检测到浏览器首次启动失败,正在重试...")
        await asyncio.sleep(1)
        browser = await p.chromium.launch(**launch_args)
    logger.event("浏览器已启动", 版本=getattr(browser, "version", "未知"))
    # 使用真实窗口尺寸，避免 Playwright 默认 viewport 覆盖最大化窗口。
    context = await browser.new_context(viewport=None)
    if cookies:
        await context.add_cookies(cookies)
        logger.info("已加载 Cookies!")
    else:
        logger.info("未找到 Cookies,将跳转至登录页.")
    page = await context.new_page()
    logger.debug(f"{config.driver}浏览器启动完成.")
    # 抹去特征
    with open(get_runtime_path("resources", "stealth.min.js"), 'r') as f:
        js = f.read()
    await page.add_init_script(js)
    logger.debug("stealth.js执行完成.")
    page.set_default_timeout(24 * 3600 * 1000)

    return page, context


async def report_login_error_later(page: Page) -> None:
    """提交账号密码后若仍停留在登录页, 收集并输出页面错误提示。"""
    await page.wait_for_timeout(6000)
    if not is_login_page(page.url):
        return
    detail = await describe_login_error(page)
    if detail:
        logger.warn(f"登录未完成, 页面提示: {detail}", shift=True)
    else:
        logger.warn("登录未完成, 请检查账号密码是否正确, 或在浏览器中手动登录.", shift=True)


async def auto_login(context: BrowserContext, page: Page, config, modules=None) -> None:
    wait_start = time.time()
    await page.goto(config.login_url, wait_until="commit")
    if not is_login_page(page.url):
        logger.info("检测到已登录,跳过登录步骤.")
        return

    error_task = None
    if config.username and config.password:
        try:
            logger.event("自动登录", 方式="账号密码", 账号="已填写")
            await perform_password_login(page, config.username, config.password)
            error_task = asyncio.create_task(report_login_error_later(page))
        except TimeoutError:
            if is_login_page(page.url):
                logger.warn("未找到自动登录控件,请在浏览器中手动完成登录.", shift=True)
                logger.event("自动登录", 方式="手动", 原因="未找到登录控件")
    else:
        logger.info("配置文件未填写账号密码,请在浏览器中手动登录.", shift=True)
        logger.event("自动登录", 方式="手动", 原因="未配置账号密码")

    captcha_task = None
    if config.enableAutoCaptcha and modules:
        logger.event("滑块任务", 状态="启动")
        captcha_task = asyncio.create_task(slider_verify(page, modules))

    try:
        await wait_for_login_complete(page)
    finally:
        for task in (error_task, captcha_task):
            if task and not task.done():
                task.cancel()
        pending = [task for task in (error_task, captcha_task) if task]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    logger.event("登录完成", 耗时=f"{time.time() - wait_start:.1f}s", 地址=page.url)
    await persist_login_cookies(context)
    logger.info(f"已保存登录凭证到: {COOKIE_PATH},下次可免密登录.")


async def ensure_login(
    context: BrowserContext, page: Page, cookies, config, modules=None
) -> bool:
    if cookies:
        logger.info("正在校验 Cookies 登录状态...")
        await page.goto(config.login_url, wait_until="domcontentloaded")
        try:
            await wait_for_login_complete(page, timeout=10000)
        except TimeoutError:
            pass
        if not is_login_page(page.url):
            logger.info("使用Cookies登录成功!")
            logger.event("登录状态", 结果="Cookies 有效", 地址=page.url)
            await persist_login_cookies(context)
            return True
        logger.warn("检测到 Cookies 已失效, 将重新登录.", shift=True)
        logger.event("登录状态", 结果="Cookies 失效", 地址=page.url)
        clear_cookies(COOKIE_PATH)
        remember_login_cookies(None)
        cookies = None

    if not config.username or not config.password:
        logger.info("请手动填写账号密码...")
    logger.info("正在等待登录完成...")
    await auto_login(context, page, config, modules)
    logger.info("登录成功!")
    return False


def save_credentials_to_config(config_path: str, username: str, password: str) -> bool:
    """把账号密码写回 config.ini, 只替换目标行, 保留文件中的其余内容和注释。"""
    raw = None
    used_encoding = "utf-8"
    for encoding in ("utf-8-sig", "gbk"):
        try:
            with open(config_path, "r", encoding=encoding) as file:
                raw = file.read()
            # utf-8-sig 仅用于剥离 BOM, 回写统一用 utf-8, 避免给原文件追加 BOM
            used_encoding = "utf-8" if encoding == "utf-8-sig" else encoding
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        logger.warn("配置文件读取失败,账号密码仅本次运行生效.", shift=True)
        return False

    def replace_field(text: str, key: str, value: str) -> str:
        # 只匹配行内空白: \s 会吞掉换行, 导致下一行被整体替换掉
        pattern = re.compile(rf"(?m)^([ \t]*{key}[ \t]*=[ \t]*).*$")
        if pattern.search(text):
            return pattern.sub(lambda match: match.group(1) + value, text, count=1)
        if "[user-account]" in text:
            return text.replace("[user-account]", f"[user-account]\n{key} = {value}", 1)
        return text.rstrip("\r\n") + f"\n[user-account]\n{key} = {value}\n"

    raw = replace_field(raw, "username", username)
    raw = replace_field(raw, "password", password)
    try:
        with open(config_path, "w", encoding=used_encoding) as file:
            file.write(raw)
    except OSError as exc:
        logger.log_exception("保存账号密码到配置文件失败.", exc)
        return False
    return True


def ensure_credentials(config) -> None:
    """配置文件未填账号密码时, 在终端引导输入并回存, 之后即可全自动登录。"""
    if config.username and config.password:
        return
    if not config.config_path or not sys.stdin.isatty() or not sys.stdout.isatty():
        return
    try:
        logger.info("配置文件未填写账号密码,现在输入一次即可永久自动登录(直接回车可跳过).", shift=True)
        username = input("请输入账号(手机号): ").strip()
        if not username:
            return
        password = getpass.getpass("请输入密码: ").strip()
        if not password:
            return
    except (EOFError, KeyboardInterrupt):
        logger.info("", shift=True)
        return
    if save_credentials_to_config(config.config_path, username, password):
        logger.event("自动登录", 方式="账号密码", 状态="已保存到配置文件", 文件=config.config_path)
    config.username = username
    config.password = password
    logger.info("已记录本次输入的账号密码,正在自动登录...")


async def main(config) -> bool:
    modules, tasks = [], []
    playback_enabled = asyncio.Event()
    all_courses_complete = True
    run_ok = True
    if config.enableAutoCaptcha:
        logger.section("依赖安装")
        logger.info("正在检查依赖库...")
        modules = installer.start(config)
        logger.info("所有依赖库安装完成!")

    logger.section("登录")
    async with async_playwright() as p:
        cookies = load_cookies(COOKIE_PATH)
        remember_login_cookies(cookies)
        logger.event("本地凭证", 数量=len(cookies) if cookies else 0, 文件=COOKIE_PATH)
        page, context = await init_page(p, config, cookies)
        # 捕获课程流程中新开的测验页面(如课堂测验跳转的新标签页), 自动作答
        def _on_new_page(new_page):
            asyncio.ensure_future(quiz_page.auto_answer_new_page(new_page, config))
        context.on("page", _on_new_page)
        logger.event(
            "测验页面捕获",
            状态="已启用" if quiz_page.llm.enabled() else "未配置 API Key, 仅监听不答题",
        )
        monitor_task = None
        try:
            login_by_cookie = await ensure_login(context, page, cookies, config, modules)

            logger.context(登录方式="Cookie" if login_by_cookie else "账号")
            tasks.extend(
                [
                    asyncio.create_task(
                        wait_for_verify(page, config, event_loop_verify)
                    ),
                    asyncio.create_task(video_optimize(page, config)),
                    asyncio.create_task(skip_questions(page, event_loop_answer)),
                    asyncio.create_task(play_video(page, playback_enabled)),
                    asyncio.create_task(periodic_cookie_sync(context)),
                ]
            )
            logger.event(
                "后台任务启动",
                任务=", ".join(task.get_coro().__name__ for task in tasks),
            )
            if config.enableHideWindow:
                await hide_window(page)
            monitor_task = asyncio.create_task(task_monitor(tasks))

            course_total = len(config.course_urls)
            for index, course_url in enumerate(config.course_urls, 1):
                logger.section(f"课程 {index}/{course_total}")
                logger.context(课程序号=f"{index}/{course_total}", 课程地址=course_url)
                logger.info("正在加载播放页...")
                await page.goto(course_url, wait_until="commit")
                await page.wait_for_timeout(1500)
                if "login" in page.url:
                    logger.warn(
                        "播放页跳转到登录页, 当前登录状态已失效, 正在重新登录.",
                        shift=True,
                    )
                    logger.event("登录失效", 地址=page.url)
                    clear_cookies(COOKIE_PATH)
                    remember_login_cookies(None)
                    await ensure_login(context, page, None, config, modules)
                    logger.info("重新进入播放页...")
                    await page.goto(course_url, wait_until="commit")
                    await page.wait_for_timeout(1500)

                catalog = await detect_catalog_after_verification(page, page.url)
                logger.info(f"检测到 {catalog.name} 课程目录.")
                logger.context(目录类型=catalog.name)
                logger.event("课程目录", 类型=catalog.name, 地址=page.url)
                await persist_login_cookies(context)
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
                            logger.context(课程名称=title)
                            logger.event("当前课程", 名称=title)

                playback_enabled.clear()
                outcome = await run_course(
                    page, catalog, config, logger, playback_enabled
                )
                playback_enabled.clear()
                logger.event("课程结果", 结果=outcome.value, 目录类型=catalog.name)
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
                await persist_login_cookies(context)
            except Exception as exc:
                logger.log_exception("刷新登录 Cookies 失败.", exc)
            try:
                await context.browser.close()
            except TargetClosedError:
                pass

    logger.section("任务结束")
    logger.event(
        "运行结果",
        正常退出=run_ok,
        全部完成=all_courses_complete,
    )
    logger.clear_context()
    if not run_ok:
        logger.warn("本轮因课时进度未确认而停止.", shift=True)
        return False
    if all_courses_complete:
        logger.info("所有课程已学习完毕!")
    else:
        logger.info("本轮已按每门课程时限结束,仍有课程未完成.", shift=True)
    show_donate(get_runtime_path("resources", "QRcode.jpg"), show=config.showDonateCode)
    return True


def parse_args():
    parser = argparse.ArgumentParser(description="Autovisor")
    parser.add_argument("--config", default=None, help="配置文件路径(默认使用程序目录下的 config.ini)")
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
        logger.section("初始化")
        logger.info("程序启动中...")
        logger.event(
            "运行环境",
            版本=__version__,
            Python=platform.python_version(),
            运行方式="打包" if getattr(sys, "frozen", False) else "源码",
            系统=platform.system(),
            系统版本=platform.release(),
            系统架构=platform.machine(),
            启动参数=(f"[{' '.join(sys.argv[1:])}]" if sys.argv[1:] else "无"),
            日志文件=logger.filename,
        )
        updater.check_for_update(logger)
        installer.validate_python_version()
        base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        default_config_name = "config.macos.ini" if sys.platform == "darwin" else "config.ini"
        config_path = args.config or os.path.join(base_dir, default_config_name)
        mirrors_path = os.path.join(base_dir, "data", "mirrors.json")
        # 启动即补齐缺失的配置文件(只创建不覆盖), 个人配置不会被提交到仓库
        created_files = ensure_config_files(config_path)
        for path in created_files:
            logger.info(f"已生成默认配置文件: {path}", shift=True)
        if config_path in created_files:
            logger.warn("配置文件为默认模板, 请填写课程链接([course-url])后重新运行.", shift=True)
            return 0
        config = Config(config_path, mirrors_path)
        logger.context(配置文件=config_path)
        logger.event(
            "运行配置",
            驱动=config.driver,
            浏览器路径=config.exe_path or "默认",
            连接现有浏览器=config.attach_existing_chrome,
            账号="已填写" if config.username else "未填写",
            密码="已填写" if config.password else "未填写",
            自动答题=config.enableAutoCaptcha,
            隐藏窗口=config.enableHideWindow,
            静音=config.soundOff,
            倍速=config.limitSpeed,
            时限分钟=config.limitMaxTime,
            课程数=len(config.course_urls),
            镜像源=len(config.mirrors),
        )
        for index, course_url in enumerate(config.course_urls, 1):
            logger.event("课程地址", 序号=f"{index}/{len(config.course_urls)}", 地址=course_url)
        if args.import_cookies:
            from modules.utils import import_zhihuishu_cookies

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
        ensure_credentials(config)
        if not asyncio.run(main(config)):
            exit_code = 1
    except TargetClosedError as exc:
        if "BrowserType.launch" in repr(exc):
            logger.log_exception("浏览器相关流程异常结束.", exc)
            logger.error("浏览器启动失败,请检查 Chrome 或 CDP 配置!")
        else:
            logger.debug(f"浏览器关闭结束运行: {logger.summarize_exception(exc)}")
        exit_code = 1
    except ConfigError as exc:
        logger.error(f"配置文件无效: {exc}", shift=True)
        logger.info("请完整解压发行包，并确保 config.ini 与 Autovisor.exe 位于同一目录。")
        exit_code = 1
    except Exception as exc:
        logger.log_exception("程序运行时出现未处理异常.", exc, shift=True)
        if isinstance(exc, KeyError):
            logger.error(f"配置文件错误!")
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
            try:
                input("程序已结束,按Enter退出...")
            except EOFError:
                # 非交互式运行(重定向/自动化)时 stdin 可能已关闭, 不应视作异常
                pass
    return exit_code


if __name__ == "__main__":
    sys.exit(cli())