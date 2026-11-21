# 给 AI agent：使用现有脚本部署大肥鱼

## 目标与范围

将 `dafeiyu_quick_deploy` 目录部署到 `key.txt` 所指的新 Ubuntu 26.04 LTS amd64 服务器，从零安装并启动 AstrBot、NapCat，配置 DeepSeek、大肥鱼人格、插件、可选云端记忆和语音，并安装 QQ 掉线守护进程（`dafeiyu-qq-watchdog.service`）。**不要迁移旧实例，不修改 AstrBot/NapCat 核心源码，不替用户登录 QQ。** QQ 登录留在 NapCat WebUI，由用户本人扫码、处理腾讯验证。守护进程默认只使用 NapCat 已保存的登录凭证做“快速登录”和重启 NapCat 登录进程，不保存 QQ 密码、不做验证码/新设备验证/扫码自动化；快速登录失效时刷新二维码、记录状态并等待用户扫码。用户可以在服务器本地自行放置可选的密码兜底文件（见密钥约定），只有用户主动创建后才会在快速登录/重启失败时尝试密码登录；遇到腾讯要求验证码、新设备验证或手机确认时必须停止自动尝试并交用户处理，不得绕过。

所有部署逻辑已经在本目录脚本中。先读 `README.md`、`deploy.sh`、`configure.py`（有 `key.example.txt` 时一并参考），然后使用脚本；不要另写一套安装流程或改成 Windows 本地 QQ 部署。

直接维护本目录，不生成或更新发布用 ZIP 压缩包。上传脚本在系统临时目录创建的传输包仍按原流程使用和清理。

## 密钥约定

`key.txt` 是 UTF-8 的 `名称=值` 文本，按第一个等号分隔，按字段名读取，字段顺序不影响部署。忽略空行、`#` 开头的注释及末尾 `AstrBot: http://...`、`NapCat: http://...` 两行展示用 URL。值无需引号或 shell 转义。**不要 source/eval 此文件，不把密码/Token 放进 shell 参数、聊天、录屏或日志。** 读取时只报告某字段是否已提供，不打印内容。只分享 `key.example.txt`，不分享实际 `key.txt`。**QQ 密码不属于 key.txt，也不要写进上传包、ZIP 或日志**；密码兜底使用项目目录可选的 `QQ.txt`（`QQ_ACCOUNT` + `QQ_PASSWORD` 或 `QQ_PASSWORD_MD5`）：一键部署成功后由 `upload.ps1` 自动同步到服务器 `~/dafeiyu/secret/qq-login.txt`（目录 700、文件 600），`QQ.txt` 本身不进上传包、内容不显示在终端；也可用 `.\upload.ps1 -SyncPassword` 单独同步。不得把密码读入对话、命令行、日志或状态文件，不得主动索要或代填密码。账号必须与机器人 QQ 号一致，否则守护进程拒绝使用。

- SSH 只读取 `SSH_HOST/SSH_USER/SSH_PASSWORD`，固定使用默认端口 22 和密码登录，用户无需填写端口。
- `OWNER_QQ` 允许留空；此时继续部署，不猜号码，不把机器人号码当主人，也不授予任何人管理员权限，主动私聊暂不启用。
- `SILICONFLOW_API_KEY` 空着就跳过记忆。
- `DOUBAO_API_KEY` 是豆包语音控制台「API Key 管理」的 API Key，请求时放在 `X-Api-Key` 头里；填了就启用「豆包·语音合成模型 Seed-TTS 2.0」（POST `https://openspeech.bytedance.com/api/v3/tts/unidirectional`，`X-Api-Resource-Id: seed-tts-2.0`，按行返回 NDJSON 音频分片）。
- `DOUBAO_APP_ID` 可选，和 API Key 同一账号时随请求带上 `X-Api-App-Id`；`DOUBAO_SPEAKER` 可选，是 Seed-TTS 2.0 的音色 ID（默认 `zh_female_vv_uranus_bigtts`，2.0 必须用 `*_uranus_bigtts` 音色）。
- `DOUBAO_ACCESS_TOKEN`（旧版控制台）只填实际 Token，不能把原始说明中的 `key:` 标签并入凭证；只在 `DOUBAO_API_KEY` 为空时和 App ID 一起回退到旧版 Seed Audio 1.0。
- **语音启用规则：`DOUBAO_API_KEY` 非空（Seed-TTS 2.0），或 `DOUBAO_APP_ID`、`DOUBAO_ACCESS_TOKEN` 同时非空（旧版 Seed Audio 1.0），才启用语音。** 否则自动跳过，不请求补填、不安装语音/唱歌插件、不使用其他 TTS 兜底。唱歌只走旧版 Seed Audio 1.0（Seed-TTS 2.0 只能说话不能唱）；没有旧版凭证时唱歌插件会借语音提供商的 API Key 去试（同一账号通常也开通了 Seed Audio），仍失败就自己放弃，不要报成部署失败。
- `NAPCAT_TOKEN/ONEBOT_TOKEN` 初始可空，由脚本生成或读取实际配置并回填。二者用途不同，不应混用。
- `QQ_WATCHDOG_WEBHOOK` 可选，是 QQ 掉线/恢复/等待扫码/等待首次扫码/密码登录失败或需要验证/WebUI 不可用/人工停机时接收 JSON 通知的地址。该地址可能包含密钥，不要打印或放进日志；留空则不发通知。

