from preview.modules.quark import quark_search
from playwright.async_api import Page, BrowserContext
from modules.logger import Logger


logger = Logger()

async def handle_quark_answer(context: BrowserContext, page: Page, ticket: str | None):
    if not ticket:
        return
    await page.wait_for_selector(".examItemWrap", state="attached")
    exam_wraps = await page.locator(".examItemWrap").all()
    for exam in exam_wraps:
        await page.wait_for_timeout(1500)
        unit_title = await exam.locator(".name.middle").text_content()
        logger.info(f"开始答题: {unit_title.strip()}", shift=True)
        # 进入答题页
        async with context.expect_page() as new_page_info:
            enter_btn = exam.locator(".themeBg")
            await enter_btn.click()
        ques_page: Page = await new_page_info.value
        await ques_page.wait_for_load_state("domcontentloaded")
        await ques_page.wait_for_selector(".examPaper_subject", state="visible")
        question_elements = await ques_page.locator(".examPaper_subject").all()
        if len(question_elements) > 0:
            logger.info("已检测到习题.", shift=True)
        else:
            logger.info("未检测到习题,即将跳过本单元", shift=True)
            break
        # 等待题目出现
        await ques_page.wait_for_selector(".subject_describe", state="visible")
        await ques_page.wait_for_selector(".subject_node", state="visible")
        for question in question_elements:
            await ques_page.wait_for_timeout(1000)
            next_btn = await ques_page.query_selector('button:has-text("下一题")')
            save_btn = await ques_page.query_selector('button:has-text("保存")')
            question_img = await question.screenshot()
            # 搜索题目答案
            logger.info("正在搜题...")
            answers = await quark_search(question_img)
            if len(answers) > 0:
                logger.info("答案搜索成功.")
            else:
                logger.warn("未搜索到答案.")
            choices = await question.locator('.examquestions-answer').all()
            for letter in answers:
                index = ord(letter.upper()) - ord("A")
                if index > len(choices):
                    logger.warn("当前答案有误,将跳过本题.")
                await choices[index].evaluate("node => node.click()")
                await ques_page.wait_for_timeout(3000)
            if next_btn:
                await ques_page.wait_for_timeout(300)
                await next_btn.evaluate("node => node.click()")
                logger.info("即将进入下一题.")
                continue
            if save_btn:
                await save_btn.evaluate("node => node.click()")
                logger.info("已保存答案,即将进入下一单元.")
                break
        else:
            logger.info("已完成当前单元所有题目,即将返回.", shift=True)
            break

        await ques_page.close()
