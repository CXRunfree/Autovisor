from __future__ import annotations

import re
from functools import lru_cache
from types import ModuleType

from playwright.async_api import Page
from playwright._impl._errors import TimeoutError

from modules.logger import Logger

logger = Logger()

INSTRUCTION_RE = re.compile(r"请点击")
TITLE_TEXT = "请完成安全验证"
CLICK_CAPTCHA_SELECTORS = (
    "#tcaptcha_iframe_dy",
    "iframe[id^='tcaptcha']",
    "[id^='tcaptcha_transform']",
    "#captcha.ignore-capcha",
)
PUZZLE_IMAGE_SELECTORS = (
    "img[alt='验证码背景']",
    "img[alt*='验证']",
    "#slideBg img",
    "#slideBg",
    ".tc-bg img",
    "canvas",
    "img",
)
SAT_LEVELS = (130, 110, 90, 70, 50)
TEMPLATE_SIZE = 48
MIN_MATCH = 0.40
COLOR_HUES = {
    "红色": 0,
    "橙色": 18,
    "黄色": 28,
    "绿色": 60,
    "青色": 90,
    "蓝色": 110,
    "紫色": 140,
    "粉色": 168,
    "灰色": None,
}

_SAME_COLOR_PATTERNS = (
    re.compile(r"请点击大写([A-Za-z])颜色一样的数字(\d)"),
    re.compile(r"请点击小写([A-Za-z])颜色一样的数字(\d)"),
    re.compile(r"请点击大写([A-Za-z])颜色一样的(?:字母|大写|小写)?([A-Za-z])"),
    re.compile(r"请点击小写([A-Za-z])颜色一样的(?:字母|大写|小写)?([A-Za-z])"),
    re.compile(r"请点击([A-Za-z0-9])颜色一样的数字(\d)"),
    re.compile(r"请点击([A-Za-z0-9])颜色一样的字母([A-Za-z])"),
    re.compile(r"请点击与([A-Za-z0-9])颜色相同的数字(\d)"),
    re.compile(r"请点击与([A-Za-z0-9])颜色相同的字母([A-Za-z])"),
)
_NAMED_COLOR_PATTERN = re.compile(
    r"请点击(?P<color>红色|黄色|蓝色|绿色|橙色|紫色|粉色|青色|灰色)的?"
    r"(?:数字|字母|大写|小写)*"
    r"(?P<target>[A-Za-z0-9])"
)
_ORIENT_PATTERNS = (
    (re.compile(r"请点击侧向的(?:小写|大写|数字)*([A-Za-z0-9])"), "sideways"),
    (re.compile(r"请点击倒立的(?:小写|大写|数字)*([A-Za-z0-9])"), "inverted"),
    (re.compile(r"请点击正向的(?:小写|大写|数字)*([A-Za-z0-9])"), "upright"),
)
# 侧躺 90° 后的常见外形，用来补 3D 字母在 90° 模板上匹配偏弱的情况。
SIDEWAYS_ALIAS = {
    "b": "u",
    "d": "n",
    "p": "n",
    "q": "u",
    "n": "u",
    "u": "n",
    "c": "u",
    "h": "c",
    "y": "h",
    "m": "e",
    "e": "m",
    "w": "e",
    "a": "e",
}


def parse_click_instruction(text: str) -> dict | None:
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    for pattern, orientation in _ORIENT_PATTERNS:
        match = pattern.search(compact)
        if match:
            return {
                "mode": "orientation",
                "orientation": orientation,
                "target": match.group(1),
                "ref": None,
                "color": None,
            }
    named = _NAMED_COLOR_PATTERN.search(compact)
    if named:
        return {
            "mode": "named_color",
            "color": named.group("color"),
            "target": named.group("target"),
            "ref": None,
        }
    for pattern in _SAME_COLOR_PATTERNS:
        match = pattern.search(compact)
        if match:
            return {
                "mode": "same_color",
                "ref": match.group(1),
                "target": match.group(2),
                "color": None,
            }
    return None


def hue_dist(left: float, right: float) -> float:
    delta = abs(left - right)
    return min(delta, 180.0 - delta)


def char_variants(token: str) -> tuple[str, ...]:
    if token.isalpha():
        return (token.upper(), token.lower())
    return (token,)


