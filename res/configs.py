#encoding=utf-8
import configparser
import re

_config = configparser.ConfigParser()
_config.read('account.ini')
# 读取用户配置
username = _config.get('user-account', 'username', raw=True)
password = _config.get('user-account', 'password', raw=True)
driver = _config.get('set-driver', 'driver', raw=True)
course_urls = _config.get('course-url', 'course_urls', raw=True).split(",\n")

# 全局常量
login_url = "https://passport.zhihuishu.com/login"
# 登录
login_js = '''document.getElementsByClassName("wall-sub-btn")[0].click();'''
block_js = '''return document.getElementsByClassName("yidun_jigsaw")[0].src'''
bg_js = '''return document.getElementsByClassName("yidun_bg-img")[0].src'''
# 弹窗
pop_js = '''document.getElementsByClassName("iconfont iconguanbi")[0].click();'''
# 其他
night_js = '''document.getElementsByClassName("Patternbtn-div")[0].click()'''
revise_speed_name = '''document.getElementsByClassName("speedTab15")[0].innerText = "X 1.8";'''
course_match_rule = re.compile("recruitAndCourseId=[a-zA-Z0-9]+")
