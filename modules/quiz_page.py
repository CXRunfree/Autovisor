# -*- coding: utf-8 -*-
"""捕获课程流程中新开的测验页面, 自动大模型作答。

挂载: Autovisor.main() 里 context.on("page", ...)。
流程:
1. 首答: 逐页 抽题->与页面已选状态比对->只点差额->确认->下一题。
2. auto_submit=true 时: 交卷前刷新页面、回到第一题, 整卷复核一遍后再提交。
"""
import asyncio
import difflib
import re
import time

from playwright._impl._errors import TargetClosedError

from modules import llm
from modules.logger import Logger

logger = Logger()

# 同一 URL 10 分钟内不重复作答
ANSWERED = {}
_ANSWER_COOLDOWN = 600

_SUBMIT_TEXTS = ("提交", "交卷", "完成测验", "完成考试", "确认提交")
_CONFIRM_TEXTS = ("确定", "确认", "继续提交")
_NEXT_TEXTS = ("下一题", "下一页", "下一个", "下一步")

JS_COLLECT = r"""
() => {
  const groups = new Map();
  let seq = 0;
  const els = [...document.querySelectorAll("input[type=radio],input[type=checkbox]")];
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    let label = null;
    if (el.id) label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
    label = label || el.closest("label") || el.closest(".el-radio")
         || el.closest(".el-checkbox") || el.closest(".ant-radio-wrapper")
         || el.closest(".ant-checkbox-wrapper");
    let text = label ? label.innerText : "";
    if (!text) { const box = el.closest("li,td,dd,div"); text = box ? box.innerText : ""; }
    text = text.trim().replace(/\s+/g, " ").slice(0, 300);
    let key = el.name;
    if (!key) {
      const ctx = el.closest("form,fieldset,.el-radio-group,.el-checkbox-group,[class*=question],[class*=topic]") || document.body;
      if (!ctx.__qhKey) ctx.__qhKey = "__ctx_" + (++seq);
      key = ctx.__qhKey;
    }
    el.dataset.qhKey = key;
    if (!groups.has(key)) groups.set(key, { type: el.type, options: [] });
    groups.get(key).options.push({ text, idx: groups.get(key).options.length, sel: !!el.checked });
  }
  return [...groups.entries()].map(([name, g]) => ({ name, type: g.type, options: g.options }));
}
"""

JS_CLICK = r"""
([key, idx]) => {
  const els = [...document.querySelectorAll("input[type=radio],input[type=checkbox]")]
    .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 || r.height > 0; })
    .filter(el => (el.dataset.qhKey || el.name) === key);
  const el = els[idx];
  if (!el) return false;
  if (el.type === "checkbox" && el.checked) return true;
  let target = null;
  if (el.id) target = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
  target = target || el.closest("label") || el.closest(".el-radio")
        || el.closest(".el-checkbox") || el.closest(".ant-radio-wrapper") || el;
  target.click();
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}
"""

JS_CHECK_ANSWERED = r"""
() => {
  const res = { hasGroups: false, nativeAnswered: false, selectedCount: 0, toast: "" };
  const inputs = [...document.querySelectorAll("input[type=radio],input[type=checkbox]")]
    .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 || r.height > 0; });
  if (inputs.length) {
    res.hasGroups = true;
    res.nativeAnswered = inputs.some(el => el.checked);
  }
  const selRe = /(^|\s)(active|checked|selected|is-active|is-checked|is-selected)(\s|$)/;
  document.querySelectorAll("li,label,div,span,[class*=option],[class*=item]").forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    const cls = el.className || "";
    if (typeof cls === "string" && selRe.test(cls)) res.selectedCount++;
  });
  const m = (document.body.innerText || "").match(/请先[作选][答择]|请[作选][答择]|尚未作答|未作答|请答题/);
  if (m) res.toast = m[0];
  return res;
}
"""

JS_TEXTBOXES = r"""
() => [...document.querySelectorAll("textarea, input[type=text]")]
  .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !el.value.trim(); })
  .map((el, i) => ({ i }))
"""

