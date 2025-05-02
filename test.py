import time

text = "\033[32m[INFO]\033[0m 测试信息"

for i in range(1, 10):
    # 进度条信息（带 \r 回到行首）
    progress = f"\r\033[32m[INFO]\033[0m 播放进度: |{'█' * i}{' ' * (9 - i)}| {i * 10}%"
    print(progress.ljust(50), end="", flush=True)  # 固定宽度确保覆盖
    time.sleep(0.3)

    # 用 \r 回到行首，输出 text（覆盖进度条）
    print(f"\r{text.ljust(50)}", end="\n", flush=True)  # 固定宽度避免残留
    time.sleep(0.3)

print()  # 循环结束后换行