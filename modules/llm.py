# -*- coding: utf-8 -*-
"""接入 DeepSeek 给课中弹题作答。配置文件: data/llm.json"""
import asyncio
import difflib
import json
import os
import re

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from modules.logger import Logger

logger = Logger()

_LLM_CONF = None
_WARNED = False

DEFAULT_CONF = {
    "api_key": "",
    "api_base": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "auto_submit": False,
}


def _conf():
    global _LLM_CONF, _WARNED
    if _LLM_CONF is not None:
        return _LLM_CONF
    _LLM_CONF = dict(DEFAULT_CONF)
    try:
        # 与启动时 ensure_config_files 的生成位置保持一致(运行根目录/data)
        path = os.path.join(logger.runtime_root, "data", "llm.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8-sig") as f:
                _LLM_CONF.update({k: v for k, v in json.load(f).items() if v})
    except Exception as exc:
        logger.log_exception("读取 data/llm.json 失败, 大模型答题已禁用.", exc)
    if not _LLM_CONF.get("api_key") and not _WARNED:
        _WARNED = True
        logger.warn("未配置 DeepSeek API Key (data/llm.json), 弹题回退为默认行为.")
    return _LLM_CONF


def _norm(s: str) -> str:
    return re.sub(r"[\s\u3000]+", "", s or "")


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _chat_sync(api: str, api_key: str, model: str, prompt: str, json_mode: bool = False) -> str:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    resp = requests.post(
        api,
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _ask_llmSync(question_text: str, options: list) -> str:
    conf = _conf()
    api = conf["api_base"].rstrip("/") + "/chat/completions"
    opt_lines = "\n".join(f"{i}. {o}" for i, o in enumerate(options))
    prompt = (
        "你是网课弹题助手。下面是一道弹题的题目和选项，直接给出正确答案。\n"
        "只输出正确选项的完整原文，不要解释，不要加标点以外的任何内容。\n\n"
        f"题目：{question_text}\n\n选项：\n{opt_lines}"
    )
    return _chat_sync(api, conf["api_key"], conf["model"], prompt)


async def _ask_llm(question_text: str, options: list) -> str:
    return await asyncio.to_thread(_ask_llmSync, question_text, options)


def enabled() -> bool:
    """是否已配置可用的 DeepSeek API。"""
    return bool(_conf().get("api_key")) and requests is not None


def conf() -> dict:
    """返回当前 LLM 配置 (只读用途)。"""
    return _conf()


def to_indexes(answer, options: list) -> list:
    """把各种形态的答案统一成选项下标数组; 填空/无法解析返回空表以外的处理见调用方。"""
    if answer is None:
        return []
    if isinstance(answer, list) and answer and all(isinstance(x, int) for x in answer):
        return answer
    items = answer if isinstance(answer, list) else [answer]
    items = [str(x).strip() for x in items if str(x).strip()]
    idxs = []
    letters = "ABCDEFGH"
    for item in items:
        if re.fullmatch(r"[A-Ha-h]+", item) and len(item) <= max(len(options), 1):
            idxs.extend(letters.index(c.upper()) for c in item.upper())
            continue
        n_item = _norm(item)
        hit = -1
        for i, o in enumerate(options):
            n_o = _norm(o)
            if n_o and (n_o == n_item or n_o in n_item or n_item in n_o):
                hit = i
                break
        if hit < 0:
            m = re.match(r"^([A-Ha-h])[\.、．:：]", item)
            if m:
                hit = letters.index(m.group(1).upper())
        if hit < 0 and item.isdigit():
            n = int(item)
            hit = n - 1 if 1 <= n <= len(options) else n
        if 0 <= hit < len(options):
            idxs.append(hit)
    return idxs


async def solve_quiz_page(text: str) -> list:
    """整页抽取测验题目并作答, 返回归一化后的题目列表。"""
    if not enabled() or not text or len(text.strip()) < 30:
        return []
    c = _conf()
    prompt = f"""下面是一个在线测验页面的文本。提取其中所有测验题目（忽略导航栏、菜单、按钮、页脚等无关文本）并作答。

只输出一个 JSON 对象，结构严格如下：
{{"questions": [
  {{"index": 1,
    "question": "题干原文",
    "options": ["选项原文1", "选项原文2"],
    "type": "single|multiple|judge|fill",
    "answer": [0],
    "confidence": "high|medium|low",
    "reason": "一句话理由"}}]}}

规则:
1. answer 对选择/判断题是选项下标数组（从 0 开始），单选长度 1、多选长度 >=1；填空题 options 留空数组、answer 是 ["答案文本"]。
2. option 必须抄页面上的选项原文，不要带 "A."、"B." 之类字母前缀，不要改写。
3. 判断题（对/错、正确/错误）按两个选项处理。
4. 没把握也要给最可能的答案，confidence 填 low。
5. 页面文本可能乱序，靠题号与选项结构还原顺序。

页面文本:
<<<
{text}
>>>"""
    try:
        answer_text = await asyncio.to_thread(
            _chat_sync,
            c["api_base"].rstrip("/") + "/chat/completions",
            c["api_key"],
            c["model"],
            prompt,
            True,
        )
    except Exception as exc:
        logger.warn(f"大模型整页作答请求失败: {exc}", shift=True)
        return []
    try:
        raw = json.loads(answer_text).get("questions", [])
    except Exception as exc:
        logger.warn(f"大模型返回的 JSON 解析失败: {exc}", shift=True)
        return []

    questions = []
    for i, q in enumerate(raw):
        if not isinstance(q, dict):
            continue
        question = str(q.get("question") or q.get("题干") or q.get("题目") or "").strip()
        options = [str(o).strip() for o in (q.get("options") or q.get("选项") or []) if str(o).strip()]
        qtype = str(q.get("type") or q.get("题型") or "").lower()
        raw_answer = q.get("answer", q.get("答案"))
        if qtype not in ("single", "multiple", "judge", "fill"):
            qtype = "fill" if not options else ("multiple" if isinstance(raw_answer, list) and len(raw_answer) > 1 else "single")
        if qtype == "fill":
            ans_text = raw_answer[0] if isinstance(raw_answer, list) and raw_answer else raw_answer
            questions.append({
                "index": q.get("index") or i + 1,
                "question": question, "options": [], "type": "fill",
                "answer": [str(ans_text or "").strip()],
                "confidence": str(q.get("confidence") or q.get("置信度") or "medium").lower(),
                "reason": str(q.get("reason") or q.get("理由") or ""),
            })
        else:
            questions.append({
                "index": q.get("index") or i + 1,
                "question": question, "options": options, "type": qtype,
                "answer": to_indexes(raw_answer, options),
                "confidence": str(q.get("confidence") or q.get("置信度") or "medium").lower(),
                "reason": str(q.get("reason") or q.get("理由") or ""),
            })
    return questions


async def pick_option(dialog_text: str, option_texts: list) -> int:
    """用大模型从弹窗文本+选项里选出正确选项下标。失败/没把握返回 -1。"""
    conf = _conf()
    if not conf.get("api_key") or requests is None or not option_texts:
        return -1
    if not any(option_texts):
        return -1
    try:
        answer = await _ask_llm(dialog_text or "请从选项中选出正确答案。", option_texts)
    except Exception as exc:
        logger.warn(f"大模型答题请求失败: {exc}, 使用默认选择.", shift=True)
        return -1
    best, best_score = -1, 0.5
    for idx, t in enumerate(option_texts):
        if not t:
            continue
        score = _sim(answer, t)
        if score > best_score:
            best, best_score = idx, score
    if best < 0:
        logger.warn(f"大模型答案未能匹配选项(回答: {answer[:50]}), 使用默认选择.", shift=True)
    return best


async def answer_with_llm(page, ques, choices) -> bool:
    """对一道弹题用大模型作答。成功点击返回 True；未启用/失败返回 False。"""
    conf = _conf()
    if not conf.get("api_key") or requests is None or not choices:
        return False

    try:
        option_texts = [" ".join((await c.inner_text()).split()) for c in choices]
    except Exception:
        return False
    if not option_texts or all(not t for t in option_texts):
        return False

    # 题干：优先 .topic-title，否则取弹窗文本去掉选项行
    question_text = ""
    try:
        title = await page.query_selector(".topic-title")
        if title:
            question_text = await title.inner_text()
    except Exception:
        pass
    if not question_text:
        try:
            dialog = await page.query_selector(".el-dialog")
            if dialog:
                question_text = await dialog.inner_text()
        except Exception:
            pass
    question_text = " ".join((question_text or "").split())

    try:
        answer = await _ask_llm(question_text, option_texts)
    except Exception as exc:
        logger.warn(f"大模型答题请求失败: {exc}, 回退默认行为.", shift=True)
        return False

    best, best_score = None, 0.0
    for idx, t in enumerate(option_texts):
        score = _sim(answer, t)
        if score > best_score:
            best, best_score = idx, score
    if best is None or best_score < 0.5:
        logger.warn(f"大模型答案未能匹配选项(回答: {answer[:50]}), 回退默认行为.", shift=True)
        return False

    logger.event("课中答题", 方式="大模型", 选项=option_texts[best], 相似度=round(best_score, 2))
    try:
        await choices[best].click(timeout=2000)
        await page.wait_for_timeout(200)
        return True
    except Exception as exc:
        logger.warn(f"点击大模型选项失败: {exc}, 回退默认行为.", shift=True)
        return False
