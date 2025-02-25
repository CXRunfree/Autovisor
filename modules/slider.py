from types import ModuleType
import requests
import random
from playwright.async_api import Page
from playwright._impl._errors import TimeoutError
from modules.logger import Logger

logger = Logger()

# 下载图片并转换为OpenCV格式
async def download_image(url):
    response = requests.get(url)
    # 转换为numpy数组供cv2使用
    image_array = np.frombuffer(response.content, np.uint8)
    return cv2.imdecode(image_array, cv2.IMREAD_COLOR)


# 图片处理流程模块化
def process_background_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(binary, 500, 900, apertureSize=3)
    return edges


def process_block_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    inverted = cv2.bitwise_not(gray)
    _, binary = cv2.threshold(inverted, 240, 255, cv2.THRESH_BINARY_INV)
    edges = cv2.Canny(binary, 500, 900, apertureSize=3)
    return edges


# 主函数，结合页面加载和图片处理
async def progress_img(page: Page):
    # 等待滑块验证码图片加载完成
    if await page.locator("div.yidun--loading").is_visible():
        await page.wait_for_selector("div.yidun--loading", state="detached")

    # 异步下载背景图片和滑块图片
    bg_url = await page.locator('img.yidun_bg-img').get_attribute('src')
    block_url = await page.locator('img.yidun_jigsaw').get_attribute('src')

    bg_img = await download_image(bg_url)
    block_img = await download_image(block_url)

    # 图片处理
    bg_edges = process_background_image(bg_img)
    block_edges = process_block_image(block_img)

    # 匹配模板
    result = cv2.matchTemplate(bg_edges, block_edges, cv2.TM_CCOEFF_NORMED)
    _, _, _, max_loc = cv2.minMaxLoc(result)

    return max_loc


# 生成随机滑动鼠标位置列表
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


async def move_slider(page: Page, distance, offset=32):
    await page.locator('div.yidun_slider').hover()
    box = await page.locator('div.yidun_slider').bounding_box()

    # 生成每次移动距离列表
    move_list = gen_movelist(distance)
    # 开始拖动
    await page.mouse.down()
    for i in range(0, len(move_list)):
        await page.mouse.move(box["x"] + sum(move_list[:i]) + offset, box["y"])
    await page.mouse.up()

# 定义全局变量
cv2 = None
np = None

async def slider_verify(page: Page, modules: list[ModuleType]):
    global cv2, np
    np, cv2 = modules
    if not cv2 or not np:
        logger.warn("OpenCV或Numpy导入失败,无法开启自动滑块验证.")
        return
    # 尝试自动验证3次
    isPassed = 0
    for x in range(0, 3):
        try:
            await page.wait_for_selector(".wall-main", state="attached")
            await page.wait_for_selector(".yidun_bgimg", state="attached")
            logger.info(f"第{x + 1}次尝试过滑块验证...")
            max_loc = await progress_img(page)
            await move_slider(page, max_loc[0])
            await page.wait_for_selector(".wall-main", state='hidden', timeout=3000)
            isPassed = 1
            break
        except TimeoutError:
            continue
    if not isPassed:
        logger.warn("自动过滑块验证失败,请手动验证!")
    else:
        logger.info("滑块验证已成功通过.")
