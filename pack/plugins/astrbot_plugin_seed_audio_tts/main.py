"""豆包语音合成提供商：默认使用「豆包·语音合成模型 Seed-TTS 2.0」（seed-tts-2.0）。

接口：POST https://openspeech.bytedance.com/api/v3/tts/unidirectional
返回按行分隔的 JSON（NDJSON），每行 data 是一段 base64 音频，code=20000000/done 表示结束。
鉴权（新版豆包语音控制台的 API Key）：
- X-Api-Key：API Key（必填）
- X-Api-App-Id：App ID（可选，和 API Key 同一个账号时可以带上）
- X-Api-Resource-Id：seed-tts-2.0
旧版兼容：把 api_mode 设为 seed_audio 时走 Seed Audio 1.0
（POST /api/v3/tts/create，用 APP ID + Access Token 或 X-Api-Key，按秒计费）。

整条语音（seed_audio_whole_reply = true，默认）：AstrBot 自带的语音会先把回复拆段、一段一段排队合成，
每段都要合成一次、声音也不完全一致。开了整条语音后由本插件掷骰子（seed_audio_reply_probability），
掷中就把整条回复一次合成一条语音，没掷中照常发分段文字。此时要把 AstrBot 的语音总开关
（provider_tts_settings.enable）关掉，不然 AstrBot 还会另外按段转语音。
"""

import base64
import json
import os
import re
import time
import uuid

import random

import aiohttp

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain, Record
from astrbot.api.star import Context, Star
from astrbot.core.star.session_llm_manager import SessionServiceManager
from astrbot.core.provider import register as _reg
from astrbot.core.provider.entities import ProviderType
from astrbot.core.provider.provider import TTSProvider
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

TYPE_NAME = "seed_audio_tts"
TTS2_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
LEGACY_URL = "https://openspeech.bytedance.com/api/v3/tts/create"
DEFAULT_SPEAKER = "zh_female_vv_uranus_bigtts"
DEFAULT_PERSONA = "一个憨萌软糯的小女生，声音甜甜的、有点奶，十几岁的感觉，嘴馋爱撒娇，带一点小傲娇"
DEFAULT_TEMPLATE = "{persona}，在QQ上给好朋友发语音，语气轻快自然，只说引号里的这句话，一字不差：“{text}”"
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def _norm(s: str) -> str:
    return _NON_WORD.sub("", s or "").lower()


def _read_env_file(path: str) -> dict:
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                out[k.strip()] = v.strip()
    return out


# 插件热重载时先摘掉旧的注册，避免「提供商类型已注册」报错。
_old = _reg.provider_cls_map.pop(TYPE_NAME, None)
if _old in _reg.provider_registry:
    _reg.provider_registry.remove(_old)