JS_FILL = r"""
(i, value) => {
  const els = [...document.querySelectorAll("textarea, input[type=text]")]
    .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !el.value.trim(); });
  const el = els[i];
  if (!el) return false;
  el.focus(); el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}
"""

JS_FIND_BUTTON = r"""
(texts) => {
  const norm = (s) => (s || "").replace(/[\s\u3000]+/g, "");
  const wanted = texts.map(t => norm(t)).filter(Boolean);
  if (!wanted.length) return false;
  const els = [...document.querySelectorAll(
    "button, a, input, div, span, li, p, img, [role=button], .el-button, .btn"
  )];
  let best = null, bestScore = Infinity;
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0 || r.height > 120) continue;
    let t = "";
    if (el.tagName === "INPUT") t = el.value || "";
    if (!t) t = el.innerText || "";
    if (!t) t = el.getAttribute("title") || "";
    if (!t) t = el.getAttribute("aria-label") || "";
    if (!t) t = el.getAttribute("alt") || "";
    t = String(t).trim();
    if (!t || t.length > 12) continue;
    const nt = norm(t);
    if (!wanted.some(w => nt === w || nt.includes(w))) continue;
    const style = getComputedStyle(el);
    const isBtn = ["BUTTON", "A", "INPUT"].includes(el.tagName) || style.cursor === "pointer";
    const score = (isBtn ? 0 : 5) + nt.length;
    if (score < bestScore) { best = el; bestScore = score; }
  }
  if (!best) return false;
  best.click();
  return true;
}
"""

# 返回码: 0=没找到选项 1=已选中(跳过) 2=已点击
JS_OPTION_CLICK = r"""
(args) => {
  const t = args[0], force = args[1];
  const n = (s) => (s || "").replace(/[\s\u3000]+/g, "");
  const t0 = n(t);
  const stripPrefix = (s) => s.replace(/^[A-Ha-h][.、．:：]\s*/, "");
  let best = null, bestLen = Infinity;
  for (const el of document.querySelectorAll("li,label,td,p,span,div,[class*=option],[class*=item],[class*=choice]")) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0 || r.height > 200) continue;
    const txt = n(el.innerText || "");
    if (!txt || txt.length > t0.length + 12) continue;
    if (txt !== t0 && stripPrefix(txt) !== t0) continue;
    if (txt.length < bestLen) { best = el; bestLen = txt.length; }
  }
  if (!best) return 0;
  const c = best.closest("li,label,[class*=item],[class*=option]") || best;
  const cls = (c.className || "") + " " + (best.className || "");
  if (!force && /(^|\s)(active|checked|selected|is-active|is-checked|is-selected)(\s|$)/.test(cls)) return 1;
  c.click();
  return 2;
}
"""

JS_SELECTED_TEXTS = r"""
() => {
  const selRe = /(^|\s)(active|checked|selected|is-active|is-checked|is-selected)(\s|$)/;
  const out = [];
  document.querySelectorAll("li,label,div,span,[class*=option],[class*=item]").forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0 || r.height > 200) return;
    const cls = el.className || "";
    if (typeof cls !== "string" || !selRe.test(cls)) return;
    const t = (el.innerText || "").trim().replace(/\s+/g, " ");
    if (t && t.length <= 60) out.push(t);
  });
  return out;
}
"""


def _norm(s: str) -> str:
    return re.sub(r"[\s\u3000]+", "", s or "")


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def match_group(question: dict, groups: list):
    """按选项文本相似度把题配到 DOM 选项组, 返回组 dict 或 None。"""
    q_opts = question.get("options") or []
    if not q_opts:
        return None
    best, best_score = None, 0.0
    for g in groups:
        dom_opts = [o.get("text", "") for o in g.get("options", [])]
        if not dom_opts:
            continue
        score = sum(max((_sim(qo, d) for d in dom_opts), default=0.0) for qo in q_opts)
        score /= len(q_opts)
        if score > best_score:
            best, best_score = g, score
    if best is not None and best_score >= 0.45:
        return best
    return None


