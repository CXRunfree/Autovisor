##  Autovisor

**Github项目主页：**[CXRunfree/Autovisor](https://github.com/CXRunfree/Autovisor)

------
#### 2026/9/15 公告

感谢大家三年多以来的喜爱与支持~

准备读研, 本项目佛系更新

#### 2026/9/24 Autovisor-3.18.4 更新

**本次更新:**

- 新增融合共享课支持: 自动跳过 AI 随堂练习弹窗、展开折叠目录、关闭弹窗后恢复播放, 并读取课时真实学习进度 ([#158](https://github.com/CXRunfree/Autovisor/pull/158)).

**近期更新:**

- 修复课程页卡死: 已读的"学前必读"弹窗是隐藏节点, 等它可见会一直等下去, 现在超时即跳过 ([#155](https://github.com/CXRunfree/Autovisor/pull/155)).
- 课时切换、目录识别的等待也加上超时, 异常页面不再长时间卡住.
- 支持 Python 3.13.

------
#### 一、程序介绍

**项目简介:**

这是一个可无人监督的自动化程序, 基于微软的 Playwright 框架, 由 Python 和 JavaScript 编写而成. 核心原理是使用浏览器模拟用户操作.

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

#### 二、使用须知

1. 请确保系统为 Windows 10 及以上.

2. 准备配置文件:

   - **发行版**: 文件夹内自带 **config.ini** (可能没显示 `.ini` 后缀名);
   - **源码运行**: 先将模板复制为本地配置再编辑:

   ```bash
   copy config.ini.example config.ini
   ```

3. 填写配置文件:

   - 默认启动 Edge 浏览器;
   - 文件里的 **EXE_PATH 项** 用于自定义浏览器路径, 但必须精确到**浏览器可执行文件的位置**;
   - 不知道浏览器的安装路径? 见下方 **五、常见问题**.

4. 根据文件内的说明填写好配置信息, 一定要**保存后**再退出.

   **注意: `config.ini` 配置项不需要加引号. 镜像源请编辑 `data/mirrors.json`, 必须遵循 JSON 格式.**

   <p align="left"><img src="resources/markdown/config_detail.png" width="600" alt="config.ini 配置说明"></p>

5. 运行 **Autovisor.exe**, 会自动打开浏览器, 进入网课界面后就能自动刷课了!

   (如果未设置 **enableAutoCaptcha=True**, 则需要**手动完成**登录时的滑块验证)

**发行版目录说明:**

- `resources/`: 图片、脚本等程序资源.
- `packages/`: 自动下载的 NumPy、OpenCV 等运行时依赖.
- `data/`: 登录 Cookies 和镜像源配置.

#### 三、macOS 源码运行

需要 macOS 和系统 Chrome. 先复制模板并填写配置:

```bash
cp config.macos.ini.example config.macos.ini
```

打开 `config.macos.ini`, 填入课程链接 (账号密码可留空, 用浏览器手动登录), 然后运行:

```bash
./run_macos.sh
```

首次运行会自动部署环境 (安装 `uv`、依赖和必要的浏览器), 之后直接启动. 环境或配置变化时会自动重新部署, 也可用 `./run_macos.sh --setup` 强制重建.

#### 四、发行版下载

- Github: [Releases · CXRunfree/Autovisor](https://github.com/CXRunfree/Autovisor/releases)
- 网盘备用: [蓝奏云 · Autovisor-for-windows](https://wwk.lanzouj.com/b05evsxif) 密码: 492l

这是已经打包好的程序, 若需要**源代码**请于 Github 项目主页下载.

#### 五、常见问题

其他问题见 [Issues](https://github.com/CXRunfree/Autovisor/issues).

1. 解压后没有 `Autovisor.exe` / 提示缺少依赖文件?

   - 多为杀毒软件误杀: 加入信任区后重新解压; 也请确认下载的是 Releases 里的发行包, 而不是源码.

2. 第一次启动很久没反应 / 依赖下载失败?

   - 首次会检查并下载运行时依赖 (numpy、opencv-python), 等后台日志跑完即可; 下载失败会自动换用 `data/mirrors.json` 里的下一个镜像.
   - 报 `ModuleNotFoundError` / `ImportError: numpy...` 时, 删掉 `packages/` 目录重新运行.

3. 提示「未检测到有效网址」/ 一直等待登录完成?

   - `[course-url]` 要填**课程播放页**的地址 (能直接看到课时的页面), 不要填课程首页.
   - 登录页改版导致的等待已在最新版修复, 请先升级到最新发行版.

4. 登录时还是要手动过滑块?

   - 只有 `enableAutoCaptcha = True` 才会自动过滑块, 否则需要手动完成.

5. 只出现命令行黑框, 没有浏览器界面?

   - 黑框是程序后台, 可以查看运行状态; 浏览器加载需要时间, 后台没异常退出就不必担心. 报错通常是浏览器路径配置有误.
   - 找浏览器路径: 打开浏览器, 地址栏输入 `chrome://version`, 其中的"可执行文件目录"就是.

   <p align="left"><img src="resources/markdown/broswer_version.png" width="720" alt="Chrome 可执行文件目录"></p>

6. 看不到浏览器窗口 / 想后台刷课 / 报 `MoveWindow 无效的窗口句柄`?

   - 最小化会让浏览器暂停渲染, 进度不增加, 也会影响弹题检测. 想后台刷课请用 `enableHideWindow = True`, 程序会把窗口移出屏幕.
   - 若报窗口句柄错误, 改回 `enableHideWindow = False`.

7. 卡在加载播放页 / 不会自动跳下一课 / 新版页面刷不了课?

   - 这类基本都是**页面结构还没适配**, 不是配置问题. 目前支持: 智慧共享课、翻转课、融合共享课.
   - 智慧树新版「AI 课程」(带 AI 角标的课程) 尚未适配, 表现就是识别不到课时、停在加载中或单个视频无限循环; 需要等待适配, 欢迎附上课程链接和日志提 issue.

8. 弹题关不掉 / 程序卡住?

   - 弹题随时可能出现, 而检测不是实时的, 所以无法完全消除; 页面长时间无响应时, 先确认浏览器没有被最小化.

9. 遇到 PPT、PDF 等没有视频的章节会卡住?

   - 目前只处理视频课时, 非视频章节需要手动切到有视频的课时.

10. 不想再弹赞赏码?

    - 感谢您对本项目的支持~ 只需要设置 `showDonateCode = False` 就好了!

------
#### 已知问题

- **长时间挂机**有概率弹出人机验证, 程序检测到后会暂停操作, 直到手动验证完成;
- 浏览器窗口若**最小化**可能导致视频播放进度不增加;
- 若出现其他异常崩溃, 请提交 issue 并附上报错信息.

#### 写在最后

觉得体验还不错? 请留下你宝贵的 Star ⭐, 并分享给更多有需要的人!

或者为项目发电支持一下~

<p align="left"><img src="resources/markdown/donate.png" width="200" alt="赞赏码"></p>

**作者的 CSDN:** [欢迎关注~](https://blog.csdn.net/Runfreeone)

**声明：本程序只可用于学习和研究计算机原理, 请于 24h 内删除所有存档！**
