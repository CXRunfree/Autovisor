import os
import threading
import time


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
        os.makedirs("logs", exist_ok=True)  # 创建日志文件夹
        new_index = len(os.listdir("logs")) + 1
        self.filename = f"logs/Log{new_index}.txt"
        self.text = ""

    def info(self, msg, shift=False):
        if shift:
            print(f"\n\033[32m[INFO]\033[0m {msg}")
        else:
            print(f"\033[32m[INFO]\033[0m {msg}")

    def warn(self, msg, shift=False):
        if shift:
            print(f"\n\033[33m[WARN]\033[0m {msg}")
        else:
            print(f"\033[33m[WARN]\033[0m {msg}")

    def error(self, msg, shift=False):
        if shift:
            print(f"\n\033[31m[ERROR]\033[0m {msg}")
        else:
            print(f"\033[31m[ERROR]\033[0m {msg}")
