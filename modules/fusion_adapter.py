# encoding=utf-8
"""智慧树【新版融合共享课 / AI 慕课】适配层 (迁移自旧版 modules/fusion.py)

背景
----
官方 Autocar(3.18.3) 已把课程主循环重构进 ``modules/course_runner.py`` 的
``run_course()``, 并通过 ``modules/lesson_navigation`` 内置了
``FUSION_CATALOG`` / ``MOOC_CATALOG``。本适配器补齐官方缺失的专有行为:

1. ``skip_ai_class_exercise`` — **AI 随堂练习弹窗**自动选选项并提交。
   - 视频播到 AI 时间点时, 智慧树会暂停视频并弹出 ``.ai-class-exercise-dialog``;
     无关闭/跳过按钮, 但选任意选项并提交即可关闭。
   - wisdom-mooc 的提交按钮是 ``.dialog-footer .btn``, 融合课仍可能是
     ``el-dialog__footer button``; 提交后点 ``.header-icon`` 关掉弹窗。
   - 关闭后视频处于暂停, 需恢复播放。
2. ``skip_question_panel`` — wisdom-mooc 课中练习面板 (``.question-body``)。
3. ``expand_catalog`` — 折叠章节展开; wisdom-mooc 还需展开被收起的侧栏。
4. ``resume_video`` -- 弹窗/异常后恢复课程视频播放的兜底。
"""
import json

from playwright.async_api import Page
from playwright._impl._errors import TargetClosedError

from modules.logger import Logger
from modules.video_state import COURSE_VIDEO_SELECTOR

logger = Logger()

# AI 随堂练习弹窗及其内部操作元素选择器。
AI_CLASS_EXERCISE_DIALOG = ".ai-class-exercise-dialog"
_OPTION_SELECTOR = ".ai-class-exercise-dialog .option"
_SUBMIT_SELECTOR = ", ".join(
    (
        ".ai-class-exercise-dialog .dialog-footer .btn:not(.is-finish)",
        ".ai-class-exercise-dialog .dialog-footer .btn",
        ".ai-class-exercise-dialog .el-dialog__footer button.el-button",
    )
)
_CLOSE_SELECTOR = ".ai-class-exercise-dialog .header-icon"
QUESTION_PANEL_SELECTOR = ".question-body"

# 弹窗里常有多道题; 只点第一个 .option 会触发「暂未作答，请完成作答后再提交」。
_SELECT_EACH_QUESTION_JS = """() => {
    const dlg = [...document.querySelectorAll('.ai-class-exercise-dialog')].find(el => {
        const s = getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || el.offsetWidth <= 0)
            return false;
        let p = el.parentElement;
        while (p && p !== document.body) {
            const ps = getComputedStyle(p);
            if (ps.display === 'none' || ps.visibility === 'hidden') return false;
            p = p.parentElement;
        }
        return true;
    });
    if (!dlg) return {ok: false, selected: 0, questions: 0};
    const items = [...dlg.querySelectorAll('.ques-list .item')];
    const roots = items.length ? items : [dlg];
    let selected = 0;
    for (const root of roots) {
        if (root.querySelector('.class-question-select.isSelect')) continue;
        const opt = root.querySelector('.option');
        if (opt) { opt.click(); selected++; }
    }
    return {ok: true, selected, questions: roots.length};
}"""
_HAS_FINISH_JS = """() => {
    const dlg = [...document.querySelectorAll('.ai-class-exercise-dialog')].find(el => {
        const s = getComputedStyle(el);
        return s.display !== 'none' && s.visibility !== 'hidden' && el.offsetWidth > 0;
    });
    return Boolean(dlg && dlg.querySelector('.btn.is-finish'));
}"""
_CLICK_SUBMIT_IN_DIALOG_JS = """() => {
    const dlg = [...document.querySelectorAll('.ai-class-exercise-dialog')].find(el => {
        const s = getComputedStyle(el);
        return s.display !== 'none' && s.visibility !== 'hidden' && el.offsetWidth > 0;
    });
    if (!dlg) return false;
    const sels = [
        '.dialog-footer .btn:not(.is-finish)',
        '.el-dialog__footer button.el-button',
        '.dialog-footer .btn',
    ];
    for (const sel of sels) {
        const el = dlg.querySelector(sel);
        if (el) { el.click(); return true; }
    }
    return false;
}"""
_CLICK_CLOSE_IN_DIALOG_JS = """() => {
    const dlg = [...document.querySelectorAll('.ai-class-exercise-dialog')].find(el => {
        const s = getComputedStyle(el);
        return s.display !== 'none' && s.visibility !== 'hidden' && el.offsetWidth > 0;
    });
    if (!dlg) return false;
    const el = dlg.querySelector('.header-icon');
    if (!el) return false;
    el.click();
    return true;
}"""


