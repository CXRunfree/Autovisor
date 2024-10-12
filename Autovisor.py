# encoding=utf-8
import asyncio
import traceback
import time
import cv2
from requests import get
from random import uniform
from typing import Tuple
from res.configs import Config
from res.progress import get_progress, show_progress
from playwright.async_api import async_playwright, Playwright, Page, Browser
from playwright.async_api import TimeoutError
from playwright._impl._errors import TargetClosedError
from res.support import show_donate
from res.utils import optimize_page, get_lesson_name, get_filtered_class, get_video_attr

# 获取全局事件循环
event_loop_verify = asyncio.Event()
event_loop_answer = asyncio.Event()


async def auto_login(config: Config, page: Page):
    await page.goto(config.login_url)
    await page.locator('#lUsername').fill(config.username)
    await page.locator('#lPassword').fill(config.password)
    await page.wait_for_timeout(500)
    await page.evaluate(config.login_js)
    #尝试自动验证5次
    isPassed = 0
    for x in range(0,5):
        try:
            print(f'[Info]尝试自动过验证第{x+1}次')
            await page.wait_for_selector(".wall-main", state="attached")
            max_loc = await progress_img(page)
            await move_slider(page, max_loc[0])
            await page.wait_for_selector(".wall-main", state='hidden', timeout = 3000)
            isPassed = 1
            break
        except TimeoutError:
            continue
    if not isPassed:
        print('[Warn]自动过验证失败, 请手动滑块')
        await page.wait_for_selector(".wall-main", state='hidden')
    else:
        print('[Info]自动过验证成功')

