from types import ModuleType
import requests
import random
from playwright.async_api import Page
from playwright._impl._errors import TimeoutError
from modules.logger import Logger

YIDUN_PUZZLE_SELECTOR = ".yidun_bgimg, img.yidun_bg-img"
IN_COURSE_APPEAR_TIMEOUT_MS = 8_000
LOGIN_APPEAR_TIMEOUT_MS = 24 * 3600 * 1000

# 定义全局变量
cv2: ModuleType
np: ModuleType
logger = Logger()


def image_to_display_point(point, image_width, image_height, display_width, display_height):
    """将 OpenCV 原图像素坐标转换为浏览器 CSS 显示坐标。"""
    return (
        point[0] * display_width / image_width,
        point[1] * display_height / image_height,
    )


# 下载验证码图片，并转换为 OpenCV 可处理的图像。
async def download_image(url):
    response = requests.get(url)
    # 图片字节需要先转为 NumPy 数组，再交给 OpenCV 解码。
    image_array = np.frombuffer(response.content, np.uint8)
    return cv2.imdecode(image_array, cv2.IMREAD_COLOR)


# 对背景图提取边缘，减少颜色和纹理对匹配的干扰。
def process_background_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(binary, 500, 900, apertureSize=3)
    return edges


def process_block_image(image):
    # 拼图块亮度方向与背景不同，因此先反色再提取边缘。
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    inverted = cv2.bitwise_not(gray)
    _, binary = cv2.threshold(inverted, 240, 255, cv2.THRESH_BINARY_INV)
    edges = cv2.Canny(binary, 500, 900, apertureSize=3)
    return edges


def _mouse(target):
    mouse = getattr(target, "mouse", None)
    if mouse is not None:
        return mouse
    return target.page.mouse


async def resolve_captcha_target(page: Page):
    """返回包含易盾拼图的 page/frame; 找不到时返回 None。"""
    if await page.locator(YIDUN_PUZZLE_SELECTOR).count() > 0:
        return page
    for frame in getattr(page, "frames", []):
        try:
            if await frame.locator(YIDUN_PUZZLE_SELECTOR).count() > 0:
                return frame
        except Exception:
            continue
    return None


# 主函数，结合页面加载和图片处理
async def progress_img(page: Page):
    # 等待易盾验证码加载完成，避免读取到空图片或旧图片。
    loading = page.locator("div.yidun--loading").first
    if await loading.count() and await loading.is_visible():
        await page.wait_for_selector("div.yidun--loading", state="detached")

    # OpenCV 处理的是原图像素，浏览器拖动使用 CSS 显示像素。
    bg_locator = page.locator("img.yidun_bg-img").first
    block_url = await page.locator("img.yidun_jigsaw").first.get_attribute("src")
    bg_url = await bg_locator.get_attribute("src")
    bg_box = await bg_locator.bounding_box()
    if not bg_url or not block_url or not bg_box:
        raise TimeoutError("yidun puzzle images not ready")
    image_size = await bg_locator.evaluate(
        'image => ({width: image.naturalWidth, height: image.naturalHeight})'
    )

    bg_img = await download_image(bg_url)
    block_img = await download_image(block_url)

    # 分别处理背景图和拼图块。
    bg_edges = process_background_image(bg_img)
    block_edges = process_block_image(block_img)

    # 匹配结果仍是原图坐标，后面必须转换到浏览器显示坐标。
    result = cv2.matchTemplate(bg_edges, block_edges, cv2.TM_CCOEFF_NORMED)
    _, _, _, max_loc = cv2.minMaxLoc(result)

    # 例如当前页面是 480x240 原图显示为 400x200，缩放比例为 0.8333。
    display_point = image_to_display_point(
        max_loc,
        image_size["width"],
        image_size["height"],
        bg_box["width"],
        bg_box["height"],
    )
    return round(display_point[0], 3), round(display_point[1], 3)


# 生成随机滑动轨迹，最后一步补齐剩余距离。
def gen_movelist(sum_n, steps=30):
    move_list = []
    for x in range(steps - 1):
        if sum_n <= 1.5:
            break
        temp = random.uniform(1, sum_n / 2)  # 每次随机生成滑动的距离
        move_list.append(round(temp, 3))  # 添加随机滑动距离
        sum_n -= temp  # 剩余距离减少
    move_list.append(round(sum_n, 3))  # 最后一步修正剩余的距离，保证总距离正确
    return move_list


async def move_slider(page: Page, distance, offset=36):
    """按浏览器显示坐标拖动滑块。

    offset 是组件几何补偿，不是图片缩放比例。当前易盾页面中，滑块按钮
    宽度约为 40px，鼠标从按钮中心开始拖动，拼图块还有内部透明边距。
    综合真实页面截图和 DOM 尺寸校准后，约 36px 时更容易对齐；这是当前
    页面布局的经验值，验证码组件尺寸变化时需要重新校准。
    """
    slider = page.locator("div.yidun_slider").first
    await slider.hover()
    box = await slider.bounding_box()

    # distance 已经是 CSS 显示坐标，不要再次乘图片缩放比例。
    move_list = gen_movelist(distance)
    # 轨道左边缘 + 识别距离 + 组件几何补偿。
    mouse = _mouse(page)
    await mouse.down()
    for i in range(0, len(move_list)):
        await mouse.move(box["x"] + sum(move_list[:i]) + offset, box["y"])
    await mouse.up()


async def slider_verify(
    page: Page,
    modules: list[ModuleType],
    appear_timeout_ms: int = LOGIN_APPEAR_TIMEOUT_MS,
) -> bool:
    global cv2, np
    np, cv2 = modules
    if not cv2 or not np:
        logger.warn("OpenCV或Numpy导入失败,无法开启自动滑块验证.")
        return False
    # 尝试自动验证3次
    isPassed = 0
    for x in range(0, 3):
        target = None
        try:
            target = await resolve_captcha_target(page)
            if target is None:
                await page.wait_for_selector(
                    YIDUN_PUZZLE_SELECTOR, state="visible", timeout=appear_timeout_ms
                )
                target = await resolve_captcha_target(page)
            if target is None:
                return False
            logger.info(f"第{x + 1}次尝试过滑块验证...")
            max_loc = await progress_img(target)
            await move_slider(target, max_loc[0])
            await target.wait_for_selector(".yidun_bgimg", state="hidden", timeout=3000)
            isPassed = 1
            break
        except TimeoutError:
            if target is None:
                return False
            continue
    if not isPassed:
        logger.warn("自动过滑块验证失败,请手动验证!")
        return False
    logger.info("滑块验证已成功通过.")
    return True
