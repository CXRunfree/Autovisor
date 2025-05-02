import json
import re
import time
import uuid

import httpx

from .config import quark_headers, quark_search_url, multiple_pattern
from .logger import Logger

logger = Logger()


# 构造 multipart/form-data 表单
async def quark_search(img_bytes: bytes):
    timestamp = int(time.time() * 1000)
    json_data = {
        "product": "photo_page",
        "chid": uuid.uuid4().hex,
        "timestamp": timestamp,
        "st": "AAJ7jTXPugvpExSkk3A8u1PaTYksaFCipUTjj40dgXSh1ZnixRXENOeQJfFkffFFTg5ZvLP10aI1/WZQsngCgc2fe0H5ZNUCehJb6Duu2U0XVw=="
    }
    files = {
        "imgFile": (f"{timestamp}.jpg", img_bytes, "image/jpeg"),
        "reqJson": (
            "blob",  # 文件名
            bytes(json.dumps(json_data), encoding="utf-8"),  # 文件内容
            "application/json"
        )
    }
    async with httpx.AsyncClient(headers=quark_headers, verify=False,timeout=5000) as client:
        # 发送请求
        resp = await client.post(quark_search_url, files=files)
        if resp.status_code != 200 or resp.json().get("code") != 0:
            logger.error(f"获取答案失败: {resp.status_code}, {resp.text}")
            return None
        ext_json = resp.json()["data"]["extJson"]
        result = resp.json()["data"]["extJson"].get("result")
        if not result:
            logger.error("获取答案失败,detail:", resp.json())
            return []
        result = result[0]["sub_result"]
        questions = result["questions"]
        if len(questions) > 0:
            answer = questions[0]["answer"]
            if "<img" in answer:
                logger.warn("暂不支持识别图片类型的答案!")
                return
            results = re.findall(multiple_pattern, answer)
            return results
        else:
            return []
