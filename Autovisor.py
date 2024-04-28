# encoding=utf-8
import random
import re
import traceback
import time
from res.configs import Config
from res.process import move_mouse, get_progress, show_progress
from res.support import show_donate
from playwright.sync_api import sync_playwright
from playwright._impl._errors import TargetClosedError, TimeoutError


def auto_login(_user, _pwd, page):
    if not user or not pwd:
        raise UserWarning
    page.goto(config.login_url)
    page.locator('#lUsername').fill(_user)
    page.locator('#lPassword').fill(_pwd)
    page.wait_for_timeout(500)
    page.evaluate(config.login_js)


def init_page(p, driver, exe_path):
    # 启动自带浏览器
    if not exe_path:
        if driver == "Chrome":
            print("正在启动Chrome浏览器...")
            browser = p.chromium.launch(channel="chrome", headless=False)
        else:
            print("正在启动Edge浏览器...")
            browser = p.chromium.launch(channel="msedge", headless=False)
    else:
        if driver == "Chrome":
            print("正在启动Chrome浏览器...")
            browser = p.chromium.launch(executable_path=exe_path, channel="chrome", headless=False)
        else:
            print("正在启动Edge浏览器...")
            browser = p.chromium.launch(executable_path=exe_path, channel="msedge", headless=False)
    context = browser.new_context()
    page = context.new_page()
    # 设置程序超时时限
    page.set_default_timeout(300 * 1000 * 1000)
    # 设置浏览器视口大小
    viewsize = page.evaluate('''() => {
                       return {width: window.screen.availWidth,height: window.screen.availHeight};}''')
    viewsize["height"] -= 50
    page.set_viewport_size(viewsize)
    return page, browser


def optimize_page(page):
    # 关闭学习须知
    page.evaluate(config.pop_js)
    # 根据当前时间切换夜间模式
    hour = time.localtime().tm_hour
    if hour >= 18 or hour < 7:
        page.wait_for_selector(".Patternbtn-div")
        page.evaluate(config.night_js)
    try:
        # 关闭上方横幅
        page.wait_for_selector(".exploreTip", timeout=1000)
        page.query_selector('a:has-text("不再提示")').click()
        # 关闭公众号提示
        page.evaluate(config.gjh_pop)
        page.wait_for_selector(".warn-box", timeout=1000)
        page.evaluate(config.close_gjh)
    finally:
        return


def get_lesson_name(page):
    title_ele = page.wait_for_selector("#lessonOrder")
    page.wait_for_timeout(500)
    title_ = title_ele.get_attribute("title")
    return title_


def video_optimize(page):
    try:
        move_mouse(page)
        page.wait_for_selector(".volumeBox").click()  # 设置静音
        page.wait_for_timeout(200)
        page.wait_for_selector(".definiBox").hover()  # 切换流畅画质
        low_quality = page.wait_for_selector(".line1bq")
        low_quality.hover()
        low_quality.click()
        page.wait_for_timeout(200)
        page.wait_for_selector(".speedBox").hover()
        # 将1.5倍速项修改为指定倍速
        page.evaluate(config.revise_speed_name)
        max_speed = page.wait_for_selector(".speedTab15")
        max_speed.hover()
        revise_speed = page.locator("div[rate=\"1.5\"]")
        revise_speed.evaluate(f'revise => revise.setAttribute("rate","{config.limitSpeed}");')
        max_speed.click()
        return True
    except:
        return False


def check_play(page):
    playing = page.query_selector(".pauseButton")
    if not playing:
        move_mouse(page)
        canvas = page.wait_for_selector(".videoArea", state="attached")
        canvas.click()
        return False
    else:
        return True


def skip_questions(page):
    page.wait_for_selector(".topic-item", state="attached")
    if not page.query_selector(".answer"):
        choices = page.locator(".topic-item").all()
        selects = random.sample(choices, k=2)
        for each in selects:
            each.click()
    page.wait_for_timeout(500)
    close = page.locator('//div[@class="btn"]')
    close.click()


def get_filtered_class(page):
    try:
        page.wait_for_selector(".time_icofinish",timeout=1000)
    except TimeoutError:
        pass
    all_class = page.locator(".clearfix.video").all()
    new_class = []
    for each in all_class:
        isDone = each.locator(".time_icofinish").count()
        if not isDone:
            new_class.append(each)
    return new_class


