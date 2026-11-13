# encoding=utf-8
"""AI 智慧课「掌握度提升」自动化.

流程(全部走前端 UI, 不碰加密接口):
    learnPage(知识点的 去提升)
      -> masteryHistory(去提升)          # 每次都会新建一份练习卷
      -> studentexamcomh5 答题页          # 按答案缓存作答
      -> 提交
      -> /point 解析页 -> /examPreview    # 抓出本次题目的参考答案
      -> 回 learnPage 读最新掌握度, 未满则再来一轮

答案按题目正文缓存到 data/mastery_answers.json, 所以第 1 轮即使乱选,
第 2 轮就能全对.
"""
import asyncio
import difflib
import json
import re
import time
from pathlib import Path

from playwright.async_api import Locator, Page

QUESTION_ITEM = ".question-item"
MASTERY_PERCENT = ".simplified-mastery__percent"
MASTERY_ACTION = ".simplified-mastery__action"
HISTORY_IMPROVE = ".improve-btn"
EXAM_QUESTION = ".questionContent"
EXAM_NEXT = ".next-topic"
EXAM_SUBMIT = ".reviewDone"
MAX_MASTERY = 100


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").split())


def cache_key(value: str | None) -> str:
    """答案缓存的键: 去掉所有空白和首尾括号, 避免判断题/空格差异导致查不到."""
    text = re.sub(r"[\s\u3000]+", "", value or "")
    text = text.replace("（", "(").replace("）", ")")
    while text.endswith("()"):
        text = text[:-2]
    return text


def loose_key(value: str | None) -> str:
    """更宽松的键: 只保留中英文和数字, 用于模糊匹配(题干里的 ____ 会被去掉)."""
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value or "")
    return text.lower()


def parse_answer_text(value: str | None) -> dict:
    """把「参考答案：B」/「参考答案：错」/「参考答案：A、B、C」解析成答案."""
    raw = " ".join((value or "").split())
    raw = raw.replace("参考答案", "").replace("：", " ").replace(":", " ").strip()
    cleaned = re.sub(r"[\s、，,;；/]+", "", raw)
    if cleaned and re.fullmatch(r"[A-Za-z]+", cleaned):
        return {"letters": [letter.upper() for letter in cleaned]}
    return {"text": raw} if raw else {}


def parse_percent(value: str | None) -> int | None:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        return None
    return min(int(digits), 100)


def is_ai_leaning_url(url: str) -> bool:
    return "ai-smart-course-student-pro.zhihuishu.com" in (url or "")


def parse_learn_url(url: str) -> dict:
    """/learnPage/<courseId>/<nodeUid>/<classId> -> 三段参数."""
    match = re.search(r"/learnPage/(\d+)/(\d+)/(\d+)", url or "")
    if not match:
        return {}
    return {
        "courseId": match.group(1),
        "nodeUid": match.group(2),
        "classId": match.group(3),
    }


def parse_exam_url(url: str) -> dict:
    match = re.search(
        r"/studentReviewTestOrExam/(\d+)/\d+/\d+/(\d+)/([^/]+)/", url or ""
    )
    if not match:
        return {}
    params = dict(re.findall(r"[?&]([^=&]+)=([^&]*)", url or ""))
    return {
        "examTestId": match.group(1),
        "courseId": match.group(2),
        "nodeName": match.group(3),
        "paperId": params.get("paperId") or params.get("examPaperId") or "",
    }


class AnswerCache:
    def __init__(self, path: Path):
        self.path = path
        self.items: dict[str, dict] = {}
        if path.is_file():
            try:
                self.items = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.items = {}
        self._loose: dict[str, dict] = {}
        for key, record in self.items.items():
            self._loose.setdefault(loose_key(key), record)

    def get(self, question: str) -> dict | None:
        """返回 {'letters': [...]} / {'text': ...} / {'values': [...]}."""
        record = self.items.get(cache_key(question))
        if record is None:
            record = self._loose.get(loose_key(question))
        if record is None:
            # 题干里的 ____ 有时候会被渲染成输入框, 导致正文对不上, 用相似度兜底
            target = loose_key(question)
            if len(target) >= 12:
                best, best_ratio = None, 0.0
                for key, candidate in self._loose.items():
                    if abs(len(key) - len(target)) > max(20, int(len(target) * 0.3)):
                        continue
                    ratio = difflib.SequenceMatcher(None, target, key).ratio()
                    if ratio > best_ratio:
                        best, best_ratio = candidate, ratio
                if best is not None and best_ratio >= 0.85:
                    record = best
        if not record:
            return None
        if record.get("letters"):
            return {"letters": record["letters"]}
        if record.get("values"):
            return {"values": record["values"]}
        text = record.get("text") or ""
        if text:
            # 旧数据里多选答案被存成 "A、B、C", 这里纠正成字母;
            # 只有纯大写 A-H 才当字母, 避免 "circular/linear" 这种文字答案被误判
            cleaned = re.sub(r"[\s、，,;；/]+", "", text)
            if re.fullmatch(r"[A-H]{1,8}", cleaned):
                return {"letters": list(cleaned)}
            return {"text": text}
        return None

    def put(self, question: str, answer: dict, options: list[str] | None = None):
        if not answer or not (
            answer.get("letters") or answer.get("text") or answer.get("values")
        ):
            return
        key = cache_key(question)
        record = {"options": options or []}
        record.update(answer)
        if self.items.get(key) == record:
            return
        self.items[key] = record
        self._loose.setdefault(loose_key(key), record)
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8"
        )


