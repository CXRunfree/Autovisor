import re
import sys
import platform
import traceback
import zipfile
import os
import requests
from importlib import import_module
from modules.progress import show_progress
from modules.logger import Logger
from modules.configs import Config

config = Config()
logger = Logger()


def test_mirrors():
    for name, url in config.mirrors.items():
        logger.info(f"正在测试 {name} 镜像源...")
        try:
            response = requests.get(url + "/simple/0", headers=config.headers, timeout=5)  # 设置超时，避免卡住
            if response.status_code == 200:
                logger.info(f"{name} 镜像源 连接成功！")
                return name, url
            else:
                logger.error(f"{name} 镜像源 连接失败（状态码 {response.status_code}）！")
        except requests.exceptions.RequestException as e:
            logger.error(f"{name} 镜像源 连接失败：{e}")
            continue

    logger.error("所有镜像源都不可用！")
    return None, None


def extract_whl(whl_path, extract_to):
    # 检查是否是一个 zip 文件
    if not zipfile.is_zipfile(whl_path):
        raise ValueError(f"{whl_path} 不是一个有效的 .whl 文件!")

    # 打开并解压 .whl 文件
    with zipfile.ZipFile(whl_path, 'r') as whl_zip:
        whl_zip.extractall(extract_to)
        logger.info(f"已将 {whl_path} 解压到: {extract_to}")


def get_system_arch():
    arch = platform.architecture()[0]
    if arch == "64bit":
        return "win_amd64"
    else:
        return "win32"


def download_wheel(mirror_name, base_url, package_name, version=None):
    # 构造 URL
    package_url = f"{base_url}/simple/{package_name}/"

    # 发送请求，找到匹配的 .whl 文件
    logger.info(f"正在从镜像源下载 {package_name}.whl 文件...")
    response = requests.get(package_url, headers=config.headers)
    response.raise_for_status()
    # 获取系统架构
    arch = get_system_arch()
    # 匹配 .whl 文件链接
    pattern = re.compile(rf'href="(?:\.\./)*([^"]+{arch}\.whl[^"]+)"')
    whl_links = pattern.findall(response.text)
    if not whl_links:
        raise ValueError(f"没有找到合适版本的 {package_name}.whl 文件!")

    # 如果指定版本，优先选择匹配该版本的链接
    if version:
        version_links = [link for link in whl_links if version in link]
        if version_links:
            wheel_link = version_links[0]
        else:
            raise ValueError(f"找不到版本为 {version} 的{package_name}.whl 文件")
    else:
        wheel_link = whl_links[-1]  # 默认选择最新版本

    # 拼接完整 URL
    wheel_url = f"{base_url}/{wheel_link}" if mirror_name != "官方" else wheel_link
    whl_path = wheel_url.split('/')[-1].split("#")[0]

    # 下载 .whl 文件
    response = requests.get(wheel_url, headers=config.headers, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    with open(whl_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=512):
            if chunk:
                f.write(chunk)
                show_progress("下载进度:", current=f.tell(), total=total_size)

    logger.info(f"{whl_path} 下载完成！")
    return whl_path


def is_installed(package, version):
    try:
        # 尝试导入 package
        module = import_module(mapping[package])
        logger.info(f"{package}-{version} 已安装！")
        return module, True
    except ImportError:
        return None, False


def install_package(package, version, mirror_name, base_url):
    alias = mapping[package]
    logger.info(f"{package}-{version} 未安装，开始下载...")

    try:
        wheel_path = download_wheel(mirror_name, base_url, package, version)
        extract_whl(wheel_path, "./res")
        logger.info(f"{package}-{version} 安装完成!")

        os.remove(wheel_path)  # 清理下载的 .whl 文件
        return import_module(alias)

    except Exception as e:
        error_message = f"{package}-{version} 处理失败！\n错误详情: {repr(e)}"
        logger.write_log(f"[ERROR] {error_message}\n{traceback.format_exc()}")
        logger.error(error_message)
        return None


# 下载器,启动!
def start():
    modules = []
    sys.path.append("./res")
    mirror_name, base_url = None, None  # 避免重复测试镜像
    for package, version in packages.items():
        module, exist = is_installed(package, version)
        if not exist:
            if not mirror_name:  # 仅在首次遇到导入失败时测试镜像
                mirror_name, base_url = test_mirrors()
                if not mirror_name:  # 如果所有镜像都失败，直接退出
                    logger.error("没有可用的镜像源，程序终止!")
                    sys.exit(-1)
            module = install_package(package, version, mirror_name, base_url)
            if not module:
                logger.save()
                sys.exit(-1)  # 下载或安装失败，立即退出
        modules.append(module)

    return modules


# 设置下载包名和版本（可选）
packages = {
    "numpy": "1.26.4",
    "opencv-python": "4.10.0.82",
}
# 包名映射
mapping = {
    "numpy": "numpy",
    "opencv-python": "cv2",
}

if __name__ == "__main__":
    start()
