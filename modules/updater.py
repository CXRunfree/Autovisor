# encoding=utf-8
import os
import re

import requests

from modules.version import __version__

REPO = "CXRunfree/Autovisor"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_PAGE_URL = f"https://github.com/{REPO}/releases/latest"
REQUEST_TIMEOUT = 5

# 发行包命名形如 Autovisor-3.18.0-windows-amd64.zip
_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_WINDOWS_ASSET_KEYWORD = "windows-amd64"


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


def pick_download_url(release):
    """仅 Windows 提供安装包直链, 其他平台引导到发行页。"""
    if os.name != "nt":
        return None
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if _WINDOWS_ASSET_KEYWORD in name and asset.get("browser_download_url"):
            return asset["browser_download_url"]
    return None


def fetch_latest_release(timeout=REQUEST_TIMEOUT, session=None):
    session = session or requests
    response = session.get(
        LATEST_RELEASE_API,
        timeout=timeout,
        headers={"Accept": "application/vnd.github+json"},
    )
    response.raise_for_status()
    return response.json()


def check_for_update(logger, current_version=__version__, timeout=REQUEST_TIMEOUT, session=None):
    """查询最新 Release, 对比当前版本并打印结果。

    3.18.1 起 tag 使用版本号; 旧版 release 的 tag 是日期(2026/9/15),
    因此优先解析 tag_name, 失败再回退到 release 名称。
    检查失败(断网、限流等)只记录 debug 日志, 不影响程序运行。
    """
    current = parse_version(current_version)
    try:
        release = fetch_latest_release(timeout=timeout, session=session)
    except Exception as exc:
        logger.debug(f"检查更新失败: {logger.summarize_exception(exc)}")
        return None

    latest = parse_version(release.get("tag_name")) or parse_version(release.get("name"))
    if latest is None:
        logger.debug("无法解析最新版本号, 跳过更新检查.")
        return None
    if not is_newer(latest, current):
        logger.info(f"当前版本{current_version},已是最新版本.")
        return None

    page_url = release.get("html_url") or RELEASE_PAGE_URL
    download_url = pick_download_url(release)
    logger.info(f"检测到新版本 {format_version(latest)} (当前 {current_version}), 请前往更新!")
    logger.info(f"更新说明与下载: {page_url}")
    if download_url:
        logger.info(f"安装包直链: {download_url}")
    return page_url
