# encoding=utf-8
import asyncio
import os
import re
import traceback
import json
import time
from json import JSONDecodeError
from playwright.sync_api import sync_playwright
from playwright._impl._errors import TargetClosedError, TimeoutError

# constants
login_url = "https://passport.zhihuishu.com/login"
# Xpath
option1 = '//*[@id="playTopic-dialog"]/div/div[2]/div/div[1]/div/div/div[2]/ul/li[1]/div[2]'
option2 = '//*[@id="playTopic-dialog"]/div/div[2]/div/div[1]/div/div/div[2]/ul/li[2]/div[2]'
# javascript
# 登录
login_js = '''document.getElementsByClassName("wall-sub-btn")[0].click();'''
block_js = '''return document.getElementsByClassName("yidun_jigsaw")[0].src'''
bg_js = '''return document.getElementsByClassName("yidun_bg-img")[0].src'''
# 弹窗
pop_js = '''document.getElementsByClassName("iconfont iconguanbi")[0].click();'''
# pop2_js = '''document.evaluate('//*[@id="app"]/div/div[1]/div[1]/span/a',document).iterateNext().click();'''
# 其他
night_js = '''document.getElementsByClassName("Patternbtn-div")[0].click()'''


def auto_login(_user, _pwd):
    if not user or not pwd:
        raise UserWarning
    page.goto(login_url)
    page.locator('#lUsername').fill(_user)
    page.locator('#lPassword').fill(_pwd)
    page.wait_for_timeout(500)
    page.evaluate(login_js)


def init_page():
    # 启动自带浏览器
    if driver == "Chrome":
        print("正在启动Chrome浏览器...")
        browser = p.chromium.launch(channel="chrome", headless=False)
    else:
        print("正在启动Edge浏览器...")
        browser = p.chromium.launch(channel="msedge", headless=False)
    context = browser.new_context()
    page = context.new_page()
    # 设置程序超时时限
    page.set_default_timeout(300 * 1000 * 1000)
    # 设置浏览器视口大小
    viewsize = page.evaluate('''() => {
                       return {width: window.screen.availWidth,height: window.screen.availHeight};}''')
    viewsize["height"] -= 50
    page.set_viewport_size(viewsize)
    return page


def optimize_page():
    # 关闭学习须知
    page.evaluate(pop_js)
    # 根据当前时间切换夜间模式
    hour = time.localtime().tm_hour
    if hour >= 18 or hour < 7:
        page.wait_for_selector(".Patternbtn-div")
        page.evaluate(night_js)
    try:
        # 关闭上方横幅
        page.wait_for_selector(".exploreTip", timeout=500)
        page.query_selector('a:has-text("不再提示")').click()
    finally:
        return


def get_lesson_name():
    title_ele = page.wait_for_selector("#lessonOrder")
    page.wait_for_timeout(500)
    title_ = title_ele.get_attribute("title")
    return title_


def move_mouse(elem):
    elem.hover()
    pos = elem.bounding_box()
    # 计算移动的目标位置
    target_x = pos['x'] + 30
    target_y = pos['y'] + 30
    page.mouse.move(target_x, target_y)


def get_progress():
    curt = "0%"
    canvas = page.wait_for_selector(".videoArea")
    move_mouse(canvas)
    progress = page.query_selector(".current_play").query_selector(".progress-num")
    if not progress:
        finish = page.query_selector(".current_play").query_selector(".time_icofinish")
        if finish:
            curt = "100%"
    else:
        curt = progress.text_content()
    return curt


def check_play():
    canvas = page.wait_for_selector(".videoArea")
    move_mouse(canvas)
    canvas.click()


def video_optimize():
    canvas = page.wait_for_selector(".videoArea")
    move_mouse(canvas)
    page.wait_for_selector(".volumeBox").click()  # 设置静音
    page.wait_for_selector(".definiBox").hover()  # 切换流畅画质
    low_quality = page.query_selector(".line1bq")
    low_quality.hover()
    low_quality.click()
    page.wait_for_selector(".speedBox").hover()  # 切换1.5倍速
    max_speed = page.query_selector(".speedTab15")
    max_speed.hover()
    max_speed.click()


def play_next():
    canvas = page.wait_for_selector(".videoArea")
    move_mouse(canvas)
    next_but = page.wait_for_selector("#nextBtn")
    page.wait_for_timeout(200)
    next_but.click()


