import configparser
import os
import threading
from tkinter import ttk, messagebox
import tkinter as tk
import sv_ttk

# === 配置文件初始化 ===
config = configparser.ConfigParser()
config_file = 'configs.ini'
config.read(config_file, encoding="utf-8")

# === 默认配置 ===
default_driver = "Chrome"
default_exepath = ""


# === 事件函数 ===
def show_help():
    help_text = (
        "【必要配置说明】\n"
        "账号密码：可选项，如留空需手动登录\n"
        "课程链接：从智慧树课程页面复制链接（以 studyvideoh5.zhihuishu.com 开头）\n"
        "时长限制：程序运行的最大时间，0 表示不限\n"
        "倍速播放：最大 1.8（平台限制）\n\n"
        "【选填功能】\n"
        "自动跳过验证码：自动完成滑动验证\n"
        "隐藏浏览器窗口：运行时最小化浏览器\n"
        "静音播放：关闭视频声音\n\n"
        "输入 True 启用，留空或填 False 表示关闭\n\n"
        "【常见问题】\n"
        "Q: 浏览器启动失败？\n"
        "A: 请尝试双击 Autovisor.exe 运行。"
    )
    messagebox.showinfo('使用说明', help_text)


def launch_script():
    messagebox.showinfo('启动中', '准备刷课！')
    os.system('python Autovisor.py')


def launch_script_in_thread():
    threading.Thread(target=launch_script, daemon=True).start()


def launch_direct():
    def run():
        messagebox.showinfo('提示', '已记录配置，开始刷课')
        os.system('python Autovisor.py')

    threading.Thread(target=run, daemon=True).start()


def read_inputs():
    return {
        "username": username_entry.get(),
        "password": password_entry.get(),
        "course_url": course_entry.get(),
        "limit_time": time_limit_entry.get(),
        "speed": speed_entry.get(),
        "auto_captcha": verify_var.get(),
        "hide_window": hide_var.get(),
        "mute": mute_var.get()
    }


def save_and_run():
    inputs = read_inputs()
    config.set('course-url', 'URL1', inputs['course_url'])
    config.set('user-account', 'username', inputs['username'])
    config.set('user-account', 'password', inputs['password'])
    config.set('browser-option', 'driver', default_driver)
    config.set('browser-option', 'exe_path', default_exepath)
    config.set('script-option', 'enableautocaptcha', inputs['auto_captcha'])
    config.set('script-option', 'enablehidewindow', inputs['hide_window'])
    config.set('course-option', 'limitmaxtime', inputs['limit_time'])
    config.set('course-option', 'limitspeed', inputs['speed'])
    config.set('course-option', 'soundoff', inputs['mute'])

    with open(config_file, 'w', encoding="utf-8") as f:
        config.write(f)

    launch_script_in_thread()


# === GUI 构建 ===
root = tk.Tk()
root.title("智慧树刷课助手")
root.geometry("660x480+80+60")
root.resizable(False, False)
sv_ttk.set_theme("light")
ttk.Label(root, text="智慧树刷课助手", font=("Microsoft YaHei", 20)).pack(pady=25)

frame = ttk.Frame(root)
frame.pack()

# 必填项
ttk.Label(frame, text="必要配置:", font=("Microsoft YaHei", 15)).grid(row=0, column=1)

ttk.Label(frame, text="手机号：", font=("Microsoft YaHei", 10)).grid(row=1, column=1)
username_entry = ttk.Entry(frame)
username_entry.grid(row=1, column=3)

ttk.Label(frame, text="密码：", font=("Microsoft YaHei", 10)).grid(row=2, column=1)
password_entry = ttk.Entry(frame, show='*')
password_entry.grid(row=2, column=3)

ttk.Label(frame, text="课程链接：", font=("Microsoft YaHei", 10)).grid(row=3, column=1)
course_entry = ttk.Entry(frame)
course_entry.grid(row=3, column=3)

ttk.Label(frame, text="时长限制：", font=("Microsoft YaHei", 10)).grid(row=4, column=1)
time_limit_entry = ttk.Entry(frame)
time_limit_entry.grid(row=4, column=3)

ttk.Label(frame, text="倍速：", font=("Microsoft YaHei", 10)).grid(row=5, column=1)
speed_entry = ttk.Entry(frame)
speed_entry.grid(row=5, column=3)

ttk.Label(frame, text="").grid(row=6, column=1, pady=15)

# 初始化选项变量
verify_var = tk.StringVar(value="False")
hide_var = tk.StringVar(value="False")
mute_var = tk.StringVar(value="False")

# 自动跳过验证码
ttk.Label(frame, text="可选配置:", font=("Microsoft YaHei", 15)).grid(row=6, column=1)
ttk.Label(frame, text="自动跳过验证码：", font=("Microsoft YaHei", 10)).grid(row=7, column=1)
ttk.Radiobutton(frame, text="True", variable=verify_var, value="True").grid(row=7, column=3, sticky="w")
ttk.Radiobutton(frame, text="False", variable=verify_var, value="False").grid(row=7, column=3, sticky="e")

# 隐藏浏览器窗口
ttk.Label(frame, text="隐藏浏览器窗口：", font=("Microsoft YaHei", 10)).grid(row=8, column=1)
ttk.Radiobutton(frame, text="True", variable=hide_var, value="True").grid(row=8, column=3, sticky="w")
ttk.Radiobutton(frame, text="False", variable=hide_var, value="False").grid(row=8, column=3, sticky="e")

# 静音播放
ttk.Label(frame, text="静音播放(闭嘴)：", font=("Microsoft YaHei", 10)).grid(row=9, column=1)
ttk.Radiobutton(frame, text="True", variable=mute_var, value="True").grid(row=9, column=3, sticky="w")
ttk.Radiobutton(frame, text="False", variable=mute_var, value="False").grid(row=9, column=3, sticky="e")

# 按钮区域 - 使用Frame包装并调整布局
button_frame = ttk.Frame(root)
button_frame.pack(pady=20)  # 统一控制按钮区域的外边距

# 左侧按钮
save_button = ttk.Button(button_frame, text="保存配置并开始刷课", command=save_and_run)
save_button.pack(side=tk.LEFT, padx=10)

# 中间按钮（新增）
help_button = ttk.Button(button_frame, text="查看帮助", command=show_help)
help_button.pack(side=tk.LEFT, padx=10, expand=True)  # expand=True让按钮居中

# 右侧按钮
direct_button = ttk.Button(button_frame, text="我填过了，直接启动", command=launch_direct)
direct_button.pack(side=tk.RIGHT, padx=10)

# 回车绑定
root.bind('<Return>', lambda event: save_and_run())

root.mainloop()