@_reg.register_provider_adapter(
    TYPE_NAME,
    "豆包语音合成 Seed-TTS 2.0（火山引擎，选好音色直接念）",
    provider_type=ProviderType.TEXT_TO_SPEECH,
    default_config_tmpl={
        "id": "seed_audio_tts",
        "type": TYPE_NAME,
        "provider": "volcengine",
        "provider_type": "text_to_speech",
        "enable": False,
        "api_mode": "tts2",
        "api_key": "",
        "app_id": "",
        "access_key": "",
        "credentials_file": "",
        "api_base": TTS2_URL,
        "resource_id": "seed-tts-2.0",
        "speaker": DEFAULT_SPEAKER,
        "user_id": "dafeiyu",
        "style_prompt": "",
        "legacy_api_base": LEGACY_URL,
        "legacy_resource_id": "seed-audio-1.0",
        "legacy_model": "seed-audio-1.0",
        "seed_audio_persona": DEFAULT_PERSONA,
        "seed_audio_prompt_template": DEFAULT_TEMPLATE,
        "seed_audio_format": "mp3",
        "seed_audio_sample_rate": 24000,
        "seed_audio_max_attempts": 2,
        "seed_audio_whole_reply": True,
        "seed_audio_reply_probability": 0.33,
        "timeout": 60,
    },
    provider_display_name="豆包语音合成 Seed-TTS 2.0",
)
class ProviderSeedAudioTTS(TTSProvider):
    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        super().__init__(provider_config, provider_settings)
        c = provider_config
        self.api_key = str(c.get("api_key", "") or "")
        self.app_id = str(c.get("app_id", "") or "")
        self.access_key = str(c.get("access_key", "") or "")
        cred = str(c.get("credentials_file", "") or "")
        if cred and not (self.api_key or (self.app_id and self.access_key)):
            env = _read_env_file(cred)
            self.api_key = self.api_key or env.get("VOLC_SPEECH_API_KEY", "")
            self.app_id = self.app_id or env.get("VOLC_SPEECH_APP_ID", "")
            self.access_key = self.access_key or env.get("VOLC_SPEECH_ACCESS_TOKEN", "")
        mode = str(c.get("api_mode") or "").strip().lower()
        if mode not in ("tts2", "seed_audio"):
            # 旧配置没有 api_mode：按 resource_id 推断，保证升级后行为不变。
            mode = "seed_audio" if str(c.get("resource_id") or "").startswith("seed-audio") else "tts2"
        self.api_mode = mode
        self.api_base = str(c.get("api_base") or TTS2_URL).strip()
        self.resource_id = str(c.get("resource_id") or "seed-tts-2.0").strip()
        self.speaker = str(c.get("speaker") or DEFAULT_SPEAKER).strip()
        self.user_id = str(c.get("user_id") or "dafeiyu").strip()
        self.style_prompt = str(c.get("style_prompt") or "").strip()
        self.legacy_api_base = str(c.get("legacy_api_base") or LEGACY_URL).strip()
        self.legacy_resource_id = str(c.get("legacy_resource_id") or "seed-audio-1.0").strip()
        self.legacy_model = str(c.get("legacy_model") or "seed-audio-1.0").strip()
        self.persona = c.get("seed_audio_persona") or DEFAULT_PERSONA
        self.template = c.get("seed_audio_prompt_template") or DEFAULT_TEMPLATE
        self.fmt = str(c.get("seed_audio_format") or "mp3").strip()
        self.sample_rate = int(c.get("seed_audio_sample_rate") or 24000)
        self.max_attempts = max(1, int(c.get("seed_audio_max_attempts") or 2))
        self.timeout = float(c.get("timeout") or 60)
        self.whole_reply = bool(c.get("seed_audio_whole_reply", False))
        prob = c.get("seed_audio_reply_probability", 0.33)
        self.reply_probability = float(0.33 if prob in (None, "") else prob)
        self.stats_path = os.path.join(get_astrbot_temp_path(), "seed_audio_calls.jsonl")

    def _prompt(self, text: str) -> str:
        line = text.replace("“", "「").replace("”", "」").replace('"', "")
        return self.template.format(persona=self.persona, text=line)

    def _headers(self, resource_id: str) -> dict:
        if not (self.api_key or (self.app_id and self.access_key)):
            raise Exception("缺少豆包语音凭证：填 API Key（或旧版 APP ID + Access Token）")
        headers = {
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "Content-Type": "application/json",
            # 流式响应按行解析，要求服务端不要压缩，否则要整包解压才能读。
            "Accept-Encoding": "identity",
        }
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
            if self.app_id:
                headers["X-Api-App-Id"] = self.app_id
        else:
            headers["X-Api-App-Id"] = self.app_id
            headers["X-Api-Access-Key"] = self.access_key
        return headers

    async def _request(self, text: str) -> tuple[bytes, dict]:
        if self.api_mode == "seed_audio":
            return await self._request_seed_audio(text)
        return await self._request_tts2(text)

    async def _request_tts2(self, text: str) -> tuple[bytes, dict]:
        req_params = {
            "text": text,
            "speaker": self.speaker,
            "audio_params": {"format": self.fmt, "sample_rate": self.sample_rate},
        }
        if self.style_prompt:
            # 可选：TTS 2.0 的语音指令（context_texts），个别模型/音色不支持时会报错。
            req_params["additions"] = json.dumps({"context_texts": [self.style_prompt]}, ensure_ascii=False)
        body = {"user": {"uid": self.user_id or "dafeiyu"}, "req_params": req_params}
        t0 = time.monotonic()
        audio = bytearray()
        heard = ""
        usage = {}
        reqid = ""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_base,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers=self._headers(self.resource_id),
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                if resp.status != 200:
                    raw = await resp.text()
                    raise Exception(f"Seed-TTS 2.0 HTTP {resp.status}: {raw[:300]}")
                while True:
                    line = await resp.content.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line.decode("utf-8", "replace"))
                    except Exception:
                        raise Exception(f"Seed-TTS 2.0 返回的不是 JSON 行：{line[:160]!r}")
                    code = int(item.get("code") or 0)
                    if code not in (0, 20000000):
                        raise Exception(f"Seed-TTS 2.0 错误 {code}：{str(item.get('message') or item)[:240]}")
                    data = item.get("data")
                    if data:
                        try:
                            audio.extend(base64.b64decode(data))
                        except Exception:
                            raise Exception("Seed-TTS 2.0 音频分片解码失败")
                    sub = item.get("subtitle")
                    if isinstance(sub, dict):
                        heard += sub.get("text") or "".join(s.get("text", "") for s in sub.get("sentences", []))
                    if isinstance(item.get("usage"), dict):
                        usage = item["usage"]
                    reqid = item.get("reqid") or reqid
                    if item.get("done") or code == 20000000:
                        break
        if not audio:
            raise Exception("Seed-TTS 2.0 没有返回音频")
        return bytes(audio), {"heard": heard, "duration": 0.0,
                              "text_words": usage.get("text_words"), "reqid": reqid,
                              "latency": time.monotonic() - t0}

    async def _request_seed_audio(self, text: str) -> tuple[bytes, dict]:
        body = {
            "model": self.legacy_model,
            "text_prompt": self._prompt(text),
            "audio_config": {"format": self.fmt, "sample_rate": self.sample_rate, "enable_subtitle": True},
        }
        t0 = time.monotonic()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.legacy_api_base,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers=self._headers(self.legacy_resource_id),
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                raw = await resp.text()
                dt = time.monotonic() - t0
                try:
                    data = json.loads(raw)
                except Exception:
                    raise Exception(f"Seed Audio HTTP {resp.status}: {raw[:200]}")
                if resp.status != 200 or not data.get("audio"):
                    brief = {k: v for k, v in data.items() if k not in ("audio", "url")}
                    raise Exception(f"Seed Audio HTTP {resp.status}: {json.dumps(brief, ensure_ascii=False)[:300]}")
                sub = data.get("subtitle") or {}
                heard = sub.get("text") or "".join(s.get("text", "") for s in sub.get("sentences", []))
                dur = float(data.get("original_duration") or data.get("duration") or 0)
                return base64.b64decode(data["audio"]), {"heard": heard, "duration": dur, "latency": dt}

    def _log(self, rec: dict) -> None:
        try:
            with open(self.stats_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    async def get_audio(self, text: str) -> str:
        target = _norm(text)
        if not target:
            raise Exception("这段没有可念的字")
        call_id = uuid.uuid4().hex[:8]
        last_err = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                audio, meta = await self._request(text)
            except Exception as e:
                last_err = str(e)
                logger.warning(f"[SeedVoice] {call_id} 第 {attempt} 次请求失败：{last_err}")
                self._log({"ts": time.time(), "id": call_id, "attempt": attempt, "text": text,
                           "ok": False, "error": last_err[:200]})
                continue
            heard = _norm(meta.get("heard") or "")
            dur = float(meta.get("duration") or 0)
            # Seed-TTS 2.0 一般不带逐字字幕：没字幕就直接用，有字幕才核对台词。
            match = (not heard) or heard == target
            words = meta.get("text_words")
            cost = f"，音频 {dur:.2f}s，约 {dur / 60:.3f} 元" if dur else (f"，计费字数 {words}" if words else "")
            logger.info(
                f"[SeedVoice] {call_id} 第 {attempt} 次 {'台词一致' if match else '台词不一致'}，"
                f"耗时 {float(meta.get('latency') or 0):.1f}s{cost}"
                + (f"，念的是：{heard}" if heard else "")
            )
            self._log({"ts": time.time(), "id": call_id, "attempt": attempt, "text": text, "heard": heard,
                       "match": match, "mode": self.api_mode, "latency": round(float(meta.get("latency") or 0), 2),
                       "duration": dur, "text_words": words, "ok": True})
            if not match:
                last_err = f"念成了「{heard}」"
                continue
            os.makedirs(get_astrbot_temp_path(), exist_ok=True)
            path = os.path.join(get_astrbot_temp_path(), f"seed_voice_{int(time.time() * 1000)}_{call_id}.{self.fmt}")
            with open(path, "wb") as f:
                f.write(audio)
            return path
        raise Exception(f"豆包语音 {self.max_attempts} 次都没成，改发文字（{last_err}）")

    async def test(self) -> None:
        """后台「测试」按钮：用一句中文试一次。"""
        path = await self.get_audio("你好呀")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception("豆包语音测试没生成音频")


class SeedAudioTTSPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._warned_double = False

    def _whole_reply_provider(self):
        for p in self.context.get_all_tts_providers():
            if isinstance(p, ProviderSeedAudioTTS) and p.whole_reply:
                return p
        return None

    @filter.on_decorating_result(priority=-1000)
    async def whole_reply_voice(self, event: AstrMessageEvent):
        """掷中就把整条回复合成一条语音（在表情包等插件处理完文字之后、AstrBot 分段之前）。"""
        result = event.get_result()
        if result is None or not result.chain or not result.is_llm_result():
            return
        prov = self._whole_reply_provider()
        if prov is None:
            return
        try:
            tts_on = bool(self.context.get_config(umo=event.unified_msg_origin)["provider_tts_settings"]["enable"])
        except Exception:
            tts_on = False
        if tts_on and not self._warned_double:
            self._warned_double = True
            logger.warning("[SeedVoice] 整条语音已由本插件处理，请把 AstrBot 的语音总开关关掉，否则没掷中的回复还会被按段转语音")
        if not await SessionServiceManager.should_process_tts_request(event):
            return
        if random.random() > prov.reply_probability:
            return
        texts = [c.text.strip() for c in result.chain if isinstance(c, Plain) and c.text.strip()]
        if not texts:
            return
        full = ""
        for t in (x.strip() for x in "\n".join(texts).splitlines()):
            if not t:
                continue
            if full and full[-1] not in "，。！？、；：～…,.!?;:~":
                full += "，"
            full += t
        if len(_norm(full)) < 2:
            return
        t0 = time.monotonic()
        try:
            path = await prov.get_audio(full)
        except Exception as e:
            logger.warning(f"[SeedVoice] 整条语音没成，照常发文字：{e}")
            return
        logger.info(f"[SeedVoice] 整条语音 {time.monotonic() - t0:.1f}s：{full}")
        new_chain, placed = [], False
        for c in result.chain:
            if isinstance(c, Plain):
                if not placed:
                    new_chain.append(Record(file=path, url=path, text=full))
                    placed = True
                continue
            new_chain.append(c)
        result.chain = new_chain
