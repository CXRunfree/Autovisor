import os
import shutil
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
shutil.copyfile("./configs.ini", f"./dist/{name}/configs.ini")
shutil.copyfile("./data/mirrors.json", f"./dist/{name}/data/mirrors.json")
shutil.copyfile("./resources/stealth.min.js", f"./dist/{name}/resources/stealth.min.js")
shutil.rmtree("./build", ignore_errors=True)
os.remove("./Autovisor.spec")