async def _click(page, key: str, idx: int) -> bool:
    try:
        return bool(await page.evaluate(JS_CLICK, [key, idx]))
    except Exception:
        return False


async def _click_by_text(page, option_text: str, force: bool = False) -> str:
    """文本匹配点选项。返回: "notfound" / "already"(已选中跳过) / "clicked"。"""
    target0 = _norm(option_text)
    if not target0 or len(target0) > 60:
        return "notfound"
    try:
        code = await page.evaluate(JS_OPTION_CLICK, [option_text, force])
    except Exception:
        return "notfound"
    return {0: "notfound", 1: "already", 2: "clicked"}.get(code, "notfound")


async def _click_prev(page) -> bool:
    try:
        return bool(await page.evaluate(JS_FIND_BUTTON, ["上一题", "上一页", "上一步"]))
    except Exception:
        return False


async def _click_next(page) -> bool:
    """三重查找: 主文档全元素扫描 -> Playwright 文本精确定位 -> 逐个 iframe。"""
    try:
        if await page.evaluate(JS_FIND_BUTTON, list(_NEXT_TEXTS)):
            return True
    except Exception:
        pass
    try:
        loc = page.get_by_text("下一题", exact=True)
        if await loc.count():
            await loc.first.click(timeout=3000)
            return True
    except Exception:
        pass
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            if await frame.evaluate(JS_FIND_BUTTON, list(_NEXT_TEXTS)):
                logger.debug("下一题按钮在 iframe 中, 已点击.")
                return True
        except Exception:
            continue
    try:
        btn_texts = await page.evaluate(
            "() => [...document.querySelectorAll('button')]"
            ".filter(b => b.getBoundingClientRect().width > 0)"
            ".map(b => (b.innerText || '').trim()).filter(Boolean)"
        )
        logger.info(f"未找到下一题按钮, 当前页面可见按钮: {btn_texts}")
    except Exception:
        pass
    return False


async def _click_confirm(page) -> bool:
    """部分考试 UI 需要先点"确认答案"才允许翻页, 有则点, 没有跳过。"""
    try:
        return bool(
            await page.evaluate(JS_FIND_BUTTON, ["确认答案", "确认作答", "确定答案", "确定"])
        )
    except Exception:
        return False


async def _try_submit(page):
    try:
        clicked = await page.evaluate(JS_FIND_BUTTON, list(_SUBMIT_TEXTS))
        if not clicked:
            logger.warn("测验页未找到提交按钮, 请手动提交.")
            return
        await page.wait_for_timeout(1200)
        for _ in range(3):
            if not await page.evaluate(JS_FIND_BUTTON, list(_CONFIRM_TEXTS)):
                break
            await page.wait_for_timeout(800)
        logger.info("测验页已点击提交并处理确认弹窗.")
    except Exception as exc:
        logger.warn(f"自动提交失败, 请手动提交: {exc}")


async def _fill_blank(page, q: dict) -> bool:
    text = (q.get("answer") or [""])[0] if isinstance(q.get("answer"), list) else str(q.get("answer") or "")
    if not str(text).strip():
        return False
    try:
        boxes = await page.evaluate(JS_TEXTBOXES)
        if not boxes:
            return False
        return bool(await page.evaluate(JS_FILL, [boxes[0]["i"], str(text)]))
    except Exception:
        return False


