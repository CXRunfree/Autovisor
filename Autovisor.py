import json
import os
import time
import traceback
from selenium import webdriver
from selenium.common import NoSuchWindowException
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def get_progress():
    curt = "进度获取中..."
    text = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "passTime")))
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


def get_name():
    title_ = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "lessonOrder"))).get_attribute("title")
    return title_


def skip_ques():
    WebDriverWait(driver, 1.5).until(EC.element_to_be_clickable((By.XPATH, option2))).click()
    driver.find_element(By.XPATH, option1).click()
    time.sleep(0.5)
    driver.find_element(By.XPATH, x).click()


# 初始化配置
print("载入数据...")
edge_options = webdriver.EdgeOptions()
edge_options.add_argument('--ignore-certificate-errors')
edge_options.add_argument("disable-extensions")
edge_options.add_experimental_option("excludeSwitches", ["enable-logging"])
driver = webdriver.Edge(options=edge_options)
# 隐藏浏览器指纹
with open("./stealth.min.js", "r") as f:
    js = f.read()
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": js})
# 读取用户信息
with open('./account.json', 'r', encoding='utf-8') as f:
    account = json.load(f)
# ElementXpath
next = '/html/body/div[1]/div/div[2]/div[1]/div[2]/div/div/div[10]/div[3]'
option1 = '//*[@id="playTopic-dialog"]/div/div[2]/div/div[1]/div/div/div[2]/ul/li[1]/div[2]'
option2 = '//*[@id="playTopic-dialog"]/div/div[2]/div/div[1]/div/div/div[2]/ul/li[2]/div[2]'
x = '/html/body/div[1]/div/div[2]/div[1]/div[2]/div[1]/div/div[3]/span/div'

# javascript
user_js = f'''document.getElementById("lUsername").value="{account['User']}";'''
pwd_js = f'''document.getElementById("lPassword").value="{account['Password']}";'''
login_js = '''document.getElementsByClassName("wall-sub-btn")[0].click();'''
pop_js = '''document.getElementsByClassName("iconfont iconguanbi")[0].click();'''
pop2_js = '''document.evaluate('//*[@id="app"]/div/div[1]/div[1]/span/a',document).iterateNext().click();'''
night = '''Patternbtn-div'''
try:
    print("正在登录...")
    # 打开登录页面,自动填充账户密码
    login_url = "https://passport.zhihuishu.com/login"
    driver.get(login_url)
    driver.execute_script(user_js)
    driver.execute_script(pwd_js)
    time.sleep(0.5)
    driver.execute_script(login_js)
    # 等待用户完成滑块验证,已设置80s等待时间
    WebDriverWait(driver, 80).until(
        EC.invisibility_of_element((By.CLASS_NAME, "wall-main")))
    # 加载播放页面
    print("加载播放页...")
    course_url = account["Url"]
    driver.get(course_url)
    # 关闭开屏弹窗
    WebDriverWait(driver, 80).until(
        EC.presence_of_element_located((By.CLASS_NAME, "studytime-div")))
    time.sleep(0.5)
    driver.execute_script(pop_js)
    # 点击"不再提示"
    driver.execute_script(pop2_js)
    # 遍历课程小节
    while True:
        title = get_name()
        print("正在学习:%s" % title)
        # 开始播放
        curtime = "0"
        check_play()
        while curtime != "100%":
            try:
                # 跳过中途弹题(只支持选择题)
                skip_ques()
                time.sleep(0.4)
            finally:
                curtime2 = get_progress()
                if curtime2 != curtime:
                    curtime = curtime2
                    print('已完成:%s' % curtime)
                else:
                    check_play()
                    print("检测到视频暂停,已自动继续..")
                    title = get_name()
                    print("正在学习:%s" % title)
                    time.sleep(0.7)
                continue

        # 进度100%时开始下一集
        above = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CLASS_NAME, "videoArea")))
        ActionChains(driver).move_to_element(above).perform()
        next_but = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, next)))
        next_but.click()
        # 延时获取新数据
        time.sleep(1.5)
        title2 = get_name()
        # 确保课程结束可以跳出程序
        if title2 != title:
            print(f"\"{title}\" Done !")
        else:
            print("已学完本课程全部内容!")
            os.system("pause")
            break

# 特殊异常捕获
except Exception as e:
    print(f"Error:{type(e)}")
    if type(e) == NoSuchWindowException:
        print("糟糕!网页关闭了~")
    else:
        log = traceback.format_exc()
        print("错误日志已保存至:log.txt")
        with open("./log.txt", "w", encoding="utf-8") as doc:
            doc.write(log)
    print("系统异常,要不重启一下?")

# 程序出口
driver.quit()
