#!/usr/bin/env python3
"""NapCat QQ 掉线守护进程：检测 QQ 是否被踢下线，并尝试自动恢复登录。

工作方式
========

* 每 20 秒通过 NapCat 本机 WebUI API（默认 http://127.0.0.1:6099）读取
  ``/api/QQLogin/CheckLoginStatus``，判断 QQ 是否在线。
* 新部署尚未首次登录时只等待用户扫码，不会自动重启登录服务。
* 连续离线超过宽限期后，按顺序尝试恢复，每一步都有等待时间和频率上限：

  1. ``/api/QQLogin/SetQuickLogin``：使用 NapCat 本地保存的登录凭证触发
     “快速登录”（与 WebUI 上的快速登录按钮相同，不需要 QQ 密码）。
  2. 可选（默认关闭）：服务器本地密码文件存在时，调用
     ``/api/QQLogin/PasswordLogin`` 尝试密码登录。密码只从
     ``secret/qq-login.txt``（建议 600 权限、仅服务器本地、不进入 key.txt
     或上传包）读取，用于快速登录失效时兜底；遇到验证码/新设备验证立即
     停止并等待人工处理，每 24 小时最多尝试 3 次，密码错误后暂停 24 小时。
  3. ``/api/QQLogin/RestartNapCat``：让 NapCat 重建 QQ 登录服务，启动时按
     已配置的 ``autoLoginAccount`` 再尝试一次快速登录。
  4. 都失败时刷新登录二维码，把状态写入 ``state/qq-watchdog.json``，并在
     配置了 ``QQ_WATCHDOG_WEBHOOK`` 时发出通知，等待用户本人扫码。

安全边界
========

* 不把 QQ 密码写入日志、状态文件、命令行参数或 key.txt；密码文件权限过宽
  （组/其他可读）时拒绝使用。
* 不绕过验证码、新设备验证或扫码确认：腾讯要求人工验证时只记录并通知。
* 不会把 WebUI Token、二维码 URL、密码或 webhook 地址写入日志。
* 恢复动作有每小时/每日上限和冷却时间，避免与“另一台终端登录”互相踢号。

用法::

    python3 qq_watchdog.py                     # 前台运行（systemd 服务使用）
    python3 qq_watchdog.py --status            # 打印当前 QQ / WebUI / 守护进程状态
    python3 qq_watchdog.py --once              # 只检查一轮，便于排查
    python3 qq_watchdog.py --dry-run --once    # 只检查不执行恢复动作
    python3 qq_watchdog.py --set-password      # 交互写入服务器本地 QQ 密码文件（可选）
    python3 qq_watchdog.py --clear-password    # 删除密码文件，关闭密码兜底
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:  # 部署目标为 Ubuntu；Windows 上仅用于本地调试。
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

SERVICE_VERSION = "1.1.0"
SERVICE_URL_LINE = re.compile(r"(?:AstrBot|NapCat):\s*https?://\S+", re.IGNORECASE)
STATE_SCHEMA = 1
PASSWORD_FILE_KEYS = frozenset(("QQ_ACCOUNT", "QQ_PASSWORD", "QQ_PASSWORD_MD5"))

EXIT_OK = 0
EXIT_OFFLINE = 2
EXIT_API_DOWN = 3
EXIT_BUSY = 4


def utc_iso(timestamp: float | None = None) -> str:
    moment = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def human_seconds(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {rest} 秒" if rest else f"{minutes} 分钟"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分钟"


def read_key_values(path: Path) -> dict:
    """Read the project's key.txt without sourcing/eval and without logging values."""
    result: dict = {}
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return result
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or SERVICE_URL_LINE.fullmatch(stripped):
            continue
        name, separator, value = line.partition("=")
        if separator and name.strip():
            result[name.strip()] = value.strip()
    return result


def read_password_values(path: Path) -> dict:
    """Read the optional server-side QQ fallback password file.

    The file lives only on the server (recommended 600/-root), never in key.txt
    or the upload bundle. Values are used only to compute the login hash and are
    never logged or persisted.
    """
    result = {}
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return result
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if separator and name.strip().upper() in PASSWORD_FILE_KEYS:
            result[name.strip().upper()] = value.strip()
    return result


class ApiError(Exception):
    """NapCat WebUI answered but the request failed."""


class ApiUnauthorized(ApiError):
    """NapCat WebUI session expired; re-authenticate and retry."""


class ApiUnavailable(ApiError):
    """NapCat WebUI is unreachable or rate limiting us."""


class ConfigError(Exception):
    """webui.json is missing or malformed."""


