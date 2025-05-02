import os
import shutil
name = "Autovisor"

cmd = (
    f"pyinstaller "
    f"--log-level=INFO "
    f"--noconfirm "
    f"-c "
    f"-i ./res/zhs.ico "
    f"--onedir "
    f"--contents-directory=internal "
    f"--name={name} "
    f"--add-binary ./res/libiconv.dll;pyzbar "
    f"--add-binary ./res/libzbar-64.dll;pyzbar "
    f"./Autovisor.py "
    f"--exclude-module cv2 "
    f"--exclude-module numpy "
    f"--exclude-module matplotlib "
)
os.system(cmd)

os.mkdir(f"./dist/{name}/res")
open(f"./dist/{name}/第一次可能启动失败, 尝试重启即可", "w").close()
shutil.copyfile("./res/QRcode.jpg", f"./dist/{name}/res/QRcode.jpg")
shutil.copyfile("./configs.ini", f"./dist/{name}/configs.ini")
shutil.copyfile("./res/stealth.min.js", f"./dist/{name}/res/stealth.min.js")
shutil.rmtree("./build", ignore_errors=True)
os.remove("./Autovisor.spec")
