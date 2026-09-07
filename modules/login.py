from urllib.parse import urlparse

from playwright.async_api import Page


LOGIN_HOSTS = {"login.zhihuishu.com", "passport.zhihuishu.com"}
LOGIN_USERNAME_SELECTOR = "#lUsername, input[name='mobile']"
LOGIN_PASSWORD_SELECTOR = "#lPassword, input[type='password']"
LOGIN_SUBMIT_SELECTOR = ".wall-sub-btn, .btn-block__grandient_login, button[type='submit']"


def is_login_page(url: str) -> bool:
    """判断 URL 是否仍处于智慧树登录流程。"""
    hostname = (urlparse(url).hostname or "").lower()
    return hostname in LOGIN_HOSTS


async def wait_for_login_complete(
    page: Page, timeout: float = 24 * 3600 * 1000
) -> None:
    """等待页面离开智慧树登录域名。"""
    if not is_login_page(page.url):
        return
    await page.wait_for_url(
        lambda url: not is_login_page(str(url)),
        wait_until="commit",
        timeout=timeout,
    )


async def accept_login_terms(page: Page) -> None:
    """新版登录页存在协议复选框时自动勾选。"""
    checkbox = page.locator("input.el-checkbox__original").first
    if not await checkbox.count():
        return

    if not await checkbox.is_checked():
        # Element UI 的原始 checkbox 通常被隐藏，不能使用 Playwright check。
        await checkbox.evaluate("element => element.click()")