class NapCatAPI:
    """Small client for the local NapCat WebUI HTTP API."""

    def __init__(self, webui_config: Path, base_url: str | None = None):
        self.webui_config = webui_config
        self.base_url_override = (base_url or "").rstrip("/") or None
        self.base_url: str | None = None
        self.credential: str | None = None
        self.last_auth_attempt: float | None = None
        self.auth_failures = 0

    def reset(self) -> None:
        self.credential = None

    # -- low level -----------------------------------------------------

    def _load_endpoint(self) -> tuple[str, str]:
        if self.base_url_override:
            endpoint = self.base_url_override
        else:
            try:
                config = json.loads(self.webui_config.read_text(encoding="utf-8"))
            except OSError as error:
                raise ConfigError(f"无法读取 NapCat 配置 {self.webui_config.name}：{error.strerror or error}") from None
            except ValueError:
                raise ConfigError(f"NapCat 配置 {self.webui_config.name} 不是有效 JSON") from None
            port = config.get("port") or 6099
            try:
                port = int(port)
            except (TypeError, ValueError):
                raise ConfigError("NapCat WebUI 端口配置无效") from None
            endpoint = f"http://127.0.0.1:{port}"
        try:
            config = json.loads(self.webui_config.read_text(encoding="utf-8"))
            token = str(config.get("token") or "").strip()
        except OSError as error:
            raise ConfigError(f"无法读取 NapCat 配置 {self.webui_config.name}：{error.strerror or error}") from None
        except ValueError:
            raise ConfigError(f"NapCat 配置 {self.webui_config.name} 不是有效 JSON") from None
        if not token:
            raise ConfigError("NapCat 配置缺少 WebUI Token")
        return endpoint, token

    def _post(self, url: str, payload: dict, credential: str | None = None, timeout: float = 15.0) -> dict:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise ApiUnauthorized("WebUI 会话已失效") from None
            if error.code == 429:
                raise ApiUnavailable("WebUI 认证或请求过于频繁") from None
            raise ApiError(f"WebUI 返回 HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise ApiUnavailable(f"连接失败（{reason}）") from None
        try:
            result = json.loads(raw)
        except ValueError:
            raise ApiError("NapCat WebUI 返回了非 JSON 内容") from None
        if not isinstance(result, dict):
            raise ApiError("NapCat WebUI 返回格式异常")
        if result.get("code") != 0:
            message = str(result.get("message") or "未知错误")
            if message.strip().lower() == "unauthorized":
                raise ApiUnauthorized("WebUI 会话已失效")
            raise ApiError(message)
        return result

    # -- public --------------------------------------------------------

    def authenticate(self) -> None:
        now = time.monotonic()
        if self.last_auth_attempt is not None and now - self.last_auth_attempt < 20:
            raise ApiUnavailable("WebUI 认证过于频繁，稍后重试")
        self.last_auth_attempt = now
        endpoint, token = self._load_endpoint()
        digest = hashlib.sha256((token + ".napcat").encode("utf-8")).hexdigest()
        result = self._post(endpoint + "/api/auth/login", {"hash": digest}, timeout=20.0)
        credential = (result.get("data") or {}).get("Credential")
        if not credential:
            raise ApiError("NapCat WebUI 认证未返回 Credential")
        self.base_url = endpoint
        self.credential = str(credential)
        self.auth_failures = 0

    def call(self, path: str, payload: dict | None = None) -> object:
        payload = {} if payload is None else payload
        if not self.credential or not self.base_url:
            self.authenticate()
        url = self.base_url + "/api/" + path.lstrip("/")
        try:
            result = self._post(url, payload, self.credential)
        except ApiUnauthorized:
            self.authenticate()
            result = self._post(url, payload, self.credential)
        return result.get("data")


class Watchdog:
    def __init__(self, opts: argparse.Namespace, api: NapCatAPI | None = None):
        self.opts = opts
        self.api = api or NapCatAPI(opts.webui_config, opts.base_url)
        self.stop = False
        self.state = "starting"
        self.message = "守护进程启动中"
        self.episode: dict | None = None
        self.last_status: dict = {}
        self.last_status_wall: float | None = None
        self.last_known_uin = ""
        self.last_uin_refresh = 0.0
        self.auto_login_checked = False
        self.ever_online = False
        self.last_online_wall: float | None = None
        self.api_down_since: float | None = None
        self.api_down_reason = ""
        self.api_down_notified = False
        self.stopped_notified = False
        self.next_api_action = 0.0
        self.quick_attempts: list = []
        self.restarts: list = []
        self.password_attempts: list = []
        self.password_cooldown_until: float | None = None
        self.password_failure_mtime: float | None = None
        self._logged: dict[str, float] = {}
        self._last_state_payload: str | None = None
        self._exit_code = EXIT_OK
        self._restore_persisted_state()

    def _restore_persisted_state(self) -> None:
        """Recover ever_online/uin/hourly attempt windows from the previous run."""
        try:
            data = json.loads(self.opts.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        if data.get("ever_online") or data.get("last_online_at"):
            self.ever_online = True
        uin = str(data.get("qq_uin") or "").strip()
        if uin.isdigit():
            self.last_known_uin = uin
        now_wall = time.time()
        now_mono = time.monotonic()
        for key, target in (("quick_login_attempt_epochs", self.quick_attempts),
                            ("restart_attempt_epochs", self.restarts),
                            ("password_attempt_epochs", self.password_attempts)):
            epochs = data.get(key)
            if not isinstance(epochs, list):
                continue
            for stamp in epochs:
                if isinstance(stamp, (int, float)):
                    age = now_wall - float(stamp)
                    limit = 86400 if key == "password_attempt_epochs" else 3600
                    if 0 <= age < limit:
                        target.append(now_mono - age)
        cooldown = data.get("password_cooldown_until_epoch")
        if isinstance(cooldown, (int, float)) and float(cooldown) > now_wall:
            self.password_cooldown_until = float(cooldown)
        failure_mtime = data.get("password_failure_file_mtime")
        if isinstance(failure_mtime, (int, float)):
            self.password_failure_mtime = float(failure_mtime)

    # -- logging -------------------------------------------------------

    def _log(self, message: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        print(line, flush=True)
        try:
            self.opts.log_file.parent.mkdir(parents=True, exist_ok=True)
            if self.opts.log_file.exists() and self.opts.log_file.stat().st_size > 2_000_000:
                backup = self.opts.log_file.with_name(self.opts.log_file.name + ".1")
                os.replace(self.opts.log_file, backup)
            with open(self.opts.log_file, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass

    def _log_throttled(self, message: str, interval: float = 300.0) -> None:
        now = time.monotonic()
        last = self._logged.get(message)
        if last is not None and now - last < interval:
            return
        self._logged[message] = now
        self._log(message)

    # -- notifications -------------------------------------------------

    def _notify(self, event: str, message: str) -> None:
        url = self.opts.webhook_url
        if not url:
            return
        payload = {
            "event": event,
            "status": self.state,
            "message": message,
            "qq_uin": self.last_known_uin,
            "time": utc_iso(),
            "source": "dafeiyu-qq-watchdog",
        }
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                response.read(1024)
            self._log(f"已发送掉线通知（{event}）")
        except Exception as error:  # notification must never break the watchdog
            self._log(f"掉线通知发送失败（{event}）：{type(error).__name__}")

    # -- state file ----------------------------------------------------

    def _wall_epochs(self, stamps: list) -> list:
        now_mono = time.monotonic()
        now_wall = time.time()
        return [round(now_wall - (now_mono - stamp), 3) for stamp in stamps]

    def _build_state(self) -> dict:
        now = time.monotonic()
        now_wall = time.time()
        retry_at = None
        if self.episode and self.episode.get("deadline") is not None:
            deadline = self.episode["deadline"]
            if deadline != float("inf"):
                retry_at = now_wall + max(0.0, deadline - now)
        payload = {
            "schema": STATE_SCHEMA,
            "service": "qq-watchdog",
            "service_version": SERVICE_VERSION,
            "updated_at": utc_iso(),
            "status": self.state,
            "message": self.message,
            "qq_uin": self.last_known_uin,
            "ever_online": self.ever_online,
            "login_phase": str(self.last_status.get("loginPhase") or ""),
            "login_error": str(self.last_status.get("loginError") or "")[:200],
            "last_online_at": utc_iso(self.last_online_wall) if self.last_online_wall else None,
            "offline_since": utc_iso(self.episode["started_wall"]) if self.episode else None,
            "next_retry_at": utc_iso(retry_at) if retry_at else None,
            "quick_login_attempts_last_hour": len(self.quick_attempts),
            "restart_attempts_last_hour": len(self.restarts),
            "quick_login_attempt_epochs": self._wall_epochs(self.quick_attempts),
            "restart_attempt_epochs": self._wall_epochs(self.restarts),
            "password_fallback_configured": self.opts.password_file.exists(),
            "password_login_attempts_last_day": len(self.password_attempts),
            "password_login_attempt_epochs": self._wall_epochs(self.password_attempts),
            "password_cooldown_until_epoch": self.password_cooldown_until,
            "password_failure_file_mtime": self.password_failure_mtime,
            "recovery_stage": self.episode.get("stage") if self.episode else None,
            "api_reachable": self.api_down_since is None,
            "last_api_ok_at": utc_iso(self.last_status_wall) if self.last_status_wall else None,
        }
        return payload

    def _write_state(self, force: bool = False) -> None:
        payload = self._build_state()
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        if not force and encoded == self._last_state_payload:
            return
        try:
            self.opts.state_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.opts.state_file.with_name(self.opts.state_file.name + ".tmp")
            temporary.write_text(encoded + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.opts.state_file)
            self._last_state_payload = encoded
        except OSError as error:
            self._log_throttled(f"写入状态文件失败：{error}", 300)

    # -- rate limits ---------------------------------------------------

    def _prune_windows(self, now: float) -> None:
        self.quick_attempts = [stamp for stamp in self.quick_attempts if now - stamp < 3600]
        self.restarts = [stamp for stamp in self.restarts if now - stamp < 3600]

    def _allow_quick(self, now: float) -> bool:
        self._prune_windows(now)
        return len(self.quick_attempts) < self.opts.max_quick_per_hour

    def _allow_restart(self, now: float) -> bool:
        self._prune_windows(now)
        if len(self.restarts) >= self.opts.max_restart_per_hour:
            return False
        if self.restarts and now - self.restarts[-1] < self.opts.min_restart_gap:
            return False
        return True

    # -- NapCat helpers -------------------------------------------------

    def _refresh_uin(self, now: float) -> None:
        if self.last_known_uin and now - self.last_uin_refresh < 600:
            return
        try:
            info = self.api.call("QQLogin/GetQQLoginInfo")
        except ApiError:
            return
        if isinstance(info, dict):
            uin = str(info.get("uin") or "").strip()
            if uin.isdigit():
                self.last_known_uin = uin
                self.last_uin_refresh = now

    def _get_uin(self) -> str:
        if self.last_known_uin:
            return self.last_known_uin
        try:
            quick = self.api.call("QQLogin/GetQuickLoginQQ")
        except ApiError:
            quick = ""
        if isinstance(quick, str) and quick.strip().isdigit():
            self.last_known_uin = quick.strip()
            return self.last_known_uin
        try:
            info = self.api.call("QQLogin/GetQQLoginInfo")
        except ApiError:
            info = None
        if isinstance(info, dict):
            uin = str(info.get("uin") or "").strip()
            if uin.isdigit():
                self.last_known_uin = uin
        return self.last_known_uin

    def _ensure_auto_login_config(self) -> None:
        """Persist the last known QQ number as autoLoginAccount when it is empty."""
        if self.auto_login_checked:
            return
        try:
            configured = self.api.call("QQLogin/GetQuickLoginQQ")
        except ApiError:
            return
        if isinstance(configured, str) and configured.strip().isdigit():
            self.auto_login_checked = True
            return
        uin = self._get_uin()
        if not uin:
            return
        self.auto_login_checked = True
        try:
            self.api.call("QQLogin/SetQuickLoginQQ", {"uin": uin})
            self._log(f"已把 QQ {uin} 写入 NapCat 自动登录账号，下次启动可尝试快速登录")
        except ApiError as error:
            self._log(f"写入自动登录账号失败：{error}")

    def _webui_hint(self) -> str:
        host = self.opts.ssh_host
        if host:
            return f"；请打开 NapCat WebUI 扫码：http://{host}:6099/webui/web_login"
        return "；请打开 NapCat WebUI 扫码"

    # -- optional password fallback ------------------------------------

    def _load_password_config(self) -> dict | None:
        """Load the optional server-side QQ password file (never from key.txt)."""
        path = self.opts.password_file
        try:
            info = path.stat()
        except OSError:
            return None
        if os.name != "nt" and info.st_mode & 0o077:
            self._log_throttled(f"QQ 密码文件权限过宽（{path} 需要 chmod 600），已拒绝使用", 3600)
            return None
        values = read_password_values(path)
        password = values.get("QQ_PASSWORD") or ""
        digest = (values.get("QQ_PASSWORD_MD5") or "").lower()
        if digest and re.fullmatch(r"[a-f0-9]{32}", digest) is None:
            self._log_throttled("QQ 密码文件中的 QQ_PASSWORD_MD5 格式无效，已忽略", 3600)
            return None
        if not password and not digest:
            self._log_throttled("QQ 密码文件缺少 QQ_PASSWORD 或 QQ_PASSWORD_MD5，已忽略", 3600)
            return None
        account = (values.get("QQ_ACCOUNT") or "").strip()
        if account and not account.isdigit():
            account = ""
        return {"account": account, "password": password, "md5": digest, "mtime": info.st_mtime}

    def _password_hash(self, config: dict) -> str:
        if config.get("md5"):
            return config["md5"]
        return hashlib.md5(config["password"].encode("utf-8")).hexdigest()

    def _prune_password_attempts(self, now: float) -> None:
        self.password_attempts = [stamp for stamp in self.password_attempts if now - stamp < 86400]

    def _password_cooldown_remaining(self, config: dict) -> float:
        if self.password_cooldown_until is None:
            return 0.0
        if self.password_failure_mtime is not None and config.get("mtime") != self.password_failure_mtime:
            self.password_cooldown_until = None
            self.password_failure_mtime = None
            self._log("QQ 密码文件已更新，重新启用密码自动登录")
            return 0.0
        remaining = self.password_cooldown_until - time.time()
        if remaining <= 0:
            self.password_cooldown_until = None
            self.password_failure_mtime = None
            return 0.0
        return remaining

    def _set_password_cooldown(self, seconds: float, config: dict) -> None:
        self.password_cooldown_until = time.time() + seconds
        self.password_failure_mtime = config.get("mtime")

    def _password_account(self, config: dict) -> str:
        file_account = (config.get("account") or "").strip()
        known = self.last_known_uin or self._get_uin()
        if file_account and known and file_account != known:
            self._log_throttled(
                f"密码文件账号 {file_account} 与当前机器人账号 {known} 不一致，已拒绝密码登录", 3600)
            return ""
        uin = file_account or known
        if not uin:
            self._log_throttled("未知机器人 QQ 号，无法尝试密码登录", 600)
        return uin

    def _try_password_login(self, now: float) -> str:
        """Try QQ password login; returns one of attempted / manual / skip."""
        config = self._load_password_config()
        if config is None:
            return "skip"
        if self._password_cooldown_remaining(config) > 0:
            self._log_throttled("QQ 密码登录处于冷却期，跳过", 3600)
            return "skip"
        self._prune_password_attempts(now)
        if len(self.password_attempts) >= self.opts.max_password_per_day:
            self._log_throttled("QQ 密码登录已达到每 24 小时上限，跳过", 3600)
            return "skip"
        uin = self._password_account(config)
        if not uin:
            return "skip"
        digest = self._password_hash(config)
        self.password_attempts.append(now)
        try:
            data = self.api.call("QQLogin/PasswordLogin", {"uin": uin, "passwordMd5": digest})
        except ApiUnavailable:
            return "skip"
        except ApiError as error:
            text = str(error)
            if any(word in text for word in ("密码错误", "密码不正确", "密码有误")) or "wrong password" in text.lower():
                self._set_password_cooldown(24 * 3600, config)
                self._log("QQ 密码登录失败：密码错误；24 小时内不再尝试，请核对密码文件后重新写入")
                self._notify("qq_password_failed", "QQ 密码错误，已暂停 24 小时自动密码登录")
                return "manual"
            self._set_password_cooldown(3600, config)
            self._log(f"QQ 密码登录失败：{text}")
            return "skip"
        if isinstance(data, dict) and (data.get("needCaptcha") or data.get("needNewDevice")):
            kind = "验证码" if data.get("needCaptcha") else "新设备验证"
            self._set_password_cooldown(6 * 3600, config)
            self._log(f"QQ 密码登录需要{kind}，无法自动完成；请在 NapCat WebUI 按提示手动处理")
            self._notify("qq_password_verify", f"QQ 密码登录需要{kind}，需要人工在 NapCat WebUI 处理")
            return "manual"
        wait = max(self.opts.recover_wait, 60.0)
        if self.episode is not None:
            self.episode["stage"] = "password"
            self.episode["last_action"] = "密码登录"
            self.episode["deadline"] = now + wait
        self._log(f"已触发 QQ 密码登录（账号 {uin}），等待 {human_seconds(wait)}")
        return "attempted"

    # -- state transitions ---------------------------------------------

    def _api_ok(self) -> None:
        if self.api_down_since is not None:
            down_for = human_seconds(time.monotonic() - self.api_down_since)
            self._log(f"NapCat WebUI 已恢复响应（不可用约 {down_for}）")
            self.api_down_since = None
            self.api_down_notified = False
            self.next_api_action = 0.0
            self.stopped_notified = False
            if self.state in ("api_down", "stopped", "config_error"):
                self.state = "starting"

    def _on_healthy(self) -> None:
        self.last_online_wall = time.time()
        self.ever_online = True
        if self.episode is not None:
            offline_for = human_seconds(time.time() - self.episode.get("started_wall", time.time()))
            action = self.episode.get("last_action") or "NapCat 自动恢复"
            self._log(f"QQ 已恢复在线（离线 {offline_for}，方式：{action}）")
            self._notify("qq_recovered", f"QQ 已恢复在线（离线 {offline_for}，方式：{action}）")
            self.episode = None
        elif self.state != "online":
            self._log("QQ 在线")
        self.state = "online"
        self.message = "QQ 在线"
        self._ensure_auto_login_config()

    def _on_unhealthy(self, now: float, status: dict) -> None:
        phase = str(status.get("loginPhase") or "")
        error = str(status.get("loginError") or "").strip()
        kind = "degraded" if status.get("isLogin") else "offline"
        self.last_status = status
        if self.episode is None:
            grace = self.opts.degraded_grace if kind == "degraded" else self.opts.grace
            self.episode = {
                "kind": kind,
                "started_mono": now,
                "started_wall": time.time(),
                "stage": "detected",
                "deadline": now + grace,
                "extensions": 0,
                "last_action": "",
                "notified_needs_scan": False,
            }
            self.state = "degraded" if kind == "degraded" else "offline"
            self.message = "QQ 在线但连接异常" if kind == "degraded" else "QQ 已离线"
            detail = f"loginPhase={phase or '未知'}"
            if error:
                detail += f"，原因：{error}"
            if not self.ever_online:
                self.state = "awaiting_login"
                self.message = "等待用户首次扫码登录"
                self.episode["stage"] = "awaiting_login"
                self.episode["deadline"] = float("inf")
                self.episode["awaiting_logged"] = True
                hint = self._webui_hint()
                self._log(f"QQ 尚未首次登录，等待用户扫码{hint}；守护进程不会自动重启登录服务")
                self._notify("qq_awaiting_login", f"等待首次扫码登录。{hint}")
                self._write_state(force=True)
                return
            self._log(
                f"检测到 {'QQ 连接异常' if kind == 'degraded' else 'QQ 离线'}（{detail}）；"
                f"{human_seconds(grace)}后尝试自动恢复"
            )
            self._notify("qq_degraded" if kind == "degraded" else "qq_offline", self.message + "：" + detail)
            self._write_state(force=True)
            return
        if not self.ever_online:
            self.state = "awaiting_login"
            self.message = "等待用户首次扫码登录"
            if not self.episode.get("awaiting_logged"):
                self.episode["awaiting_logged"] = True
                hint = self._webui_hint()
                self._log(f"QQ 尚未首次登录，等待用户扫码{hint}；守护进程不会自动重启登录服务")
                self._notify("qq_awaiting_login", f"等待首次扫码登录。{hint}")
            return
        if kind != self.episode["kind"]:
            self.episode["kind"] = kind
        if self.state in ("starting", "online", "api_down", "config_error", "stopped", "needs_qr"):
            if self.episode["stage"] in ("detected", "quick", "restart"):
                self.state = "degraded" if kind == "degraded" else "offline"
                self.message = "QQ 在线但连接异常" if kind == "degraded" else "QQ 已离线"
        if now < self.episode["deadline"]:
            return
        if phase == "qrcode_scanned":
            scanned_since = self.episode.get("scanned_since")
            if scanned_since is None:
                self.episode["scanned_since"] = now
                self.episode["deadline"] = now + 60
                self._log("二维码已被扫描，等待手机 QQ 确认")
                return
            if now - scanned_since < 180:
                self.episode["deadline"] = now + 60
                return
            self._log("扫码后等待手机 QQ 确认超时，继续自动恢复流程")
            self.episode.pop("scanned_since", None)
            self.episode["deadline"] = now
        if phase in ("reconnecting", "initializing", "generating_qrcode") and self.episode["extensions"] < 3:
            self.episode["extensions"] += 1
            self.episode["deadline"] = now + 90
            self._log(f"NapCat 正在重建登录服务（{phase}），再等待 90 秒")
            return
        self._act(now, status)

    def _act(self, now: float, status: dict) -> None:
        stage = self.episode["stage"] if self.episode else "detected"
        if self.opts.dry_run:
            self._log("（dry-run）检测到需要恢复，但未执行任何恢复动作")
            if self.episode is not None:
                self.episode["stage"] = "needs_qr"
                self.episode["deadline"] = now + self.opts.cooldown
            return
        if stage == "detected":
            if self.episode and self.episode["kind"] == "degraded":
                if self._try_restart(now):
                    return
            else:
                if self._try_quick_login(now):
                    return
                password = self._try_password_login(now)
                if password == "attempted":
                    return
                if password == "manual":
                    self._enter_needs_qr(now, status, "密码登录需要人工验证")
                    return
                if self._try_restart(now):
                    return
            self._enter_needs_qr(now, status, "自动恢复未成功")
        elif stage == "quick":
            password = self._try_password_login(now)
            if password == "attempted":
                return
            if password == "manual":
                self._enter_needs_qr(now, status, "密码登录需要人工验证")
                return
            if self._try_restart(now):
                return
            self._enter_needs_qr(now, status, "快速登录失败")
        elif stage == "password":
            if self._try_restart(now):
                return
            self._enter_needs_qr(now, status, "密码登录未成功")
        elif stage == "restart":
            self._enter_needs_qr(now, status, "重启 NapCat 后仍未恢复")
        elif stage == "needs_qr":
            self.episode["stage"] = "detected"
            self.episode["extensions"] = 0
            self.episode["deadline"] = now
            self.state = "offline"
            self.message = "QQ 已离线，正在重试自动恢复"
            self._log("冷却结束，重新尝试自动恢复")

    def _try_quick_login(self, now: float) -> bool:
        if not self._allow_quick(now):
            self._log_throttled("快速登录尝试已达每小时上限，跳过", 3600)
            return False
        uin = self._get_uin()
        if not uin:
            self._log_throttled("未知机器人 QQ 号，无法触发快速登录", 600)
            return False
        try:
            self.api.call("QQLogin/SetQuickLogin", {"uin": uin})
            self.quick_attempts.append(now)
            self.episode["stage"] = "quick"
            self.episode["last_action"] = "快速登录"
            self.episode["deadline"] = now + self.opts.recover_wait
            self._log(f"已触发快速登录（账号 {uin}），等待 {human_seconds(self.opts.recover_wait)}")
        except ApiError as error:
            self.quick_attempts.append(now)
            self.episode["stage"] = "quick"
            self.episode["deadline"] = now + min(self.opts.recover_wait, 20)
            self._log(f"快速登录触发失败：{error}")
        return True

    def _try_restart(self, now: float) -> bool:
        if not self._allow_restart(now):
            self._log_throttled("NapCat 重启次数已达上限或间隔过短，跳过", 3600)
            return False
        try:
            data = self.api.call("QQLogin/RestartNapCat")
            self.restarts.append(now)
            self.episode["stage"] = "restart"
            self.episode["last_action"] = "重启 NapCat 登录进程"
            self.episode["deadline"] = now + self.opts.restart_wait
            detail = ""
            if isinstance(data, dict) and data.get("message"):
                detail = f"（{data['message']}）"
            self._log(f"请求重启 NapCat 登录进程{detail}，等待 {human_seconds(self.opts.restart_wait)}")
            return True
        except ApiError as error:
            self._log(f"重启 NapCat 失败：{error}")
            return False

    def _ensure_qr(self, status: dict) -> None:
        if str(status.get("qrcodeurl") or ""):
            return
        if str(status.get("loginPhase") or "") == "reconnecting":
            return
        try:
            data = self.api.call("QQLogin/RefreshQRcode")
        except ApiError as error:
            if "QQ Is Logined" in str(error):
                return
            self._log_throttled(f"刷新登录二维码失败：{error}", 600)
            return
        if isinstance(data, dict) and data.get("restarting"):
            self._log("NapCat 正在恢复登录服务，稍后会自动生成二维码")
        else:
            self._log("已请求刷新登录二维码")

    def _enter_needs_qr(self, now: float, status: dict, reason: str) -> None:
        self.state = "needs_qr"
        self.message = "自动恢复失败，需要人工扫码登录"
        if self.episode is not None:
            self.episode["stage"] = "needs_qr"
            self.episode["deadline"] = now + self.opts.cooldown
        error = str(status.get("loginError") or "").strip()
        detail = reason + (f"（{error}）" if error else "")
        hint = self._webui_hint()
        self._log(f"自动恢复失败：{detail}{hint}，{human_seconds(self.opts.cooldown)}后再次尝试")
        self._ensure_qr(status)
        if self.episode is not None and not self.episode.get("notified_needs_scan"):
            self.episode["notified_needs_scan"] = True
            self._notify("qq_needs_scan", f"自动恢复失败，需要人工扫码登录。{detail}{hint}")

    # -- API down / docker fallback -------------------------------------

    def _handle_api_error(self, now: float, error: Exception) -> None:
        """WebUI answered but the request failed (auth/config/API error).

        This is not a connectivity problem, so never restart containers for it.
        """
        if self.api_down_since is not None:
            self.api_down_since = None
            self.api_down_notified = False
            self.next_api_action = 0.0
            self.stopped_notified = False
            self._log("NapCat WebUI 已恢复响应，但接口返回错误")
        self.state = "api_error"
        self.message = "NapCat WebUI 接口错误"
        self._log_throttled(f"NapCat WebUI 接口错误：{error}（不会自动重启容器）", 300)

    def _handle_api_down(self, now: float, reason: str) -> None:
        if self.api_down_since is None:
            self.api_down_since = now
            self.api_down_reason = reason
            self._log(f"无法连接 NapCat WebUI：{reason}")
            if self.episode is not None:
                self._log("NapCat WebUI 不可用，暂停掉线恢复流程，等待其恢复")
        if self.state not in ("api_down", "stopped", "config_error"):
            self.state = "api_down"
            self.message = "NapCat WebUI 无法访问"
            if not self.api_down_notified:
                self.api_down_notified = True
                self._notify("qq_api_down", f"NapCat WebUI 无法访问：{self.api_down_reason}")
        if now - self.api_down_since < self.opts.api_down_grace:
            return
        if now < self.next_api_action:
            return
        self.next_api_action = now + 300
        if self.opts.dry_run:
            self._log_throttled("（dry-run）NapCat WebUI 不可用，跳过容器级恢复", 3600)
            return
        self._docker_recover(now)

    def _docker_output(self, arguments: list[str], timeout: float = 45.0) -> str | None:
        executable = shutil.which("docker")
        if not executable:
            return None
        try:
            result = subprocess.run(
                [executable, *arguments],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def _docker_container(self, service: str) -> str:
        identifiers = self._docker_output(
            ["ps", "-aq", "--filter", f"label=com.docker.compose.service={service}"]
        )
        if identifiers:
            return identifiers.splitlines()[0].strip()
        identifiers = self._docker_output(["ps", "-aq", "--filter", f"name=dafeiyu-video-{service}-1"])
        if identifiers:
            return identifiers.splitlines()[0].strip()
        return ""

    def _docker_running(self, container: str) -> bool | None:
        output = self._docker_output(["inspect", "-f", "{{.State.Running}}", container])
        if output is None:
            return None
        return output.strip().lower() == "true"

    def _docker_age_seconds(self, container: str) -> float | None:
        """How long the container has been running (None if unknown)."""
        output = self._docker_output(["inspect", "-f", "{{.State.StartedAt}}", container])
        if not output:
            return None
        try:
            started = datetime.strptime(output[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        return (datetime.now(timezone.utc) - started).total_seconds()

    def _docker_recover(self, now: float) -> None:
        """Host-level fallback when the WebUI itself is unresponsive.

        Only acts when the container state makes it safe: never starts containers
        when AstrBot is stopped or its state is unknown (deliberate shutdown).
        """
        if self.opts.dry_run:
            self._log_throttled("（dry-run）跳过 Docker 容器级恢复", 3600)
            return
        if self.opts.no_docker:
            self._log_throttled("NapCat WebUI 无响应；已禁用 Docker 自动恢复", 3600)
            return
        if not shutil.which("docker"):
            self._log_throttled("NapCat WebUI 无响应；服务器上没有 docker 命令", 3600)
            return
        napcat = self._docker_container("napcat")
        if not napcat:
            self._log_throttled("NapCat WebUI 无响应；未找到 NapCat 容器", 600)
            return
        napcat_running = self._docker_running(napcat)
        astrbot = self._docker_container("astrbot")
        astrbot_running = self._docker_running(astrbot) if astrbot else None
        if napcat_running is False and astrbot_running is False:
            self.state = "stopped"
            self.message = "AstrBot 与 NapCat 均已停止，视为人工停机"
            self._log_throttled("AstrBot 与 NapCat 容器均已停止，视为人工停机，不自动拉起", 3600)
            if not self.stopped_notified:
                self.stopped_notified = True
                self._notify("qq_stopped", "AstrBot 与 NapCat 均已停止，守护进程不自动拉起")
            return
        if napcat_running is False:
            if astrbot_running is not True:
                self._log_throttled("NapCat 容器已停止，但无法确认 AstrBot 也在运行，暂不自动拉起", 600)
                return
            self._log("NapCat 容器未运行，正在启动容器")
            self._docker_output(["start", napcat], timeout=120)
            self.api.reset()
            return
        if napcat_running is None:
            self._log_throttled("无法读取 NapCat 容器状态，跳过 Docker 恢复", 600)
            return
        age = self._docker_age_seconds(napcat)
        if age is not None and age < 180:
            self._log_throttled("NapCat 容器刚启动不足 3 分钟，继续等待其就绪，不重启容器", 300)
            return
        if not self._allow_restart(now):
            self._log_throttled("NapCat 容器重启次数已达上限，跳过", 3600)
            return
        self.restarts.append(now)
        self._log("NapCat 容器运行中但 WebUI 无响应，正在重启容器")
        output = self._docker_output(["restart", napcat], timeout=240)
        if output is None:
            self._log("重启 NapCat 容器失败，请查看 docker logs --tail=50 napcat")
        self.api.reset()

    # -- main loop -----------------------------------------------------

    def tick(self) -> None:
        now = time.monotonic()
        try:
            status = self.api.call("QQLogin/CheckLoginStatus")
        except ConfigError as error:
            self.state = "config_error"
            self.message = str(error)
            self._log_throttled(f"配置错误：{error}", 300)
            raise
        except ApiUnavailable as error:
            self._handle_api_down(now, str(error))
            return
        except ApiError as error:
            self._handle_api_error(now, error)
            return
        self._api_ok()
        if not isinstance(status, dict):
            self._handle_api_down(now, "CheckLoginStatus 返回格式异常")
            return
        healthy = bool(status.get("isLogin") and status.get("coreReady"))
        self.last_status = status
        self.last_status_wall = time.time()
        if healthy:
            self._refresh_uin(now)
            self._on_healthy()
        else:
            self._on_unhealthy(now, status)

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while not self.stop and time.monotonic() < deadline:
            time.sleep(min(0.5, max(0.05, deadline - time.monotonic())))

    def run(self) -> int:
        self._log(
            f"QQ 掉线守护启动（v{SERVICE_VERSION}，检查间隔 {human_seconds(self.opts.interval)}，"
            f"状态文件 {self.opts.state_file}）"
        )
        self._write_state(force=True)
        while not self.stop:
            started = time.monotonic()
            try:
                self.tick()
            except ConfigError:
                self._write_state(force=True)
                self._sleep(max(60.0, self.opts.interval))
                continue
            except Exception as error:  # keep the service alive on unexpected errors
                self._log_throttled(f"守护进程内部错误：{error!r}", 60)
                self._sleep(max(30.0, self.opts.interval))
                continue
            self._write_state()
            self._sleep(max(0.2, self.opts.interval - (time.monotonic() - started)))
        self.state = "stopped"
        self.message = "守护进程已停止"
        self._write_state(force=True)
        self._log("收到停止信号，守护进程退出")
        return EXIT_OK

    def exit_code(self) -> int:
        if self.api_down_since is not None:
            return EXIT_API_DOWN
        return EXIT_OK if self.state == "online" else EXIT_OFFLINE


def acquire_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    if fcntl is None:  # 本地 Windows 调试：不强制单实例
        return descriptor
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    os.ftruncate(descriptor, 0)
    os.write(descriptor, str(os.getpid()).encode("ascii"))
    return descriptor


def cmd_status(opts: argparse.Namespace) -> int:
    state = {}
    try:
        state = json.loads(opts.state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    api = NapCatAPI(opts.webui_config, opts.base_url)
    try:
        status = api.call("QQLogin/CheckLoginStatus")
    except ApiUnavailable as error:
        print(f"NapCat WebUI：无法访问（{error}）")
        if state:
            print(f"守护进程记录：{state.get('status')}，更新于 {state.get('updated_at')}")
        return EXIT_API_DOWN
    except (ApiError, ConfigError) as error:
        text = str(error)
        print(f"NapCat WebUI：接口异常（{error}）")
        if state:
            print(f"守护进程记录：{state.get('status')}，更新于 {state.get('updated_at')}")
        if "rate limit" in text.lower() and state.get("status") == "online":
            print("提示：NapCat 登录接口限流（每分钟 3 次），稍后重试即可；守护进程记录为在线。")
            return EXIT_OK
        return EXIT_API_DOWN
    if not isinstance(status, dict):
        print("NapCat WebUI：返回格式异常")
        return EXIT_API_DOWN
    healthy = bool(status.get("isLogin") and status.get("coreReady"))
    uin = ""
    try:
        info = api.call("QQLogin/GetQQLoginInfo")
        if isinstance(info, dict):
            uin = str(info.get("uin") or "").strip()
    except ApiError:
        pass
    if healthy:
        print(f"QQ 状态：在线{('（账号 ' + uin + '）') if uin else ''}，loginPhase={status.get('loginPhase') or '未知'}")
    else:
        detail = f"loginPhase={status.get('loginPhase') or '未知'}"
        if status.get("loginError"):
            detail += f"，最近错误：{status.get('loginError')}"
        print(f"QQ 状态：未在线（{detail}）")
    if state:
        print(
            f"守护进程记录：{state.get('status')}，更新于 {state.get('updated_at')}，"
            f"恢复阶段 {state.get('recovery_stage') or '无'}"
        )
    else:
        print("守护进程记录：暂无（服务可能刚启动）")
    if opts.password_file.exists():
        cooldown = state.get("password_cooldown_until_epoch") if state else None
        if isinstance(cooldown, (int, float)) and float(cooldown) > time.time():
            print(f"密码自动登录：已配置（冷却中，约 {human_seconds(float(cooldown) - time.time())}）")
        else:
            print("密码自动登录：已配置（仅在快速登录和重启都失败时使用）")
    else:
        print("密码自动登录：未配置（默认关闭）")
    return EXIT_OK if healthy else EXIT_OFFLINE


def _write_password_file(path: Path, account: str, password: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    temporary = path.with_name(path.name + ".tmp")
    lines = [f"QQ_ACCOUNT={account}", f"QQ_PASSWORD={password}"]
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def cmd_set_password(opts: argparse.Namespace) -> int:
    account = (opts.account or "").strip()
    if account and not account.isdigit():
        print("--account 必须是机器人 QQ 号（纯数字）。", file=sys.stderr)
        return 1
    if not account:
        try:
            state = json.loads(opts.state_file.read_text(encoding="utf-8"))
            if isinstance(state, dict) and str(state.get("qq_uin") or "").isdigit():
                account = str(state["qq_uin"])
        except (OSError, ValueError):
            pass
    if not account:
        try:
            account = input("机器人 QQ 号: ").strip()
        except EOFError:
            account = ""
    if not account or not account.isdigit():
        print("缺少机器人 QQ 号：请用 --account 指定。", file=sys.stderr)
        return 1
    try:
        password = getpass.getpass("机器人 QQ 密码（输入不回显）: ")
        confirm = getpass.getpass("再次输入密码确认: ")
    except (EOFError, OSError):
        print("无法读取密码输入（需要终端）。也可以用 sudo nano 手动创建密码文件。", file=sys.stderr)
        return 1
    if not password:
        print("密码为空，未写入。", file=sys.stderr)
        return 1
    if password != confirm:
        print("两次输入不一致，未写入。", file=sys.stderr)
        return 1
    try:
        _write_password_file(opts.password_file, account, password)
    except OSError as error:
        print(f"写入密码文件失败：{error}", file=sys.stderr)
        return 1
    print(f"已写入密码文件 {opts.password_file}（600 权限，仅保存在服务器）。")
    print("快速登录/重启都失败时，守护进程最多每 24 小时尝试 3 次密码登录；")
    print("遇到验证码或新设备验证会停止自动尝试，密码错误会暂停 24 小时。")
    return 0


def cmd_clear_password(opts: argparse.Namespace) -> int:
    try:
        opts.password_file.unlink()
    except FileNotFoundError:
        print("密码文件不存在，无需删除。")
        return 0
    except OSError as error:
        print(f"删除密码文件失败：{error}", file=sys.stderr)
        return 1
    print("已删除密码文件，密码自动登录已关闭。")
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NapCat QQ 掉线守护进程：检测离线并尝试快速登录恢复。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent,
                        help="部署目录（包含 napcat/ 和 state/）")
    parser.add_argument("--webui-config", type=Path, default=None, help="NapCat webui.json 路径")
    parser.add_argument("--state-dir", type=Path, default=None, help="状态目录")
    parser.add_argument("--key-file", type=Path, default=None, help="key.txt 路径（读取可选 webhook 配置）")
    parser.add_argument("--base-url", default=None, help="覆盖 NapCat WebUI 地址，默认读取 webui.json 端口")
    parser.add_argument("--interval", type=float, default=20.0, help="检查间隔（秒）")
    parser.add_argument("--grace", type=float, default=60.0, help="检测到未登录后等待多久再恢复（秒）")
    parser.add_argument("--recover-wait", type=float, default=45.0, help="快速登录后等待多久检查结果（秒）")
    parser.add_argument("--restart-wait", type=float, default=120.0, help="重启 NapCat 后等待多久检查结果（秒）")
    parser.add_argument("--degraded-grace", type=float, default=180.0, help="已登录但连接异常时等待多久再重启（秒）")
    parser.add_argument("--cooldown", type=float, default=900.0, help="需要人工扫码后的重试冷却（秒）")
    parser.add_argument("--api-down-grace", type=float, default=120.0, help="WebUI 不可用多久后尝试容器级恢复（秒）")
    parser.add_argument("--max-quick-per-hour", type=int, default=4, help="快速登录每小时上限")
    parser.add_argument("--max-restart-per-hour", type=int, default=2, help="NapCat 重启每小时上限")
    parser.add_argument("--min-restart-gap", type=float, default=900.0, help="两次重启之间的最小间隔（秒）")
    parser.add_argument("--password-file", type=Path, default=None,
                        help="可选的 QQ 密码兜底文件（服务器本地，建议 600 权限，不随部署包上传）")
    parser.add_argument("--max-password-per-day", type=int, default=3, help="密码登录每 24 小时上限")
    parser.add_argument("--set-password", action="store_true", help="交互式写入 QQ 密码兜底文件后退出")
    parser.add_argument("--clear-password", action="store_true", help="删除 QQ 密码兜底文件后退出")
    parser.add_argument("--account", default=None, help="--set-password 时指定机器人 QQ 号")
    parser.add_argument("--no-docker", action="store_true", help="禁用 Docker 容器级恢复")
    parser.add_argument("--dry-run", action="store_true", help="只检测，不执行恢复动作")
    parser.add_argument("--once", action="store_true", help="只检查一轮后退出")
    parser.add_argument("--status", action="store_true", help="打印状态后退出")
    parser.add_argument("--no-lock", action="store_true", help="不获取单实例锁（测试用）")
    parser.add_argument("--log-file", type=Path, default=None, help="日志文件路径")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.webui_config is None:
        args.webui_config = root / "napcat" / "config" / "webui.json"
    if args.state_dir is None:
        args.state_dir = root / "state"
    if args.key_file is None:
        args.key_file = root / "key.txt"
    if args.log_file is None:
        args.log_file = args.state_dir / "qq-watchdog.log"
    if args.password_file is None:
        args.password_file = root / "secret" / "qq-login.txt"
    args.state_dir = args.state_dir.resolve()
    args.state_file = args.state_dir / "qq-watchdog.json"
    args.lock_file = args.state_dir / ".qq-watchdog.lock"
    keys = read_key_values(args.key_file)
    args.webhook_url = (keys.get("QQ_WATCHDOG_WEBHOOK") or "").strip()
    args.ssh_host = (keys.get("SSH_HOST") or "").strip()
    return args


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    opts = parse_args(argv)
    if opts.set_password:
        return cmd_set_password(opts)
    if opts.clear_password:
        return cmd_clear_password(opts)
    if opts.status:
        return cmd_status(opts)
    lock = None
    if not opts.no_lock:
        try:
            lock = acquire_lock(opts.lock_file)
        except OSError as error:
            print(f"无法创建锁文件：{error}", file=sys.stderr)
            return EXIT_BUSY
        if lock is None:
            print("已有 qq_watchdog 实例在运行，本次退出。", file=sys.stderr)
            return EXIT_BUSY
    watchdog = Watchdog(opts)

    def handle_stop(signum, frame):
        watchdog.stop = True

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    try:
        if opts.once:
            try:
                watchdog.tick()
            except ConfigError as error:
                print(f"配置错误：{error}", file=sys.stderr)
                watchdog._write_state(force=True)
                return EXIT_API_DOWN
            watchdog._write_state(force=True)
            return watchdog.exit_code()
        return watchdog.run()
    finally:
        if lock is not None:
            try:
                os.close(lock)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
