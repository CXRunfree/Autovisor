"""Optional, bounded DeepSeek image-point verification for course dialogs."""

import asyncio
import base64
import io
import json
import math
import os
import sys

import httpx
from PIL import Image
from playwright.async_api import TimeoutError
from playwright._impl._errors import TargetClosedError

KEYCHAIN_SERVICE = "com.autovisor.deepseek"
NORMALIZED_SIZE = (1000, 1000)
MAX_ATTEMPTS = 3


def parse_point(content, width=1000, height=1000):
    """Accept JSON surrounded by prose, but reject uncertain/invalid points."""
    text = content.strip()
    data, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
    if not isinstance(data, dict) or data.get("uncertain") is not False:
        raise ValueError("模型无法确定目标")
    point = data.get("center_px")
    if not isinstance(point, list) or len(point) != 2:
        raise ValueError("模型没有返回单个坐标")
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in point):
        raise ValueError("模型返回无效坐标")
    x, y = point
    if not (0 < x < width and 0 < y < height):
        raise ValueError("模型坐标超出截图范围")
    return x, y


def to_page_point(point, size, box):
    return (
        box["x"] + point[0] * box["width"] / size[0],
        box["y"] + point[1] * box["height"] / size[1],
    )


def safe_image_point(point, box):
    x, y = to_page_point(point, NORMALIZED_SIZE, box)
    if not (
        box["x"] + 5 < x < box["x"] + box["width"] - 5
        and box["y"] + 5 < y < box["y"] + box["height"] - 5
    ):
        raise ValueError("目标未落在验证图片内部")
    if x > box["x"] + box["width"] - 45 and y < box["y"] + 45:
        raise ValueError("目标落在刷新按钮区域")
    return x, y


async def api_key():
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    if sys.platform != "darwin":
        raise RuntimeError("请设置 DEEPSEEK_API_KEY 环境变量")
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    key = stdout.decode().strip()
    if process.returncode or not key:
        raise RuntimeError("没有可用的 DeepSeek Key")
    return key


async def visible_locator(page, selectors):
    for selector in selectors:
        candidates = page.locator(selector)
        for index in range(await candidates.count()):
            candidate = candidates.nth(index)
            if await candidate.is_visible():
                return candidate
    return None


def request_payload(prompt, crop):
    with Image.open(io.BytesIO(crop)) as png:
        enlarged = png.resize((png.width * 3, png.height * 3))
        encoded = io.BytesIO()
        enlarged.save(encoded, format="PNG")
    return {
        "model": "deepseek-flash",
        "thinking": {"type": "disabled"},
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": (
                f"题目文字：{prompt}\n附件仅包含验证图像，没有标题和底部提示。"
                "按题目判断需要点击的单个字母、数字或图形。区分大小写、颜色、"
                "立体朝向；朝向指正面与侧面的方向，不要把所有直立字母都当作相同朝向。"
                "返回 JSON，字段 instruction、target、center_px、uncertain。"
                "center_px 是目标可见正面中心的归一化 [x,y]。横纵坐标均为0到1000，"
                "原点为附件左上角，右下角为[1000,1000]。不要点击刷新或按钮。"
                "不确定、需要多点或不是点击题时，uncertain=true、center_px=null。只输出 JSON。"
            )},
            {"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(encoded.getvalue()).decode(),
                "detail": "original",
            }},
        ]}],
    }


async def attempt_course_verification(page, logger):
    """Try up to three clicks, then leave the dialog for manual verification."""
    try:
        key = await api_key()
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                dialog = await visible_locator(page, (".yidun_modal", ".yidun_popup"))
                if dialog is None:
                    return False
                prompt = await dialog.inner_text(timeout=2000)
                if "点击" not in prompt or "滑" in prompt:
                    logger.warn("当前验证类型不支持视觉单点点击，请手动完成.")
                    return False
                image = await visible_locator(page, (
                    ".yidun_modal img.yidun_bg-img", ".yidun_popup img.yidun_bg-img",
                ))
                if image is None:
                    logger.warn("没有找到验证图片，请手动完成.")
                    return False
                image_src = await image.get_attribute("src")
                crop = await image.screenshot(scale="css", timeout=3000)
                logger.event("视觉验证请求", 次数=attempt)
                response = await asyncio.wait_for(client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": "Bearer " + key},
                    json=request_payload(prompt, crop),
                ), timeout=50)
                if response.status_code != 200:
                    logger.warn(f"DeepSeek 请求失败 HTTP {response.status_code}，请手动验证.")
                    return False
                point = parse_point(response.json()["choices"][0]["message"]["content"])
                if not await dialog.is_visible():
                    return True
                if (image_src != await image.get_attribute("src")
                        or prompt != await dialog.inner_text(timeout=2000)):
                    logger.warn("识别期间题目已变化，丢弃旧坐标.")
                    continue
                box = await image.bounding_box()
                if not box:
                    return False
                x, y = safe_image_point(point, box)
                logger.event("视觉验证点击", 次数=attempt, 图片归一化坐标=str(point))
                await page.mouse.click(x, y)
                try:
                    await dialog.wait_for(state="hidden", timeout=6000)
                    logger.event("视觉验证结果", 结果="弹窗已消失", 次数=attempt)
                    return True
                except TimeoutError:
                    logger.event("视觉验证结果", 结果="未通过", 次数=attempt)
                    await asyncio.sleep(2)
    except (asyncio.CancelledError, TargetClosedError):
        raise
    except Exception as exc:
        # Do not log requests, responses, exception text, screenshots or credentials.
        logger.warn(f"视觉验证停止（{type(exc).__name__}），请手动完成.")
        return False
    logger.warn("视觉验证最多三次仍未通过，停止重试，请手动完成.")
    return False
