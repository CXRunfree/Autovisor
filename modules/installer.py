import re
import sys
import platform
import zipfile
import os
import shutil
import glob
import requests
from urllib.parse import urldefrag, urljoin
from importlib import import_module
from modules.progress import show_progress
from modules.logger import Logger
from modules.configs import Config

config = Config()
logger = Logger()


SUPPORTED_PYTHON = ((3, 10), (3, 11), (3, 12))


def validate_python_version(version_info=sys.version_info):
    version = (version_info.major, version_info.minor)
    if version not in SUPPORTED_PYTHON:
        supported = ", ".join(f"{major}.{minor}" for major, minor in SUPPORTED_PYTHON)
        raise RuntimeError(
            f"不支持 Python {version[0]}.{version[1]}，当前仅支持 Python {supported}。"
        )


def wheel_tags(filename):
    name = os.path.basename(filename).split("#", 1)[0]
    if not name.endswith(".whl"):
        return None
    parts = name[:-4].rsplit("-", 3)
    if len(parts) != 4:
        return None
    distribution_version, python_tag, abi_tag, platform_tag = parts
    if "-" not in distribution_version:
        return None
    _, version = distribution_version.rsplit("-", 1)
    return version, python_tag, abi_tag, platform_tag


def is_compatible_wheel(filename, package, version, python_tag, abi_tag, platform_tag):
    tags = wheel_tags(filename)
    if not tags:
        return False
    wheel_version, wheel_python, wheel_abi, wheel_platform = tags
    requested_version = normalize_version(package, version) if version else None
    actual_version = normalize_version(package, wheel_version)
    if (requested_version and actual_version != requested_version) or wheel_platform != platform_tag:
        return False
    python_ok = python_tag in wheel_python or "py3" in wheel_python
    if "abi3" in wheel_abi:
        match = re.fullmatch(r"cp(\d+)", wheel_python)
        if match:
            python_ok = int(python_tag[2:]) >= int(match.group(1))
    abi_ok = abi_tag in wheel_abi or "abi3" in wheel_abi or "none" in wheel_abi
    return python_ok and abi_ok


def build_wheel_url(package_url, wheel_link):
    link, _ = urldefrag(wheel_link)
    return urljoin(package_url, link)


def normalize_version(package, version):
    if package == "opencv-python":
        return ".".join(version.split(".")[:3])
    return version


def get_runtime_root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_res_dir():
    return os.path.join(get_runtime_root(), "packages")


def add_runtime_search_paths(res_dir):
    runtime_paths = [
        res_dir,
        os.path.join(res_dir, "cv2"),
        os.path.join(res_dir, "numpy.libs"),
    ]
    for path in runtime_paths:
        if not os.path.isdir(path):
            continue
        if path not in sys.path:
            sys.path.insert(0, path)
        if os.name == "nt":
            try:
                os.add_dll_directory(path)
            except (AttributeError, FileNotFoundError, OSError):
                pass


def test_mirrors(config_obj=config):
    available_mirrors = []
    for name, url in config_obj.mirrors.items():
        logger.info(f"正在测试 {name} 镜像源...")
        try:
            response = requests.get(url + "/simple/0", headers=config_obj.headers, timeout=5)  # 设置超时，避免卡住
            if response.status_code == 200:
                logger.info(f"{name} 镜像源 连接成功！")
                available_mirrors.append((name, url))
            else:
                logger.error(f"{name} 镜像源 连接失败（状态码 {response.status_code}）！")
        except requests.exceptions.RequestException as e:
            logger.error(f"{name} 镜像源 连接失败：{e}")
            continue

    if not available_mirrors:
        logger.error("所有镜像源都不可用！")
    return available_mirrors


def extract_whl(whl_path, extract_to):
    # 检查是否是一个 zip 文件
    if not zipfile.is_zipfile(whl_path):
        raise ValueError(f"{whl_path} 不是一个有效的 .whl 文件!")

    # 打开并解压 .whl 文件
    with zipfile.ZipFile(whl_path, 'r') as whl_zip:
        whl_zip.extractall(extract_to)
        logger.info(f"已将 {whl_path} 解压到: {extract_to}")


