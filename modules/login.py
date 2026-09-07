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
    terms = page.locator(".privacy-checkbox").first
    if not await terms.count() or not await terms.is_visible():
        return

    checkbox = terms.locator("input[type='checkbox']").first
    if await checkbox.count() and not await checkbox.is_checked():
        await terms.click()