def start_course_loop(page, course_url):
    page.goto(course_url)
    page.wait_for_selector(".studytime-div")
    # 关闭弹窗,优化页面体验
    optimize_page(page)
    # 获取当前课程名
    course_title = page.wait_for_selector(".source-name").text_content()
    print(f"当前课程:<<{course_title}>>")
    page.wait_for_selector(".clearfix.video", state="attached")
    all_class = get_filtered_class(page)
    start_time = time.time()  # 记录开始学习时间
    for each in all_class:
        page.wait_for_selector(".current_play", state="attached")
        each.click()
        page.wait_for_timeout(1000)
        title = get_lesson_name(page)  # 获取课程小节名
        print("正在学习:%s" % title)
        try:  # 防止一开始就是题目界面
            page.wait_for_selector(".topic-item", timeout=3000)
            skip_questions(page)
        except TimeoutError:
            pass
        # 根据进度条判断播放状态
        curtime = get_progress(page)[0]
        if curtime != "100%":
            check_play(page)  # 开始播放
            video_optimize(page)  # 对播放页进行初始化配置
        page.set_default_timeout(4000)
        while curtime != "100%":
            try:
                page.wait_for_timeout(1000)
                if page.query_selector(".topic-item"):
                    skip_questions(page)
                check_play(page)
                curtime, total_time = get_progress(page)
                time_period = (time.time() - start_time) / 60
                if 0 < config.limitMaxTime <= time_period:
                    break
                else:
                    show_progress(desc="完成进度:", cur_str=curtime)
            except TimeoutError as e:
                if page.query_selector(".yidun_modal__title"):
                    print("\n检测到安全验证,正在等待手动完成...")
                    page.wait_for_selector(".yidun_modal__title", state="hidden", timeout=90 * 60 * 1000)
                elif page.query_selector(".topic-item"):
                    skip_questions(page)
                else:
                    print(f"\n[Warn]{e}")
        # 完成该小节后的操作
        page.set_default_timeout(90 * 60 * 1000)
        time_period = (time.time() - start_time) / 60
        if 0 < config.limitMaxTime <= time_period:  # 若达到设定的时限将直接进入下一节
            print(f"\n当前课程已达时限:{config.limitMaxTime}min\n即将进入下一节!")
            break
        # 如果当前小节是最后一节代表课程学习完毕
        class_name = all_class[-1].get_attribute('class')
        if "current_play" in class_name:
            print("\n已学完本课程全部内容!")
            print("==" * 10)
        else:  # 否则为完成当前课程的一个小节
            print(f"\n\"{title}\" Done !")
            # 每完成一节提示一次时间
            print("本次课程已学习:%.1f min" % time_period)


def main_function():
    with sync_playwright() as p:
        page, browser = init_page(p, driver,exe_path)
        # 进行登录
        print("等待登录完成...")
        auto_login(user, pwd, page)
        # 等待完成滑块验证,已设置5min等待时间
        page.wait_for_selector(".wall-main", state="hidden")
        # 遍历所有课程,加载网页
        id_pattern = config.course_match_rule  # 匹配网址格式
        for course_url in urls:
            matched = re.findall(id_pattern, course_url)
            if not matched:
                print(f"\"{course_url.strip()}\"\n不是一个有效网址,即将自动跳过!")
                continue
            print("开始加载播放页...")
            page.set_default_timeout(90 * 60 * 1000)
            # 启动课程主循环
            start_course_loop(page, course_url)
        browser.close()
    print("==" * 10)
    print("所有课程学习完毕!")
    show_donate("res/QRcode.jpg")
    time.sleep(5)


if __name__ == "__main__":
    print("Github:CXRunfree All Rights Reserved.")
    print("===== Runtime Log =====")
    try:
        print("正在载入数据...")
        config = Config()
        user = config.username
        pwd = config.password
        driver = config.driver
        exe_path = config.exe_path
        urls = config.course_urls
        if not isinstance(urls, list):
            print('[Error]"Url"项格式错误!')
            raise KeyError
        main_function()
    except Exception as e:
        if isinstance(e, KeyError):
            input("[Error]可能是account文件的配置出错!")
        elif isinstance(e, UserWarning):
            input("[Error]是不是忘记填账号密码了?")
        elif isinstance(e, FileNotFoundError):
            print(f"文件缺失: {e.filename}")
            input("[Error]程序缺失依赖文件,请重新安装程序!")
        elif isinstance(e, TargetClosedError):
            input("[Error]糟糕,网页关闭了!")
        else:
            print(f"[Error]{e}")
            with open("log.txt", "w", encoding="utf-8") as log:
                log.write(traceback.format_exc())
            print("错误日志已保存至:log.txt")
            input("系统出错,请检查后重新启动!")