async def read_mastery(page: Page) -> int | None:
    try:
        text = await page.locator(MASTERY_PERCENT).first.text_content(timeout=8000)
    except Exception:
        return None
    return parse_percent(text)


async def read_exam_question(page: Page) -> dict | None:
    return await page.evaluate(
        """() => {
            const q = document.querySelector('.questionContent');
            if (!q) return null;
            const numberText = q.querySelector('.letterSortNum')?.textContent || '';
            const number = (numberText.match(/(\\d+)/) || [])[1] || '';
            const radio = q.querySelector('ul.radio-view');
            const checkbox = q.querySelector('.checkbox-view');
            let selector = '';
            let options = [];
            if (radio) {
                selector = 'ul.radio-view li';
                options = [...radio.querySelectorAll('li')].map((li) => ({
                    letter: (li.querySelector('.letterSort')?.textContent || '').replace(/[^A-Za-z]/g, ''),
                    text: (li.querySelector('.stem')?.innerText || '').trim(),
                }));
            } else if (checkbox) {
                selector = '.checkbox-view label.el-checkbox';
                options = [...checkbox.querySelectorAll('label.el-checkbox')].map((li) => ({
                    letter: (li.querySelector('.letterSort')?.textContent || '').replace(/[^A-Za-z]/g, ''),
                    text: (li.querySelector('pre')?.innerText || '').trim(),
                    checked: !!(li.querySelector('input') && li.querySelector('input').checked),
                }));
            } else {
                // 兜底: 其它题型(判断题/选项结构变体) 统一按 label 抓
                const labels = [...q.querySelectorAll('label.el-radio, label.el-checkbox')];
                if (labels.length) {
                    selector = '.questionContent label.el-radio, .questionContent label.el-checkbox';
                    options = labels.map((el) => ({
                        letter: (el.querySelector('.letterSort')?.textContent || '').replace(/[^A-Za-z]/g, ''),
                        text: (el.querySelector('pre')?.innerText || el.innerText || '').trim(),
                    }));
                }
            }
            // 填空客观题: 有 input 输入框, 没有选项
            const blankInputs = [...q.querySelectorAll('.input-ques input, ul.fillAnswer input')];
            let kind = 'choice';
            if (blankInputs.length && !options.length) {
                kind = 'blank';
                selector = '.input-ques .el-input__inner, ul.fillAnswer .el-input__inner';
            }
            return {
                number,
                type: numberText.replace(/[\\d.\\s]/g, ''),
                text: (q.querySelector('.centent-pre')?.innerText || '').trim(),
                selector,
                options,
                kind,
                blankCount: blankInputs.length,
            };
        }"""
    )


def split_blank_answer(text: str, count: int) -> list[str]:
    """把「遗传；变异；生产实践」这类参考答案按填空个数拆开."""
    raw = re.sub(r"参考答案[:：]?", "", text or "").strip()
    raw = re.sub(r"^\d+[.、]\s*", "", raw)
    if not raw:
        return [""] * count
    if count <= 1:
        return [raw]
    parts = [part.strip() for part in re.split(r"[;；、|,，/／]+", raw) if part.strip()]
    if len(parts) == count:
        return parts
    # 空白分隔(「遗传 变异 生产实践」)也是常见形式
    spaced = [part for part in re.split(r"\s+", raw.strip()) if part]
    if len(spaced) == count:
        return spaced
    # 也支持「1.遗传 2.变异 3.生产实践」这种编号写法
    numbered = re.findall(r"\d+[.、]\s*([^0-9；;]+)", raw)
    if len(numbered) == count:
        return [part.strip() for part in numbered]
    return [raw] + [""] * (count - 1)


