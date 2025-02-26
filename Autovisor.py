# encoding=utf-8
import asyncio
import os
import time
import traceback
import sys
from playwright.async_api import async_playwright, Playwright, Page, Browser
from playwright.async_api import TimeoutError
from playwright._impl._errors import TargetClosedError
from modules.logger import Logger
from modules.configs import Config
from modules.progress import get_course_progress, show_course_progress
from modules.support import show_donate
from modules.utils import optimize_page, get_lesson_name, get_filtered_class, get_video_attr
from modules.slider import slider_verify
from modules.tasks import video_optimize, play_video, skip_questions, wait_for_verify
from modules import installer

# 获取全局事件循环
event_loop_verify = asyncio.Event()
event_loop_answer = asyncio.Event()


async def auto_login(config: Config, page: Page, modules=None):
    await page.goto(config.login_url, wait_until="commit")
    if "login" not in page.url:
        logger.info("检测到已登录,跳过登录步骤.")
        return
    if config.username and config.password:
        await page.wait_for_selector("#lUsername", state="attached")
        await page.wait_for_selector("#lPassword", state="attached")
        await page.locator('#lUsername').fill(config.username)
        await page.locator('#lPassword').fill(config.password)
        await page.wait_for_selector(".wall-sub-btn", state="attached")
        await page.wait_for_timeout(500)
        await page.evaluate(config.login_js)
    if config.get_autoCaptcha() and modules:
        await slider_verify(page, modules)
    await page.wait_for_selector(".wall-main", state='hidden')


async def init_page(p: Playwright, config: Config) -> tuple[Page, Browser]:
    driver = "msedge" if config.driver == "edge" else config.driver
    logger.info(f"正在启动{config.driver}浏览器...")
    browser = await p.chromium.launch(
        channel=driver,
        headless=False,
        executable_path=config.exe_path if config.exe_path else None,
    )
    page = await browser.new_page()
    logger.write_log(f"{config.driver}浏览器启动完成.\n")
    #抹去特征
    with open('res/stealth.min.js', 'r') as f:
        js = f.read()
    await page.add_init_script(js)
    logger.write_log(f"stealth.js注入完成.\n")
    page.set_default_timeout(24 * 3600 * 1000)
    viewsize = await page.evaluate(
        '''() => {
            return {width: window.screen.availWidth, height: window.screen.availHeight};
        }'''
    )
    viewsize["height"] -= 60
    await page.set_viewport_size(viewsize)
    logger.write_log(f"窗口大小设置完成.\n")
    return page, browser


async def learning_loop(page: Page, start_time):
    cur_time = await get_course_progress(page)
    while cur_time != "100%":
        try:
            limit_time = config.limitMaxTime
            time_period = (time.time() - start_time) / 60
            if 0 < limit_time <= time_period:
                break
            cur_time = await get_course_progress(page)
            show_course_progress(desc="完成进度:", cur_time=cur_time)
            await asyncio.sleep(0.5)
        except TimeoutError as e:
            if await page.query_selector(".yidun_modal__title"):
                await event_loop_verify.wait()
            elif await page.query_selector(".topic-title"):
                await event_loop_answer.wait()
            else:
                logger.warn(repr(e))


async def review_loop(page: Page, start_time):
    total_time = await get_video_attr(page, "duration")
    await page.evaluate(config.reset_curtime)  # 重置视频播放时间
    while True:
        limit_time = config.limitMaxTime
        cur_time = await get_video_attr(page, "currentTime")
        if cur_time >= total_time:
            break
        try:
            time_period = (time.time() - start_time) / 60
            if 0 < limit_time <= time_period:
                break
            show_course_progress(desc="完成进度:", cur_time=time_period, limit_time=limit_time)
            await asyncio.sleep(0.5)
        except TimeoutError as e:
            if await page.query_selector(".yidun_modal__title"):
                await event_loop_verify.wait()
            elif await page.query_selector(".topic-title"):
                await event_loop_answer.wait()
            else:
                logger.warn(repr(e))


async def working_loop(page: Page, is_new_version=False):
    # 获取所有课程元素
    await page.wait_for_selector(".clearfix.video", state="attached")
    to_learn_class = await get_filtered_class(page, is_new_version)
    learning = True if len(to_learn_class) > 0 else False
    if learning:
        all_class = to_learn_class
    else:
        all_class = await get_filtered_class(page, is_new_version, include_all=True)
    start_time = time.time()
    cur_index = 0

    while cur_index < len(all_class):
        await all_class[cur_index].click()
        await page.wait_for_selector(".current_play", state="attached")
        await page.wait_for_timeout(1000)
        title = await get_lesson_name(page)
        logger.info(f"正在学习:{title}")
        page.set_default_timeout(10000)
        # 移除视频暂停功能
        await page.wait_for_selector("video", state="attached")
        await page.evaluate(config.remove_pause)
        if learning:
            await learning_loop(page, start_time)
        else:
            await review_loop(page, start_time)
        if "current_play" in await all_class[cur_index].get_attribute('class'):
            cur_index += 1
        reachTimeLimit = await check_time_limit(page, start_time, all_class, title)
        if reachTimeLimit:
            return


