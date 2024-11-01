import re
import sys
import platform
import traceback
import zipfile
import os
from importlib import import_module
import requests
from requests import HTTPError
from modules.progress import show_progress
from modules.logger import Logger

logger = Logger()

def extract_whl(whl_file, extract_to):
    # 检查是否是一个 zip 文件
    if not zipfile.is_zipfile(whl_file):
        logger.error(f"{whl_file} 不是一个有效的 .whl 文件!")
        return

    # 打开并解压 .whl 文件
    with zipfile.ZipFile(whl_file, 'r') as whl_zip:
        whl_zip.extractall(extract_to)
        logger.info(f"已将 {whl_file} 解压到: {extract_to}")


def get_system_architecture():
    arch = platform.architecture()[0]
    if arch == "64bit":
        return "win_amd64"
    else:
        return "win32"


def download_wheel(package_name, version=None):
    # 生成清华镜像源 URL
    base_url = f"https://pypi.tuna.tsinghua.edu.cn/simple/{package_name}/"

    # 请求包的页面，找到匹配的 .whl 文件
    logger.info(f"正在从清华源下载 {package_name} 的 .whl 文件...")
    response = requests.get(base_url)
    response.raise_for_status()
    # 获取系统架构
    arch = get_system_architecture()
    # 匹配 .whl 文件链接
    pattern = re.compile(rf'href="([^"]+{arch}\.whl[^"]+)"')
    whl_links = pattern.findall(response.text)
    if not whl_links:
        raise ValueError("没有找到合适版本的 .whl 文件")

    # 如果指定版本，优先选择匹配该版本的链接
    if version:
        version_links = [link for link in whl_links if version in link]
        if version_links:
            wheel_url = version_links[0]
        else:
            raise ValueError(f"找不到版本为 {version} 的 .whl 文件")
    else:
        wheel_url = whl_links[-1]  # 默认选择最新版本

    # 拼接完整 URL
    wheel_url = f"https://pypi.tuna.tsinghua.edu.cn/simple/{wheel_url}"
    whl_path = wheel_url.split('/')[-1].split("#")[0]

    # 下载 .whl 文件
    response = requests.get(wheel_url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    with open(whl_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=512):
            if chunk:
                f.write(chunk)
                show_progress("下载进度:", current=f.tell(), total=total_size)

    logger.info(f"{whl_path} 下载完成！")
    return whl_path


def install_package(package, version):
    alias = mapping[package]
    try:
        # 尝试导入 package
        module = import_module(alias)
        logger.info(f"{package}-{version} 已安装！")
        return module
    except ImportError:
        # 如果导入失败，则下载安装 .whl 文件
        logger.info(f"{package}-{version} 未安装,正在开始下载...")
        try:
            wheel_path = download_wheel(package, version)
            # 解压 .whl 文件
            extract_whl(wheel_path, "./res")
            logger.info(f"{package}-{version} 安装完成！")
            # 删除安装包
            os.remove(wheel_path)
            return import_module(alias)
        except HTTPError as e:
            logger.write_log(f"[ERROR]{repr(e)}\n{traceback.format_exc()}")
            logger.error(f"{package}-{version} 下载失败！")
            return None
        except Exception as e:
            logger.write_log(f"[ERROR]{repr(e)}\n{traceback.format_exc()}")
            logger.error(f"{package}-{version} 安装失败！")
            return None


# 下载器,启动!
def start():
    modules = []
    sys.path.append("./res")
    for package, version in packages.items():
        module = install_package(package, version)
        modules.append(module)
    return modules


# 设置下载包名和版本（可选）
packages = {
    "numpy": "1.26.4",
    "opencv-python": "4.10.0.82",
}
mapping = {
    "numpy": "numpy",
    "opencv-python": "cv2",
}