async def fill_blanks(page: Page, question: dict, answer: dict | None) -> list[str]:
    """把答案填进填空框, 返回填写的内容."""
    count = question.get("blankCount") or 1
    values: list[str] = []
    if answer:
        if answer.get("values"):
            values = list(answer["values"])
        elif answer.get("text"):
            values = split_blank_answer(answer["text"], count)
    if len(values) < count:
        values = [value or "未知" for value in values] + ["未知"] * (count - len(values))
    # 没有缓存答案时也要填点东西, 否则页面认为未作答, 交卷会被拦住
    values = [(value or "未知") for value in values]
    inputs = page.locator(question.get("selector") or ".input-ques .el-input__inner")
    filled = []
    for index, value in enumerate(values):
        if index >= count:
            break
        target = inputs.nth(index)
        try:
            await target.click(timeout=6000)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Delete")
            await page.keyboard.type(value, delay=25)
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(400)
            filled.append(value)
        except Exception:
            filled.append("")
    # 最后一个空往往不会触发保存, 再补一次输入并切走焦点(单个空也要补)
    if len(values) >= count and count >= 1:
        try:
            last = inputs.nth(count - 1)
            await last.click(timeout=4000)
            await page.keyboard.press("Control+A")
            await page.keyboard.type(values[count - 1], delay=20)
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(400)
        except Exception:
            pass
    # 触发 blur, 让页面把每个空的答案写进答题模型
    try:
        await inputs.first.click(timeout=3000)
    except Exception:
        pass
    try:
        await page.locator(".questionName").first.click(timeout=3000)
    except Exception:
        pass
    try:
        await page.evaluate(
            """() => [...document.querySelectorAll(
                '.questionContent .input-ques input, .questionContent ul.fillAnswer input'
            )].forEach((el) => {
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: false }));
            })"""
        )
    except Exception:
        pass
    await page.wait_for_timeout(1200)
    try:
        actual = await page.evaluate(
            """() => [...document.querySelectorAll('.questionContent .input-ques input, '
                + '.questionContent ul.fillAnswer input')]
                .map((el) => el.value)"""
        )
    except Exception:
        actual = []
    return [value for value in filled if value], actual


async def pick_options(page: Page, answer: dict | None, question: dict) -> list[str]:
    """按缓存答案点击选项; 支持单选(radio)/多选(checkbox)/判断题(文字答案)."""
    options = question.get("options") or []
    selector = question.get("selector") or "ul.radio-view li"
    option_count = len(options)
    indexes: list[int] = []
    answer = answer or {}
    for letter in answer.get("letters") or []:
        index = ord(letter.upper()) - ord("A")
        if 0 <= index < option_count:
            indexes.append(index)
    if not indexes and answer.get("text"):
        wanted = re.sub(r"[\s\u3000]+", "", answer["text"])
        for index, option in enumerate(options):
            text = re.sub(r"[\s\u3000]+", "", option.get("text") or "")
            if text and (text == wanted or wanted in text or text in wanted):
                indexes.append(index)
                break
    if not indexes:
        indexes = [0]

    picked = []
    for index in indexes:
        letter = options[index].get("letter") if index < option_count else ""
        if options[index].get("checked"):
            # 已经勾上的多选题选项不要再点, 否则会被点掉
            picked.append((letter or chr(ord("A") + index)).upper())
            continue
        locator = page.locator(selector).nth(index)
        clicked = False
        for attempt in range(3):
            try:
                await locator.click(timeout=6000)
                clicked = True
                break
            except Exception:
                try:
                    await locator.click(timeout=4000, force=True)
                    clicked = True
                    break
                except Exception:
                    await page.wait_for_timeout(800)
        if not clicked:
            raise RuntimeError(f"选项点不到(选择器 {selector} 第 {index} 个)")
        await page.wait_for_timeout(600)
        letter = options[index].get("letter") if index < option_count else ""
        picked.append((letter or chr(ord("A") + index)).upper())
    return picked


async def go_to_first_question(page: Page) -> None:
    """答题页可能停在上次的位置, 先退回第 1 题, 否则只会答到最后一题."""
    for _ in range(40):
        previous = page.locator(".pre-topic")
        if not await previous.count():
            return
        classes = await previous.first.get_attribute("class") or ""
        if "nopre" in classes:
            return
        try:
            await previous.first.click(timeout=5000)
        except Exception:
            return
        await page.wait_for_timeout(700)


async def unanswered_questions(page: Page) -> list[str]:
    """答题卡上还没作答的题号(只看可见的题目节点)."""
    return await page.evaluate(
        """() => [...document.querySelectorAll(
            '.sheet-box .custom-tree-answer-normal.no-answer'
        )].filter((el) => el.querySelector('.font-sec-style-node'))
          .filter((el) => el.offsetParent !== null)
          .map((el) => (el.innerText || '').trim())"""
    )


async def sheet_answered_numbers(page: Page) -> set[str]:
    """答题卡上已作答的题号集合(只看可见的题目节点)."""
    answered = await page.evaluate(
        """() => [...document.querySelectorAll('.sheet-box .custom-tree-answer-normal')]
            .filter((el) => el.querySelector('.font-sec-style-node'))
            .filter((el) => el.offsetParent !== null)
            .filter((el) => !el.classList.contains('no-answer'))
            .map((el) => (el.innerText || '').trim())"""
    )
    return set(answered or [])


