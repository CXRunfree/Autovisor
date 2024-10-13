import os
import shutil
name = "Autovisor"
os.system(
    "pyinstaller "
    "--log-level=INFO "
    "--noconfirm "
    "-c "
    "-i ./res/zhs.ico "
    "--onedir "
    f"--name={name} "
    "./Autovisor.py "
    "--exclude-module cv2 "
    "--exclude-module numpy "
)
os.mkdir(f"./dist/{name}/res")
shutil.copyfile("./res/QRcode.jpg", f"./dist/{name}/res/QRcode.jpg")
shutil.copyfile("./configs.ini", f"./dist/{name}/configs.ini")
shutil.copyfile("./res/stealth.min.js", f"./dist/{name}/res/stealth.min.js")
shutil.rmtree("./build", ignore_errors=True)
os.remove("./Autovisor.spec")