async def check_time_limit(page: Page, start_time, all_class, title) -> bool:
    reachTimeLimit = False
    page.set_default_timeout(24 * 3600 * 1000)
    time_period = (time.time() - start_time) / 60
    if 0 < config.limitMaxTime <= time_period:
        logger.info(f"当前课程已达时限:{config.limitMaxTime}min", shift=True)
        logger.info("即将进入下门课程!")
        reachTimeLimit = True
    else:
        class_name = await all_class[-1].get_attribute('class')
        if "current_play" in class_name:
            logger.info("已学完本课程全部内容!", shift=True)
            print("==" * 10)
        else:
            logger.info(f"\"{title}\" 已完成!", shift=True)
            logger.info(f"本次课程已学习:{time_period:.1f} min")
    return reachTimeLimit


async def main(config: Config):
    modules, tasks = [], []
    if config.get_autoCaptcha():
        print("===== Install log =====")
        logger.info("开始下载依赖库...")
        modules = installer.start()
        logger.info("所有依赖库下载完成!")
    try:
        print("===== Runtime Log =====")
        async with async_playwright() as p:
            page, browser = await init_page(p, config)
            # 进行登录
            if not config.username or not config.password:
                logger.info("请手动填写账号密码...")
            logger.info("正在等待登录完成...")
            # 先启动人机验证协程
            verify_task = asyncio.create_task(wait_for_verify(page, event_loop_verify))
            await auto_login(config, page, modules)
            # 启动协程任务
            video_optimize_task = asyncio.create_task(video_optimize(page, config))
            skip_ques_task = asyncio.create_task(skip_questions(page, event_loop_answer))
            play_video_task = asyncio.create_task(play_video(page))
            tasks.extend([verify_task, video_optimize_task, skip_ques_task, play_video_task])
            # 遍历所有课程,加载网页
            for course_url in config.course_urls:
                print("==" * 10)
                is_new_version = "fusioncourseh5" in course_url
                logger.info("正在加载播放页...")
                await page.goto(course_url, wait_until="commit")
                # 关闭弹窗,优化页面结构
                await optimize_page(page, config, is_new_version)
                logger.info("页面优化完成!")
                # 获取课程标题
                if not is_new_version:
                    title_selector = await page.wait_for_selector(".source-name")
                    course_title = await title_selector.text_content()
                    logger.info(f"当前课程:<<{course_title}>>")
                # 启动课程主循环
                await working_loop(page, is_new_version=is_new_version)
        print("==" * 10)
        logger.info("所有课程已学习完毕!")
        show_donate("res/QRcode.jpg")
    except TargetClosedError as e:
        if "BrowserType.launch" in repr(e):
            logger.error("浏览器启动失败,请重新启动程序!")
        else:
            logger.error("浏览器被关闭,程序退出.")
    except Exception as e:
        logger.error(repr(e), shift=True)
    finally:
        logger.write_log(traceback.format_exc())
        # 结束所有协程任务
        await asyncio.gather(*tasks, return_exceptions=True) if tasks else None


if __name__ == "__main__":
    print("Github:CXRunfree All Rights Reserved.")
    logger = Logger()
    try:
        logger.info("程序启动中...")
        config = Config("configs.ini")
        if not config.course_urls:
            logger.info("未检测到有效网址或不支持此类网页,请检查配置文件!")
            time.sleep(2)
            sys.exit(-1)
        asyncio.run(main(config))
    except Exception as e:
        logger.error(repr(e), shift=True)
        logger.write_log(traceback.format_exc())
        if isinstance(e, KeyError):
            logger.error(f"配置文件错误!")
        elif isinstance(e, FileNotFoundError):
            logger.error(f"依赖文件缺失: {e.filename},请重新安装程序!")
        elif isinstance(e, UnicodeDecodeError):
            logger.error("配置文件编码错误,保存时请选择UTF-8或GBK编码!")
        else:
            logger.error("系统出错,请检查后重新启动!")
        logger.write_log(traceback.format_exc())
        logger.save()
    finally:
        os.system("pause")
