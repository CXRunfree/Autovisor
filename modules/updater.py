# encoding=utf-8
import os
import re
import warnings
from urllib.parse import urlparse

import requests

from modules.version import __version__

REPO = "CXRunfree/Autovisor"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_PAGE_URL = f"https://github.com/{REPO}/releases/latest"
REQUEST_TIMEOUT = 5
REQUEST_HEADERS = {"Accept": "application/vnd.github+json"}

# 发行包命名形如 Autovisor-3.18.0-windows-amd64.zip
_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_WINDOWS_ASSET_KEYWORD = "windows-amd64"

# 只展示 GitHub 官方域名的链接, 避免被中间人替换成其他下载地址
_TRUSTED_HOSTS = ("github.com", "githubusercontent.com")


def parse_version(text):
    """从 "Autovisor-3.18.0" 之类的文本中提取 (major, minor, patch)。"""
    if not text:
        return None
    match = _VERSION_PATTERN.search(str(text))
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def format_version(version):
    return ".".join(str(part) for part in version)


def is_newer(latest, current):
    """latest 是否比 current 新; 任一无法解析时视为无更新。"""
    if latest is None or current is None:
        return False
    return latest > current


def is_trusted_url(url):
    """链接是否为 GitHub 官方域名(https)。"""
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == trusted or host.endswith("." + trusted) for trusted in _TRUSTED_HOSTS
    )


def pick_download_url(release):
    """仅 Windows 提供安装包直链, 其他平台引导到发行页。"""
    if os.name != "nt":
        return None
    for asset in release.get("assets") or []:
        url = asset.get("browser_download_url")
        if _WINDOWS_ASSET_KEYWORD in str(asset.get("name") or "") and is_trusted_url(url):
            return url
    return None


def fetch_latest_release(timeout=REQUEST_TIMEOUT, session=None, verify=True):
    session = session or requests
    if verify:
        response = session.get(
            LATEST_RELEASE_API, timeout=timeout, headers=REQUEST_HEADERS
        )
    else:
        # 关闭校验时 urllib3 会打印 InsecureRequestWarning, 这里静默处理
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            response = session.get(
                LATEST_RELEASE_API,
                timeout=timeout,
                headers=REQUEST_HEADERS,
                verify=False,
            )
    response.raise_for_status()
    return response.json()


def check_for_update(logger, current_version=__version__, timeout=REQUEST_TIMEOUT, session=None):
    """查询最新 Release, 对比当前版本并打印结果。

    3.18.1 起 tag 使用版本号; 旧版 release 的 tag 是日期(2026/9/15),
    因此优先解析 tag_name, 失败再回退到 release 名称。
    部分网络(代理/加速工具)会替换 GitHub 证书且未安装对应根证书, 导致校验失败,
    此时关闭校验重试一次; 版本查询不涉及敏感数据, 但下载链接只展示 GitHub 官方域名。
    检查失败(断网、限流等)只记录 debug 日志, 不影响程序运行。
    """
    current = parse_version(current_version)
    try:
        release = fetch_latest_release(timeout=timeout, session=session)
    except requests.exceptions.SSLError as exc:
        logger.debug(f"证书校验失败: {logger.summarize_exception(exc)}, 关闭校验重试.")
        logger.event("更新检查降级", 原因="证书校验失败", 错误=logger.summarize_exception(exc))
        try:
            release = fetch_latest_release(timeout=timeout, session=session, verify=False)
        except Exception as retry_exc:
            logger.debug(f"检查更新失败: {logger.summarize_exception(retry_exc)}")
            logger.event("更新检查", 结果="失败", 错误=logger.summarize_exception(retry_exc))
            return None
    except Exception as exc:
        logger.debug(f"检查更新失败: {logger.summarize_exception(exc)}")
        logger.event("更新检查", 结果="失败", 错误=logger.summarize_exception(exc))
        return None

    latest = parse_version(release.get("tag_name")) or parse_version(release.get("name"))
    if latest is None:
        logger.debug("无法解析最新版本号, 跳过更新检查.")
        return None
    if not is_newer(latest, current):
        logger.info(f"当前版本{current_version},已是最新版本.")
        logger.event("更新检查", 当前=current_version, 结果="已是最新")
        return None

    page_url = release.get("html_url")
    if not is_trusted_url(page_url):
        page_url = RELEASE_PAGE_URL
    download_url = pick_download_url(release)
    logger.info(f"检测到新版本 {format_version(latest)} (当前 {current_version}), 请前往更新!")
    logger.info(f"更新说明与下载: {page_url}")
    logger.event(
        "更新检查",
        当前=current_version,
        最新=format_version(latest),
        结果="发现新版本",
        下载页=page_url,
    )
    if download_url:
        logger.info(f"安装包直链: {download_url}")
    return page_url
