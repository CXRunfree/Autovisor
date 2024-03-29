import traceback
import json
import time
from json import JSONDecodeError

from selenium import webdriver
from selenium.common import NoSuchWindowException, JavascriptException, TimeoutException
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def add_opts(option):
    option.add_argument('--ignore-certificate-errors')
    option.add_argument("disable-extensions")
    option.add_experimental_option("excludeSwitches", ["enable-logging"])


def driver_init(driver_type):
    if driver_type == "Edge":
        options = webdriver.EdgeOptions()
        add_opts(options)
        _driver = webdriver.Edge(options)
    elif driver_type == "Chrome":
        options = webdriver.ChromeOptions()
        add_opts(options)
        _driver = webdriver.Chrome(options)
    else:
        _driver = None
    return _driver


def auto_login(user, pwd):
    if not user or not pwd:
        raise UserWarning
    driver.get(login_url)
    driver.execute_script(user_js)
    driver.execute_script(pwd_js)
    time.sleep(0.5)
    driver.execute_script(login_js)


def optimize_page():
    try:
        # 关闭课程结束提示
        driver.execute_script(pop_late)
        # 关闭上方横幅
        driver.execute_script(pop2_js)
    except JavascriptException:
        pass  # 不是每次都有此类弹窗
    #  关闭学习须知
    driver.execute_script(pop_js)
    # 根据当前时间切换夜间模式
    hour = time.localtime().tm_hour
    if hour >= 18 or hour < 7:
        driver.execute_script(night_js)


def get_progress():
    curt = "进度获取中..."
    text = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "passTime")))
    try:
        # 最多保留2位小数;不足则输出原形
        s = text.get_attribute('style').split(": ")[1][:-1]
        if len(s) > 5:
            s = s.split(".")
            curt = f"{s[0]}.{s[1][:2]}%"
        else:
            curt = s
    finally:
        return curt


def check_play():
    canvas = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.CLASS_NAME, "videoArea")))
    ActionChains(driver).move_to_element(canvas).click().perform()


def shut_volume():
    driver.execute_script(show_controlsBar)
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "volumeBox"))).click()


def play_next():
    driver.execute_script(show_controlsBar)
    next_but = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "nextBtn")))
    next_but.click()


def get_lesson_name():
    title_ = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "lessonOrder"))).get_attribute("title")
    return title_


def skip_question():
    try:
        WebDriverWait(driver, 1.5).until(EC.element_to_be_clickable((By.XPATH, option1)))
    except TimeoutException:
        return
    try:
        driver.find_element(By.XPATH, option1).click()
        driver.find_element(By.XPATH, option2).click()
    finally:
        time.sleep(0.5)
        driver.find_element(By.XPATH, x_close).click()
        return


def detect_auth():
    try:
        WebDriverWait(driver, 1).until(EC.element_to_be_clickable((By.CLASS_NAME, "yidun_modal__title")))
        hasAuth = True
    except TimeoutException:
        hasAuth = False
    return hasAuth


# 初始化配置>>>>>>>>>>>>>>>>>>>>
print("载入数据...")
# 读取用户信息
try:
    with open('./account.json', 'r', encoding='utf-8') as f:
        account = json.load(f)
except JSONDecodeError:
    print("account文件内容有误!")
    exit(-1)

# 启动driver
driver = driver_init(account["Driver"].strip())
if not driver:
    print("暂不支持该浏览器,请检查配置!")
    exit(-1)

# 隐藏浏览器指纹
with open("Res/stealth.min.js", "r") as f:
    js = f.read()
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": js})

# constants
login_url = "https://passport.zhihuishu.com/login"
lesson_finish = True
user = account['User'].strip()
pwd = account['Password'].strip()

# ElementXpath
drag_bar = "/html/body/div[31]/div[2]/div/div/div[2]/div/div[2]/div[2]"
option1 = '//*[@id="playTopic-dialog"]/div/div[2]/div/div[1]/div/div/div[2]/ul/li[1]/div[2]'
option2 = '//*[@id="playTopic-dialog"]/div/div[2]/div/div[1]/div/div/div[2]/ul/li[2]/div[2]'
x_close = '/html/body/div[1]/div/div[2]/div[1]/div[2]/div[1]/div/div[3]/span/div'