def clear_package_files(package, extract_to):
    package_patterns = {
        "numpy": ("numpy", "numpy.libs", "numpy-*.dist-info"),
        "opencv-python": ("cv2", "opencv_python-*.dist-info", "opencv_python.libs"),
    }
    for pattern in package_patterns[package]:
        for path in glob.glob(os.path.join(extract_to, pattern)):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)


def get_system_arch():
    arch = platform.architecture()[0]
    if arch == "64bit":
        return "win_amd64"
    else:
        return "win32"


def download_wheel(mirror_name, base_url, package_name, version=None, config_obj=config):
    # 构造 URL
    package_url = f"{base_url}/simple/{package_name}/"

    # 发送请求，找到匹配的 .whl 文件
    logger.info(f"正在从镜像源下载 {package_name}.whl 文件...")
    response = requests.get(package_url, headers=config_obj.headers)
    response.raise_for_status()
    validate_python_version()
    # 获取当前 Python 与系统架构
    arch = get_system_arch()
    python_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    abi_tag = python_tag
    # 匹配 .whl 文件链接，再按 Python、ABI、平台和版本筛选
    pattern = re.compile(r"href=[\"']([^\"']+\.whl(?:#[^\"']*)?)[\"']", re.IGNORECASE)
    whl_links = [link for link in pattern.findall(response.text)
                 if is_compatible_wheel(link, package_name, version, python_tag, abi_tag, arch)]
    if not whl_links:
        raise ValueError(f"没有找到合适版本的 {package_name}.whl 文件!")

    wheel_link = whl_links[0]

    # 拼接完整 URL
    wheel_url = build_wheel_url(package_url, wheel_link)
    whl_path = os.path.basename(wheel_url)

    # 下载 .whl 文件
    response = requests.get(wheel_url, headers=config_obj.headers, stream=True)
    response.raise_for_status()
    total_size = int(response.headers.get('content-length', 0))
    with open(whl_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=512):
            if chunk:
                f.write(chunk)
                show_progress("下载进度:", current=f.tell(), total=total_size)

    if not zipfile.is_zipfile(whl_path):
        os.remove(whl_path)
        raise ValueError(f"下载的 {whl_path} 不是有效的 wheel 文件,请检查镜像源响应。")

    logger.info(f"{whl_path} 下载完成！")
    return whl_path


def is_installed(package, version):
    try:
        # 尝试导入 package
        module = import_module(mapping[package])
        installed_version = getattr(module, "__version__", None)
        expected_version = normalize_version(package, version)
        if installed_version and installed_version != expected_version:
            logger.warn(f"检测到 {package}-{installed_version}，与目标版本 {version} 不一致，将重新安装。")
            return None, False
        logger.info(f"{package}-{version} 已安装！")
        return module, True
    except ImportError:
        return None, False


def install_package(package, version, mirrors, config_obj=config):
    alias = mapping[package]
    res_dir = get_res_dir()
    logger.info(f"{package}-{version} 未安装，开始下载...")

    for mirror_name, base_url in mirrors:
        wheel_path = None
        try:
            wheel_path = download_wheel(mirror_name, base_url, package, version, config_obj)
            clear_package_files(package, res_dir)
            extract_whl(wheel_path, res_dir)
            add_runtime_search_paths(res_dir)
            module = import_module(alias)
            logger.info(f"{package}-{version} 安装完成!")
            return module
        except Exception as e:
            logger.error(f"{package}-{version} 使用 {mirror_name} 镜像源失败，将尝试下一个镜像源：{e}")
        finally:
            if wheel_path and os.path.exists(wheel_path):
                os.remove(wheel_path)

    logger.error(f"{package}-{version} 在所有镜像源上的处理都失败！")
    return None


# 下载器,启动!
def start(config_obj=config):
    validate_python_version()
    modules = []
    res_dir = get_res_dir()
    os.makedirs(res_dir, exist_ok=True)
    add_runtime_search_paths(res_dir)
    mirrors = None  # 避免重复测试镜像
    for package, version in packages.items():
        module, exist = is_installed(package, version)
        if not exist:
            if mirrors is None:  # 仅在首次遇到导入失败时测试镜像
                mirrors = test_mirrors(config_obj)
                if not mirrors:  # 如果所有镜像都失败，直接退出
                    logger.error("没有可用的镜像源，程序终止!")
                    sys.exit(-1)
            module = install_package(package, version, mirrors, config_obj)
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
