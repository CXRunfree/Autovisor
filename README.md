# Autovisor · 大模型答题增强版

**基于 [CXRunfree/Autovisor](https://github.com/CXRunfree/Autovisor) v3.18.4 的个人增强版**
**本版维护：** tianjiannb ｜ **本版仓库：** `<在这里填入你的仓库地址>`

在原版"全自动挂机刷课"的基础上，这个版本补齐了三件事：**弹题不用再瞎蒙**（接入 DeepSeek 大模型作答）、**账号密码只输一次**（首次运行引导输入并自动保存，之后全自动登录）、**登录状态更抗丢**（运行中定期落盘 Cookies，崩溃断电也不怕）。

------

## 一、本版增强功能

### 1. DeepSeek 大模型自动答题（可选）

配置 `data/llm.json` 后，程序会用大模型作答，覆盖三类场景：

| 场景 | 原版行为 | 本版行为（配置 API 后） |
|---|---|---|
| 旧版共享课课中弹题 | 随机选一个 | 大模型作答 |
| 新版共享课弹题页 (studywisdomh5) | 无法处理 | 大模型尽力作答，失败回退手动 |
| 融合共享课 AI 随堂练习弹窗 | 固定选第一个 | 大模型作答 |
| **自动弹出的测验/考试页面**（新标签页） | 无处理 | **自动捕获，逐题作答整张卷子** |

测验页面的作答流程：自动抽取全部题目 → 与页面已选状态比对 → 只点未作答的题 → 翻页直到答完。

- `auto_submit = false`（默认）：全部答完但**不交卷**，留给你人工核对后手动提交；
- `auto_submit = true`：交卷前刷新页面回到第一题，**整卷复核一遍后再自动提交**；
- 同一个测验页面 10 分钟内不会重复作答；
- 未配置 API Key 时**完全保持原版行为**，不报错、不弹窗；
- API 请求失败或答案匹配不上选项时，自动回退原默认行为，绝不中断刷课。

### 2. 全自动账号密码登录

- `config.ini` 里填了账号密码：打开登录页自动填写、自动勾选协议、自动提交，配合自动过滑块做到全程无感；
- 账号密码**留空**：首次运行时会在命令行窗口引导输入一次（密码不回显），并自动保存回 `config.ini`，之后每次启动都是全自动登录；
- 已适配智慧树新版登录页（login.zhihuishu.com），新老页面都能自动填写；
- 登录没成功时，日志会输出页面上的具体错误提示（如密码错误、连续失败锁定），方便排查。

### 3. 登录 Cookies 更可靠的保存

- **运行中每 5 分钟自动续存**一次 Cookies（有变化才写盘）：以前只在登录和退出时保存，服务器中途续期的凭证会随崩溃/断电丢失，现在不会了；
- 按 `*.zhihuishu.com` 域名筛选保存，不再依赖固定的子域列表，新子域也能覆盖；
- 加载时自动过滤已过期的 Cookies；文件损坏时记日志后自动重新登录，不会崩溃；
- 磁盘写入采用"临时文件 + 原子替换"，写一半断电也不会留下坏文件。

### 4. 保留的原版功能

- 自动过登录滑块验证（可选，需 `enableAutoCaptcha = True`）
- 自动播放、自动切换下一集、自动检测暂停并续播
- 自动跳过弹窗和课中弹题
- 自动静音、指定倍速（0.5–1.8）
- 支持智慧共享课、翻转课、融合共享课；支持刷习惯分
- 支持隐藏窗口后台刷课
- 启动时自动检查更新，后台实时上报学习进度
- macOS 支持源码运行（`./run_macos.sh`）

------

## 二、快速开始（Windows 源码运行）

环境要求：Windows 10+，Python 3.10–3.13，系统已装 Edge 或 Chrome 浏览器（程序直接调用系统浏览器，**无需** `playwright install` 下载浏览器）。

```bat
:: 1. 创建虚拟环境并安装依赖（含滑块验证所需 numpy/opencv）
python -m venv .venv
.venv\Scripts\pip install -e ".[captcha]"

:: 2. 直接启动: 缺失的 config.ini 和 data/llm.json 会自动生成默认模板
::    (双击 run-autovisor-llm.bat 也可以)
.venv\Scripts\python.exe Autovisor.py

:: 3. 按 提示/注释 编辑 config.ini 填写课程链接, 再次运行即可
```

首次启动流程：程序自动生成配置文件 → 在 `config.ini` 里填课程链接后重启 → 命令行输入一次账号密码（自动保存，以后不再问）→ 自动登录开始刷课。

**常用命令行参数：**

| 参数 | 作用 |
|---|---|
| `--config 路径` | 指定配置文件（默认用程序目录下的 `config.ini`） |
| `--check-browser` | 只检查浏览器启动和登录状态，不刷课 |
| `--check-course URL` | 阻止进度上报和播放，只检查课程目录选择器是否适配 |
| `--import-cookies PATH` | 从 Requests CookieJar 格式的 JSON 安全导入未过期 Cookie |

macOS：复制 `config.macos.ini.example` 为 `config.macos.ini` 填好课程链接后，运行 `./run_macos.sh`，首次运行会自动部署环境。

------

## 三、配置说明

### config.ini

> 缺失时首次运行自动生成默认模板（macOS 生成 `config.macos.ini`），也可以从 `config.ini.example` 手动复制。已存在的文件**永远不会被程序覆盖**。

```ini
[user-account]
username =          ; 账号(手机号), 留空则首次运行时在终端引导输入并自动保存
password =          ; 密码, 同上

[browser-option]
driver = Edge       ; 浏览器: Edge 或 Chrome
EXE_PATH =          ; 浏览器可执行文件路径, 不填用系统默认

[script-option]
enableAutoCaptcha = True    ; 自动过登录滑块(需要 numpy/opencv 依赖)
enableHideWindow = False    ; 隐藏浏览器窗口后台刷课(勿最小化, 用此项)
showDonateCode = True       ; 展示原版赞赏码(个人版可设为 False)

[course-option]
limitMaxTime = 30   ; 每门课程学习时限/分钟, 0 = 不限制
limitSpeed = 1.0    ; 播放倍速, 上限 1.8
soundOff = True     ; 静音播放

[course-url]
URL1 = https://...  ; 必须是能直接看到课程视频的"播放页"地址, 不是课程首页
URLn =              ; 可继续添加多个
```

> 配置项不需要加引号；找浏览器路径：浏览器地址栏输入 `chrome://version`，其中"可执行文件目录"就是。

### data/llm.json（大模型答题）

```json
{
  "api_key": "在 https://platform.deepseek.com 申请",
  "api_base": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "auto_submit": false
}
```

| 字段 | 说明 |
|---|---|
| `api_key` | **留空 = 完全关闭大模型答题**，程序按原版行为运行。Key 只存在本地，不上传任何服务器 |
| `api_base` | 兼容 OpenAI 接口格式，可换成其他兼容服务 |
| `model` | 默认 `deepseek-chat`，可换 `deepseek-reasoner` 等 |
| `auto_submit` | `false`：测验页只作答不交卷，人工核对后提交；`true`：复核整卷后自动交卷 |

费用参考：弹题请求很短，整个挂机周期的调用量很小，按 DeepSeek 官方价格计费，一般可忽略不计。

------

## 四、常见问题

1. **解压/克隆后启动报缺少依赖文件？**
   源码运行请先完成"快速开始"的依赖安装；打包版多为杀毒软件误杀，加入信任区后重新解压。

2. **第一次启动很久没反应 / 依赖下载失败？**
   首次会检查并下载运行时依赖（numpy、opencv-python），失败会自动换用 `data/mirrors.json` 里的下一个镜像。报 `ModuleNotFoundError: numpy` 时删掉 `packages/` 目录重跑。

3. **提示"未检测到有效网址"？**
   `[course-url]` 要填**课程播放页**地址（能直接看到课程视频的页面），不要填课程首页或个人中心。

4. **登录时还是要手动过滑块？**
   只有 `enableAutoCaptcha = True` 才会自动过滑块。账号密码已配置但仍停在登录页时，看日志里的"登录未完成, 页面提示: xxx"。

5. **只出现命令行窗口，没有浏览器界面？**
   命令行是程序后台，浏览器加载需要时间。报错通常是 `EXE_PATH` 配置有误。

6. **看不到浏览器窗口 / 想后台刷课？**
   最小化会导致视频进度不增加、弹题检测失效。后台刷课请用 `enableHideWindow = True`。

7. **卡在加载播放页 / 识别不到课时？**
   智慧树新版 **AI 课程**（带 AI 角标）尚未适配。目前支持智慧共享课、翻转课、融合共享课。

8. **配置了 API Key 但弹题还是乱选 / 测验页没反应？**
   依次检查：`data/llm.json` 是否和 `Autovisor.py` 在同一运行目录；`api_key` 是否非空；`.venv` 里是否装了 `requests`（`pip install requests`）。启动日志里"测验页面捕获"一栏会显示当前状态。

9. **大模型会答错吗？交卷要慎重吗？**
   会。大模型是尽力作答，专业性强或题库冷门的题可能出错。建议保持 `auto_submit = false`，答完后人工核对再交卷。

10. **遇到 PPT、PDF 等没有视频的章节会卡住？**
    目前只处理视频课时，非视频章节需要手动切到有视频的课时。

11. **不想再弹赞赏码？**
    设置 `showDonateCode = False`。

------

## 五、已知问题

- 长时间挂机有概率弹出人机验证，程序检测到后会暂停操作，需要手动完成验证；
- 浏览器窗口**最小化**可能导致视频播放进度不增加，请用 `enableHideWindow` 代替最小化；
- 大模型作答依赖页面结构，平台改版可能导致个别题型回退为默认行为。

------

## 六、声明与致谢

- 本项目基于 [CXRunfree/Autovisor](https://github.com/CXRunfree/Autovisor)（MIT License）修改，感谢原作者三年多的维护；
- 大模型答题功能使用了 [DeepSeek 开放平台](https://platform.deepseek.com) 的 API 服务；
- **声明：本程序只可用于学习和研究计算机原理，请于 24h 内删除所有存档！使用本程序产生的一切后果由使用者自行承担。**
- **隐私：** 所有个人配置与凭证（`config.ini`、`config.macos.ini`、`data/llm.json`、`data/cookies.json`）均在 `.gitignore` 中显式排除，不会被提交或上传；API Key 和登录 Cookies 只保存在本地。
