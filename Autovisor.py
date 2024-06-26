# encoding=utf-8
import traceback
import time
from typing import Tuple, List
from res.configs import Config
from res.process import move_mouse, get_progress, show_progress
from playwright.sync_api import sync_playwright, Playwright, Page, Browser, Locator
from playwright._impl._errors import TargetClosedError, TimeoutError
from res.support import show_donate  # 预加载影响不大


def auto_login(config: Config, page: Page):
    page.goto(config.login_url)
    page.goto(config.login_url)
    page.locator('#lUsername').fill(config.username)
    page.locator('#lPassword').fill(config.password)
    page.wait_for_timeout(500)
    page.evaluate(config.login_js)
    # 等待完成滑块验证
    page.wait_for_selector(".wall-main", state="hidden")


def init_page(p: Playwright, config: Config) -> Tuple[Page, Browser]:
    # 启动指定的浏览器
    driver = "msedge" if config.driver == "edge" else config.driver
    if not config.exe_path:
        print(f"正在启动{config.driver}浏览器...")
        browser = p.chromium.launch(channel=driver, headless=False)
    else:
        print(f"正在启动{config.driver}浏览器...")
        browser = p.chromium.launch(executable_path=config.exe_path, channel=driver, headless=False)
    context = browser.new_context()
    page = context.new_page()
    # 设置程序超时时限
    page.set_default_timeout(300 * 1000 * 1000)
    # 设置浏览器视口大小
    viewsize = page.evaluate(
        '''() => {
                       return {width: window.screen.availWidth,height: window.screen.availHeight};}'''
    )
    viewsize["height"] -= 50
    page.set_viewport_size(viewsize)
    return page, browser


def optimize_page(page: Page):
    try:
        # 关闭学习须知
        page.evaluate(config.pop_js)
        # 根据当前时间切换夜间模式
        hour = time.localtime().tm_hour
        if hour >= 18 or hour < 7:
            page.wait_for_selector(".Patternbtn-div")
            page.evaluate(config.night_js)
        # 关闭右侧AI助手
        page.wait_for_selector(".show-icon.icon-appear", timeout=1500)
        page.evaluate(config.close_assist)
        # 关闭上方横幅
        page.wait_for_selector(".exploreTip", timeout=1000)
        page.query_selector('a:has-text("不再提示")').click()
        # 关闭公众号提示
        page.evaluate(config.gzh_pop)
        page.wait_for_selector(".warn-box", timeout=1000)
        page.evaluate(config.close_gjh)
    except TimeoutError:
        return


def get_lesson_name(page: Page):
    title_ele = page.wait_for_selector("#lessonOrder")
    page.wait_for_timeout(500)
    title_ = title_ele.get_attribute("title")
    return title_


def video_optimize(page: Page):
    try:
        move_mouse(page)
        # 设置静音
        page.wait_for_selector(".volumeBox").click()
        page.wait_for_timeout(200)
        # 切换流畅画质
        page.wait_for_selector(".definiBox").hover()
        low_quality = page.wait_for_selector(".line1bq")
        low_quality.hover()
        low_quality.click()
        page.wait_for_timeout(200)
        # 将1.5倍速项修改为指定倍速
        page.wait_for_selector(".speedBox").hover()
        page.evaluate(config.revise_speed_name)
        max_speed = page.wait_for_selector(".speedTab15")
        max_speed.hover()
        revise_speed = page.locator("div[rate=\"1.5\"]")
        revise_speed.evaluate(
            f'revise => revise.setAttribute("rate","{config.limitSpeed}");'
        )
        max_speed.click()
        return True
    except:
        return False


def play_video(page: Page):
    playing = page.query_selector(".pauseButton")
    if not playing:
        move_mouse(page)
        canvas = page.wait_for_selector(".videoArea", state="attached")
        canvas.click()
    # 等待播放键样式改变
    page.wait_for_selector(".pauseButton", state="attached")


def skip_questions(page: Page):
    try:
        page.wait_for_selector(".topic-item", state="attached", timeout=1000)
    except TimeoutError:
        return
    if not page.query_selector(".answer"):
        choices = page.locator(".topic-item").all()
        # 直接遍历点击所有选项
        for each in choices:
            each.click()
            page.wait_for_timeout(100)
    # close = page.locator('//div[@class="btn"]')
    # close.click()
    # js模拟ESC键关闭更快
    page.evaluate(config.close_ques)


def get_filtered_class(page: Page, enableRepeat=False) -> List[Locator]:
    try:
        page.wait_for_selector(".time_icofinish", timeout=1000)
    except TimeoutError:
        pass
    all_class = page.locator(".clearfix.video").all()
    if enableRepeat:
        return all_class
    else:
        new_class = []
        for each in all_class:
            isDone = each.locator(".time_icofinish").count()
            if not isDone:
                new_class.append(each)
        return new_class


def tail_work(page: Page, start_time, all_class, title):
    reachTimeLimit = False
    page.set_default_timeout(90 * 60 * 1000)
    time_period = (time.time() - start_time) / 60
    if 0 < config.limitMaxTime <= time_period:  # 若达到设定的时限将直接进入下一门课
        print(f"\n当前课程已达时限:{config.limitMaxTime}min\n即将进入下门课程!")
        reachTimeLimit = True
    # 如果当前小节是最后一节代表课程学习完毕
    class_name = all_class[-1].get_attribute('class')
    if "current_play" in class_name:
        print("\n已学完本课程全部内容!")
        print("==" * 10)
    else:  # 否则为完成当前课程的一个小节
        print(f"\n\"{title}\" Done !")
        # 每完成一节提示一次时间
        print(f"本次课程已学习:{time_period:.1f} min")
    return reachTimeLimit


