# encoding=utf-8
import configparser
import json
import os
import re
import sys


class ConfigError(Exception):
    pass


class Config:
    def __init__(self, config_path=None, mirrors_path=None):
        self.config_path = config_path
        if config_path:
            self._config = configparser.ConfigParser()
            # 用户常量
            self._read_config()
            self.driver = self.get_driver()
            self.username = self._config.get('user-account', 'username', raw=True)
            self.password = self._config.get('user-account', 'password', raw=True)
            # 浏览器选项
            self.exe_path = self._config.get('browser-option', 'EXE_PATH', raw=True)
            self.attach_existing_chrome = self.get_bool_field('browser-option', 'attachExistingChrome', fallback=False)
            self.cdp_url = self._config.get('browser-option', 'cdpUrl', raw=True, fallback='http://127.0.0.1:9222').strip()
            # 脚本选项
            self.enableAutoCaptcha = self.get_bool_field('script-option', 'enableAutoCaptcha')
            self.enableHideWindow = self.get_bool_field('script-option', 'enableHideWindow')
            self.showDonateCode = self.get_bool_field("script-option", "showDonateCode")
            # 课程选项
            self.soundOff = self.get_bool_field('course-option', 'soundOff')
            self.course_match_rule = re.compile("https://[-A-Za-z0-9+&@#/%?=~_|!:,.;]+[-A-Za-z0-9+&@#/%=~_|]")
            self.course_urls = self.get_course_urls()
        # 登录
        self.login_url = "https://passport.zhihuishu.com/login"
        self.block_js = '''return document.getElementsByClassName("yidun_jigsaw")[0].src'''
        self.bg_js = '''return document.getElementsByClassName("yidun_bg-img")[0].src'''
        # 弹窗
        self.pop_js = '''document.getElementsByClassName("iconfont iconguanbi")[0].click();'''

        self.mirrors = self._read_mirrors(mirrors_path)

    def _read_config(self) -> None:
        if not os.path.isfile(self.config_path):
            raise ConfigError(f"未找到配置文件: {self.config_path}")
        try:
            self._config.read(self.config_path, encoding='utf-8-sig')
        except UnicodeDecodeError:
            self._config.read(self.config_path, encoding='gbk')
        required_sections = {
            "user-account", "browser-option", "script-option", "course-option", "course-url"
        }
        missing_sections = required_sections - set(self._config.sections())
        if missing_sections:
            raise ConfigError(
                f"配置文件缺少必要配置段: {', '.join(sorted(missing_sections))}"
            )

    def _read_mirrors(self, mirrors_path=None) -> dict:
        if not mirrors_path:
            if self.config_path:
                base_dir = os.path.dirname(self.config_path)
            elif getattr(sys, "frozen", False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            mirrors_path = os.path.join(base_dir, "data", "mirrors.json")
        if not os.path.isfile(mirrors_path):
            raise ConfigError(f"未找到镜像配置文件: {mirrors_path}")
        try:
            with open(mirrors_path, "r", encoding="utf-8-sig") as file:
                mirrors = json.load(file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConfigError(f"镜像配置文件无效: {mirrors_path}") from error
        if not isinstance(mirrors, dict):
            raise ConfigError("镜像配置文件必须是 JSON 对象")
        mirrors = {str(name): str(url).strip() for name, url in mirrors.items() if str(url).strip()}
        if not mirrors:
            raise ConfigError("镜像配置文件至少需要配置一个镜像源")
        return mirrors

    def get_driver(self) -> str:
        driver = self._config.get('browser-option', 'driver', raw=True)
        if not driver:
            driver = "edge"
        return driver.lower()

    def get_bool_field(self, section: str, option: str, fallback: bool = False) -> bool:
        field = self._config.get(section, option, raw=True, fallback=str(fallback)).strip().lower()
        if field == "true":
            return True
        else:
            return False

    def get_course_urls(self) -> list:
        course_urls = []
        _options = self._config.options("course-url")
        for _option in _options:
            course_url = self._config.get("course-url", _option, raw=True)
            matched = re.findall(self.course_match_rule, course_url)
            if not matched:
                print(f"\"{course_url.strip()}\"\n不是一个有效网址,将忽略该网址.")
                continue
            course_urls.append(course_url)
        return course_urls

    # @property修饰器可设置属性
    # 这样写可实时响应配置变化
    def _safe_get_float(self, section: str, option: str, default: float = 0.0) -> float:
        try:
            value = self._config.get(section, option, raw=True, fallback='').strip()
            if not value:
                return default
            return float(value)
        except (ValueError, configparser.Error):
            return default

    @property
    def limitMaxTime(self) -> float:
        self._read_config()
        return self._safe_get_float('course-option', 'limitMaxTime', 0.0)

    @property
    def limitSpeed(self) -> float:
        self._read_config()
        speed = self._safe_get_float('course-option', 'limitSpeed', 1.0)
        return min(max(speed, 0.5), 1.8)


# 以下模板用于启动时自动生成缺失的配置文件, 与 *.example 保持一致。
CONFIG_TEMPLATE = """[user-account]
;配置账号密码，留空则打开网页后需手动登录
;留空时首次运行会在终端引导输入一次并自动保存到本文件, 之后即可全自动登录
username =
password =

[browser-option]
;配置浏览器,可选 Edge 或 Chrome
driver = Edge
;指定浏览器所在路径,不填则使用默认路径
EXE_PATH =

[script-option]
;是否自动过登录时的滑块验证(默认:True)
enableAutoCaptcha = True
;是否自动隐藏浏览器窗口(默认:False)
enableHideWindow = False
;是否展示赞赏码(默认:True)
showDonateCode = True

[course-option]
;限制每门课程刷课时长/min (不限制:0)
limitMaxTime = 30
;限定播放倍速 (最高:1.8)
limitSpeed = 1.0
;设置是否静音播放 (默认:True)
soundOff = True

[course-url]
;配置要学习的课程链接,支持(智慧)共享课
;可继续添加多个课程链接
URL1 =
URL2 =
URL3 =
URL4 =
URLn =
"""

LLM_TEMPLATE = {
    "api_key": "",
    "api_base": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "auto_submit": False,
}

DEFAULT_MIRRORS = {
    "Huawei": "https://mirrors.huaweicloud.com/repository/pypi",
    "Aliyun": "https://mirrors.aliyun.com/pypi",
    "Tsinghua": "https://pypi.tuna.tsinghua.edu.cn",
    "Official": "https://pypi.org",
}


def _runtime_root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_config_files(config_path: str) -> list:
    """启动时补齐缺失的配置文件, 只创建、绝不覆盖已有文件。

    config.ini 按传入路径生成; data/llm.json 与 data/mirrors.json 固定生成在
    运行根目录的 data/ 下, 与程序运行时的读取位置保持一致。
    返回本次新建文件的路径列表, 由调用方负责提示用户。
    """
    created = []

    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8", newline="\n") as file:
            file.write(CONFIG_TEMPLATE)
        created.append(config_path)

    data_dir = os.path.join(_runtime_root(), "data")
    os.makedirs(data_dir, exist_ok=True)
    for name, content in (
        ("llm.json", LLM_TEMPLATE),
        ("mirrors.json", DEFAULT_MIRRORS),
    ):
        path = os.path.join(data_dir, name)
        if os.path.exists(path):
            continue
        with open(path, "w", encoding="utf-8") as file:
            json.dump(content, file, ensure_ascii=False, indent=2)
            file.write("\n")
        created.append(path)
    return created
