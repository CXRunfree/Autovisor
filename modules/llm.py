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
}


def _conf():
    global _LLM_CONF, _WARNED
    if _LLM_CONF is not None:
        return _LLM_CONF
    _LLM_CONF = dict(DEFAULT_CONF)
    try:
        path = os.path.join("data", "llm.json")
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


def _ask_llmSync(question_text: str, options: list) -> str:
    conf = _conf()
    api = conf["api_base"].rstrip("/") + "/chat/completions"
    opt_lines = "\n".join(f"{i}. {o}" for i, o in enumerate(options))
    prompt = (
        "你是网课弹题助手。下面是一道弹题的题目和选项，直接给出正确答案。\n"
        "只输出正确选项的完整原文，不要解释，不要加标点以外的任何内容。\n\n"
        f"题目：{question_text}\n\n选项：\n{opt_lines}"
    )
    resp = requests.post(
        api,
        headers={"Authorization": f"Bearer {conf['api_key']}"},
        json={
            "model": conf["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


async def _ask_llm(question_text: str, options: list) -> str:
    return await asyncio.to_thread(_ask_llmSync, question_text, options)


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
