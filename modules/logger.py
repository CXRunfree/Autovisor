import os
import sys
import threading
import time
import traceback


# 单例模式日志器
class Logger:
    _instance = None
    _lock = threading.Lock()  # 线程安全锁

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Logger, cls).__new__(cls)
                cls._instance._init()
        return cls._instance

    def _init(self):
        self.runtime_root = self.get_runtime_root()
        self.log_dir = os.path.join(self.runtime_root, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.log_dir, 0o700)
        new_index = len(os.listdir(self.log_dir)) + 1
        self.filename = os.path.join(self.log_dir, f"Log{new_index}.txt")
        self._write_lock = threading.Lock()
        with open(self.filename, "w", encoding="utf-8"):
            pass
        if os.name != "nt":
            os.chmod(self.filename, 0o600)

    @staticmethod
    def get_runtime_root():
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @staticmethod
    def summarize_exception(exc):
        first_line = str(exc).splitlines()[0].strip()
        return f"{type(exc).__name__}: {first_line}"

    def write_log(self, msg):
        date = time.strftime("%H:%M:%S", time.localtime())
        record = f"[{date}] {msg}"
        with self._write_lock:
            with open(self.filename, "a", encoding="utf-8") as f:
                f.write(record)
                f.flush()

    def log_exception(self, msg, exc=None, shift=False):
        detail_lines = []
        if exc is not None:
            detail_lines = [
                f"异常类型: {type(exc).__name__}",
                f"异常详情: {exc}",
            ]
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        else:
            tb = traceback.format_exc()
        self.error(msg, shift=shift)
        if detail_lines:
            self.write_log("\n".join(detail_lines) + "\n")
        self.write_log(f"{tb}\n")

    def save(self, inform=True):
        if inform:
            print(f"\n日志文件已保存至: {self.filename}")

    def debug(self, msg):
        self.write_log(f"[DEBUG] {msg}\n")

    def info(self, msg, shift=False):
        if shift:
            text = f"\r\n\033[32m[INFO]\033[0m {msg}"
        else:
            text = f"\r\033[32m[INFO]\033[0m {msg}"
        print(text.ljust(50))
        self.write_log(f"[INFO] {msg}\n")

    def warn(self, msg, shift=False):
        if shift:
            text = f"\r\n\033[33m[WARN]\033[0m {msg}"
        else:
            text = f"\r\033[33m[WARN]\033[0m {msg}"
        print(text.ljust(50))
        self.write_log(f"[WARN] {msg}\n")

    def error(self, msg, shift=False):
        if shift:
            text = f"\r\n\033[31m[ERROR]\033[0m {msg}"
        else:
            text = f"\r\033[31m[ERROR]\033[0m {msg}"
        print(text.ljust(50))
        self.write_log(f"[ERROR] {msg}\n")
