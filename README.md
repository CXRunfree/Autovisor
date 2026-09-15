##  Autovisor

**Github项目主页：**[CXRunfree/Autovisor](https://github.com/CXRunfree/Autovisor)

------
#### 2026/5/8 公告

本项目自设立以来已度过三年有余, 这期间受到了广大朋友们的喜爱与支持, 在此表示衷心的感谢~~

不过作者即将毕业, 很少使用zhs平台上课, 我想以后大概会停更吧！

但终归是有源源不断的新人步入大学生活，同样要面对繁重的网课任务，所以我希望能有人fork这个项目，让它能在未来帮助更多同学！如果你能写出下一个衍生版，可以通过邮箱联系我，我会把优秀的仓库链接置顶！

---

#### 2026/9/7 Autovisor-3.17.3 更新

**本次更新:**

- 修复了限时功能在安全验证期间未暂停计时的问题.
- 修复智慧树新版登录页兼容问题.
- 修复从非项目目录启动时无法读取 `configs.ini` 的问题.
- 限制运行环境为 Python 3.10、3.11 或 3.12.
- 更新运行时依赖下载器, 按 Python、ABI 和系统架构选择匹配的 wheel, 并避免新旧依赖混装.
- 依赖配置升级为 `pyproject.toml`.
- 镜像源移至 `data/mirrors.json`, 支持按顺序切换备用镜像.
- 重整发行版目录, 使用 `resources/`、`packages/` 和 `data/` 分类存放文件.

**近期更新:**

- 新增了对**登录Cookies过期**的自动检测, 避免直接进入播放页后白屏空转;
- 优化了首次启动浏览器与运行时依赖加载的稳定性, 减少首次运行失败的情况;
- 重构了日志系统, 并补充更详细的异常记录, 便于排查问题;
- 优化了浏览器关闭时的处理逻辑, 手动关闭浏览器时不会再频繁打印误导性的报错信息;
- 其他细节调整与代码优化, 提高整体稳定性;
- 添加了一个好看的logo.

------

#### 一、程序介绍:

**项目简介：**

这是一个可无人监督的自动化程序，基于微软的 Playwright 框架，由 Python 和 JavaScript 编写而成。核心原理是使用浏览器模拟用户操作。

**程序功能:**

- **支持自动登录**
- **自动通过滑块验证(可选)**
- **自动播放和切换下一集**
- **跳过弹窗和弹出的题目**
- **自动静音、调成指定的倍速**
- **检测视频是否暂停并续播**
- **支持刷习惯分**
- **支持智慧共享课**
- **支持翻转课**
- 检测当前学习进度并后台实时更新
- 根据当前时间自动设置背景颜色(白天/夜晚)
- 完成章节时将提示已刷课时长
- 各种自定义配置

#### 二、使用须知:

1.请确保系统为windows10及以上

2.文件夹内有 **configs.ini 文件** (可能没显示 **.ini** 后缀名)，请用文本编辑器打开;

3.填写配置文件

- 默认启动Edge浏览器；
- 文件里的 **EXE_PATH项** 用于自定义浏览器路径, 但必须精确到**浏览器可执行文件的位置**；

​    不知道浏览器的安装路径? 请看下方  **四、常见问题** 

4.根据文件内的说明填写好配置信息，一定要**保存后**再退出。

**注意: `configs.ini` 配置项不需要加引号。镜像源请编辑 `data/mirrors.json`，必须遵循 JSON 格式。**

<img src="https://i-blog.csdnimg.cn/direct/e3f06598535c4b48bc1e8a52eb2d0ef8.png"/>

5.运行 **Autovisor.exe**，会自动打开浏览器，进入网课界面后就能自动刷课了 !

(如果未设置 **enableAutoCaptcha=True**, 则需要**手动完成**登录时的滑块验证)

发行版目录说明:

- `resources/`: 图片、脚本等程序资源.
- `packages/`: 自动下载的 NumPy、OpenCV 等运行时依赖.
- `data/`: 登录 Cookies 和镜像源配置.

#### macOS 源码运行

macOS 版本使用 `uv` 管理隔离的 Python 3.13 环境，默认启动独立、可见的系统 Chrome。`run_macos.sh` 是一键部署脚本：

- **首次运行**：自动安装 `uv`（优先 Homebrew，否则官方脚本），从 `configs.macos.ini` 生成不进入 Git 的 `configs.local.ini`（权限 `0600`），根据配置安装依赖（`enableAutoCaptcha=True` 时附带 `captcha` 依赖），并在 `driver=chromium` 时下载 Playwright Chromium。
- **后续运行**：检测到环境未变化时直接启动，不再重复安装。
- 修改 `pyproject.toml`、`uv.lock` 或配置文件后会自动重新部署；也可用 `./run_macos.sh --setup` 强制重新部署。

```bash
./run_macos.sh                # 首次部署并启动
./run_macos.sh --setup        # 强制重新部署环境
```

首次部署前请编辑生成的 `configs.local.ini`，填写 `[course-url]` 课程链接（可留空账号密码，用浏览器手动登录）。若已有 Requests/CookieJar JSON，可先安全导入；导入器会丢弃其他域名、空域名和过期项，不会输出 Cookie 值：

```bash
./run_macos.sh --import-cookies /path/to/cookies.json
```

只读检查不会进入课程，也不会下载媒体或上报进度：

```bash
./run_macos.sh --check-browser
./run_macos.sh --check-course 'https://studywisdomh5.zhihuishu.com/study/index?recruitAndCourseId=...'
```

`--check-browser` 只验证 Chrome 启动和智慧树登录状态；`--check-course` 只报告页面使用的新旧目录选择器，当前智慧共享课目录会识别 `.child-info.hasvideo`、项内完成标记和 `aria-valuenow` 进度。确认识别成功后再正常启动即可。

macOS 注意事项：

- 浏览器与 CDP 均由配置文件决定，不读取环境变量：`driver = Chrome`（或 `chromium`），`EXE_PATH` 通常留空即可。
- `attachExistingChrome = False` 是稳定默认值，程序启动隔离窗口并只保存智慧树 Cookie。
- 实验性的附着模式可设为 `True`，需要先在 `chrome://inspect/#remote-debugging` 勾选允许远程调试。Chrome 150 会通过本机 `DevToolsActivePort` 动态公布端点，程序不会把瞬时 endpoint 写入配置或日志。
- `enableHideWindow = False`，课中安全验证需要保持窗口可见并手动完成。
- 自动滑块为可选功能；在 `configs.local.ini` 将 `enableAutoCaptcha` 设为 `True` 后重新运行 `./run_macos.sh`（会自动安装 `captcha` 依赖）。它只处理登录页滑块，不能绕过课中安全验证。
- 当前智慧共享课的课中弹题会暂停播放并等待手动处理；“平时测试”和期末考试不属于视频播放流程，本版本不会自动作答或提交。

------

#### 三、发行版下载:

Github: [Releases · CXRunfree/Autovisor (github.com)](https://github.com/CXRunfree/Autovisor/releases)

网盘备用: [[蓝奏云\] Autovisor-for-windows](https://wwk.lanzouj.com/b05evsxif) 密码:492l

这是已经打包好的程序, 若需要**源代码**请于Github项目主页下载.

#### 四、常见问题 :

0.为什么解压后没有Autovisor.exe / 运行报错**缺失依赖文件**?

- 可能是被杀毒软件误杀了, 考虑暂时关闭杀毒软件;

1.为什么会出现一个命令行黑框?

- 这是程序运行的后台，你可以查看当前运行的状态;

2.为什么第一次启动就失败了?

- 首次启动会检查并下载运行时依赖，请等待后台日志完成。如果下载失败，程序会自动尝试 `data/mirrors.json` 中的下一个镜像源。

3.为什么运行程序只出现后台却没出现浏览器界面？

- 加载需要时间，只要后台未异常退出就不必担心; 如果报错可能是你的浏览器安装路径有问题

4.我想自定义要启动的浏览器, 但是找不到装在哪里? 

- 打开你的浏览器, 在地址栏中输入 Chrome://version 回车之后, 如图的"可执行文件目录" 就是浏览器安装目录了。

  
  
  <img src="https://i-blog.csdnimg.cn/blog_migrate/e8fd696257e0b4623a19d4a9e0448bfd.png" alt="img">

5.关于弹题关不掉/程序卡住的问题:

- 因为弹题是时刻有可能发生的, 而弹题检测不是时刻都进行, 所以这个问题不能完全消除;
- 程序使用异步任务进行答题检测。如果页面长时间没有响应，请先确认浏览器没有被最小化。

6.我已经打赏过了,不希望再弹赞赏码怎么办?

- 感谢您对本项目的支持~ 只需要设置 `showDonateCode = False` 就好了！

------

**已知Bug:**

- **长时间挂机**有概率弹出人机验证, 程序检测到后会暂停操作，直到手动验证完成; 
- 浏览器窗口若**最小化**可能导致视频播放进度不增加;
- 若出现其他异常崩溃，请提交issue并附上报错信息。

**碎碎念:**

觉得体验还不错 ?  请留下你宝贵的Star ⭐, 并分享给更多有需要的人!

或者为项目发电支持一下 ~ 

<img src="https://i-blog.csdnimg.cn/blog_migrate/0d254d88c1cd0cb0a2fe6c50f8992efb.png" alt="img" style="zoom: 50%;" />

**作者的CSDN:** [欢迎关注~](https://blog.csdn.net/Runfreeone)

**声明：本程序只可用于学习和研究计算机原理, 请于24h删除所有存档 ! **
