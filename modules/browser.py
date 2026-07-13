from dataclasses import dataclass
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright
from playwright._impl._errors import TargetClosedError


@dataclass
class BrowserSession:
    browser: Browser
    context: BrowserContext
    page: Page
    attached: bool

    async def close(self) -> None:
        """Close only resources owned by Autovisor."""
        try:
            if self.attached:
                if not self.page.is_closed():
                    await self.page.close()
                return
            await self.browser.close()
        except TargetClosedError:
            return


def get_effective_driver(config_driver: str, env=None) -> str:
    env = os.environ if env is None else env
    return env.get("AUTOVISOR_DRIVER", config_driver).strip().lower()


def resolve_browser_channel(driver: str) -> str | None:
    if driver == "edge":
        return "msedge"
    if driver == "chromium":
        return None
    return driver


def resolve_executable_path(driver: str, configured_path: str) -> str | None:
    path = configured_path.strip().strip("\"'")
    if not path or driver == "chromium":
        return None
    if path.endswith(".app"):
        app_name = Path(path).stem
        return str(Path(path) / "Contents" / "MacOS" / app_name)
    return path


def resolve_cdp_endpoint(
    configured_url: str,
    env=None,
    active_port_path: Path | None = None,
) -> str:
    env = os.environ if env is None else env
    if env.get("AUTOVISOR_CDP_URL"):
        return env["AUTOVISOR_CDP_URL"].strip()

    configured_url = configured_url.strip()
    default_url = "http://127.0.0.1:9222"
    if configured_url and configured_url != default_url:
        return configured_url

    if active_port_path is None and sys.platform == "darwin":
        active_port_path = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Google"
            / "Chrome"
            / "DevToolsActivePort"
        )
    if active_port_path and active_port_path.is_file():
        lines = active_port_path.read_text(encoding="utf-8").splitlines()
        if len(lines) >= 2 and lines[0].isdigit() and lines[1].startswith("/devtools/browser/"):
            return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
    return configured_url or default_url


def is_loopback_cdp_endpoint(endpoint: str) -> bool:
    host = (urlparse(endpoint).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _launch_args(config) -> dict:
    driver = get_effective_driver(config.driver)
    channel = resolve_browser_channel(driver)
    executable_path = resolve_executable_path(driver, config.exe_path)
    args = {
        "headless": False,
        "args": [
            "--window-size=1600,900",
            "--window-position=100,100",
        ],
    }
    if executable_path:
        args["executable_path"] = executable_path
    elif channel:
        args["channel"] = channel
    return args


async def _launch_browser(playwright: Playwright, config, logger) -> Browser:
    launch_args = _launch_args(config)
    try:
        return await playwright.chromium.launch(**launch_args)
    except TargetClosedError as exc:
        logger.log_exception("首次启动浏览器失败,准备重试.", exc)
        return await playwright.chromium.launch(**launch_args)


async def create_browser_session(
    playwright: Playwright,
    config,
    cookies,
    logger,
) -> BrowserSession:
    if config.attach_existing_chrome:
        cdp_endpoint = resolve_cdp_endpoint(config.cdp_url)
        if not is_loopback_cdp_endpoint(cdp_endpoint):
            raise RuntimeError("为避免凭据泄露，CDP 端点只允许连接本机 loopback 地址")
        logger.info("正在连接现有 Chrome 的远程调试端点...")
        page = None
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_endpoint)
            if not browser.contexts:
                raise RuntimeError("Chrome CDP 连接成功,但没有可用浏览器上下文")
            context = browser.contexts[0]
            page = await context.new_page()
            attached = True
            logger.info("已连接现有 Chrome,将复用当前登录状态.")
            await _prepare_page(page, logger)
            return BrowserSession(browser, context, page, attached)
        except BaseException as exc:
            if page is not None and not page.is_closed():
                try:
                    await page.close()
                except TargetClosedError:
                    pass
            if not isinstance(exc, Exception) or isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(
                "无法连接现有 Chrome; 请启用 chrome://inspect/#remote-debugging, "
                "或将 attachExistingChrome 设为 False"
            ) from exc
    else:
        logger.info(f"正在启动 {config.driver} 浏览器...")
        browser = await _launch_browser(playwright, config, logger)
        try:
            context = await browser.new_context()
            if cookies:
                await context.add_cookies(cookies)
                logger.info("已加载 Cookies!")
            else:
                logger.info("未找到 Cookies,将跳转至登录页.")
            page = await context.new_page()
            await _prepare_page(page, logger)
            return BrowserSession(browser, context, page, False)
        except BaseException:
            try:
                await browser.close()
            except TargetClosedError:
                pass
            raise


async def _prepare_page(page: Page, logger) -> None:
    stealth_path = Path(logger.runtime_root) / "res" / "stealth.min.js"
    if stealth_path.is_file():
        await page.add_init_script(path=str(stealth_path))
        logger.debug("stealth.js执行完成.")
    page.set_default_timeout(24 * 3600 * 1000)
