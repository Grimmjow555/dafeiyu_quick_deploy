"""帮助页：使用顺序、状态含义和安全边界。"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


_HELP_HTML = """
<h2>使用顺序</h2>
<ol>
  <li>在「配置」页确认 key.txt 的服务器、DeepSeek、AstrBot 账号密码等字段齐全，并保存。</li>
  <li>点击「一键部署 / 更新」。首次会下载镜像和插件，可能持续十几分钟；重复运行是幂等的。</li>
  <li>部署完成后，点击「NapCat 扫码登录」，用机器人小号的手机 QQ 扫码并按腾讯提示确认。</li>
  <li>用你的 QQ 给机器人发一条消息测试回复。首次部署完成但 QQ 未登录属于正常状态。</li>
</ol>

<h2>日常操作</h2>
<ul>
  <li><b>刷新状态</b>：执行 upload.ps1 -Status；不会自动轮询，避免触发 NapCat 登录接口限流。</li>
  <li><b>启动 / 停止服务</b>：对应服务器上的 start.sh / stop.sh；停止不删除 data/、napcat/。</li>
  <li><b>同步 Token</b>：部署结束时通常已自动完成；失败时可单独重试。</li>
  <li><b>同步密码兜底</b>：仅当项目目录存在 QQ.txt 时可用；界面不读取文件内容。</li>
  <li><b>SSH 终端</b>：新开一个 PowerShell 窗口执行 upload.ps1 -Connect，适合手动运行服务器命令。</li>
</ul>

<h2>状态怎么理解</h2>
<ul>
  <li><b>在线 / 离线</b>：QQ 是否已登录。离线不等于部署失败。</li>
  <li><b>等待扫码</b>：自动恢复失败或首次部署尚未登录，请在 NapCat 后台扫码。</li>
  <li><b>等待首次扫码</b>：新部署的正常状态，守护进程不会反复重启登录。</li>
  <li><b>WebUI 不可用 / 接口错误</b>：NapCat 后台暂时访问失败；可稍后刷新，或检查服务器状态。</li>
  <li><b>语音未启用</b>：语音测试失败时部署会保留凭证并继续基础部署；修正凭证后重跑部署即可重试。</li>
  <li><b>NapCat 接口限流</b>：WebUI 登录接口每分钟最多 3 次；等待一分钟再刷新，状态可能取自守护进程记录。</li>
</ul>

<h2>安全提醒</h2>
<ul>
  <li>界面不会显示、复制或记录 key.txt 中的密码、API Key 和 Token；表单默认隐藏敏感字段。</li>
  <li>界面从不读取或显示 QQ.txt，也不会向你索要 QQ 密码；需要密码兜底时请在服务器上自行配置。</li>
  <li>SSH 主机密钥变化时，必须先在服务器控制台核对指纹，再手动输入 YES；不会自动确认。</li>
  <li>不要在群聊、录屏或截图中展示 key.txt、QQ.txt 或 Webhook 地址。</li>
  <li>阿里云安全组需要放行 TCP 6099（NapCat）和 6185（AstrBot），SSH 保留 22。</li>
</ul>

<h2>常见命令（SSH 终端内）</h2>
<pre>sudo python3 ~/dafeiyu/qq_watchdog.py --status
sudo systemctl status dafeiyu-qq-watchdog
sudo python3 ~/dafeiyu/qq_watchdog.py --set-password</pre>

<p>更多细节见项目根目录的 README.md。图形界面只是 upload.ps1 的封装，命令行方式始终可用。</p>
"""


class HelpPage(QWidget):
    open_readme_requested = pyqtSignal()
    open_project_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        title = QLabel("使用帮助")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        description = QLabel(
            "图形界面只调用现有部署脚本；它不替代命令行，也不改变服务器端的任何行为。"
        )
        description.setObjectName("PageDescription")
        description.setWordWrap(True)
        layout.addWidget(description)
        view = QTextBrowser()
        view.setObjectName("HelpView")
        view.setOpenExternalLinks(True)
        view.setHtml(_HELP_HTML)
        view.setFocusPolicy(Qt.StrongFocus)
        layout.addWidget(view, 1)
        buttons = QHBoxLayout()
        readme = QPushButton("打开 README")
        readme.clicked.connect(self.open_readme_requested)
        folder = QPushButton("打开项目目录")
        folder.clicked.connect(self.open_project_requested)
        buttons.addWidget(readme)
        buttons.addWidget(folder)
        buttons.addStretch(1)
        layout.addLayout(buttons)
