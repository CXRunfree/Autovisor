# coding=utf-8
import io
from PIL import Image
import numpy as np
import cv2


def get_target(img_bytes: bytes = None):
    image = Image.open(io.BytesIO(img_bytes))
    w, h = image.size
    starttx = 0
    startty = 0
    end_x = 0
    end_y = 0
    for x in range(w):
        for y in range(h):
            p = image.getpixel((x, y))
            if p[-1] == 0:
                if startty != 0 and end_y == 0:
                    end_y = y

                if starttx != 0 and end_x == 0:
                    end_x = x
            else:
                if startty == 0:
                    startty = y
                    end_y = 0
                else:
                    if y < startty:
                        startty = y
                        end_y = 0
        if starttx == 0 and startty != 0:
            starttx = x
        if end_y != 0:
            end_x = x
    return image.crop((starttx, startty, end_x, end_y)), starttx, startty


def slide_match(target_bytes: bytes = None, background_bytes: bytes = None, simple_target: bool = False,
                flag: bool = False):
    if not simple_target:
        try:
            target, target_x, target_y = get_target(target_bytes)
            target = cv2.cvtColor(np.asarray(target), cv2.IMREAD_ANYCOLOR)
        except SystemError as e:
            # SystemError: tile cannot extend outside image
            if flag:
                raise e
            return slide_match(target_bytes=target_bytes, background_bytes=background_bytes,
                                    simple_target=True,
                                    flag=True)
    else:
        target = cv2.imdecode(np.frombuffer(target_bytes, np.uint8), cv2.IMREAD_ANYCOLOR)
        target_y = 0

    background = cv2.imdecode(np.frombuffer(background_bytes, np.uint8), cv2.IMREAD_ANYCOLOR)

    background = cv2.Canny(background, 100, 200)
    target = cv2.Canny(target, 100, 200)

    background = cv2.cvtColor(background, cv2.COLOR_GRAY2RGB)
    target = cv2.cvtColor(target, cv2.COLOR_GRAY2RGB)

    res = cv2.matchTemplate(background, target, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    h, w = target.shape[:2]
    bottom_right = (max_loc[0] + w, max_loc[1] + h)
    return {"target_y": target_y,
            "target": [int(max_loc[0]), int(max_loc[1]), int(bottom_right[0]), int(bottom_right[1])]}

