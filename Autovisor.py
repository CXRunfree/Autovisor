import json
import os
import time
import traceback
from selenium import webdriver
from selenium.common import NoSuchWindowException, TimeoutException
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def get_progress():
    curt = "进度获取中..."
    text = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "passTime")))
    try:
        s = text.get_attribute('style').split(": ")[1][:-1]
        if len(s) > 5:
            s = s.split(".")
            curt = f"{s[0]}.{s[1][:2]}%"
        else:
            curt = s
    finally:
        return curt


def check_play():
    driver.execute_script("document.readyState == 'complete'")
    canvas = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "videoArea")))
    ActionChains(driver).move_to_element(canvas).perform()
    play = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "playButton")))
    play.click()  # 继续播放


def get_name():
    driver.execute_script("document.readyState == 'complete'")
    title_ = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "lessonOrder"))).get_attribute("title")
    return title_


# 初始化
print("正在载入...")
with open('./account.json', 'r', encoding='utf-8') as f:
    account = json.load(f)
url = account["Url"]
edge_option = webdriver.EdgeOptions()
edge_option.add_argument('--ignore-certificate-errors')
edge_option.add_argument("disable-extensions")
edge_option.add_experimental_option("excludeSwitches", ["enable-logging"])
driver = webdriver.Edge(options=edge_option)
with open("./stealth.min.js", "r") as f:
    js = f.read()
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": js})
driver.get(url)
# 开始抓取
user = '/html/body/div[6]/div/form/div[1]/ul[1]/li[1]/input[4]'
pas = '/html/body/div[6]/div/form/div[1]/ul[1]/li[2]/input'
login = '/html/body/div[6]/div/form/div[1]/span'

next = '/html/body/div[1]/div/div[2]/div[1]/div[2]/div/div/div[10]/div[3]'
pas_t = '//*[@id="vjs_container"]/div[10]/div[1]/div/div[2]'

option1 = '//*[@id="playTopic-dialog"]/div/div[2]/div/div[1]/div/div/div[2]/ul/li[1]/div[2]'
option2 = '//*[@id="playTopic-dialog"]/div/div[2]/div/div[1]/div/div/div[2]/ul/li[2]/div[2]'
x = '/html/body/div[1]/div/div[2]/div[1]/div[2]/div[1]/div/div[3]/span/div'

try:
    # 自动填充登录账户密码
    driver.execute_script("document.readyState == 'complete'")
    WebDriverWait(driver, 80).until(EC.element_to_be_clickable((By.XPATH, user)))
    driver.find_element(By.XPATH, user).send_keys(account['User'])
    driver.find_element(By.XPATH, pas).send_keys(account['Password'])
    time.sleep(0.2)
    driver.find_element(By.XPATH, login).click()  # 确认登录

    try:
        # 等待用户完成滑块验证,已设置80s等待时间
        WebDriverWait(driver, 80).until(
            EC.invisibility_of_element((By.CLASS_NAME, "yidun_modal__header")))
        # 关掉开屏弹窗
        driver.execute_script("document.readyState == 'complete'")
        pop = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="app"]/div/div[6]/div[2]/div[1]/i')))
        pop.click()
        # 确认弹窗被关闭,否则等待用户手动关闭,设置20s
        WebDriverWait(driver, 20).until(
            EC.invisibility_of_element((By.XPATH, '//*[@id="app"]/div/div[6]/div[2]/div[1]/i')))
    finally:
        while True:
            title = get_name()
            print("正在学习:%s" % title)
            curtime = "0"
            try:
                # 开始播放
                check_play()
            finally:
                while curtime != "100%":
                    try:
                        # 跳过中途弹题(只支持选择题)
                        driver.execute_script("document.readyState == 'complete'")
                        WebDriverWait(driver, 1.5).until(EC.element_to_be_clickable((By.XPATH, option2))).click()
                        driver.find_element(By.XPATH, option1).click()
                        time.sleep(0.5)
                        driver.find_element(By.XPATH, x).click()
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
                try:
                    driver.execute_script("document.readyState == 'complete'")
                    # 下一集
                    above = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CLASS_NAME, "videoArea")))
                    ActionChains(driver).move_to_element(above).perform()
                    next_but = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, next)))
                    next_but.click()
                    time.sleep(1.5)
                    title2 = get_name()
                    # 确保课程结束可以跳出程序
                    if title2 != title:
                        print(f"\"{title}\" Done !")
                    else:
                        print("All works done!")
                        os.system("pause")
                        break
                except:
                    continue
# 特殊异常捕获
except Exception as e:
    print(f"Error:{type(e)}")
    if type(e) == NoSuchWindowException:
        print("糟糕!网页关闭了~")
    elif type(e) == TimeoutException:
        print("网络似乎不太稳定<O.o?>")
    else:
        log = traceback.format_exc()
        print("错误日志已保存至:log.txt")
        with open("./log.txt", "w", encoding="utf-8") as doc:
            doc.write(log)
    print("系统异常,要不重启一下?")

# 程序出口
driver.quit()