def skip_question():
    try:
        page.wait_for_selector(".topic-item", timeout=2000)
        choices = page.query_selector_all(".topic-item")
        choices[0].click()
        choices[1].click()
        page.wait_for_timeout(500)
        page.query_selector_all(".btn")[3].click()
    except TimeoutError:
        return


def main_function():
    # 进行登录
    print("等待登录完成...")
    auto_login(user, pwd)
    # 等待完成滑块验证,已设置5min等待时间
    page.wait_for_selector(".wall-main", state="hidden")
    # 遍历所有课程,加载网页
    for course_url in urls:
        id_pat = re.compile("recruitAndCourseId=[a-zA-Z0-9]+")
        matched = re.findall(id_pat, course_url)
        if not matched:
            print(f"\"{course_url.strip()}\"\n不是一个有效网址,即将自动跳过!")
            continue
        print("开始加载播放页...")
        page.goto(course_url)
        page.wait_for_selector(".studytime-div")
        # 关闭弹窗,优化页面体验
        optimize_page()
        # 获取当前课程名
        course_title = page.wait_for_selector(".source-name").text_content()
        print(f"当前课程:<<{course_title}>>")
        start_time = time.time()  # 记录开始学习时间
        while True:
            # 获取课程小节名
            title = get_lesson_name()
            print("正在学习:%s" % title)
            # 根据进度条判断播放状态
            curtime = get_progress()
            check_play()  # 开始播放
            video_optimize()  # 对播放页进行初始化配置
            page.set_default_timeout(2000)
            while curtime != "100%":
                try:
                    skip_question()  # 跳过中途弹题(只支持选择题)
                    playBut = page.query_selector_all(".pauseButton")
                    curtime = get_progress()
                    if not playBut and curtime != "100%":
                        check_play()
                        print("当前小节未刷满,将继续播放..")
                        title = get_lesson_name()
                        print("正在学习:%s" % title)
                    else:
                        print('完成进度:%s' % curtime)
                        page.wait_for_timeout(2000)
                except TimeoutError:
                    input("进度获取超时,可能存在安全验证?\n按Enter继续:")
            page.set_default_timeout(300 * 1000 * 1000)
            title = get_lesson_name()
            play_next()  # 进度100%时开始下一集
            time_period = (time.time() - start_time) / 60
            if time_period >= 1:  # 每完成一节提示一次时间
                print("本次课程已学习:%.1f min" % time_period)
            # 如果当前小节是最后一节代表课程学习完毕
            all_class = page.query_selector_all(".clearfix.video")
            class_name = all_class[-1].get_attribute('class')
            if "current_play" in class_name:
                print("已学完本课程全部内容!")
                print("==" * 10)
                break
            else:  # 否则为完成当前课程的一个小节
                print(f"\"{title}\" Done !")
            page.wait_for_timeout(1000)


if __name__ == "__main__":
    print("===== Runtime Log =====")
    try:
        print("正在载入数据...")
        with open("account.json", "r", encoding="utf-8") as f:
            account = json.loads(f.read())
        user = account["User"].strip()
        pwd = account["Password"].strip()
        driver = account["Driver"].strip()
        urls = account["Url"]
        if not isinstance(urls, list):
            print('[Error]"Url"项格式错误!')
            raise KeyError
        with sync_playwright() as p:
            page = init_page()
            main_function()
            print("==" * 10)
            print("所有课程学习完毕!")
            input()
    except Exception as e:
        if isinstance(e, JSONDecodeError):
            print("[Error]account文件内容有误!")
        elif isinstance(e, KeyError):
            print("[Error]可能是account文件的配置出错!")
        elif isinstance(e, UserWarning):
            print("[Error]是不是忘记填账号密码了?")
        elif isinstance(e, FileNotFoundError):
            print("[Error]程序缺失依赖文件,请重新安装程序!")
        elif isinstance(e, TargetClosedError):
            print("[Error]糟糕,网页关闭了!")
        elif isinstance(e, TimeoutError):
            print("[Error]网页长时间无响应,自动退出...")
        else:
            print(f"[Error]{e}")
            with open("log.txt", "w", encoding="utf-8") as doc:
                doc.write(traceback.format_exc())
            print("错误日志已保存至:log.txt")
            print("系统出错,要不重启一下?")
        input()