async def _answer_questions_once(page, questions, groups, pass_name: str):
    """对当前页的题目与已选状态比对后作答, 返回 (ok, fail, filled)。"""
    ok, fail, filled = 0, 0, 0
    for i, q in enumerate(questions):
        num = q.get("index") or i + 1
        try:
            if q.get("type") == "fill":
                if await _fill_blank(page, q):
                    filled += 1
                else:
                    fail += 1
                    logger.warn(f"  [{pass_name}] 题{num} 填空失败: 无可用输入框")
                continue
            answers = [a for a in (q.get("answer") or []) if isinstance(a, int)]
            if not answers:
                fail += 1
                logger.warn(f"  [{pass_name}] 题{num} 答案为空")
                continue
            group = match_group(q, groups)
            if group:
                sel = {o["idx"] for o in group.get("options", []) if o.get("sel")}
                need = [a for a in answers if a not in sel]
                wrong = sorted(sel - set(answers))
                if not need and not wrong:
                    ok += 1
                    logger.info(f"  [{pass_name}] 题{num} 与已选一致, 跳过点击")
                    continue
                plan = list(need)
                if wrong and group.get("type") == "checkbox":
                    plan += wrong  # 多选: 点掉选错的
                done = all(await _click(page, group["name"], a) for a in plan)
                if done:
                    ok += 1
                    detail = []
                    if need:
                        detail.append(f"补选{len(need)}项")
                    if wrong:
                        detail.append(f"取消错选{len(wrong)}项" if group.get("type") == "checkbox" else "更正单选")
                    logger.info(
                        f"  [{pass_name}] 题{num} 已作答: {q.get('question', '')[:24]}"
                        f" ({', '.join(detail) or '点击完成'}, 置信度:{q.get('confidence', '?')})"
                    )
                    await page.wait_for_timeout(150)
                    continue
                logger.warn(f"  [{pass_name}] 题{num} 原生控件点击失败, 尝试文本匹配...")
            # 文本匹配兜底 (自定义 UI)
            opts = q.get("options") or []
            statuses = []
            for a in answers:
                if a >= len(opts):
                    statuses.append("notfound")
                    break
                statuses.append(await _click_by_text(page, opts[a]))
                await page.wait_for_timeout(150)
            if statuses and all(s in ("clicked", "already") for s in statuses):
                ok += 1
                kept = statuses.count("already")
                logger.info(
                    f"  [{pass_name}] 题{num} 已作答(文本匹配): {q.get('question', '')[:24]}"
                    + (f" (保持已选{kept}项, 补点{statuses.count('clicked')}项)" if kept else "")
                )
                # 自定义 UI: 检查有没有选错的 (只告警不反选, 避免误伤)
                try:
                    sel_texts = await page.evaluate(JS_SELECTED_TEXTS)
                    want = {_norm(opts[a]) for a in answers if a < len(opts)}
                    wrong = [
                        t for t in sel_texts
                        if _norm(t) and not any(w and (w in _norm(t) or _norm(t) in w) for w in want)
                    ]
                    if wrong:
                        logger.warn(f"  [{pass_name}] 题{num} 检测到疑似错选: {wrong[:3]}")
                except Exception:
                    pass
            else:
                fail += 1
                logger.warn(f"  [{pass_name}] 题{num} 未能匹配选项控件")
        except TargetClosedError:
            raise
        except Exception as exc:
            fail += 1
            logger.debug(f"  [{pass_name}] 题{num} 作答异常: {exc}")
    return ok, fail, filled