async def progress_img(page: Page):
    #等待图片加载完成
    if page.locator("div.yidun--loading") != None:
        await page.wait_for_selector("div.yidun--loading", state="detached")
    #下载图片
    bg_url = await page.locator('img.yidun_bg-img').get_attribute('src')
    with open("./bg.jpg", "wb") as f:
        f.write(get(bg_url).content)
    block_url = await page.locator('img.yidun_jigsaw').get_attribute('src')
    with open("./block.png", "wb") as f:
        f.write(get(block_url).content)

    #背景处理
    bg_img = cv2.imread("./bg.jpg")
    #灰度处理
    bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
    #噪点处理
    bg_deno = cv2.fastNlMeansDenoising(bg_gray, None, 10, 7, 21)
    #Otsu’s二值化
    ret2,bg_th = cv2.threshold(bg_deno,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    #边沿检测
    bg_canny = cv2.Canny(bg_th, threshold1=500, threshold2=900, apertureSize=3)

    #滑块处理
    block_img = cv2.imread("./block.png")
    block_gray = cv2.cvtColor(block_img, cv2.COLOR_BGR2GRAY)
    #反色
    block_opsite = cv2.bitwise_not(block_gray)
    #简单二值化
    ret, bthimg = cv2.threshold(block_opsite, 240, 255, cv2.THRESH_BINARY_INV)
    block_canny = cv2.Canny(bthimg, threshold1=500, threshold2=900, apertureSize=3)
    
    result = cv2.matchTemplate(bg_canny, block_canny, cv2.TM_CCOEFF_NORMED)

    # 获取匹配结果的位置
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    top_left2 = max_loc
    bottom_right2 = (top_left2[0] + block_img.shape[1], top_left2[1] + block_img.shape[0])

    # 在输入图像上绘制矩形标记
    cv2.imwrite('./bg.jpg', cv2.rectangle(bg_img, top_left2, bottom_right2, (0, 0, 255), 2))

    return max_loc

#生成随机滑动鼠标位置列表
async def gen_movelist(sum_b):
    num_list = []
    sum_n = sum_b
    for x in range(0,30):
        temp = uniform(1, sum_n/2)
        if sum_n <= 1.5 or x == 29:
            num_list.append(round(sum_n,3))
            break
        else:
            num_list.append(round(temp,3))
            sum_n = sum_b - temp
            sum_b = sum_n
    return num_list

async def move_slider(page: Page, distance):
    box = await page.locator('div.yidun_slider').bounding_box()
    await page.locator('div.yidun_slider').hover()

    #生成每次移动距离列表
    move_list = []
    move_list = await gen_movelist(distance)
    #开始拖动
    await page.mouse.down()
    for i in range(0,len(move_list)):
        #30为预设偏移量，如果稳定偏差某一值，请修改
        await page.mouse.move(box["x"] + sum(move_list[:i]) + 30 + uniform(-1.5, 1.5), box["y"] +uniform(-10, 10), steps=4)
    await page.mouse.up()
    

async def init_page(p: Playwright, config: Config) -> Tuple[Page, Browser]:
    driver = "msedge" if config.driver == "edge" else config.driver

    print(f"[Info]正在启动{config.driver}浏览器...")
    browser = await p.chromium.launch(
        channel=driver,
        headless=False,
        executable_path = config.exe_path if config.exe_path else None
        )
    
    context = await browser.new_context()
    page = await context.new_page()

    #抹去特征
    with open('stealth.min.js','r') as f:
        js=f.read()
    await page.add_init_script(js)

    page.set_default_timeout(24 * 3600 * 1000)
    viewsize = await page.evaluate(
        '''() => {
            return {width: window.screen.availWidth, height: window.screen.availHeight};
        }'''
    )
    viewsize["height"] -= 50
    await page.set_viewport_size(viewsize)
    return page, browser


async def video_optimize(page: Page, config: Config) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(1)
            await page.wait_for_selector("video", state="attached", timeout=3000)
            if await get_video_attr(page, "volume") != 0:
                await page.evaluate(config.volume_none)
                await page.evaluate(config.set_none_icon)
                print("[Info]视频已静音.")
            if await get_video_attr(page, "playbackRate") != config.limitSpeed:
                await page.evaluate(config.revise_speed)
                await page.evaluate(config.revise_speed_name)
                print(f"[Info]视频已修改为{config.limitSpeed}倍速.")
        except Exception as e:
            continue


async def play_video(page: Page) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(1)
            await page.wait_for_selector("video", state="attached", timeout=1000)
            paused = await page.evaluate("document.querySelector('video').paused")
            if paused:
                print("\n[Info]检测到视频暂停,正在尝试播放...")
                await page.wait_for_selector(".videoArea", timeout=1000)
                await page.evaluate('document.querySelector("video").play();')
                print("[Info]视频已恢复播放.")
        except Exception as e:
            continue


async def skip_questions(page: Page, event_loop) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(0.5)
            await page.wait_for_selector(".el-dialog", state="attached", timeout=1000)
            total_ques = await page.query_selector_all(".number")
            for ques in total_ques:
                await ques.click(timeout=500)
                if not await page.query_selector(".answer"):
                    choices = await page.query_selector_all(".topic-item")
                    for each in choices[:2]:
                        await each.click(timeout=500)
                        await page.wait_for_timeout(100)
            await page.press(".el-dialog", "Escape", timeout=1000)
            event_loop.set()
        except Exception as e:
            not_finish_close = await page.query_selector(".el-message-box__headerbtn")
            if not_finish_close:
                await not_finish_close.click()
            continue


async def wait_for_verify(page: Page, event_loop) -> None:
    await page.wait_for_load_state("domcontentloaded")
    while True:
        try:
            await asyncio.sleep(1)
            await page.wait_for_selector(".yidun_modal__title", state="attached", timeout=1000)
            print("\n[Warn]检测到安全验证,请手动点击完成...")
            await page.wait_for_selector(".yidun_modal__title", state="hidden", timeout=24 * 3600 * 1000)
            event_loop.set()
            print("\n[Info]安全验证已完成,继续播放...")
        except Exception as e:
            continue


async def learning_loop(page: Page, config: Config):
    title_selector = await page.wait_for_selector(".source-name")
    course_title = await title_selector.text_content()
    print(f"[Info]当前课程:<<{course_title}>>")
    await page.wait_for_selector(".clearfix.video", state="attached")
    all_class = await get_filtered_class(page)
    start_time = time.time()
    cur_index = 0
    while cur_index < len(all_class):
        await all_class[cur_index].click()
        await page.wait_for_selector(".current_play", state="attached")
        await page.wait_for_timeout(1000)
        title = await get_lesson_name(page)
        print("[Info]正在学习:%s" % title)
        page.set_default_timeout(10000)
        curtime, total_time = await get_progress(page)
        timer = 0
        while curtime != "100%":
            try:
                time_period = (time.time() - start_time) / 60
                timer += 1
                if 0 < config.limitMaxTime <= time_period:
                    break
                elif timer % 5 == 0:
                    curtime, total_time = await get_progress(page)
                    show_progress(desc="完成进度:", cur_time=curtime)
                await asyncio.sleep(0.5)
            except TimeoutError as e:
                if await page.query_selector(".yidun_modal__title"):
                    await event_loop_verify.wait()
                elif await page.query_selector(".topic-title"):
                    await event_loop_answer.wait()
                else:
                    print(f"\n[Warn]{repr(e)}")
        if "current_play" in await all_class[cur_index].get_attribute('class'):
            cur_index += 1
        reachTimeLimit = await tail_work(page, start_time, all_class, title)
        if reachTimeLimit:
            return


async def reviewing_loop(page: Page, config: Config):
    limit_time = config.limitMaxTime
    title_selector = await page.wait_for_selector(".source-name")
    course_title = await title_selector.text_content()
    print(f"当前课程:<<{course_title}>>")
    await page.wait_for_selector(".clearfix.video", state="attached")
    all_class = await get_filtered_class(page, enableRepeat=True)
    course_start_time = time.time()
    cur_index = 0
    while cur_index < len(all_class):
        await all_class[cur_index].click()
        await page.wait_for_selector(".current_play", state="attached")
        await page.wait_for_timeout(1000)
        title = await get_lesson_name(page)
        print("\n正在学习:%s" % title)
        page.set_default_timeout(10000)
        curtime, total_time = await get_progress(page)
        start_time = time.time()
        timer = 0
        while True:
            est_time = (time.time() - start_time) * config.limitSpeed
            if est_time > total_time:
                break
            try:
                time_period = (time.time() - course_start_time) / 60
                timer += 1
                if 0 < config.limitMaxTime <= time_period:
                    break
                elif timer % 5 == 0:
                    show_progress(desc="完成进度:", cur_time=time_period, limit_time=limit_time, enableRepeat=True)
                await asyncio.sleep(0.5)
            except TimeoutError as e:
                if await page.query_selector(".yidun_modal__title"):
                    await event_loop_verify.wait()
                elif await page.query_selector(".topic-title"):
                    await event_loop_answer.wait()
                else:
                    print(f"\n[Warn]{repr(e)}")
        if "current_play" in await all_class[cur_index].get_attribute('class'):
            cur_index += 1
        reachTimeLimit = await tail_work(page, course_start_time, all_class, title)
        if reachTimeLimit:
            return

async def tail_work(page: Page, start_time, all_class, title) -> bool:
    reachTimeLimit = False
    page.set_default_timeout(24 * 3600 * 1000)
    time_period = (time.time() - start_time) / 60
    if 0 < config.limitMaxTime <= time_period:
        print(f"\n当前课程已达时限:{config.limitMaxTime}min\n即将进入下门课程!")
        reachTimeLimit = True
    else:
        class_name = await all_class[-1].get_attribute('class')
        if "current_play" in class_name:
            print("\n已学完本课程全部内容!")
            print("==" * 10)
        else:
            print(f"\"{title}\" Done !")
            print(f"本次课程已学习:{time_period:.1f} min")
    return reachTimeLimit


async def entrance(config: Config):
    tasks = []
    try:
        async with async_playwright() as p:
            page, browser = await init_page(p, config)
            # 进行登录
            if not config.username or not config.password:
                print("[Info]请手动输入账号密码...")
            print("[Info]等待登录完成...")
            await auto_login(config, page)
            # 启动协程任务
            video_optimize_task = asyncio.create_task(video_optimize(page, config))
            skip_ques_task = asyncio.create_task(skip_questions(page, event_loop_answer))
            play_video_task = asyncio.create_task(play_video(page))
            verify_task = asyncio.create_task(wait_for_verify(page, event_loop_verify))
            tasks.extend([video_optimize_task, skip_ques_task, play_video_task, verify_task])
            # 遍历所有课程,加载网页
            for course_url in config.course_urls:
                print("[Info]开始加载播放页...")
                await page.goto(course_url)
                await page.wait_for_selector(".studytime-div")
                # 关闭弹窗,优化页面体验
                await optimize_page(page, config)
                # 启动课程主循环
                if config.enableRepeat:
                    await reviewing_loop(page, config)
                else:
                    await learning_loop(page, config)
        print("==" * 10)
        print("所有课程学习完毕!")
        show_donate("res/QRcode.jpg")
    except Exception as e:
        print(f"\n[Error]:{repr(e)}")
        if isinstance(e, TargetClosedError):
            print("[Error]检测到网页关闭,正在退出程序...")
    finally:
        # 结束所有协程任务
        await asyncio.gather(*tasks, return_exceptions=True) if tasks else None
        time.sleep(3)


if __name__ == "__main__":
    print("Github:CXRunfree All Rights Reserved.")
    print("===== Runtime Log =====")
    try:
        print("[Info]正在载入数据...")
        config = Config()
        if not config.course_urls:
            print("[Error]不存在有效网址或程序不支持此类网页,请检查配置!")
            time.sleep(3)
            exit(-1)
        asyncio.run(entrance(config))
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
