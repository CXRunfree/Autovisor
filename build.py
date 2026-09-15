import os
import shutil
import sys
name = "Autovisor"

cmd = (
    f"pyinstaller "
    f"--log-level=INFO "
    f"--noconfirm "
    f"-c "
    f"-i ./resources/zhs.ico "
    f"--onedir "
f"--contents-directory=internal "
    f"--name={name} "
    f"./Autovisor.py "
    f"--exclude-module cv2 "
    f"--exclude-module numpy "
)
os.system(cmd)

os.mkdir(f"./dist/{name}/resources")
os.mkdir(f"./dist/{name}/data")
shutil.copyfile("./resources/QRcode.jpg", f"./dist/{name}/resources/QRcode.jpg")
shutil.copyfile("./config.ini.example", f"./dist/{name}/config.ini")
shutil.copyfile("./data/mirrors.json", f"./dist/{name}/data/mirrors.json")
shutil.copyfile("./resources/stealth.min.js", f"./dist/{name}/resources/stealth.min.js")

# 稳定 ABI (abi3) 扩展(如 opencv 的 cv2.pyd)依赖 python3.dll,
# PyInstaller 不会自动收集,必须随包提供,否则运行时报 "DLL load failed while importing cv2".
python3_dll = os.path.join(sys.base_prefix, "python3.dll")
if os.path.isfile(python3_dll):
    shutil.copyfile(python3_dll, f"./dist/{name}/internal/python3.dll")
else:
    print(f"WARNING: 未找到 {python3_dll}, 发行版可能因缺少 python3.dll 导致 cv2 加载失败!")

shutil.rmtree("./build", ignore_errors=True)
os.remove("./Autovisor.spec")