async def _answer_all_pages(page, pass_name: str) -> dict:
    """逐页作答循环 (含确认/翻页/补救阶梯), 不负责提交。返回统计。"""
    total = {"ok": 0, "fail": 0, "fill": 0, "pages": 0}
    last_sig = None
    same_rounds = 0
    for _step in range(120):
        try:
            text = (await page.inner_text("body"))[:60000]
        except TargetClosedError:
            raise
        questions = await llm.solve_quiz_page(text)
        if not questions:
            logger.info(f"[{pass_name}] 当前页未识别出题目, 测验可能已到最后一页或已结束.")
            break
        # 页面签名: 翻页点击无效时重答+重试; 连续无效则 上一题→下一题→刷新 阶梯补救
        sig = "|".join(_norm(q.get("question", "")) for q in questions)[:300]
        if sig == last_sig:
            same_rounds += 1
            if same_rounds >= 5:
                logger.warn(f"[{pass_name}] 重答/上一题/刷新均无效, 停止本趟, 请手动处理.")
                break
            if same_rounds == 3:
                logger.warn(f"[{pass_name}] 连续 3 轮无变化, 尝试先点上一题再点下一题...")
                await _click_prev(page)
                await page.wait_for_timeout(2500)
                await _click_next(page)
                await page.wait_for_timeout(2500)
                last_sig = sig
                continue
            if same_rounds == 4:
                logger.warn(f"[{pass_name}] 仍无变化, 刷新页面重试...")
                try:
                    await page.reload(wait_until="domcontentloaded")
                    await page.wait_for_timeout(5000)
                except Exception as exc:
                    logger.warn(f"[{pass_name}] 刷新失败: {exc}")
                last_sig = sig
                continue
            logger.warn(f"[{pass_name}] 页面内容无变化({same_rounds}/5), 将重答本题并重试翻页...")
        else:
            same_rounds = 0
            total["pages"] += 1
        last_sig = sig

        groups = await page.evaluate(JS_COLLECT)
        ok, fail, filled = await _answer_questions_once(page, questions, groups, pass_name)
        total["ok"] += ok
        total["fail"] += fail
        total["fill"] += filled

        if ok == 0 and fail == 0 and filled == 0:
            logger.info(f"[{pass_name}] 本页没有可作答的题目, 停止翻页.")
            break

        # 答完本页: 部分考试 UI 需要先点"确认答案"才放行翻页
        await _click_confirm(page)

        # 翻到下一题 (按钮可能在作答后才渲染/启用, 多重试几次)
        advanced = False
        for _ in range(8):
            await page.wait_for_timeout(3000)
            if await _click_next(page):
                advanced = True
                break
        if advanced:
            logger.info(f"  [{pass_name}] 已点击下一题, 进入第 {total['pages'] + 1} 页...")
            await page.wait_for_timeout(2000)
            continue
        break  # 没有"下一题"了: 最后一页, 由调用方决定是否提交
    return total


def _summary(r: dict) -> str:
    return f"共 {r['pages']} 页, 选择 {r['ok']} 题, 填空 {r['fill']} 题, 失败 {r['fail']} 题"


async def auto_answer_new_page(page, config=None):
    """context.on('page') 回调: 捕获新开页面并自动作答测验。"""
    try:
        await asyncio.sleep(2)
        url = page.url or ""
        if not any(d in url for d in ("zhihuishu.com", "polymas.com")):
            return
        if not llm.enabled():
            logger.debug("检测到新开页面, 但未配置 DeepSeek API, 跳过自动答题.")
            return
        now = time.time()
        if url in ANSWERED and now - ANSWERED[url] < _ANSWER_COOLDOWN:
            return
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(4000)  # 等 SPA 渲染
        text = (await page.inner_text("body"))[:60000]
        if len(text.strip()) < 30:
            return

        ANSWERED[url] = now
        logger.info("捕获到测验页面, 进入逐题自动作答模式...")
        logger.event("测验页面捕获", 地址=url)

        r1 = await _answer_all_pages(page, "首答")
        logger.info(f"[首答] 完成: {_summary(r1)}")
        logger.event("测验页面首答", **r1)

        if not llm.conf().get("auto_submit", False):
            logger.info(
                "首答完成, 请核对后自行提交 (data/llm.json 中 auto_submit=true 可开启复核+自动提交)"
            )
            return

        # 交卷前: 刷新页面, 回到第一题, 整卷复核一遍
        logger.info("auto_submit 已开启: 刷新页面, 从第一题开始复核全部答案...")
        try:
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
        except Exception as exc:
            logger.warn(f"刷新失败, 直接尝试返回第一题: {exc}")
        for _ in range(80):
            if not await _click_prev(page):
                break
            await page.wait_for_timeout(800)
        r2 = await _answer_all_pages(page, "复核")
        logger.info(f"[复核] 完成: {_summary(r2)}")
        await _try_submit(page)
        logger.event("测验页面作答", 首答=_summary(r1), 复核=_summary(r2), 已提交=True)
    except TargetClosedError:
        pass
    except Exception as exc:
        logger.debug(f"测验页面自动作答跳过: {exc}")
