import json
import threading

from playwright.async_api import Page, BrowserContext
import asyncio
from io import BytesIO
from .config import quark_index_url
from PIL import Image
import qrcode
from pyzbar.pyzbar import decode
from .logger import Logger

logger = Logger()


def show_login_image(image_data):
    logger.info("正在识别二维码...")
    image = Image.open(BytesIO(image_data))
    decoded = decode(image)
    if not decoded:
        logger.info("识别二维码内容失败!")
        return
    # 提取二维码内容
    logger.info("===== 正在将二维码打印至终端 =====")
    data = decoded[0].data.decode("utf-8")
    qr = qrcode.QRCode(box_size=1, border=1)
    qr.add_data(data)
    # invert=True白底黑块
    qr.print_ascii(invert=True)
    logger.info("请使用手机夸克扫码完成登录...",shift=True)


async def get_user_ticket(page: Page):
    while True:
        data_str: str = await page.evaluate("localStorage.QK_SOUTI_USER_INFO")
        if data_str:
            data = json.loads(data_str)
            ticket = data.get("service_ticket")
            if ticket:
                return ticket
        await asyncio.sleep(0.1)


async def login(context: BrowserContext):
    print("[Info]正在获取quark登录二维码...")
    page = await context.new_page()
    await page.goto(quark_index_url)
    await page.wait_for_load_state(state="domcontentloaded")
    user_btn_name = ".i-view.w-avatar.w-avatar-circle"
    await page.locator(user_btn_name).click()
    qrcode_element = await page.wait_for_selector(".login-guide", state="visible")
    svg_elements = await page.locator("svg").all()
    ticket = ""
    if qrcode_element and len(svg_elements) > 0:
        qrcode_img = await qrcode_element.screenshot()
        # 启动一个新线程来显示图片，并传递二维码的 bytes 数据
        thread = threading.Thread(target=show_login_image, args=(qrcode_img,))
        thread.daemon = True  # 设置为守护线程
        thread.start()
        ticket = await get_user_ticket(page)
    await page.close()
    return ticket


