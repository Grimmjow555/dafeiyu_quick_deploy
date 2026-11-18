"""key.txt 的读取、校验与原子保存。

部署脚本仍然是最终权威：本模块只把 README / configure.py / upload.ps1 中已经
写明的字段规则复刻到 GUI 侧，用于表单提示和提前拦截明显错误。保存时保留原
文件的注释、空行、字段顺序、换行风格、BOM 和末尾 URL 行，避免出现意外 diff。
"""

from __future__ import annotations

import codecs
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

SERVICE_URL_RE = re.compile(r"^(AstrBot|NapCat):\s*https?://\S+$", re.IGNORECASE)
SSH_HOST_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.-]*$")
SSH_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]*[$]?$")
DOUBAO_SPEAKER_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
DOUBAO_LABEL_RE = re.compile(r"(?i)^key\s*[:：]")

QQ_PASSWORD_FILE = "QQ.txt"

REQUIRED_FOR_DEPLOY = (
    "SSH_HOST",
    "SSH_USER",
    "SSH_PASSWORD",
    "DEEPSEEK_API_KEY",
    "ASTRBOT_USERNAME",
    "ASTRBOT_PASSWORD",
)


class KeyFileError(Exception):
    """key.txt 无法读取或保存。消息中不得包含字段值。"""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    group: str
    secret: bool = False
    placeholder: str = ""
    hint: str = ""


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "SSH_HOST",
        "服务器地址",
        "服务器",
        placeholder="例如 1.2.3.4 或 example.com",
        hint="公网 IPv4 或域名，SSH 固定使用 22 端口。",
    ),
    FieldSpec(
        "SSH_USER",
        "SSH 用户",
        "服务器",
        placeholder="建议 root",
        hint="非 root 用户需要免密 sudo 权限。",
    ),
    FieldSpec(
        "SSH_PASSWORD",
        "SSH 密码",
        "服务器",
        secret=True,
        hint="只保存在本机 key.txt；界面默认隐藏，不会写入日志。",
    ),
    FieldSpec(
        "DEEPSEEK_API_KEY",
        "DeepSeek API Key",
        "模型与记忆",
        secret=True,
        hint="需要可用额度；用于机器人的主模型。",
    ),
    FieldSpec(
        "DEEPSEEK_MODEL",
        "DeepSeek 模型",
        "模型与记忆",
        placeholder="留空使用默认 deepseek-flash",
        hint="按开放平台实际提供的模型名填写。",
    ),
    FieldSpec(
        "SILICONFLOW_API_KEY",
        "硅基流动 API Key",
        "模型与记忆",
        secret=True,
        hint="可选。填写后启用 bge-m3 云端记忆；空着跳过记忆。",
    ),
    FieldSpec(
        "DOUBAO_API_KEY",
        "豆包 API Key",
        "语音",
        secret=True,
        hint="可选。填写后启用 Seed-TTS 2.0；留空则跳过语音。",
    ),
    FieldSpec(
        "DOUBAO_APP_ID",
        "豆包 App ID",
        "语音",
        hint="可选。与 API Key 同一账号时随请求发送，也可以留空。",
    ),
    FieldSpec(
        "DOUBAO_SPEAKER",
        "豆包音色 ID",
        "语音",
        placeholder="留空使用 zh_female_vv_uranus_bigtts",
        hint="Seed-TTS 2.0 音色必须以 _uranus_bigtts 结尾。",
    ),
    FieldSpec(
        "DOUBAO_ACCESS_TOKEN",
        "旧版 Access Token",
        "语音",
        secret=True,
        hint="可选。仅旧版 Seed Audio 1.0；和 App ID 同时填写才生效。",
    ),
    FieldSpec(
        "OWNER_QQ",
        "主人 QQ",
        "机器人账号",
        placeholder="可留空",
        hint="留空时不设置管理员，也不启用主动私聊。",
    ),
    FieldSpec(
        "ASTRBOT_USERNAME",
        "AstrBot 后台账号",
        "机器人账号",
        hint="用于登录 AstrBot 管理后台。",
    ),
    FieldSpec(
        "ASTRBOT_PASSWORD",
        "AstrBot 后台密码",
        "机器人账号",
        secret=True,
        hint="至少 8 位，需包含大写、小写字母和数字。",
    ),
    FieldSpec(
        "ONEBOT_TOKEN",
        "OneBot Token",
        "高级",
        secret=True,
        hint="通常留空；部署时自动生成并回填，两个容器之间使用。",
    ),
    FieldSpec(
        "NAPCAT_TOKEN",
        "NapCat Token",
        "高级",
        secret=True,
        hint="通常留空；部署完成并验证后台后自动回填。",
    ),
    FieldSpec(
        "QQ_WATCHDOG_WEBHOOK",
        "掉线通知 Webhook",
        "高级",
        secret=True,
        placeholder="可留空",
        hint="可选。地址可能包含密钥，因此默认隐藏，不要外传。",
    ),
)