async def answer_missing(page: Page, cache: "AnswerCache", logger) -> bool:
    """把答题卡里漏做的题补答掉, 避免「未做完就交卷」."""
    stuck: dict[str, int] = {}
    for _ in range(4):
        missing = await unanswered_questions(page)
        if missing:
            answered = await sheet_answered_numbers(page)
            missing = [number for number in missing if number not in answered]
        if not missing:
            return True
        key = ",".join(missing)
        stuck[key] = stuck.get(key, 0) + 1
        if stuck[key] > 1:
            # 再点一次会把多选题已勾的选项「点掉」, 反而更糟
            logger.warn(f"题 {missing} 补答一次仍未被记录, 不再重复点击.")
            return False
        logger.info(f"还有 {len(missing)} 题未作答 {missing[:6]}, 去补答")
        clicked = await page.evaluate(
            """() => {
                const node = [...document.querySelectorAll(
                    '.sheet-box .custom-tree-answer-normal.no-answer'
                )].find((el) => el.querySelector('.font-sec-style-node'));
                if (!node) return false;
                const row = node.closest('.el-tree-node__content') || node;
                row.click();
                return true;
            }"""
        )
        if not clicked:
            return False
        await page.wait_for_timeout(1500)
        if not await answer_current(page, cache, logger):
            return False
        await page.wait_for_timeout(500)
    return False


async def answer_current(page: Page, cache: "AnswerCache", logger) -> dict | None:
    """作答当前显示的这一题."""
    question = await read_exam_question(page)
    if not question or not question["text"]:
        return None
    # 答题卡显示这题已经作答, 就不要再点一遍(多选会被点掉)
    answered_numbers = await sheet_answered_numbers(page)
    if question["number"] and question["number"] in answered_numbers:
        logger.info(f"第{question['number']}题已作答, 跳过重复点击.")
        return {
            "text": question["text"],
            "picked": [],
            "cached": True,
            "skipped": True,
        }
    known = cache.get(question["text"])
    picked: list = []
    if question.get("kind") == "blank":
        try:
            picked, actual = await fill_blanks(page, question, known)
            logger.info(f"填空题 缓存={known} 应填={picked} 实填={actual}")
        except Exception as error:
            logger.warn(f"第{question['number']}题填空失败: {type(error).__name__}")
    elif not question.get("options"):
        logger.warn(f"第{question['number']}题没有可点选项, 跳过.")
    else:
        try:
            picked = await pick_options(page, known, question)
        except Exception as error:
            logger.warn(f"第{question['number']}题作答失败: {type(error).__name__}")
    logger.info(
        f"第{question['number']}题 {'命中缓存' if known else '未命中缓存'}: {picked}"
    )
    return {"text": question["text"], "picked": picked, "cached": bool(known)}


async def answer_exam(page: Page, cache: AnswerCache, logger) -> list[dict]:
    await page.wait_for_selector(EXAM_QUESTION, timeout=30_000)
    await page.wait_for_timeout(1000)
    await go_to_first_question(page)
    await page.wait_for_timeout(600)
    answered = []
    last_number = None
    for _ in range(50):
        question = await read_exam_question(page)
        if not question or not question["text"]:
            break
        if question["number"] and question["number"] == last_number:
            break
        last_number = question["number"]
        record = await answer_current(page, cache, logger)
        if record:
            answered.append(record)
        next_button = page.locator(EXAM_NEXT)
        classes = await next_button.get_attribute("class") or ""
        if "nopre" in classes:
            break
        await next_button.click()
        await page.wait_for_timeout(1200)
    # 顺序作答可能漏题(题型异常/切题失败), 交卷前按答题卡补齐
    await answer_missing(page, cache, logger)
    return answered


async def _visible_dialog_text(page: Page) -> str:
    try:
        return await page.evaluate(
            """() => {
                const dlg = [...document.querySelectorAll(
                    '.el-dialog__wrapper, .el-message-box__wrapper'
                )].find((el) => el.offsetParent !== null);
                return dlg ? (dlg.innerText || '') : '';
            }"""
        )
    except Exception:
        return ""


async def _click_text(page: Page, text: str, timeout: int = 3000) -> bool:
    button = page.get_by_text(text, exact=True)
    if await button.count():
        try:
            await button.last.click(timeout=timeout)
            return True
        except Exception:
            return False
    return False


async def submit_exam(page: Page, logger, cache=None) -> bool:
    """交卷. 有未作答的题先补答, 弹「未做完」提示时取消而不是硬交."""
    for attempt in range(1, 4):
        if cache is not None:
            await answer_missing(page, cache, logger)
        # 直接走 JS 点击, 避免被浮层挡住或被判为不可点击
        clicked = await page.evaluate(
            """() => {
                const el = document.querySelector('.reviewDone') ||
                           document.querySelector('.right-H .reviewDone');
                if (!el) return false;
                el.click();
                return true;
            }"""
        )
        if not clicked:
            await page.locator(EXAM_SUBMIT).first.click()
        await page.wait_for_timeout(2000)

        dialog = await _visible_dialog_text(page)
        if any(word in dialog for word in ("未做完", "还有题目", "没有完成", "未完成")):
            if attempt < 3:
                logger.warn("检测到「未做完题目」提示, 先取消再补答")
                await _click_text(page, "取消")
                await page.wait_for_timeout(800)
                if cache is not None:
                    await answer_missing(page, cache, logger)
                continue
            # 补不上就先强制交卷, 别把整轮练习浪费掉
            logger.warn("仍有题目无法作答, 强制提交本卷")
            for text in ("继续提交", "提交试卷", "确定", "确认"):
                if await _click_text(page, text):
                    break
            await page.wait_for_timeout(1500)

        confirmed = False
        for selector in (
            ".el-dialog__wrapper:visible .comfirm",
            ".el-dialog__wrapper:visible .cancle-ai",
            ".el-message-box__btns .el-button--primary",
        ):
            locator = page.locator(selector)
            if await locator.count():
                try:
                    await locator.last.click(timeout=3000)
                    logger.info("已确认提交弹窗")
                    confirmed = True
                    break
                except Exception:
                    continue
        if not confirmed and dialog:
            for text in ("确定", "确认", "交卷", "提交试卷"):
                if await _click_text(page, text):
                    logger.info(f"已点确认按钮: {text}")
                    break

        for _ in range(20):
            await page.wait_for_timeout(1000)
            if "/point/" in page.url or "/examPreview/" in page.url:
                return True
        if "/point/" in page.url:
            return True
    return "/point/" in page.url