def _font_candidates() -> tuple[str, ...]:
    return (
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    )


@lru_cache(maxsize=1)
def _load_font(size: int):
    from PIL import ImageFont

    for path in _font_candidates():
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


@lru_cache(maxsize=256)
def render_char(ch: str, angle: int = 0, size: int = TEMPLATE_SIZE):
    from PIL import Image, ImageDraw

    canvas = 64
    image = Image.new("L", (canvas, canvas), 0)
    draw = ImageDraw.Draw(image)
    font = _load_font(48)
    bbox = draw.textbbox((0, 0), ch, font=font)
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((canvas - width) / 2 - bbox[0], (canvas - height) / 2 - bbox[1]),
        ch,
        fill=255,
        font=font,
    )
    if angle:
        image = image.rotate(angle, resample=Image.BILINEAR, fillcolor=0)
    return image


def _pil_to_mask(image, np, cv2, size: int = TEMPLATE_SIZE):
    array = np.array(image)
    ys, xs = np.where(array > 0)
    if len(xs) == 0:
        return np.zeros((size, size), np.uint8)
    cropped = array[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    padded = cv2.copyMakeBorder(cropped, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
    return cv2.resize(padded, (size, size), interpolation=cv2.INTER_AREA)


def match_char(bitmap, ch: str, np, cv2, angles=None) -> float:
    if angles is None:
        angles = range(-30, 31, 5)
    best = -1.0
    for angle in angles:
        template = _pil_to_mask(render_char(ch, int(angle)), np, cv2)
        score = float(
            cv2.matchTemplate(bitmap, template, cv2.TM_CCOEFF_NORMED).max()
        )
        if score > best:
            best = score
    return best


def extract_glyphs(image, hsv, sat_min: int, np, cv2) -> list[dict]:
    hue, sat, val = cv2.split(hsv)
    height, width = image.shape[:2]
    min_area = max(80, int(height * width * 0.003))
    max_area = int(height * width * 0.35)
    bg_val = float(np.median(val))
    color_mask = (sat > sat_min) & (val > 140)
    gray_mask = (sat <= 45) & (val < bg_val - 25) & (val > 50)
    mask = (color_mask | gray_mask).astype(np.uint8) * 255
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    glyphs = []
    for index in range(1, count):
        x, y, box_w, box_h, area = (int(value) for value in stats[index])
        if area < min_area or area > max_area or box_w < 8 or box_h < 8:
            continue
        region = labels == index
        # 右上角刷新按钮，不是题目里的字母。
        if x + box_w > width * 0.86 and y < height * 0.28 and box_w <= 42 and box_h <= 42:
            continue
        glyphs.append(
            {
                "bbox": (x, y, box_w, box_h),
                "cx": float(centroids[index][0]),
                "cy": float(centroids[index][1]),
                "area": area,
                "hue": float(hue[region].mean()),
                "sat": float(sat[region].mean()),
                "mask": region,
            }
        )
    return glyphs


def glyph_bitmap(glyph: dict, np, cv2, size: int = TEMPLATE_SIZE):
    x, y, box_w, box_h = glyph["bbox"]
    mask = glyph["mask"][y : y + box_h, x : x + box_w]
    bitmap = mask.astype(np.uint8) * 255
    bitmap = cv2.copyMakeBorder(bitmap, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
    return cv2.resize(bitmap, (size, size), interpolation=cv2.INTER_AREA)


def score_glyph(glyph: dict, chars: tuple[str, ...], np, cv2, angles=None) -> float:
    bitmap = glyph_bitmap(glyph, np, cv2)
    return max(match_char(bitmap, char, np, cv2, angles=angles) for char in chars)


def pick_orientation_target(glyphs: list[dict], parsed: dict, np, cv2):
    target_chars = char_variants(parsed["target"])
    alias = SIDEWAYS_ALIAS.get(parsed["target"].lower(), "")
    alias_chars = char_variants(alias) if alias else ()
    scored = []
    for glyph in glyphs:
        upright = score_glyph(glyph, target_chars, np, cv2, angles=(0, -15, 15))
        sideways = score_glyph(
            glyph, target_chars, np, cv2, angles=(90, 270, 75, 105, 255, 285)
        )
        inverted = score_glyph(glyph, target_chars, np, cv2, angles=(180, 165, 195))
        lookalike = (
            score_glyph(glyph, alias_chars, np, cv2, angles=(0, -20, 20))
            if alias_chars
            else 0.0
        )
        scored.append((glyph, upright, sideways, inverted, lookalike))
    if not scored:
        return None
    orientation = parsed["orientation"]
    if orientation == "sideways":
        eligible = []
        for item in scored:
            upright, sideways, _inverted, lookalike = item[1:]
            rotated = max(sideways, lookalike)
            if rotated < 0.35:
                continue
            # 正向字母的 upright 分通常明显高于侧躺外形，直接排除。
            if upright >= 0.62 and rotated < upright + 0.12:
                continue
            eligible.append(item)
        if not eligible:
            return None
        pool = eligible

        def rank(item):
            return max(item[2], item[4]) - 0.5 * item[1]
    elif orientation == "inverted":
        pool = scored

        def rank(item):
            return item[3] - 0.35 * item[1]
    else:
        pool = scored

        def rank(item):
            return item[1]

    best = max(pool, key=rank)
    confidence = rank(best)
    if confidence < 0.12:
        return None
    return confidence, best[0]["cx"], best[0]["cy"]


def pick_target(glyphs: list[dict], parsed: dict, np, cv2):
    if parsed["mode"] == "orientation":
        return pick_orientation_target(glyphs, parsed, np, cv2)
    if not glyphs:
        return None
    target_chars = char_variants(parsed["target"])
    scored = []
    for glyph in glyphs:
        target_score = score_glyph(glyph, target_chars, np, cv2)
        ref_score = 0.0
        if parsed.get("ref"):
            ref_score = score_glyph(glyph, char_variants(parsed["ref"]), np, cv2)
        scored.append((glyph, target_score, ref_score))

    if parsed["mode"] == "named_color":
        named_hue = COLOR_HUES[parsed["color"]]
        candidates = [item for item in scored if item[1] >= MIN_MATCH]
        if not candidates:
            candidates = scored
            if not candidates:
                return None

        def named_rank(item):
            if named_hue is None:
                sat_score = 1.0 - min(item[0]["sat"] / 80.0, 1.0)
                return item[1] * 0.55 + sat_score * 0.45
            color = 1.0 - min(hue_dist(item[0]["hue"], named_hue) / 40.0, 1.0)
            return item[1] * 0.7 + color * 0.3

        best = max(candidates, key=named_rank)
        return named_rank(best), best[0]["cx"], best[0]["cy"]

    if len(scored) < 2:
        return None
    ref_item = max(scored, key=lambda item: item[2])
    if ref_item[2] < MIN_MATCH:
        return None
    candidates = [
        item
        for item in scored
        if item[0] is not ref_item[0] and item[1] >= MIN_MATCH
    ]
    if not candidates:
        others = [item for item in scored if item[0] is not ref_item[0]]
        if not others:
            return None
        others.sort(key=lambda item: hue_dist(item[0]["hue"], ref_item[0]["hue"]))
        candidates = others[:2]

    def color_rank(item):
        color = 1.0 - min(hue_dist(item[0]["hue"], ref_item[0]["hue"]) / 40.0, 1.0)
        return item[1] * 0.65 + color * 0.35

    best = max(candidates, key=color_rank)
    confidence = color_rank(best) * (0.5 + 0.5 * ref_item[2])
    return confidence, best[0]["cx"], best[0]["cy"]


def find_click_point(image, instruction: str, np, cv2):
    parsed = parse_click_instruction(instruction)
    if parsed is None or image is None or image.size == 0:
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    best = None
    for sat_min in SAT_LEVELS:
        glyphs = extract_glyphs(image, hsv, sat_min, np, cv2)
        result = pick_target(glyphs, parsed, np, cv2)
        if result is None:
            continue
        if best is None or result[0] > best[0]:
            best = result
        if best[0] >= 0.55:
            break
    if best is None:
        return None
    return best[1], best[2]


def decode_png(data, np, cv2):
    array = np.frombuffer(data, np.uint8)
    return cv2.imdecode(array, cv2.IMREAD_COLOR)


async def _iter_targets(page: Page):
    yield page
    for frame in getattr(page, "frames", []):
        if frame is page or getattr(page, "main_frame", None) is frame:
            continue
        yield frame


async def resolve_click_captcha_target(page: Page):
    async def matches(target) -> bool:
        try:
            if await target.get_by_text(TITLE_TEXT).count():
                return True
            if await target.get_by_text(INSTRUCTION_RE).count():
                return True
            for selector in CLICK_CAPTCHA_SELECTORS:
                if await target.locator(selector).count():
                    return True
        except Exception:
            return False
        return False

    if await matches(page):
        return page
    async for target in _iter_targets(page):
        if await matches(target):
            return target
    return None


async def read_instruction(target) -> str:
    locator = target.get_by_text(INSTRUCTION_RE)
    try:
        if await locator.count():
            text = (await locator.first.inner_text()).strip()
            if text:
                return text
    except Exception:
        pass
    try:
        body = await target.locator("body").inner_text()
    except Exception:
        return ""
    for line in body.splitlines():
        if "请点击" in line:
            return line.strip()
    return body.strip()


async def find_puzzle_image(target):
    best = None
    best_score = 0.0
    for selector in PUZZLE_IMAGE_SELECTORS:
        try:
            locator = target.locator(selector)
            count = await locator.count()
        except Exception:
            continue
        for index in range(count):
            element = locator.nth(index)
            try:
                if not await element.is_visible():
                    continue
                box = await element.bounding_box()
            except Exception:
                continue
            if not box or box["width"] < 80 or box["height"] < 40:
                continue
            area = box["width"] * box["height"]
            ratio = box["width"] / max(box["height"], 1)
            score = area * (2.0 if 1.5 <= ratio <= 2.8 else 1.0)
            if score > best_score:
                best = element
                best_score = score
        if best is not None and best_score >= 12_000:
            return best
    return best


def _mouse(target):
    mouse = getattr(target, "mouse", None)
    if mouse is not None:
        return mouse
    return target.page.mouse


async def click_image_point(target, image_locator, pixel_x, pixel_y, image_shape):
    box = await image_locator.bounding_box()
    if not box:
        return False
    height, width = image_shape[:2]
    css_x = pixel_x * box["width"] / width
    css_y = pixel_y * box["height"] / height
    await _mouse(target).click(box["x"] + css_x, box["y"] + css_y)
    return True


async def _refresh(target) -> None:
    for locator in (
        target.get_by_role("button", name=re.compile("刷新")),
        target.locator("button[title*='刷新'], .reload, .tc-refresh"),
    ):
        try:
            if await locator.count():
                await locator.first.click(timeout=1000)
                return
        except Exception:
            continue


async def solve_click_captcha(page: Page, modules: list[ModuleType], attempts: int = 3) -> bool:
    np_mod, cv_mod = modules
    if not np_mod or not cv_mod:
        logger.warn("OpenCV或Numpy导入失败,无法自动识别点选验证.")
        return False
    target = await resolve_click_captcha_target(page)
    if target is None:
        return False

    for attempt in range(attempts):
        try:
            instruction = await read_instruction(target)
            parsed = parse_click_instruction(instruction)
            image_locator = await find_puzzle_image(target)
            if parsed is None or image_locator is None:
                logger.warn("未解析到点选验证码题目或图片.")
                return False
            png = await image_locator.screenshot(type="png")
            image = decode_png(png, np_mod, cv_mod)
            point = find_click_point(image, instruction, np_mod, cv_mod)
            if point is None:
                logger.warn(f"第{attempt + 1}次点选识别失败,正在刷新...")
                await _refresh(target)
                await page.wait_for_timeout(800)
                continue
            logger.info(
                f"第{attempt + 1}次尝试点选验证: {instruction} -> "
                f"({point[0]:.0f}, {point[1]:.0f})"
            )
            await click_image_point(target, image_locator, point[0], point[1], image.shape)
            await page.wait_for_timeout(1200)
            if await resolve_click_captcha_target(page) is None:
                logger.info("点选验证已成功通过.")
                return True
            logger.warn(f"第{attempt + 1}次点选未通过,正在刷新...")
            await _refresh(target)
            await page.wait_for_timeout(800)
        except TimeoutError:
            continue
        except Exception as exc:
            logger.warn(f"点选验证异常: {exc}")
            await _refresh(target)
            await page.wait_for_timeout(800)
    logger.warn("自动点选验证失败,请手动验证!")
    return False