# javascript
# 登录
user_js = f'''document.getElementById("lUsername").value="{user}";'''
pwd_js = f'''document.getElementById("lPassword").value="{pwd}";'''
login_js = '''document.getElementsByClassName("wall-sub-btn")[0].click();'''
block_js = '''return document.getElementsByClassName("yidun_jigsaw")[0].src'''
bg_js = '''return document.getElementsByClassName("yidun_bg-img")[0].src'''
# 弹窗
pop_late = '''document.getElementsByClassName("el-dialog__close el-icon el-icon-close")[2].click()'''
pop_js = '''document.getElementsByClassName("iconfont iconguanbi")[0].click();'''
pop2_js = '''document.evaluate('//*[@id="app"]/div/div[1]/div[1]/span/a',document).iterateNext().click();'''
# 其他
night_js = '''document.getElementsByClassName("Patternbtn-div")[0].click()'''
show_controlsBar = '''document.getElementsByClassName("controlsBar")[0].setAttribute("style","z-index: 2; overflow: inherit;")'''

try:
    print("正在登录...")
    # 打开登录页面,自动填充账户密码
    auto_login(user, pwd)
    # 等待完成滑块验证,已设置5min等待时间
    WebDriverWait(driver, 300).until(
        EC.invisibility_of_element((By.CLASS_NAME, "wall-main")))
    # 遍历所有课程,加载网页
    for course_url in account["Url"]:
        if "CourseId" not in course_url.strip():
            continue
        print("加载播放页...")
        driver.get(course_url)
        # 等待开屏弹窗出现
        WebDriverWait(driver, 300).until(
            EC.presence_of_element_located((By.CLASS_NAME, "studytime-div")))
        time.sleep(0.5)
        # 关闭弹窗,优化页面体验
        optimize_page()
        # 遍历课程小节
        while True:
            # 获取课程名
            title = get_lesson_name()
            print("正在学习:%s" % title)
            # 根据进度条判断播放状态
            curtime = "0"
            check_play()  # 开始播放
            shut_volume()  # 设置为静音
            while curtime != "100%":
                hasAuth = detect_auth()
                while hasAuth:
                    print("请手动完成安全验证!")
                    input("程序已暂停,按Enter继续...")
                    hasAuth = detect_auth()
                skip_question()  # 跳过中途弹题(只支持选择题)
                curtime2 = get_progress()
                if curtime2 != curtime:  # 进度条若相同则说明视频已暂停
                    curtime = curtime2
                    print('已完成:%s' % curtime)
                else:
                    check_play()
                    print("检测到视频暂停,已自动继续..")
                    title = get_lesson_name()
                    print("正在学习:%s" % title)
            try:
                play_next()  # 进度100%时开始下一集
            except Exception:  # 捕获有时点击失败的情况
                continue
            # 延时获取新数据
            time.sleep(1.5)
            title2 = get_lesson_name()
            # 点完下一集后若标题不改变,判定为课程结束
            if title2 != title:
                print(f"\"{title}\" Done !")
            else:
                print("已学完本课程全部内容!")
                print("==" * 10)
                break
        time.sleep(1)
# 特殊异常捕获
except Exception as e:
    print(f"Error:{type(e)}")
    if type(e) == UserWarning:
        print("哎呀,是不是忘填账号密码了~")
    elif type(e) == NoSuchWindowException:
        print("糟糕!网页关闭了~")
    else:
        log = traceback.format_exc()
        print("错误日志已保存至:log.txt")
        with open("./log.txt", "w", encoding="utf-8") as doc:
            doc.write(log)
    print("系统异常,要不重启一下?")
    lesson_finish = False
# 程序出口
driver.quit()
if lesson_finish:
    print("所有课程学习完毕!")
input()