async def scrape_preview_answers(page: Page, logger) -> dict[str, dict]:
    """从 /examPreview 解析页抓取 题目 -> 正确答案(字母或文字)."""
    await page.wait_for_selector(QUESTION_ITEM, timeout=30_000)
    await page.wait_for_timeout(1000)
    raw = await page.evaluate(
        """() => [...document.querySelectorAll('.question-item')].map((item) => {
            const text = (item.querySelector('.option-name')?.innerText || '').trim();
            const labels = [...item.querySelectorAll('.el-radio__label, .el-checkbox__label')];
            const options = labels.map((el) => ({
                letter: (el.querySelector('span')?.textContent || '').replace(/[^A-Za-z]/g, ''),
                text: (el.querySelector('.inner-box')?.innerText || el.innerText || '').trim(),
            }));
            const answerText = (item.querySelector('.answer-title')?.innerText || '').trim();
            const analysis = (item.querySelector('.html-v-analysis')?.innerText || '').trim();
            const inner = item.innerText || '';
            const resultText = inner.includes('回答正确') ? '正确'
                : (inner.includes('回答错误') ? '错误' : '');
            return { text, options, answerText, analysis, resultText };
        })"""
    )
    answers: dict[str, dict] = {}
    for entry in raw:
        text = normalize_text(entry.get("text"))
        answer_text = entry.get("answerText", "")
        if entry.get("options"):
            answer = parse_answer_text(answer_text)
        else:
            # 填空/简答: 参考答案是纯文字, 按原文保存
            cleaned = re.sub(r"^\s*参考答案\s*[:：]?\s*", "", answer_text).strip()
            answer = {"text": cleaned} if cleaned else {}
        if text and answer:
            answers[text] = answer
            shown = "".join(answer.get("letters") or []) or answer.get("text", "")
            wrong = "  <== 本次答错" if entry.get("resultText") == "错误" else ""
            logger.info(f"解析: {text[:24]}... -> {shown}{wrong}")
    return answers


async def open_practice(page: Page, learn_url: str, logger) -> dict:
    """learnPage -> 去提升 -> masteryHistory -> 去提升 -> 答题页. 返回试卷信息."""
    await page.goto(learn_url, wait_until="domcontentloaded")
    await page.wait_for_selector(MASTERY_ACTION, timeout=30_000)
    # 掌握度卡片先渲染 0%, 数据回填后才变成真实值, 等接口静默再读
    try:
        await page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        pass
    await page.wait_for_timeout(1500)
    mastery_before = await read_mastery(page)
    logger.info(f"当前掌握度: {mastery_before}%")

    # 卡片刚出现时 Vue 事件可能还没挂上, 点击后要确认真的跳转了
    for attempt in range(4):
        await page.locator(MASTERY_ACTION).first.click()
        try:
            await page.wait_for_url("**/masteryHistory/**", timeout=8000)
            break
        except Exception:
            logger.debug(f"去提升点击未跳转, 重试第 {attempt + 1} 次")
            await page.wait_for_timeout(1000)
    await page.wait_for_selector(HISTORY_IMPROVE, state="attached", timeout=30_000)
    await page.wait_for_timeout(1200)
    await page.locator(HISTORY_IMPROVE).first.click()
    for _ in range(30):
        await page.wait_for_timeout(1000)
        if "studentexamcomh5" in page.url:
            break
    info = parse_exam_url(page.url)
    info["mastery_before"] = mastery_before
    logger.event("掌握度练习", 试卷=info.get("paperId"), 掌握度=mastery_before)
    return info


def build_preview_url(learn: dict, exam: dict) -> str:
    return (
        "https://ai-smart-course-student-pro.zhihuishu.com/examPreview/"
        f"{learn['courseId']}/{exam['paperId']}/{exam['examTestId']}"
        f"/{learn['nodeUid']}/{learn['classId']}"
        f"?from=history&nodeName={exam['nodeName']}"
    )