## 执行步骤

1. 检查字段是否齐全，确认目标是新服务器。必填缺失时一次列出缺失字段；主人 QQ、记忆和语音凭证属于可选项。
2. 首选在 Windows 运行一次 `powershell -NoProfile -ExecutionPolicy Bypass -File .\upload.ps1`。它会上传到 `~/dafeiyu`，随即通过 SSH 运行部署命令，成功后自动把 Token 同步回本机；如果项目目录存在 `QQ.txt`，部署成功后还会自动同步为服务器 `secret/qq-login.txt`（600），不存在则跳过密码兜底。无需另开 Ubuntu 终端，也不要重复执行下面的手工部署步骤。脚本自动读取 SSH 密码；用户使用 `root`，或具有免密 sudo 权限的账户。它使用 Windows 自带 tar、OpenSSH 和 .NET Framework；密码通过助手的专用管道提供，不写入命令行或日志。部署完成后，日常启停可直接在本地运行 `.\upload.ps1 -Start` / `-Stop` / `-Status`（或加 `-StartArgs/-StopArgs` 传参），同样读取 `key.txt` 的 SSH 凭据且不上传文件。
3. **仅在不使用 Windows 一键入口时**，agent 可通过已有 SSH/SFTP 工具的凭证参数连接。先运行 `upload.ps1 -PrepareOnly`，按输出取得 Windows 系统临时目录中的安装包，用 SFTP 上传为 `~/dafeiyu-upload.tar.gz`，再执行下列解压命令。传输后删除本地临时安装包；它包含真实凭证。没有 SFTP 工具但运行环境已提供 Python/Paramiko 时，也可以用它传输；不要把本机必须安装 Python 变成普通用户的前提。

   ```bash
   umask 077
   mkdir -p ~/dafeiyu
   tar -xzf ~/dafeiyu-upload.tar.gz -C ~/dafeiyu
   chmod 600 ~/dafeiyu/key.txt
   rm -f ~/dafeiyu-upload.tar.gz
   ```

   SSH 主机密钥验证必须保留，使用 Windows 用户目录下标准的 `.ssh/known_hosts`，不在项目中创建或分发主机记录。Windows 入口先通过禁用凭证认证的 SSH 握手在临时目录获取 ED25519 公钥：首次保存、匹配时继续；密钥变化或仅有其他类型记录时，显示旧、新 SHA256 指纹并要求用户输入 `YES`，确认后备份 `known_hosts.old`、更新该服务器记录并继续。实际连接使用严格验证和 ED25519；探测失败、用户取消时不更改记录。自动密码助手仍只回答密码请求，不回答主机密钥确认。agent 不得自动代填 `YES`；用户可通过阿里云控制台运行 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256` 核对指纹。
4. 采用上一步手工传输方式时，在 Ubuntu 运行：

   ```bash
   cd ~/dafeiyu
   sudo bash deploy.sh
   ```

   agent 工具单次执行时间短时，可将原脚本放后台运行，日志限定在私人目录；之后读取尾部了解进度，避免因工具超时重启服务：

   ```bash
   cd ~/dafeiyu
   mkdir -p state
   chmod 700 state
   nohup sudo bash deploy.sh >state/deploy.log 2>&1 </dev/null &
   ```

5. 首次下载通常耗时较长，按 `[1/6]` 至 `[6/6]` 输出判断进度。Ubuntu 软件源使用阿里云，Docker 安装包使用南大镜像，容器镜像使用 DaoCloud 后回退官方源；签名、摘要、TLS 校验不能关闭。失败后先看实际错误，修正网络问题再重跑同一脚本。不要反复删除数据或重新创建容器来尝试 QQ 登录。
6. 提醒用户在阿里云安全组放行 TCP 6099、6185。脚本会在已启用的 UFW 上放行这两个端口，保留原有规则；云安全组需要用户或已有云工具处理。无需公网开放 6199。
7. 运行 `sudo bash deploy.sh --check`。检查两个后台可用、预期插件激活、没有加载失败、OneBot 地址/Token 一致、NapCat Token 与服务器 `key.txt` 一致，并检查 `dafeiyu-qq-watchdog.service` 是否 active、最近状态是什么。`state/verification.json` 保存检查结果，不包含密钥（新增 `qq_watchdog_active`、`qq_watchdog_status`、`voice_mode`、`voice_model` 字段）。`state/` 与 `data/`、`napcat/` 都是在服务器运行时生成的目录，不在发布包中携带历史数据。守护进程自己的状态在 `state/qq-watchdog.json`、日志在 `state/qq-watchdog.log`，也可用 `python3 qq_watchdog.py --status` 查看；不要删除这些文件，不要用循环手动重启代替它。若用户要求密码兜底，只提醒用户自己在服务器执行 `sudo python3 qq_watchdog.py --set-password`（或手动创建 600 权限的 `secret/qq-login.txt`），不要经手密码。
8. Windows 一键入口会在部署成功后自动回填 Token，并在本机 `key.txt` 末尾写入 `AstrBot: http://SSH_HOST:6185/`、`NapCat:  http://SSH_HOST:6099/webui/web_login`，其中 `SSH_HOST` 替换为实际服务器地址。服务器完成检查后也会更新其 `key.txt` 末尾的 URL；重复执行应替换旧地址，避免重复追加。手工部署或需要重新同步时，再运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\upload.ps1 -SyncKey`。用 SFTP 的 agent 可下载服务器 `key.txt` 到私人临时路径，再仅合并 `NAPCAT_TOKEN`、`ONEBOT_TOKEN` 并刷新末尾 URL；不要覆盖本机其他新编辑的字段或排列顺序。完成后校验本地值与服务器当前配置相同，只报告相同与否，不打印值。
9. 向用户给出 `http://服务器IP:6185/` 和 `http://服务器IP:6099/webui/web_login`，说明 AstrBot 登录使用已填账号密码、NapCat 使用 `key.txt` 中的 `NAPCAT_TOKEN`，并提示现在自行扫码。同时说明日常启停：本地可直接运行 `.\upload.ps1 -Start` / `-Stop` / `-Status`（自动读取 key.txt 的 SSH 凭据），对应服务器上的 `start.sh` / `stop.sh`；`-Stop` 会真正停止服务，可先用 `-StopArgs '--dry-run'` 预览。

