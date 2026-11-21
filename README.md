# 大肥鱼控制台：Windows 图形化部署指南

大肥鱼用于将 AstrBot、NapCat 和 QQ 部署到 Ubuntu 26.04 服务器。推荐使用本地 Windows 桌面控制台「大肥鱼控制台」，无需逐条输入 SSH 或部署命令；命令行入口仍完整保留。

![大肥鱼控制台界面预览](docs/gui-preview.png)

## 一、推荐方式：本地图形界面

图形界面运行在本机 Windows，只负责：

- 编辑并保存 `key.txt`
- 调用现有的 `upload.ps1` 完成部署或更新
- 查看容器、QQ、守护进程、语音、记忆和插件状态
- 启动、停止或预览停止服务
- 同步 NapCat / OneBot Token
- 同步可选的 QQ 密码兜底文件
- 打开后台或 SSH 终端

图形界面不会代填 QQ 密码，不读取或显示 `QQ.txt` 内容，不自动扫码，不绕过腾讯安全验证，也不会代替用户确认主机密钥变化。

### 直接运行 exe（推荐）

项目已提供生成好的单文件程序：

```text
大肥鱼控制台.exe
```

双击启动即可。它适用于 Windows 10/11 x64，不要求安装 Python 或 PyQt5，但 exe 应放在项目根目录，或者项目根目录的 `dist/` 子目录中。程序会调用同目录下的 `upload.ps1`、读取 `key.txt` 并操作服务器。

若未找到项目文件，请确认 exe 与下列文件位于正确位置：

- `upload.ps1`
- `key.txt`
- `deploy.sh`
- `configure.py`
- `dafeiyu_gui/`
- `pack/`

首次启动可能解压到系统临时目录并等待几秒。exe 未做代码签名，SmartScreen 或杀毒软件可能提示“未知发布者”；确认文件来自本项目后再运行。不要把 exe 单独复制到没有项目脚本和密钥文件的目录。

### 从源码运行

需要 Windows + Python 3.10 或更高版本：

```powershell
python -m pip install -r requirements-gui.txt
.\run_gui.bat
```

也可手动启动：

```powershell
python -m dafeiyu_gui
```

修改界面源码后重新构建 exe：

```powershell
python -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_gui_exe.ps1
```

产物仍为项目根目录中的 `大肥鱼控制台.exe`。

## 二、填写配置

首次使用时复制 `key.example.txt` 为 `key.txt`，或在图形界面的「配置」页填写并保存。建议用记事本以 UTF-8 保存。

格式为：

```text
字段名=值
```

按第一个等号读取，顺序不影响部署，不需要为 `=` 或 `#` 加转义，不要添加引号。部署成功后会在末尾写入两行后台地址，重复部署会更新而不会重复追加。

| 字段 | 用途 |
|---|---|
| `SSH_HOST` | Ubuntu 服务器公网 IPv4 或域名 |
| `SSH_USER` | 建议使用 `root`；其他账户必须具有免密 sudo |
| `SSH_PASSWORD` | SSH 登录密码，固定使用 22 端口 |
| `DEEPSEEK_API_KEY` | 必填，DeepSeek API Key |
| `DEEPSEEK_MODEL` | 可选，平台实际提供的模型 |
| `ASTRBOT_USERNAME` | 必填，AstrBot 后台账号 |
| `ASTRBOT_PASSWORD` | 必填，至少 8 位且包含大写、小写字母和数字 |
| `SILICONFLOW_API_KEY` | 可选，启用 BGE-M3 云端记忆；留空则跳过 |
| `DOUBAO_API_KEY` | 可选，启用豆包 Seed-TTS 2.0 语音 |
| `DOUBAO_APP_ID` | 可选，和 API Key 同账户的 App ID |
| `DOUBAO_SPEAKER` | 可选，必须使用 `*_uranus_bigtts` 结尾的 2.0 音色 ID |
| `DOUBAO_ACCESS_TOKEN` | 可选，旧版 Seed Audio 1.0 Access Token |
| `OWNER_QQ` | 可选，大号 QQ；留空不猜主人、不授予管理员 |
| `NAPCAT_TOKEN` | 留空，由脚本生成并回填 |
| `ONEBOT_TOKEN` | 留空，由脚本生成并回填 |
| `QQ_WATCHDOG_WEBHOOK` | 可选，QQ 状态通知 webhook；留空不发送 |