def answers_from_paper_payload(payload: dict | None) -> dict[str, dict]:
    """从 questions-paper 的 aiExamQuestionInfo 里解析出题目 -> 正确答案.

    这份数据是交卷后由 /point 页拉取的, 比再跳一次 /examPreview 快得多.
    """
    answers: dict[str, dict] = {}
    data = (payload or {}).get("data") or {}
    for question in data.get("aiExamQuestionInfo") or []:
        text = normalize_text(question.get("content"))
        options = question.get("optionDtos") or []
        correct = [option for option in options if option.get("isCorrect") == 1]
        if not text:
            continue
        if question.get("questionType") == 3 or "填空" in (question.get("questionTypeName") or ""):
            # 填空客观题: 每个空对应一个 optionDto, result 里是逗号分隔的标准答案
            values = []
            raw_result = question.get("result")
            if isinstance(raw_result, str) and raw_result.strip():
                values = [part.strip() for part in re.split(r"[,，]", raw_result) if part.strip()]
            if not values and correct:
                ordered = sorted(correct, key=lambda item: item.get("sort") or 0)
                values = [normalize_text(item.get("content")) for item in ordered]
            if values:
                answers[text] = {"values": values}
            continue
        if not correct:
            continue
        letters = []
        for option in correct:
            sort = option.get("sort") or 0
            if 1 <= int(sort) <= 26:
                letters.append(chr(ord("A") + int(sort) - 1))
        record = {"letters": letters}
        if not letters:
            record = {"text": normalize_text(correct[0].get("content"))}
        answers[text] = record
    return answers


