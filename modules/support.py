# encoding=utf-8
from PIL import Image


def show_donate(imgpath="resources/QRcode.jpg", show=True):
    if not show:
        print("如果觉得对你有帮助, 请为本项目点亮star吧~")
        return
    try:
        img = Image.open(imgpath)
        print("感觉还不错? 来请作者喝杯coffee~")
        img.show()
        print("不希望显示赞赏码? 删除resources文件夹的QRcode文件就好啦~")
    except FileNotFoundError:
        return
