import re

# 公共请求头
quark_headers = {
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "origin": "https://vt.quark.cn",
    "referer": "https://vt.quark.cn/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0"
}

# 登录
quark_index_url = "https://vt.quark.cn/blm/qk-souti-759/index"
quark_token_url = "https://api.open.uc.cn/cas/ajax/getTokenForQrcodeLogin"
quark_ticket_url = "https://api.open.uc.cn/cas/ajax/getServiceTicketByQrcodeToken"

# 搜题
quark_search_url = "https://page-souti.myquark.cn/api/pc/souti"
# 单选题/判断题匹配
single_pattern = re.compile(r"(?:\S*)?([A-Z])(?:\S*)?")
# 多选题匹配
multiple_pattern = re.compile(r"([A-Z])")