## 验收边界

- `services_ready=true` 表示后台、配置和插件检查通过。
- `qq_watchdog_active=true` 表示掉线守护服务正在运行；`qq_watchdog_status=online` 表示 QQ 在线，`offline/degraded` 表示正在检测或恢复，`needs_qr` 表示自动恢复失败、需要用户扫码，`awaiting_login` 表示新部署尚未首次登录、等待用户扫码，`api_down` 表示 NapCat WebUI 不可访问，`api_error` 表示接口/认证错误，`stopped` 表示两个容器都已停止（视为人工停机），`starting` 表示刚启动。
- 守护进程只允许有限次快速登录/NapCat 重启（每小时有上限并有冷却）、以及可选的有限次密码登录（每 24 小时最多 3 次，密码错误暂停 24 小时），不得改成无限重试；不得绕过验证码/新设备验证/扫码确认，不得把 QQ 密码写入 key.txt、上传包、日志或状态文件。
- 用户尚未扫码时 `qq_logged_in=false` 是待用户操作状态，不是安装失败。新部署（`awaiting_login`）时不要循环重启、不要触发密码登录或自动扫描二维码；等待用户扫码即可。
- 自动恢复是否成功以 `state/qq-watchdog.json` 和 journalctl 日志为准，不要只凭“容器在运行”或 HTTP 200 判断 QQ 已恢复；也不要把“需要扫码”或“等密码验证”报告成自动恢复成功。
- NapCat WebUI 登录接口有每分钟 3 次的限制（`loginRate`）。`configure.py check`/`sync` 会在限流时等待窗口；若 `--check` 仍无法认证但守护进程状态文件可用，应降级用 `state/qq-watchdog.json` 的最近状态判断 QQ 是否在线，并在报告里标记 `napcat_auth_limited=true`、提示稍后重查，而不是把部署判为失败。重复执行部署是幂等的；最后一步写本机 `key.txt` 失败只影响 Token 回填，不应影响服务器部署结论，应提示用户用 `.\upload.ps1 -SyncKey` 重试。
- `start.sh`/`stop.sh`：start 后两个容器应为 running 且 `dafeiyu-qq-watchdog.service` 为 active；stop 后所有容器停止且守护进程 inactive。stop 必须先停守护进程，避免停机过程中被自动拉起；两个脚本都不得删除 `data/`、`napcat/`、`state/`，不得打印 Token 或密码。`stop.sh --dry-run` 必须不产生任何改动。
- 一键部署时若项目目录存在 `QQ.txt`：`upload.ps1` 必须先校验格式（仅 `QQ_ACCOUNT/QQ_PASSWORD/QQ_PASSWORD_MD5`，账号为纯数字、MD5 为 32 位），部署成功后同步为服务器 `~/dafeiyu/secret/qq-login.txt`，目录 700、文件 600，状态文件应出现 `password_fallback_configured=true`；不得把 `QQ.txt` 放进上传包，不得打印其内容。`.\upload.ps1 -SyncPassword` 只做同步、不触发部署。格式错误时应在部署前报错并提示修正或删除 `QQ.txt`。
- 本机 `upload.ps1 -Start` / `-Stop` / `-Status` 只通过 SSH 执行服务器上的 `start.sh` / `stop.sh` / `start.sh --status`，不得触发上传、部署或 Token 同步；`-Stop` 是真实停止，验证时可加 `-StopArgs '--dry-run'`。
- 不发送真实 QQ 消息来测试；需要用户在手机端发消息验收，不把 HTTP 200 或模型测试冒充 QQ 端到端成功。
- 首次完整配置会进行小额 DeepSeek/向量/已启用语音的接口测试。`--check` 不调用收费模型；成功且密钥/配置包未变时重跑会跳过重复导入与收费测试。
- 已填写的可选语音测试失败时，脚本保留凭证并关闭语音/唱歌，继续验证基础部署。必须向用户说明语音失败，不能把 `voice_enabled=false` 写成语音成功；修正外部服务权限后重跑部署会自动重试语音（失败状态不会让 apply 直接跳过），也可用 `--configure` 显式重试。
- 以后用户补填主人 QQ 或语音凭证后，重新上传 `key.txt`，运行 `sudo bash deploy.sh --configure`。它会按配置包重新应用设置，不应在用户没有要求时覆盖其 WebUI 自定义设置。
- 任何环节失败都要报告具体未完成项，不将“容器已启动”写成“完整机器人部署成功”。最终说明服务状态、两个访问地址、Token 已回填与否、待用户扫码的状态即可。

本目录的 `pack/` 是已有大肥鱼配置包的部署用子集，保留其许可证和自带插件，复用 `pack/tools/import_dafeiyu.py`。适配仅涉及部署工具：允许主人 QQ 暂空、缺少凭证时跳过可选功能、导入失败返回失败状态。第三方插件由 AstrBot 插件市场安装，表情包由资源广场下载。