async def run_mastery(
    page: Page,
    learn_url: str,
    cache: AnswerCache,
    logger,
    max_attempts: int = 4,
    target: int = MAX_MASTERY,
) -> dict:
    learn = parse_learn_url(learn_url)
    if not learn:
        raise RuntimeError(f"无法解析学习页地址: {learn_url}")

    captured: list[dict] = []

    async def on_response(response):
        url = response.url or ""
        if "mastery-statistics" not in url and "questions-paper" not in url:
            return
        try:
            text = await response.text()
        except Exception:
            return
        limit = 200_000 if "questions-paper" in url else 4_000
        captured.append({"url": url.split("zhihuishu.com")[-1], "body": text[:limit]})

    page.on("response", lambda r: asyncio.ensure_future(on_response(r)))

    history: list[dict] = []
    mastery = None
    rounds = max_attempts
    for attempt in range(1, rounds + 1):
        logger.info(f"—— 掌握度提升 第 {attempt}/{rounds} 轮 ——")
        captured.clear()
        exam = await open_practice(page, learn_url, logger)
        if not exam.get("paperId"):
            logger.error("没有进入答题页, 停止.")
            break
        # 题库大小决定要刷几轮: 每轮只能抽到 6 题
        if attempt == 1:
            bank = 0
            for item in captured:
                matched = re.search(r'"questionNum"\s*:\s*(\d+)', item["body"])
                if matched:
                    bank = max(bank, int(matched.group(1)))
            if bank:
                rounds = min(max(max_attempts, bank // 6 + 4), 12)
                logger.info(f"题库 {bank} 题, 本轮计划刷 {rounds} 轮")

        answered = await answer_exam(page, cache, logger)
        logger.event(
            "答题完成",
            题数=len(answered),
            命中缓存=sum(1 for item in answered if item["cached"]),
        )
        if not await submit_exam(page, logger, cache):
            logger.warn("提交后没有跳到解析页, 本轮结束.")
        else:
            # /point 页的 questions-paper 响应要等 1~3 秒才回来, 先等它到齐
            for _ in range(12):
                await page.wait_for_timeout(1000)
                if any("aiExamQuestionInfo" in item["body"] for item in captured):
                    break
            answers: dict[str, dict] = {}
            for item in captured:
                if "questions-paper" not in item["url"]:
                    continue
                try:
                    payload = json.loads(item["body"])
                except json.JSONDecodeError:
                    logger.debug(
                        f"payload 解析失败 len={len(item['body'])} head={item['body'][:60]!r}"
                    )
                    continue
                parsed = answers_from_paper_payload(payload)
                logger.debug(f"payload {item['url'][-40:]} -> {len(parsed)} 题")
                if parsed:
                    answers.update(parsed)
            logger.event("答案解析", 题目=len(answers), 来源="接口")
            if not answers:
                preview_url = build_preview_url(learn, exam)
                await page.goto(preview_url, wait_until="domcontentloaded")
                try:
                    answers = await scrape_preview_answers(page, logger)
                except Exception as error:
                    logger.warn(f"解析页抓取失败: {type(error).__name__}")
                    answers = {}
                logger.event("答案解析", 题目=len(answers), 来源="解析页")
            for text, answer in answers.items():
                cache.put(text, answer)
            logger.event("答案入库", 本轮=len(answers), 累计=len(cache.items))

        await page.goto(learn_url, wait_until="domcontentloaded")
        await page.wait_for_selector(MASTERY_ACTION, timeout=30_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)
        mastery = await read_mastery(page)
        history.append(
            {
                "attempt": attempt,
                "mastery": mastery,
                "cached": sum(1 for item in answered if item["cached"]),
                "questions": len(answered),
            }
        )
        logger.event("掌握度结果", 轮次=attempt, 掌握度=mastery)
        for item in captured:
            if "get-knowledge-mastery-stat" in item["url"]:
                logger.event("掌握度统计", 轮次=attempt, 原始=item["body"])
            if "/exam/questions-paper" in item["url"]:
                logger.event("试卷信息", 轮次=attempt, 原始=item["body"])
        if mastery is not None and mastery >= target:
            logger.info(f"掌握度已达标: {mastery}%")
            break
        # 有的知识点即使全对也要刷好几轮掌握度才涨, 所以连续 3 轮没变化才放弃
        if len(history) >= 4:
            recent = [item["mastery"] for item in history[-3:]]
            all_cached = all(
                item["cached"] >= item["questions"] and item["questions"]
                for item in history[-3:]
            )
            if len(set(recent)) == 1 and all_cached:
                logger.warn("连续 3 轮全对但掌握度不再变化, 停止该知识点.")
                break
        time.sleep(0.5)

    return {"mastery": mastery, "attempts": history}


# ---------------------------------------------------------------- 知识点枚举

THEME_API = "knowledge-study/list-knowledge-theme"
DIC_API = "knowledge-study/get-course-knowledge-dic"


def parse_course_url(url: str) -> tuple[str, str]:
    """从 singleCourse / learnPage 地址里取 (courseId, classId)."""
    match = re.search(r"/singleCourse/knowledgeStudy/(\d+)/(\d+)", url or "")
    if not match:
        match = re.search(r"/learnPage/(\d+)/\d+/(\d+)", url or "")
    if not match:
        raise RuntimeError(f"无法从地址解析 courseId/classId: {url}")
    return match.group(1), match.group(2)


def _nodes_from_theme_payload(payload: dict) -> list[dict]:
    data = (payload or {}).get("data") or {}
    nodes = []
    for theme in data.get("courseThemeList") or data.get("themeList") or []:
        module = (theme.get("themeName") or "").strip()
        for sub in theme.get("subThemeList") or []:
            unit = (sub.get("themeName") or "").strip()
            for knowledge in sub.get("knowledgeList") or []:
                uid = str(knowledge.get("knowledgeId") or "").strip()
                if not uid:
                    continue
                nodes.append(
                    {
                        "nodeUid": uid,
                        "name": (knowledge.get("knowledgeName") or "").strip(),
                        "module": module,
                        "unit": unit,
                        "freeExam": knowledge.get("freeExam") or 0,
                        "mastery": knowledge.get("masteryPercentage"),
                        "studyProgress": knowledge.get("studyProgress"),
                        "finished": knowledge.get("finishedResourceCount") or 0,
                        "total": knowledge.get("resourceCount") or 0,
                    }
                )
    return nodes


async def enumerate_nodes(page: Page, course_url: str, timeout_ms: int = 40_000) -> dict:
    """打开课程页(入口页或学习页), 从接口响应里枚举全部知识点, 不需要抓包."""
    collected: dict[str, str] = {}

    async def on_response(response):
        url = response.url or ""
        if THEME_API not in url and DIC_API not in url:
            return
        try:
            text = await response.text()
        except Exception:
            return
        collected[url] = text

    handler = lambda response: asyncio.ensure_future(on_response(response))
    page.on("response", handler)
    try:
        await page.goto(course_url, wait_until="domcontentloaded")
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline and not collected:
            await page.wait_for_timeout(500)
        if not collected:
            # 兜底: 从大纲点进第一个知识点, 触发 learnPage 的知识点字典接口
            item = page.locator(".conlist-content-box .item-content").first
            if await item.count():
                await item.click()
                await page.wait_for_timeout(1000)
                while time.monotonic() < deadline and not collected:
                    await page.wait_for_timeout(500)
    finally:
        try:
            page.remove_listener("response", handler)
        except Exception:
            pass

    nodes: list[dict] = []
    for text in collected.values():
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        parsed = _nodes_from_theme_payload(payload)
        if len(parsed) > len(nodes):
            nodes = parsed
    if not nodes:
        raise RuntimeError("没能从课程页枚举出知识点")

    course_id, class_id = parse_course_url(course_url)
    seen = set()
    unique = []
    for node in nodes:
        if node["nodeUid"] in seen:
            continue
        seen.add(node["nodeUid"])
        unique.append(node)
    return {"courseId": course_id, "classId": class_id, "nodes": unique}


# ---------------------------------------------------------------- 整门课遍历


def load_nodes(path: Path) -> dict:
    """读取 tools/export_nodes.py 导出的知识点清单."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {"courseId": "", "classId": "", "nodes": payload}
    return payload


def build_learn_url(course_id: str, node_uid: str, class_id: str) -> str:
    return (
        "https://ai-smart-course-student-pro.zhihuishu.com/learnPage/"
        f"{course_id}/{node_uid}/{class_id}?catalogActiveTab=personal"
    )


async def read_node_mastery(page: Page, learn_url: str) -> int | None:
    """只读掌握度, 不点任何按钮."""
    await page.goto(learn_url, wait_until="domcontentloaded")
    await page.wait_for_selector(MASTERY_ACTION, timeout=30_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    await page.wait_for_timeout(1200)
    return await read_mastery(page)


async def run_course_mastery(
    page: Page,
    nodes: list[dict],
    course_id: str,
    class_id: str,
    cache: AnswerCache,
    logger,
    target: int = 97,
    max_attempts: int = 3,
    limit: int = 0,
    passes: int = 3,
) -> dict:
    """遍历课程里所有知识点把掌握度刷到 target.

    一轮跑完仍有没达标的, 会自动再跑一轮(只跑没达标的, 并加轮数),
    最多 passes 轮; 某一轮毫无进展就提前停.
    """
    summary = {
        "done": [],
        "skipped": [],
        "failed": [],
        "target": target,
        "passes": [],
    }
    missing_uid = [node for node in nodes if not node.get("nodeUid")]
    if missing_uid:
        logger.warn(f"跳过 {len(missing_uid)} 个没有 nodeUid 的知识点")
    nodes = [node for node in nodes if node.get("nodeUid")]
    if limit:
        nodes = nodes[:limit]
    logger.info(f"共 {len(nodes)} 个知识点待处理, 目标掌握度 {target}%")

    pending = [node for node in nodes if not node.get("freeExam")]
    records: dict[str, dict] = {}
    skipped_free = [node for node in nodes if node.get("freeExam")]
    for node in skipped_free:
        summary["skipped"].append(
            {"name": node.get("name") or node["nodeUid"], "reason": "免考"}
        )
    if skipped_free:
        logger.info(f"免考知识点 {len(skipped_free)} 个, 不计入掌握度, 跳过.")

    for pass_index in range(1, max(1, passes) + 1):
        if not pending:
            break
        section = getattr(logger, "section", None)
        if callable(section):
            section(f"掌握度 第 {pass_index}/{passes} 轮")
        else:
            logger.info(f"===== 掌握度 第 {pass_index}/{passes} 轮 =====")
        logger.event(
            "掌握度轮次",
            轮次=pass_index,
            待处理=len(pending),
            最大刷题轮数=max_attempts + (pass_index - 1) * 2,
        )
        still_pending: list[dict] = []
        improved = 0
        for index, node in enumerate(pending, 1):
            name = node.get("name") or node["nodeUid"]
            prefix = (
                f"[{pass_index}-{index}/{len(pending)}] "
                f"{node.get('module', '')} / {node.get('unit', '')} / {name}"
            )
            logger.info(f"===== {prefix} =====")
            learn_url = build_learn_url(course_id, node["nodeUid"], class_id)
            try:
                mastery = await read_node_mastery(page, learn_url)
            except Exception as error:
                logger.warn(f"读取掌握度失败: {type(error).__name__}: {error}")
                still_pending.append(node)
                continue
            logger.event("知识点状态", 名称=name, 掌握度=mastery)
            if mastery is not None and mastery >= target:
                summary["skipped"].append({"name": name, "mastery": mastery})
                logger.info(f"已达标, 跳过: {mastery}%")
                continue

            try:
                result = await run_mastery(
                    page,
                    learn_url,
                    cache,
                    logger,
                    max_attempts=max_attempts + (pass_index - 1) * 2,
                    target=target,
                )
            except Exception as error:
                logger.error(f"刷掌握度异常: {type(error).__name__}: {error}")
                still_pending.append(node)
                continue

            final = result.get("mastery")
            record = {
                "name": name,
                "nodeUid": node["nodeUid"],
                "before": mastery,
                "after": final,
                "pass": pass_index,
                "attempts": result.get("attempts"),
            }
            records[node["nodeUid"]] = record
            if final is not None and final >= target:
                pass
            else:
                still_pending.append(node)
                if final is not None and mastery is not None and final > mastery:
                    improved += 1
            logger.event("知识点完成", 名称=name, 前=mastery, 后=final, 轮次=pass_index)

        summary["passes"].append(
            {"pass": pass_index, "pending": len(pending), "still": len(still_pending)}
        )
        logger.event(
            "本轮汇总",
            轮次=pass_index,
            本轮待处理=len(pending),
            仍未达标=len(still_pending),
            有提升=improved,
        )
        if not still_pending:
            break
        if improved == 0 and pass_index > 1:
            logger.warn("本轮所有未达标知识点都没有提升, 停止补刷.")
            break
        # 补刷只跑没达标的, 且不放宽免考过滤
        pending = still_pending
        logger.info(f"进入第 {pass_index + 1} 轮补刷, 剩余 {len(pending)} 个知识点.")

    for record in records.values():
        if record.get("after") is not None and record["after"] >= target:
            summary["done"].append(record)
        else:
            summary["failed"].append(record)

    logger.event(
        "课程掌握度汇总",
        达标=len(summary["done"]),
        跳过=len(summary["skipped"]),
        未达标=len(summary["failed"]),
        轮数=len(summary["passes"]),
    )
    return summary