def _visible_script(selector: str) -> str:
    return f"""() => {{
        const dlg = document.querySelector({json.dumps(selector)});
        if (!dlg) return false;
        let p = dlg.parentElement;
        while (p && p !== document.body) {{
            const s = getComputedStyle(p);
            if (s.display==='none' || s.visibility==='hidden')
                return false;
            p = p.parentElement;
        }}
        return dlg.offsetWidth > 0 &&
               getComputedStyle(dlg).display !== 'none';
    }}"""


def _click_script(selector: str) -> str:
    return f"""() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (el) {{ el.click(); return true; }}
        return false;
    }}"""


class FusionAdapter:
    """融合课 / AI 慕课适配层: 只做官方 run_course / tasks 未覆盖的附加行为。"""

    @staticmethod
    async def ai_exercise_visible(page: Page) -> bool:
        """AI 随堂弹窗当前是否可见(考虑祖先 display/visibility, 过滤隐藏的)。"""
        try:
            return bool(await page.evaluate(_visible_script(AI_CLASS_EXERCISE_DIALOG)))
        except Exception as exc:
            logger.debug_throttled(
                "fusion:ai_visible",
                f"AI随堂弹窗检测跳过: {logger.summarize_exception(exc)}",
            )
            return False

    @staticmethod
    async def expand_catalog(page: Page) -> int:
        """展开侧栏与折叠章节, 返回展开个数。"""
        try:
            n = await page.evaluate(
                """() => {
                    let n = 0;
                    const wrap = document.querySelector('.chapter-wrapper');
                    if (wrap && wrap.classList.contains('hidden')) {
                        const toggle = document.querySelector(
                            '.course-catalog .collapse-box, .collapse-box'
                        );
                        if (toggle) { toggle.click(); n++; }
                    }
                    document.querySelectorAll('.el-collapse-item').forEach(it => {
                        if ((it.className||'').indexOf('is-active') < 0) {
                            const h = it.querySelector('.el-collapse-item__header');
                            if (h) { h.click(); n++; }
                        }
                    });
                    return n;
                }"""
            )
            if n:
                await page.wait_for_timeout(400)
                logger.debug(f"目录已展开 {n} 个折叠项")
            return n or 0
        except Exception as e:
            logger.debug_throttled(
                "fusion:expand", f"展开折叠目录失败: {logger.summarize_exception(e)}"
            )
            return 0

    @staticmethod
    async def resume_video(page: Page) -> None:
        """AI弹窗关闭后/任意暂停时, 恢复课程视频播放(静音兜底防自动暂停)。"""
        try:
            await page.evaluate(
                f"""() => {{
                    const v = document.querySelector({json.dumps(COURSE_VIDEO_SELECTOR)});
                    if (v) {{ v.muted = true; v.play().catch(()=>{{}}); }}
                }}"""
            )
        except TargetClosedError:
            logger.debug("fusion:resume 浏览器已关闭.")
        except Exception as exc:
            logger.debug_throttled(
                "fusion:resume",
                f"恢复视频播放跳过: {logger.summarize_exception(exc)}",
            )

    @staticmethod
    async def skip_ai_exercise(page: Page) -> bool:
        """检测 AI 随堂弹窗并自动选选项+提交, 成功(或已处理)返回 True。

        顺序: 每道题选一个选项 -> 点提交 -> 等已完成/弹窗消失 -> 点关闭图标 -> 恢复播放。
        未作答的题不能提交也不能关闭; 只点第一题会把播放循环卡死。
        """
        if not await FusionAdapter.ai_exercise_visible(page):
            return False
        logger.info("检测到 AI随堂练习弹窗, 自动选择并提交.")
        try:
            if await page.evaluate(_HAS_FINISH_JS):
                await page.evaluate(_CLICK_CLOSE_IN_DIALOG_JS)
                await page.wait_for_timeout(400)
                if not await FusionAdapter.ai_exercise_visible(page):
                    logger.info("AI 随堂练习已自动提交关闭.")
                    await FusionAdapter.resume_video(page)
                    return True

            result = await page.evaluate(_SELECT_EACH_QUESTION_JS) or {}
            selected = int(result.get("selected") or 0)
            questions = int(result.get("questions") or 0)
            if questions:
                logger.info(f"AI随堂已选择 {selected}/{questions} 题.")
            elif not selected:
                logger.debug_throttled("fusion:ai_opt", "未找到选项按钮")
            await page.wait_for_timeout(500)
            await page.evaluate(_CLICK_SUBMIT_IN_DIALOG_JS)

            closed = False
            for _ in range(12):
                await page.wait_for_timeout(400)
                if not await FusionAdapter.ai_exercise_visible(page):
                    closed = True
                    break
                if await page.evaluate(_HAS_FINISH_JS):
                    await page.evaluate(_CLICK_CLOSE_IN_DIALOG_JS)
            if not closed and await FusionAdapter.ai_exercise_visible(page):
                await page.evaluate(_CLICK_CLOSE_IN_DIALOG_JS)
                await page.wait_for_timeout(400)
                closed = not await FusionAdapter.ai_exercise_visible(page)

            if closed:
                logger.info("AI 随堂练习已自动提交关闭.")
                await FusionAdapter.resume_video(page)
                return True
            logger.warn("AI 随堂练习仍未关闭,稍后重试.")
            await page.wait_for_timeout(1500)
            return True
        except TargetClosedError:
            logger.debug("fusion:ai 浏览器已关闭.")
            return False
        except Exception as exc:
            logger.debug_throttled(
                "fusion:ai", f"AI随堂自动提交失败: {logger.summarize_exception(exc)}"
            )
            return False

    @staticmethod
    async def skip_question_panel(page: Page) -> bool:
        """wisdom-mooc 课中练习面板: 选题、提交, 必要时关掉面板。"""
        try:
            if not bool(await page.evaluate(_visible_script(QUESTION_PANEL_SELECTOR))):
                return False
        except TargetClosedError:
            logger.debug("fusion:question 浏览器已关闭.")
            return False
        except Exception as exc:
            logger.debug_throttled(
                "fusion:question_visible",
                f"课中练习面板检测跳过: {logger.summarize_exception(exc)}",
            )
            return False

        logger.info("检测到课中练习面板, 自动选择并提交.")
        try:
            handled = bool(
                await page.evaluate(
                    f"""() => {{
                        const root = document.querySelector({json.dumps(QUESTION_PANEL_SELECTOR)});
                        if (!root) return false;
                        const opt = root.querySelector('.option');
                        if (opt) opt.click();
                        const submit = root.querySelector(
                            '.submit-btn .submits, .submit-footer .submit-btn, .submit-btn'
                        );
                        if (submit) submit.click();
                        return Boolean(opt || submit);
                    }}"""
                )
            )
            await page.wait_for_timeout(800)
            await page.evaluate(
                f"""() => {{
                    const root = document.querySelector({json.dumps(QUESTION_PANEL_SELECTOR)});
                    const close = root && root.querySelector('.close-box');
                    if (close) close.click();
                }}"""
            )
            await FusionAdapter.resume_video(page)
            return handled
        except TargetClosedError:
            logger.debug("fusion:question 浏览器已关闭.")
            return False
        except Exception as exc:
            logger.debug_throttled(
                "fusion:question",
                f"课中练习自动提交失败: {logger.summarize_exception(exc)}",
            )
            return False

    @staticmethod
    async def skip_blocking_quizzes(page: Page) -> bool:
        """处理当前挡住播放的 AI 随堂弹窗或课中练习面板。"""
        skipped = await FusionAdapter.skip_ai_exercise(page)
        skipped = await FusionAdapter.skip_question_panel(page) or skipped
        return skipped
