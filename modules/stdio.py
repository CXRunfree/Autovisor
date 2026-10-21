# encoding=utf-8
"""Windows 控制台/Cursor 终端输出编码。

Cursor 的集成终端按 UTF-8 捕获 stdout; 中文 Windows 上 Python 默认用系统代码页
(常见为 GBK/cp936) 打印, 于是横幅和 [INFO] 中文会变成 `` 乱码。启动时把
stdout/stderr 切到 UTF-8, 并切换控制台代码页。
"""
import sys

WINDOWS_UTF8_CODEPAGE = 65001


def configure_stdio() -> None:
    if sys.platform != "win32":
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            continue
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(WINDOWS_UTF8_CODEPAGE)
        kernel32.SetConsoleCP(WINDOWS_UTF8_CODEPAGE)
    except Exception:
        return
