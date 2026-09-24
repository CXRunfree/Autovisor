# encoding=utf-8
"""智慧树【新版融合共享课】适配层 (迁移自旧版 modules/fusion.py)

背景
----
官方 Autocar(3.18.3) 已把课程主循环重构进 ``modules/course_runner.py`` 的
``run_course()``, 并通过 ``modules/lesson_navigation`` 内置了
``FUSION_CATALOG``(识别 ``.chapter-content-second / .finish-icon / .item-name``)。
即"目录识别"和"课时循环"官方已支持。本适配器补齐官方缺失的三个融合页专有行为:

1. ``skip_ai_class_exercise`` — **AI 随堂练习弹窗**自动选选项并提交(官方没有)。
   - 视频播到 AI 时间点时, 智慧树会暂停视频并弹出 ``.ai-class-exercise-dialog``;
     无关闭/跳过按钮, 但选任意选项并提交即可关闭。
   - 关闭后视频处于暂停, 需恢复播放。
2. ``expand_catalog`` — 融合目录的折叠小节展开 (官方 `get_filtered_class` 不展开)。
3. ``resume_video`` -- 弹窗/异常后恢复视频播放的兜底。

设计原则
--------
与官方 3.18.3 对齐: 复用 ``modules.logger.Logger`` 的
``event`` / ``debug_throttled`` / ``summarize_exception``; 只提供"适配小函数",
由官方 ``tasks.skip_questions`` 或 ``course_runner`` 在融合 catalog 分支调用,
不复制官方主循环, 便于独立测试与回退。
"""
from playwright.async_api import Page
from playwright._impl._errors import TargetClosedError

from modules.logger import Logger

logger = Logger()

# AI 随堂练习弹窗及其内部操作元素选择器。
AI_CLASS_EXERCISE_DIALOG = ".ai-class-exercise-dialog"
_OPTION_SELECTOR = ".ai-class-exercise-dialog .option"
_SUBMIT_SELECTOR = ".ai-class-exercise-dialog .el-dialog__footer button.el-button"
# 折叠章节头(Element-UI collapse), 需展开以采集完整课时列表。
COLLAPSE_HEADER_SELECTOR = ".el-collapse-item__header"


class FusionAdapter:
    """融合课适配层: 只做官方 run_course / tasks 未覆盖的融合页附加行为。"""

    @staticmethod
    async def ai_exercise_visible(page: Page) -> bool:
        """AI 随堂弹窗当前是否可见(考虑祖先 display/visibility, 过滤隐藏的)。"""
        try:
            return bool(
                await page.evaluate(
                    """() => {
                        const dlg = document.querySelector(%s);
                        if (!dlg) return false;
                        let p = dlg.parentElement;
                        while (p && p !== document.body) {
                            const s = getComputedStyle(p);
                            if (s.display==='none' || s.visibility==='hidden')
                                return false;
                            p = p.parentElement;
                        }
                        return dlg.offsetWidth > 0 &&
                               getComputedStyle(dlg).display !== 'none';
                    }"""
                    % ("'" + AI_CLASS_EXERCISE_DIALOG + "'",)
                )
            )
        except Exception as exc:
            logger.debug_throttled(
                "fusion:ai_visible",
                f"AI随堂弹窗检测跳过: {logger.summarize_exception(exc)}",
            )
            return False

    @staticmethod
    async def expand_catalog(page: Page) -> int:
        """展开折叠目录里未激活的章节头, 返回展开个数。"""
        try:
            n = await page.evaluate(
                """() => {
                    let n = 0;
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
                logger.debug(f"融合目录已展开 {n} 个折叠项")
            return n or 0
        except Exception as e:
            logger.debug_throttled(
                "fusion:expand", f"展开折叠目录失败: {logger.summarize_exception(e)}"
            )
            return 0

    @staticmethod
    async def resume_video(page: Page) -> None:
        """AI弹窗关闭后/任意暂停时, 恢复视频播放(静音兜底防自动暂停)。"""
        try:
            await page.evaluate(
                """() => {
                    const v = document.querySelector('video');
                    if (v) { v.muted = true; v.play().catch(()=>{}); }
                }"""
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

        顺序: 选第一个选项 -> 点提交 -> 关闭后恢复播放。
        """
        if not await FusionAdapter.ai_exercise_visible(page):
            return False
        logger.info("检测到 AI随堂练习弹窗, 自动选择并提交.")
        try:
            clicked = bool(
                await page.evaluate(
                    """() => {
                        const opt = document.querySelector(%s);
                        if (opt) { opt.click(); return true; }
                        return false;
                    }""" % ("'" + _OPTION_SELECTOR + "'",)
                )
            )
            if not clicked:
                logger.debug_throttled("fusion:ai_opt", "未找到选项按钮")
            await page.wait_for_timeout(600)
            submitted = bool(
                await page.evaluate(
                    """() => {
                        const btn = document.querySelector(%s);
                        if (btn) { btn.click(); return true; }
                        return false;
                    }""" % ("'" + _SUBMIT_SELECTOR + "'",)
                )
            )
            await page.wait_for_timeout(1000)
            logger.info("AI 随堂练习已自动提交关闭.")
            await FusionAdapter.resume_video(page)
            return bool(clicked or submitted)
        except TargetClosedError:
            logger.debug("fusion:ai 浏览器已关闭.")
            return False
        except Exception as exc:
            logger.debug_throttled(
                "fusion:ai", f"AI随堂自动提交失败: {logger.summarize_exception(exc)}"
            )
            return False