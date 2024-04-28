# encoding=utf-8
import configparser
import re


class Config:
    def __init__(self):
        self._config = configparser.ConfigParser()
        self.filename = 'configs.ini'
        # 读取用户常量
        self._config.read(self.filename)
        self.username = self._config.get('user-account', 'username', raw=True)
        self.password = self._config.get('user-account', 'password', raw=True)
        self.driver = self._config.get('custom-option', 'driver', raw=True)
        self.exe_path = self._config.get('custom-option', 'EXE_PATH', raw=True)
        self.course_urls = self.get_course_urls()
        # 全局常量
        self.login_url = "https://passport.zhihuishu.com/login"
        # 登录
        self.login_js = '''document.getElementsByClassName("wall-sub-btn")[0].click();'''
        self.block_js = '''return document.getElementsByClassName("yidun_jigsaw")[0].src'''
        self.bg_js = '''return document.getElementsByClassName("yidun_bg-img")[0].src'''
        # 弹窗
        self.pop_js = '''document.getElementsByClassName("iconfont iconguanbi")[0].click();'''
        self.gjh_pop = '''document.getElementsByClassName("course-warn")[0].click();'''
        self.close_gjh = '''document.getElementsByClassName("rlready-bound-btn")[0].click();'''
        # 其他
        self.night_js = '''document.getElementsByClassName("Patternbtn-div")[0].click()'''
        self.course_match_rule = re.compile("recruitAndCourseId=[a-zA-Z0-9]+")

    def get_course_urls(self):
        course_urls = []
        _options = self._config.options("course-url")
        for _option in _options:
            course_url = self._config.get("course-url", _option, raw=True)
            course_urls.append(course_url)
        return course_urls

    #@property修饰器可设置属性
    #这样写可实时响应配置变化
    @property
    def limitMaxTime(self):
        self._config.read(self.filename)
        return float(self._config.get('custom-option', 'limitMaxTime'))

    @property
    def limitSpeed(self):
        self._config.read(self.filename)
        return float(self._config.get('custom-option', 'limitSpeed', raw=True))

    @property
    def revise_speed_name(self):
        return f'''document.getElementsByClassName("speedTab15")[0].innerText = "X {self.limitSpeed}";'''