语音规则：

- 填 `DOUBAO_API_KEY`：启用 Seed-TTS 2.0，只能说话不能唱歌。
- 同时填 `DOUBAO_APP_ID` 和 `DOUBAO_ACCESS_TOKEN`：回退旧版 Seed Audio 1.0，支持唱歌。
- 两类凭证都未填写：不安装语音与唱歌插件，不调用任何第三方 TTS。

阿里云安全组入方向至少放行：

- TCP 6099：NapCat
- TCP 6185：AstrBot
- TCP 22：SSH

无需公网开放 6199。

## 三、图形界面部署流程

1. 打开「大肥鱼控制台」。
2. 进入「配置」，检查必填字段并保存 `key.txt`。
3. 在「总览」点击「一键部署 / 更新」。
4. 首次部署会下载镜像、插件和配置包，可能持续较长时间。
5. 部署结束后点击「刷新状态」。
6. 点击「NapCat 扫码登录」，用机器人小号的手机 QQ 执行扫码。
7. 腾讯要求确认时，由本人完成手机确认。
8. 使用自己的 QQ 给机器人发送一条消息，确认端到端回复。

部署完成后可直接打开：

- AstrBot：`http://服务器IP:6185/`
- NapCat：`http://服务器IP:6099/webui/web_login`

首次部署中 QQ 尚未登录属于正常待操作状态，不代表基础部署失败。

### 总览页操作

| 操作 | 实际行为 |
|---|---|
| 一键部署 / 更新 | 完整执行 `upload.ps1`；重复运行是幂等的 |
| 刷新状态（F5） | 执行 `upload.ps1 -Status`，不会自动轮询 |
| 启动服务 | 启动 AstrBot、NapCat 和 QQ 守护进程 |
| 停止服务 | 先停守护进程，再停容器，保留运行数据 |
| 同步 Token | 将服务器 NapCat / OneBot Token 合并回本机 `key.txt` |
| 同步密码兜底 | 仅同步项目目录中的 `QQ.txt` |
| SSH 终端 | 打开新的 PowerShell SSH 窗口 |
| 后台地址 | 使用系统浏览器打开 AstrBot 或 NapCat WebUI |

界面会显示服务、QQ、守护进程、语音、记忆和插件状态，并实时输出运行日志。状态不会自动轮询，避免触发 NapCat 登录接口限流。

## 四、状态含义

- `services_ready=true`：后台、配置和插件检查通过。
- 在线：QQ 已登录。
- 离线：QQ 未登录或掉线，不等于部署失败。
- 等待首次扫码：新部署尚未登录，守护进程等待用户扫码，不会循环重启。
- 等待扫码：自动恢复失败，需要人工扫码或确认。
- `api_down`：NapCat WebUI 不可访问。
- `api_error`：接口或认证异常。
- `stopped`：服务已由用户停止。
- `starting`：服务刚刚启动。
- 语音未启用：可选语音测试失败，基础部署仍可继续。
- NapCat 限流：等待一分钟后再刷新状态。

`dafeiyu-qq-watchdog.service` 每 20 秒检查一次 QQ 登录状态。若掉线，它有限次尝试快速登录、重启 NapCat 登录进程，失败后刷新二维码并等待用户扫码。自动恢复是否成功以守护进程状态文件和 journal 日志为准。

查看服务器状态：

```bash
sudo bash ~/dafeiyu/deploy.sh --check
sudo python3 ~/dafeiyu/qq_watchdog.py --status
sudo systemctl status dafeiyu-qq-watchdog
sudo journalctl -u dafeiyu-qq-watchdog -n 50
sudo cat ~/dafeiyu/state/qq-watchdog.json
```

## 五、命令行部署

