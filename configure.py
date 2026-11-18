"""Configure a fresh deployment using files and AstrBot's supported APIs."""

import hashlib
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVICE_URL_LINE = re.compile(r"(?:AstrBot|NapCat):\s*https?://\S+", re.IGNORECASE)


def keys():
    result = {}
    for line in (ROOT / "key.txt").read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if SERVICE_URL_LINE.fullmatch(line.strip()):
            continue
        name, separator, value = line.partition("=")
        if not separator or name.strip() in result:
            raise ValueError("key.txt 存在无效行或重复字段，请按 key.example.txt 填写。")
        result[name.strip()] = value.strip()
    return result


def validate(k):
    for name in ("SSH_HOST", "ASTRBOT_USERNAME", "ASTRBOT_PASSWORD", "DEEPSEEK_API_KEY"):
        if not k.get(name):
            raise ValueError(f"key.txt 缺少 {name}")
    password = k["ASTRBOT_PASSWORD"]
    if len(password) < 8 or not all(re.search(p, password) for p in ("[A-Z]", "[a-z]", "[0-9]")):
        raise ValueError("ASTRBOT_PASSWORD 至少 8 位，且包含大写、小写字母和数字。")
    if k.get("OWNER_QQ") and not k["OWNER_QQ"].isdigit():
        raise ValueError("OWNER_QQ 应为你的大号 QQ，或者留空。")
    for name in ("DOUBAO_API_KEY", "DOUBAO_ACCESS_TOKEN"):
        if re.match(r"(?i)^key\s*[:：]", k.get(name, "")):
            raise ValueError(f"{name} 只填写凭证本身，不要包含 key: 等字段标签。")
    if k.get("DOUBAO_API_KEY") and re.search(r"\s", k["DOUBAO_API_KEY"]):
        raise ValueError("DOUBAO_API_KEY 不应包含空格，请只粘贴 API Key 本身。")
    if k.get("DOUBAO_SPEAKER") and not re.fullmatch(r"[A-Za-z0-9_.\-]+", k["DOUBAO_SPEAKER"]):
        raise ValueError("DOUBAO_SPEAKER 应是音色 ID（如 zh_female_vv_uranus_bigtts），不能带空格或引号。")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def service_active(name):
    try:
        completed = subprocess.run(["systemctl", "is-active", "--quiet", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def update_keys(updates, write_urls=False):
    path = ROOT / "key.txt"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if write_urls:
        host = keys()["SSH_HOST"]
        lines = [line for line in lines if not SERVICE_URL_LINE.fullmatch(line.strip())]
    pending = dict(updates)
    for index, line in enumerate(lines):
        name = line.partition("=")[0].strip()
        if not line.lstrip().startswith("#") and name in pending:
            lines[index] = f"{name}={pending.pop(name)}"
    lines.extend(f"{name}={value}" for name, value in pending.items())
    if write_urls:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(["", f"AstrBot: http://{host}:6185/", f"NapCat:  http://{host}:6099/webui/web_login"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def init():
    k = keys()
    validate(k)
    for name in ("data", "napcat/config", "napcat/qq", "napcat/plugins", "state"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    identity = ROOT / "napcat/machine-id"
    if not identity.exists():
        identity.write_text(uuid.uuid4().hex + "\n", encoding="ascii")
    env = ROOT / ".env"
    if not env.exists():
        tail = identity.read_text().strip()[:10]
        env.write_text("NAPCAT_MAC=02:" + ":".join(tail[i:i + 2] for i in range(0, 10, 2)) + "\n", encoding="ascii")
        env.chmod(0o600)
    onebot_path = ROOT / "napcat/config/onebot11.json"
    if onebot_path.exists():
        onebot_token = json.loads(onebot_path.read_text())["network"]["websocketClients"][0]["token"]
    else:
        onebot_token = k.get("ONEBOT_TOKEN") or secrets.token_urlsafe(32)
        write_json(onebot_path, {"network": {
            "httpServers": [], "httpClients": [], "websocketServers": [],
            "websocketClients": [{"name": "AstrBot", "enable": True,
                "url": "ws://astrbot:6199/ws", "messagePostFormat": "array",
                "token": onebot_token, "reportSelfMessage": False,
                "enableForcePushEvent": True, "debug": False,
                "heartInterval": 30000, "reconnectInterval": 30000}]},
            "musicSignUrl": "", "enableLocalFile2Url": False, "parseMultMsg": False})
    update_keys({"ONEBOT_TOKEN": onebot_token})
    webui = ROOT / "napcat/config/webui.json"
    if not webui.exists():
        write_json(webui, {"host": "0.0.0.0", "port": 6099, "prefix": "",
            "token": k.get("NAPCAT_TOKEN") or secrets.token_urlsafe(32), "loginRate": 3})
    config = ROOT / "data/cmd_config.json"
    if config.exists():
        print("保留已有业务配置与 QQ 会话；不会重置已有账号密码。", flush=True)
        return
    salt = secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac("sha256", k["ASTRBOT_PASSWORD"].encode(), bytes.fromhex(salt), 600000).hex()
    model = "deepseek/" + (k.get("DEEPSEEK_MODEL") or "deepseek-flash")
    write_json(config, {"config_version": 5,
        "dashboard": {"enable": True, "username": k["ASTRBOT_USERNAME"],
            "password": hashlib.md5(k["ASTRBOT_PASSWORD"].encode()).hexdigest(),
            "pbkdf2_password": f"pbkdf2_sha256$600000${salt}${password_hash}",
            "password_storage_upgraded": True, "password_change_required": False,
            "jwt_secret": secrets.token_hex(32), "host": "0.0.0.0", "port": 6185},
        "platform": [{"id": "大肥鱼", "type": "aiocqhttp", "enable": True,
            "ws_reverse_host": "0.0.0.0", "ws_reverse_port": 6199, "ws_reverse_token": onebot_token}],
        "provider_sources": [{"id": "deepseek", "provider": "deepseek",
            "type": "openai_chat_completion", "provider_type": "chat_completion",
            "key": [k["DEEPSEEK_API_KEY"]], "api_base": "https://api.deepseek.com/v1",
            "timeout": 120, "proxy": "", "custom_headers": {}, "enable": True}],
        "provider": [{"id": model, "provider_source_id": "deepseek",
            "enable": True, "model": model.split("/", 1)[1],
            "modalities": ["text", "tool_use"],
            "custom_extra_body": {"thinking": {"type": "disabled"}}}],
        "agent_runner": {"type": "local", "config": {"model": {"provider_id": model}}},
        "platform_settings": {"enable_id_white_list": False},
        "provider_settings": {"computer_use_runtime": "none", "streaming_response": False},
        "admins_id": [k["OWNER_QQ"]] if k.get("OWNER_QQ") else []})
    print("已生成全新配置；后台密码已哈希，OneBot 仅在容器内网监听。", flush=True)


def request(base, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path,
        data=None if data is None else json.dumps(data).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def napcat_credential(base, token, timeout_seconds=180):
    """Authenticate to NapCat WebUI, waiting out its login rate limit (loginRate/minute)."""
    payload = {"hash": hashlib.sha256((token + ".napcat").encode()).hexdigest()}
    deadline = time.monotonic() + max(20, timeout_seconds)
    last_message = "未知错误"
    while True:
        try:
            response = request(base, "/auth/login", payload)
        except urllib.error.HTTPError as error:
            if error.code == 429 and time.monotonic() < deadline:
                last_message = "HTTP 429 限流"
                time.sleep(20)
                continue
            raise RuntimeError(f"NapCat 后台认证失败：HTTP {error.code}") from None
        except OSError as error:
            raise RuntimeError(f"无法连接 NapCat WebUI：{error}") from None
        credential = (response.get("data") or {}).get("Credential")
        if credential:
            return credential
        message = str(response.get("message") or "未知错误")
        last_message = message
        if "rate limit" in message.lower() and time.monotonic() < deadline:
            time.sleep(20)
            continue
        raise RuntimeError("NapCat 后台认证失败：" + message)


def sync():
    path = ROOT / "napcat/config/webui.json"
    rate_limit_retries = 0
    for attempt in range(90):
        try:
            config = json.loads(path.read_text())
            credential = napcat_credential("http://127.0.0.1:6099/api", config["token"], timeout_seconds=120)
            update_keys({"NAPCAT_TOKEN": config["token"]})
            print("NapCat 后台已可用，实际 Token 已写回服务器 key.txt（不在终端显示）。", flush=True)
            return
        except RuntimeError as error:
            if "rate limit" in str(error).lower() and rate_limit_retries < 3:
                rate_limit_retries += 1
                print("NapCat WebUI 登录限流，等待 65 秒后重试…", flush=True)
                time.sleep(65)
                continue
            if attempt == 89:
                raise RuntimeError("NapCat 启动超时，请查看 docker compose logs --tail=50 napcat。") from None
            time.sleep(2)
        except (OSError, ValueError, KeyError, TypeError):
            if attempt == 89:
                raise RuntimeError("NapCat 启动超时，请查看 docker compose logs --tail=50 napcat。") from None
            time.sleep(2)


def importer():
    spec = importlib.util.spec_from_file_location("dafeiyu_import", ROOT / "pack/tools/import_dafeiyu.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def login(module):
    k = keys()
    for attempt in range(120):
        try:
            urllib.request.urlopen("http://127.0.0.1:6185/", timeout=3).close()
            break
        except OSError:
            if attempt == 119:
                raise RuntimeError("AstrBot 启动超时，请查看 docker compose logs --tail=50 astrbot。") from None
            time.sleep(2)
    api = module.Api("http://127.0.0.1:6185")
    if not api.login(k["ASTRBOT_USERNAME"], k["ASTRBOT_PASSWORD"]):
        raise RuntimeError("AstrBot 登录失败，请核对 key.txt；不会自动重置已有密码。")
    return api


def configuration_signature(k):
    signature = hashlib.sha256()
    signature.update(json.dumps({name: k.get(name, "") for name in (
        "OWNER_QQ", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "SILICONFLOW_API_KEY",
        "DOUBAO_API_KEY", "DOUBAO_APP_ID", "DOUBAO_ACCESS_TOKEN", "DOUBAO_SPEAKER")},
        sort_keys=True).encode())
    for path in sorted((ROOT / "pack").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            signature.update(path.relative_to(ROOT / "pack").as_posix().encode())
            signature.update(path.read_bytes())
    return signature.hexdigest()


def voice_credentials(k):
    """返回当前要用的豆包语音凭证与模式。

    - 填了 DOUBAO_API_KEY：用「豆包·语音合成模型 Seed-TTS 2.0」（API Key 鉴权，App ID 可选一起带）。
    - 只有旧版 DOUBAO_APP_ID + DOUBAO_ACCESS_TOKEN：回退到旧版 Seed Audio 1.0。
    """
    api_key = k.get("DOUBAO_API_KEY", "")
    app_id, token = k.get("DOUBAO_APP_ID", ""), k.get("DOUBAO_ACCESS_TOKEN", "")
    speaker = k.get("DOUBAO_SPEAKER", "")
    if api_key:
        return {"mode": "tts2", "api_key": api_key, "app_id": app_id, "access_token": "", "speaker": speaker}
    if app_id and token:
        return {"mode": "seed_audio", "api_key": "", "app_id": app_id, "access_token": token, "speaker": speaker}
    return {"mode": "none", "api_key": "", "app_id": "", "access_token": "", "speaker": speaker}


def voice_digest_of(k):
    """语音凭证指纹：模式 + 实际用到的凭证 + 音色，任何一个变了都要重新测试。"""
    credentials = voice_credentials(k)
    mode = credentials["mode"]
    if mode == "tts2":
        raw = "tts2\n" + credentials["api_key"] + "\n" + credentials["app_id"] + "\n" + credentials["speaker"]
    elif mode == "seed_audio":
        raw = "seed_audio\n" + credentials["app_id"] + "\n" + credentials["access_token"] + "\n" + credentials["speaker"]
    else:
        raw = "none\n\n\n"
    return hashlib.sha256(raw.encode()).hexdigest()


def apply():
    k = keys()
    validate(k)
    m = importer()
    api = login(m)
    credentials = voice_credentials(k)
    voice_requested = credentials["mode"] != "none"
    voice_digest = voice_digest_of(k)
    failed_voice = ROOT / "state/voice-failed.sha256"
    cached_failure = failed_voice.exists() and failed_voice.read_text().strip() == voice_digest
    memory = bool(k.get("SILICONFLOW_API_KEY"))
    signature = configuration_signature(k)
    marker = ROOT / "state/configured.sha256"
    marker_matched = marker.exists() and marker.read_text().strip() == signature
    # 上次语音没配好时不能直接跳过：否则用户在控制台开通服务后再重跑部署，也永远不会重试语音。
    retry_voice = marker_matched and voice_requested and cached_failure
    if marker_matched and not retry_voice:
        print("配置与上次成功部署一致，跳过重复导入和收费模型测试。", flush=True)
        return
    if retry_voice:
        print("上次豆包语音测试没通过，这次部署重新测试语音。", flush=True)
        cached_failure = False
    voice = voice_requested and not cached_failure
    if voice_requested and cached_failure:
        print("本组豆包语音凭证上次测试失败，本次先保持关闭；修好后重跑一次部署会自动重试，也可用 --configure 立即重试。", flush=True)
    elif not voice:
        print("豆包语音未配置（DOUBAO_API_KEY 为空，或旧版 App ID/Access Token 不全）：跳过语音和唱歌，不安装其插件。", flush=True)
    if not k.get("OWNER_QQ"):
        print("主人 QQ 留空：暂不设置管理员，不启用主动私聊；基础聊天正常配置。", flush=True)
    if voice:
        existing = {p["name"] for p in api.call("GET", "/plugins")["data"]}
        for name in ("astrbot_plugin_seed_audio_tts", "astrbot_plugin_dafeiyu_sing"):
            if name in existing:
                result = api.call("PATCH", "/plugins/enabled", {"plugin_id": name, "enabled": True})
                if not api.ok(result):
                    raise RuntimeError("无法启用语音插件：" + name)
    config = api.call("GET", "/config-profiles/default")["data"]["config"]
    source = next(p for p in config["provider_sources"] if p["id"] == "deepseek")
    source["key"] = [k["DEEPSEEK_API_KEY"]]
    # Provider-source edits through the configuration API are applied at runtime.
    model = "deepseek/" + (k.get("DEEPSEEK_MODEL") or "deepseek-flash")
    provider = next((p for p in config["provider"] if p.get("provider_source_id") == "deepseek"), None)
    if provider:
        provider.update(id=model, model=model.split("/", 1)[1])
    config["agent_runner"]["config"]["model"]["provider_id"] = model
    result = api.call("PUT", "/config-profiles/default", config)
    if not api.ok(result):
        raise RuntimeError("无法更新基础模型配置：" + api.msg(result))
    m.ANSWERS = {"base_url": "http://127.0.0.1:6185", "username": k["ASTRBOT_USERNAME"],
        "password": k["ASTRBOT_PASSWORD"], "owner_qq": k.get("OWNER_QQ", ""),
        "memory": "2" if memory else "0", "siliconflow_key": k.get("SILICONFLOW_API_KEY", ""),
        "voice": "3" if voice else "0", "volc_mode": credentials["mode"],
        "volc_api_key": credentials["api_key"],
        "volc_app_id": credentials["app_id"], "volc_access_token": credentials["access_token"],
        "volc_speaker": credentials["speaker"]}
    imported = m.main()
    failures = {name for name, good in getattr(m, "LAST_RESULTS", []) if not good}
    if "语音" in failures:
        failed_voice.write_text(voice_digest + "\n", encoding="ascii")
    elif voice and failed_voice.exists():
        failed_voice.unlink()
    if not imported and (not failures or failures - {"语音"}):
        raise RuntimeError("部分导入项目失败，修正输出中的原因后重跑 sudo bash deploy.sh --configure。")
    voice_ready = voice and "语音" not in failures
    if voice and not voice_ready:
        print("可选语音测试失败：保留原凭证，关闭语音和唱歌，继续完成基础部署。修好后重跑部署会自动重试语音，也可用 --configure 立即重试。", flush=True)
        if credentials["mode"] == "tts2":
            print("提示：确认账号已开通「豆包·语音合成模型 Seed-TTS 2.0」，并检查 API Key 和音色 ID（要用 *_uranus_bigtts）。", flush=True)
        else:
            print("提示：如果豆包语音控制台已经换成新版 API Key，请把 key.txt 的 DOUBAO_API_KEY 填上再重跑部署。", flush=True)
    if not voice_ready:
        existing = {p["name"] for p in api.call("GET", "/plugins")["data"]}
        for name in ("astrbot_plugin_seed_audio_tts", "astrbot_plugin_dafeiyu_sing"):
            if name in existing:
                result = api.call("PATCH", "/plugins/enabled", {"plugin_id": name, "enabled": False})
                if not api.ok(result):
                    raise RuntimeError("无法停用旧语音插件：" + name)
    good, _ = m.test_provider(api, model)
    if not good:
        raise RuntimeError("DeepSeek 测试未通过，请核对 API Key、模型名称与账户余额。")
    marker.write_text(signature + "\n", encoding="ascii")
    write_json(ROOT / "state/features.json", {"voice_requested": voice_requested,
        "voice_enabled": voice_ready, "voice_test_failed": cached_failure or "语音" in failures,
        "voice_mode": credentials["mode"],
        "voice_model": ("seed-tts-2.0" if credentials["mode"] == "tts2" else
            ("seed-audio-1.0" if credentials["mode"] == "seed_audio" else "")),
        "voice_speaker": credentials["speaker"]})
    print("基础模型与配置导入成功。", flush=True)


def check():
    k = keys()
    m = importer()
    api = login(m)
    assert (ROOT / "state/configured.sha256").is_file(), "配置导入尚未全部成功"
    plugins = api.call("GET", "/plugins")["data"]
    credentials = voice_credentials(k)
    voice_requested = credentials["mode"] != "none"
    config = api.call("GET", "/config-profiles/default")["data"]["config"]
    voice_provider = next((p for p in config["provider"] if p.get("type") == "seed_audio_tts"), None)
    voice = voice_requested and bool(voice_provider and voice_provider.get("enable"))
    if voice:
        expected_mode = credentials["mode"]
        actual_mode = str(voice_provider.get("api_mode") or (
            "seed_audio" if str(voice_provider.get("resource_id") or "").startswith("seed-audio") else "tts2"))
        assert actual_mode == expected_mode, (
            f"语音提供商模式和 key.txt 不一致（{actual_mode} != {expected_mode}），重跑一次部署或 sudo bash deploy.sh --configure")
    memory = bool(k.get("SILICONFLOW_API_KEY"))
    expected = {"astrbot_plugin_group_chat_plus", "meme_manager", "astrbot_plugin_qzone",
        "astrbot_plugin_qqprofile", "astrbot_plugin_proactive_chat", "astrbot_plugin_dafeiyu_signature",
        "astrbot_plugin_dafeiyu_clean"}
    if memory:
        expected.add("astrbot_plugin_livingmemory")
    if voice:
        expected.update({"astrbot_plugin_seed_audio_tts", "astrbot_plugin_dafeiyu_sing"})
    active = {p["name"] for p in plugins if p.get("activated")}
    assert expected <= active, "部分插件未激活：" + ", ".join(sorted(expected - active))
    assert not api.call("GET", "/plugins/failed").get("data"), "存在加载失败的插件"
    if not voice:
        assert not {"astrbot_plugin_seed_audio_tts", "astrbot_plugin_dafeiyu_sing"} & active, "可选语音应处于关闭状态"
    onebot = json.loads((ROOT / "napcat/config/onebot11.json").read_text())["network"]["websocketClients"][0]
    platform = next(p for p in config["platform"] if p["type"] == "aiocqhttp")
    assert platform["ws_reverse_token"] == onebot["token"] == k["ONEBOT_TOKEN"], "OneBot Token 不一致"
    assert platform["ws_reverse_host"] == "0.0.0.0" and onebot["url"] == "ws://astrbot:6199/ws", "OneBot 地址不一致"
    nap_config = json.loads((ROOT / "napcat/config/webui.json").read_text())
    assert nap_config["token"] == k["NAPCAT_TOKEN"], "NapCat Token 未同步"
    base = "http://127.0.0.1:6099/api"
    watchdog_active = service_active("dafeiyu-qq-watchdog.service")
    watchdog_data = {}
    try:
        loaded = json.loads((ROOT / "state/qq-watchdog.json").read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            watchdog_data = loaded
    except (OSError, ValueError):
        pass
    watchdog_status = watchdog_data.get("status")
    napcat_auth_limited = False
    try:
        token = napcat_credential(base, k["NAPCAT_TOKEN"], timeout_seconds=120)
        status = request(base, "/QQLogin/CheckLoginStatus", {}, token)["data"]
    except RuntimeError as error:
        if watchdog_status is None:
            raise RuntimeError("无法读取 QQ 在线状态：NapCat 后台认证失败（" + str(error) + "），且守护进程状态不可用。") from None
        napcat_auth_limited = True
        watchdog_online = watchdog_status == "online"
        status = {"isLogin": watchdog_online, "coreReady": watchdog_online}
        print("警告：NapCat WebUI 认证暂时受限（" + str(error) + "），本次检查使用守护进程最近状态判断 QQ 状态。", flush=True)
    watchdog_labels = {"online": "在线", "offline": "离线", "degraded": "连接异常",
        "needs_qr": "等待扫码", "api_down": "WebUI 不可用", "api_error": "接口错误",
        "awaiting_login": "等待首次扫码", "stopped": "已停机",
        "config_error": "配置错误", "starting": "启动中"}
    report = {"checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "services_ready": True, "plugins_active": len(expected), "voice_requested": voice_requested, "voice_enabled": voice,
        "voice_mode": credentials["mode"],
        "voice_model": ("seed-tts-2.0" if credentials["mode"] == "tts2" else
            ("seed-audio-1.0" if credentials["mode"] == "seed_audio" else "")),
        "memory_enabled": memory, "owner_configured": bool(k.get("OWNER_QQ")),
        "qq_logged_in": bool(status.get("isLogin") and status.get("coreReady")),
        "napcat_token_saved": True, "qq_delivery_tested": False,
        "napcat_auth_limited": napcat_auth_limited,
        "qq_watchdog_active": watchdog_active, "qq_watchdog_status": watchdog_status}
    write_json(ROOT / "state/verification.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    print(f"AstrBot：http://{k['SSH_HOST']}:6185/", flush=True)
    print(f"NapCat：http://{k['SSH_HOST']}:6099/webui/web_login", flush=True)
    if napcat_auth_limited:
        print("提示：NapCat WebUI 登录接口被限流，本次 QQ 状态取自守护进程；稍后可重跑 --check 直接查询。", flush=True)
    if watchdog_active:
        print(f"QQ 掉线守护：已运行，最近状态：{watchdog_labels.get(str(watchdog_status), str(watchdog_status or '启动中'))}", flush=True)
    else:
        print("QQ 掉线守护：未运行；重跑 deploy.sh 可自动安装。", flush=True)
    print("QQ 已登录；本次检查未发送 QQ 消息。" if report["qq_logged_in"] else "等待用户用机器人 QQ 扫码登录；未执行 QQ 登录或发送消息。", flush=True)
    update_keys({}, write_urls=True)


if __name__ == "__main__":
    os.umask(0o077)
    actions = {"init": init, "sync": sync, "apply": apply, "check": check}
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in actions:
            raise ValueError("用法：python3 configure.py init|sync|apply|check")
        actions[sys.argv[1]]()
    except Exception as error:
        message = str(error)
        try:
            credentials = keys()
        except (OSError, ValueError):
            credentials = {}
        for name, value in credentials.items():
            if len(value) > 4 and any(word in name for word in ("PASSWORD", "KEY", "TOKEN")):
                message = message.replace(value, "[REDACTED]")
        print("错误：" + message, file=sys.stderr)
        sys.exit(1)
