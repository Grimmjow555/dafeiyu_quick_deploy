"""测试用的临时目录和合成项目。"""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def make_scratch_dir(prefix: str = ".dafeiyu-test-") -> Path:
    """在项目目录下建一个临时目录。

    不使用 tempfile.mkdtemp：某些 Windows 沙箱会给它生成无法再写入的子目录 ACL。
    测试结束由调用方删除。
    """
    path = ROOT / (prefix + uuid.uuid4().hex[:10])
    path.mkdir()
    return path


def remove_scratch_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def sample_key_text(*, crlf: bool = True) -> str:
    lines = [
        "# 测试用合成配置，不包含真实凭证",
        "SSH_HOST=203.0.113.9",
        "SSH_USER=root",
        "SSH_PASSWORD=secret-ssh-password",
        "DEEPSEEK_API_KEY=sk-test-deepseek-secret",
        "DEEPSEEK_MODEL=deepseek-flash",
        "",
        "ASTRBOT_USERNAME=admin",
        "ASTRBOT_PASSWORD=Abcdef12",
        "OWNER_QQ=",
        "",
        "AstrBot: http://203.0.113.9:6185/",
        "NapCat:  http://203.0.113.9:6099/webui/web_login",
    ]
    newline = "\r\n" if crlf else "\n"
    return newline.join(lines) + newline


def write_sample_key(path: Path, *, crlf: bool = True, bom: bool = False) -> None:
    text = sample_key_text(crlf=crlf)
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)


def fake_upload_script() -> str:
    return (
        "param([switch]$Status,[switch]$Start,[switch]$Stop,[string[]]$StartArgs=@(),[string[]]$StopArgs=@())\n"
        "Write-Host 'NAME   SERVICE   STATUS'\n"
        "Write-Host '大肥鱼正在运行。'\n"
        "Write-Host 'QQ 掉线守护：active'\n"
        "Write-Host 'QQ 状态：在线（账号 123456）'\n"
        "Write-Host '守护进程记录：online，更新于 2026-11-18T01:00:00Z'\n"
        "Write-Host 'leaked secret-ssh-password should be hidden'\n"
        "exit 0\n"
    )