FIELD_ORDER: tuple[str, ...] = tuple(spec.name for spec in FIELD_SPECS)
FIELD_BY_NAME: dict[str, FieldSpec] = {spec.name: spec for spec in FIELD_SPECS}
FIELD_GROUPS: tuple[str, ...] = tuple(dict.fromkeys(spec.group for spec in FIELD_SPECS))


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str
    severity: str = "error"

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


@dataclass
class KeyDocument:
    path: Path
    lines: list[str]
    values: dict[str, str]
    parse_errors: list[str]
    newline: str
    has_bom: bool
    trailing_newline: bool
    mtime_ns: int
    size: int
    service_urls: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.parse_errors

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default)


def _detect_newline(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    if crlf and crlf >= lf and crlf >= cr:
        return "\r\n"
    if lf:
        return "\n"
    if cr:
        return "\r"
    return "\r\n" if os.name == "nt" else "\n"


def parse_key_lines(
    lines: Iterable[str],
) -> tuple[dict[str, str], list[str], dict[str, str]]:
    """按 upload.ps1 / configure.py 的规则解析行，返回 (值, 错误, 展示 URL)。"""
    values: dict[str, str] = {}
    errors: list[str] = []
    service_urls: dict[str, str] = {}
    for index, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        url_match = SERVICE_URL_RE.fullmatch(stripped)
        if url_match:
            name = "AstrBot" if url_match.group(1).lower() == "astrbot" else "NapCat"
            service_urls[name] = stripped.split(":", 1)[1].strip()
            continue
        if "=" not in line:
            errors.append(f"第 {index} 行不是“名称=值”格式")
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name:
            errors.append(f"第 {index} 行缺少字段名")
            continue
        if name in values:
            errors.append(f"字段 {name} 重复出现")
            continue
        values[name] = value.strip()
    return values, errors, service_urls


def read_key_file(path: Path | str) -> KeyDocument:
    file_path = Path(path)
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise KeyFileError(f"无法读取 key.txt：{exc.strerror or exc}") from exc
    has_bom = raw.startswith(codecs.BOM_UTF8)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise KeyFileError("key.txt 不是有效的 UTF-8 文件，请用记事本另存为 UTF-8。") from exc
    lines = text.splitlines()
    newline = _detect_newline(text)
    trailing_newline = text.endswith(("\n", "\r"))
    values, parse_errors, service_urls = parse_key_lines(lines)
    try:
        stat = file_path.stat()
    except OSError as exc:
        raise KeyFileError(f"无法读取 key.txt 的文件信息：{exc.strerror or exc}") from exc
    return KeyDocument(
        path=file_path,
        lines=lines,
        values=values,
        parse_errors=parse_errors,
        newline=newline,
        has_bom=has_bom,
        trailing_newline=trailing_newline,
        mtime_ns=stat.st_mtime_ns,
        size=stat.st_size,
        service_urls=service_urls,
    )


def _trailing_block_start(lines: list[str]) -> int:
    """返回末尾由空行和展示 URL 行组成的块之前的插入位置。"""
    index = len(lines)
    while index > 0:
        stripped = lines[index - 1].strip()
        if not stripped or SERVICE_URL_RE.fullmatch(stripped):
            index -= 1
            continue
        break
    return index


def render_key_update(doc: KeyDocument, updates: Mapping[str, str]) -> str:
    """返回更新后的全文，不写盘。只更新给定字段，未知内容原样保留。"""
    pending = {name: str(value).strip() for name, value in updates.items()}
    lines = list(doc.lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or SERVICE_URL_RE.fullmatch(stripped):
            continue
        if "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if name in pending:
            lines[index] = f"{name}={pending.pop(name)}"
    if pending:
        ordered = [name for name in FIELD_ORDER if name in pending]
        ordered += [name for name in pending if name not in FIELD_BY_NAME]
        insert_at = _trailing_block_start(lines)
        lines[insert_at:insert_at] = [f"{name}={pending[name]}" for name in ordered]
    text = doc.newline.join(lines)
    if doc.trailing_newline or not lines:
        text += doc.newline
    return text


def write_key_file(doc: KeyDocument, updates: Mapping[str, str]) -> KeyDocument:
    """原子写回 key.txt，随后重新读取并返回新的文档。"""
    text = render_key_update(doc, updates)
    tmp_path = doc.path.with_name(doc.path.name + ".tmp")
    encoding = "utf-8-sig" if doc.has_bom else "utf-8"
    try:
        with open(tmp_path, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, doc.path)
    except OSError as exc:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        reason = exc.strerror or str(exc)
        raise KeyFileError(
            f"无法保存 key.txt：{reason}。如果文件只读，请取消只读属性后重试。"
        ) from exc
    return read_key_file(doc.path)


def validate_values(values: Mapping[str, str]) -> list[ValidationIssue]:
    """按部署脚本现有规则做 GUI 侧格式校验，不回显字段值。"""
    issues: list[ValidationIssue] = []
    for name in REQUIRED_FOR_DEPLOY:
        if not values.get(name):
            issues.append(ValidationIssue(name, f"必填字段 {name} 未填写"))
    host = values.get("SSH_HOST", "")
    if host and not SSH_HOST_RE.fullmatch(host):
        issues.append(ValidationIssue("SSH_HOST", "SSH_HOST 只能是 IP 或域名，不能包含空格、斜杠或引号"))
    user = values.get("SSH_USER", "")
    if user and not SSH_USER_RE.fullmatch(user):
        issues.append(ValidationIssue("SSH_USER", "SSH_USER 格式不正确（例如 root 或 ubuntu）"))
    password = values.get("ASTRBOT_PASSWORD", "")
    if password and (
        len(password) < 8
        or not re.search(r"[A-Z]", password)
        or not re.search(r"[a-z]", password)
        or not re.search(r"[0-9]", password)
    ):
        issues.append(ValidationIssue("ASTRBOT_PASSWORD", "至少 8 位，且包含大写字母、小写字母和数字"))
    owner = values.get("OWNER_QQ", "")
    if owner and not owner.isdigit():
        issues.append(ValidationIssue("OWNER_QQ", "OWNER_QQ 应为纯数字，或者留空"))
    doubao_key = values.get("DOUBAO_API_KEY", "")
    if DOUBAO_LABEL_RE.match(doubao_key):
        issues.append(ValidationIssue("DOUBAO_API_KEY", "只填写 API Key 本身，不要包含 key: 等标签"))
    if doubao_key and re.search(r"\s", doubao_key):
        issues.append(ValidationIssue("DOUBAO_API_KEY", "API Key 不应包含空格"))
    access_token = values.get("DOUBAO_ACCESS_TOKEN", "")
    if DOUBAO_LABEL_RE.match(access_token):
        issues.append(ValidationIssue("DOUBAO_ACCESS_TOKEN", "只填写 Token 本身，不要包含 key: 等标签"))
    speaker = values.get("DOUBAO_SPEAKER", "")
    if speaker and not DOUBAO_SPEAKER_RE.fullmatch(speaker):
        issues.append(ValidationIssue("DOUBAO_SPEAKER", "音色 ID 不能包含空格或引号"))
    return issues


def validate_document(doc: KeyDocument) -> list[ValidationIssue]:
    issues = [ValidationIssue("", message) for message in doc.parse_errors]
    issues.extend(validate_values(doc.values))
    return issues


def blocking_issues(issues: Iterable[ValidationIssue]) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.is_error]


def missing_required(values: Mapping[str, str]) -> list[str]:
    return [name for name in REQUIRED_FOR_DEPLOY if not values.get(name)]


def voice_mode(values: Mapping[str, str]) -> str:
    """返回 none / tts2 / seed_audio，表示部署时预期启用的语音模式。"""
    if values.get("DOUBAO_API_KEY"):
        return "tts2"
    if values.get("DOUBAO_APP_ID") and values.get("DOUBAO_ACCESS_TOKEN"):
        return "seed_audio"
    return "none"


def voice_configured(values: Mapping[str, str]) -> bool:
    return voice_mode(values) != "none"


def memory_configured(values: Mapping[str, str]) -> bool:
    return bool(values.get("SILICONFLOW_API_KEY"))


def service_urls(values: Mapping[str, str]) -> dict[str, str]:
    host = values.get("SSH_HOST", "").strip()
    if not host or not SSH_HOST_RE.fullmatch(host):
        return {}
    return {
        "AstrBot": f"http://{host}:6185/",
        "NapCat": f"http://{host}:6099/webui/web_login",
    }


def qq_password_file_path(root: Path | str) -> Path:
    return Path(root) / QQ_PASSWORD_FILE