不使用图形界面时，在项目目录打开 Windows PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\upload.ps1
```

脚本会读取 `key.txt`、上传文件、通过 SSH 部署服务器、回填 Token 并更新本机后台地址。固定使用端口 22 和密码登录，不要求本机安装 Python。

缺少 Windows OpenSSH Client 时，以管理员身份运行：

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

### 常用命令

```powershell
# 查看状态
.\upload.ps1 -Status

# 启动服务
.\upload.ps1 -Start

# 停止服务
.\upload.ps1 -Stop

# 预览停止，不改动任何内容
.\upload.ps1 -Stop -StopArgs '--dry-run'

# 单独同步 Token
.\upload.ps1 -SyncKey

# 单独同步 QQ.txt 密码兜底
.\upload.ps1 -SyncPassword

# 打开 SSH 终端
.\upload.ps1 -Connect
```

这些日常命令只操作现有服务，不触发上传或重新部署。完整部署仍使用不带参数的 `upload.ps1`。

部署脚本会严格校验 `.ssh\known_hosts` 中的 ED25519 主机密钥：首次保存，指纹一致时继续，指纹变化时显示旧、新 SHA256 指纹并要求手动输入 `YES`。

可在阿里云服务器控制台核对指纹：

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

## 六、服务器日常维护

服务器上的脚本位于 `~/dafeiyu`：

```bash
sudo bash ~/dafeiyu/start.sh
sudo bash ~/dafeiyu/start.sh --status
sudo bash ~/dafeiyu/start.sh --no-wait

sudo bash ~/dafeiyu/stop.sh --dry-run
sudo bash ~/dafeiyu/stop.sh
sudo bash ~/dafeiyu/stop.sh --down
sudo bash ~/dafeiyu/stop.sh --timeout 120
```

停止时先停守护进程，再停容器，以免守护进程把服务重新拉起。`stop.sh --down` 只移除容器，不删除 `data/`、`napcat/` 或 `state/`。完整重启或重新部署仍使用原脚本，不要手动删除运行目录。

## 七、可选 QQ 密码兜底

默认关闭。守护进程只使用 NapCat 已保存的登录凭证快速登录，不保存密码、不绕过验证码或新设备验证。

需要兜底时，在项目目录创建不提交的 `QQ.txt`：

```text
QQ_ACCOUNT=机器人QQ号
QQ_PASSWORD=机器人QQ密码
```

也可以使用密码 MD5：

```text
QQ_ACCOUNT=机器人QQ号
QQ_PASSWORD_MD5=32位MD5
```

限制：

- 只允许上述三个字段。
- `QQ_ACCOUNT` 必须是纯数字，并与机器人 QQ 一致。
- 部署成功后同步到 `~/dafeiyu/secret/qq-login.txt`。
- 服务器目录权限为 700，文件权限为 600。
- `QQ.txt` 不进入上传包，不打印到终端。

也可直接在服务器交互创建：

```bash
sudo python3 ~/dafeiyu/qq_watchdog.py --set-password
```

遇到验证码、新设备验证、手机确认或密码错误时，守护进程停止自动尝试并等待用户处理，不会绕过腾讯安全机制。

可选通知：在 `key.txt` 增加 `QQ_WATCHDOG_WEBHOOK=地址`。掉线、恢复、等待扫码、密码登录失败、验证要求和人工停机时会发送 JSON；地址可能包含密钥，不要公开。

## 八、安全与验收边界

- 不公开真实 `key.txt`、`QQ.txt`、Webhook 或包含日志截图。
- 不把 QQ 密码写入 `key.txt`、上传包、日志或状态文件。
- 不发送真实 QQ 消息来测试基础部署；由用户在手机端验收端到端回复。
- 守护进程有快速登录、重启和密码登录频率限制，不会无限重试。
- 已填写的语音测试失败时，保留凭证并继续基础部署；修正外部权限后重跑部署或执行 `sudo bash deploy.sh --configure` 重试。
- 容器运行或 HTTP 200 不代表 QQ 已登录成功。
- 完整部署应确认：后台可访问、配置检查通过、守护进程 active，以及 QQ 在线或明确处于等待扫码状态。

完整变更记录见 [CHANGELOG.md](CHANGELOG.md)。