# 学习模式: 从未完成课程开始
def learning_loop(page: Page, config: Config):
    # 获取当前课程名
    course_title = page.wait_for_selector(".source-name").text_content()
    print(f"当前课程:<<{course_title}>>")
    page.wait_for_selector(".clearfix.video", state="attached")
    all_class = get_filtered_class(page)
    start_time = time.time()  # 记录开始学习时间
    for each in all_class:
        page.wait_for_selector(".current_play", state="attached")
        skip_questions(page)
        each.click()
        page.wait_for_timeout(1000)
        title = get_lesson_name(page)  # 获取课程小节名
        print("正在学习:%s" % title)
        skip_questions(page)
        # 根据进度条判断播放状态
        curtime, total_time = get_progress(page)
        if curtime != "100%":
            play_video(page)  # 开始播放
            video_optimize(page)  # 对播放页进行初始化配置
        page.set_default_timeout(4000)
        timer = 0
        while curtime != "100%":
            try:
                skip_questions(page)
                play_video(page)
                time_period = (time.time() - start_time) / 60
                timer += 1
                if 0 < config.limitMaxTime <= time_period:
                    break  # 到达限定时间就结束当前课程
                elif timer % 5 == 0:  # 降低更新频率,减少卡住情况
                    curtime, total_time = get_progress(page)
                    show_progress(desc="完成进度:", cur_str=curtime)
            except TimeoutError as e:
                if page.query_selector(".yidun_modal__title"):
                    print("\n检测到安全验证,正在等待手动完成...")
                    page.wait_for_selector(
                        ".yidun_modal__title", state="hidden", timeout=90 * 60 * 1000
                    )
                elif page.query_selector(".topic-item"):
                    skip_questions(page)
                else:
                    print(f"\n[Warn]{e.message}")
        # 完成该小节后的操作
        reachTimeLimit = tail_work(page, start_time, all_class, title)
        if reachTimeLimit:
            return


# 复习模式: 允许播放已完成课程小节
def reviewing_loop(page: Page, config: Config):
    # 获取当前课程名
    course_title = page.wait_for_selector(".source-name").text_content()
    print(f"当前课程:<<{course_title}>>")
    page.wait_for_selector(".clearfix.video", state="attached")
    all_class = get_filtered_class(page, enableRepeat=True)
    course_start_time = time.time()  # 记录开始学习时间
    for each in all_class:
        page.wait_for_selector(".current_play", state="attached")
        skip_questions(page)
        each.click()
        page.wait_for_timeout(1000)
        title = get_lesson_name(page)  # 获取课程小节名
        print("正在学习:%s" % title)
        skip_questions(page)
        # 根据进度条判断播放状态
        curtime, total_time = get_progress(page)
        play_video(page)  # 开始播放
        video_optimize(page)  # 对播放页进行初始化配置
        start_time = time.time()
        page.set_default_timeout(4000)
        timer = 0
        while True:
            est_time = (time.time() - start_time) * config.limitSpeed
            if est_time > total_time:
                break
            try:
                skip_questions(page)
                play_video(page)
                time_period = (time.time() - course_start_time) / 60
                timer += 1
                if 0 < config.limitMaxTime <= time_period:
                    break  # 到达限定时间就结束当前课程
                elif timer % 5 == 0:  # 降低更新频率,减少卡住情况
                    curtime, total_time = get_progress(page)
                    show_progress(desc="完成进度:", cur_str=f"{int(est_time * 100 // total_time)}%", enableRepeat=True)
            except TimeoutError as e:
                if page.query_selector(".yidun_modal__title"):
                    print("\n检测到安全验证,正在等待手动完成...")
                    page.wait_for_selector(
                        ".yidun_modal__title", state="hidden", timeout=90 * 60 * 1000
                    )
                elif page.query_selector(".topic-item"):
                    skip_questions(page)
                else:
                    print(f"\n[Warn]{e.message}")
        # 完成该小节后的操作
        reachTimeLimit = tail_work(page, course_start_time, all_class, title)
        if reachTimeLimit:
            return


def main_function(config: Config):
    with sync_playwright() as p:
        page, browser = init_page(p, config)
        # 进行登录
        if not config.username or not config.password:
            print("请手动输入账号密码...")
        print("等待登录完成...")
        auto_login(config, page)
        # 遍历所有课程,加载网页
        for course_url in config.course_urls:
            print("开始加载播放页...")
            page.set_default_timeout(90 * 60 * 1000)
            page.goto(course_url)
            page.wait_for_selector(".studytime-div")
            # 关闭弹窗,优化页面体验
            optimize_page(page)
            # 启动课程主循环
            if config.enableRepeat:
                reviewing_loop(page, config)
            else:
                learning_loop(page, config)
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
        main_function(config)
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
        elif isinstance(e, UnicodeDecodeError):
            print("configs配置文件编码有误,保存时请选择utf-8或gbk!")
            input(f"[Error]{e}")
        else:
            print(f"[Error]{e}")
            with open("log.txt", "w", encoding="utf-8") as log:
                log.write(traceback.format_exc())
            print("错误日志已保存至:log.txt")
            input("系统出错,请检查后重新启动!")
