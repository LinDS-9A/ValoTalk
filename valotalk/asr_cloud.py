"""云端语音识别：可接多家服务，不绑定某一家。

★ 2026-11-23：和翻译那栏打通 —— `asr.cloud_*` 留空时**直接跟随 `translate.llm`**
（base_url / model / api_key），用户只要填过一次 LLM，识别就自动用同一套配置，
不用再单独配一遍。要单独用别家再填 asr.cloud_* 覆盖即可。

支持三种协议（按 cloud_provider 选，或从 base_url 自动猜）：

  deepseek  POST {base}/tools/asr            multipart, 字段 file
  openai    POST {base}/audio/transcriptions multipart, file + model
  dashscope POST /api/v1/services/aigc/multimodal-generation/generation
            base64 JSON（qwen3-asr-flash 走这个）

换服务商只需改配置，不用改代码：

  阿里云      "cloud_provider": "dashscope", "cloud_model": "qwen3-asr-flash"
  硅基流动    "cloud_provider": "openai",
             "cloud_base_url": "https://api.siliconflow.cn/v1",
             "cloud_model": "FunAudioLLM/SenseVoiceSmall"
  Groq       "cloud_provider": "openai",
             "cloud_base_url": "https://api.groq.com/openai/v1",
             "cloud_model": "whisper-large-v3-turbo"
  本地服务    "cloud_provider": "openai",
             "cloud_base_url": "http://127.0.0.1:8080/v1"

⚠️ DeepSeek 官方 API 只有 chat 那一套，文档里没有语音识别端点；
   拿它的 key 填识别栏大概率只会 401。要识别请用真正支持 /audio/transcriptions 的服务。

延迟实测（复用 HTTP 连接是关键，不复用慢 10 倍）：
    2.04s 音频 → 首次 3.45s（TLS 握手），之后 0.34s
    3.31s 音频 → 0.35~0.40s
    6.12s 音频 → 0.44~0.65s
"""
from __future__ import annotations

import base64
import io
import threading
import time
import wave
from typing import Callable

import numpy as np
import requests

__all__ = ["CloudASR", "fix_ja_terms", "PROVIDERS", "guess_provider"]

# 各家的默认端点与方法
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "base": "https://api.deepseek.com/v1",
        "path": "/tools/asr",
        "kind": "multipart",
        "model": "",                     # 不需要填模型
        "label": "DeepSeek",
    },
    "dashscope": {
        "base": "https://dashscope.aliyuncs.com",
        "path": "/api/v1/services/aigc/multimodal-generation/generation",
        "kind": "dashscope",
        "model": "qwen3-asr-flash",
        "label": "阿里云百炼",
    },
    "openai": {
        "base": "https://api.openai.com/v1",
        "path": "/audio/transcriptions",
        "kind": "multipart",
        "model": "whisper-1",
        "label": "OpenAI 兼容",
    },
}

DEFAULT_MODEL = "qwen3-asr-flash"


def _origin(url: str) -> str:
    """只保留 scheme://host[:port]，去掉所有路径。

    阿里云百炼的原生 ASR 接口是 /api/v1/services/...，
    而翻译那栏的 base_url 往往带 /compatible-mode/v1 后缀，直接拼会 404。
    """
    try:
        from urllib.parse import urlsplit
        p = urlsplit(url if "//" in url else "https://" + url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    # 退路：手动切
    parts = url.split("/")
    if len(parts) >= 3:
        return "/".join(parts[:3])
    return url.rstrip("/")


def guess_provider(base_url: str) -> str:
    """没显式配 provider 时，按 base_url 猜。"""
    low = (base_url or "").lower()
    if "deepseek" in low:
        return "deepseek"
    if "dashscope" in low or "aliyun" in low or "qianwen" in low:
        return "dashscope"
    if low:
        return "openai"                  # 自建 / 其它兼容服务
    return "dashscope"


# 日语 ASR 最常见的同音字错误 → 正确术语。
# 为什么需要：专用 ASR 任务普遍不支持传热词或上下文
# （qwen3-asr-flash 试过 hotwords / context / vocabulary / 文本提示，全部无效或被拒）。
# LLM 翻译有时能自己纠正（売ると → 我开大），但不稳定 ——
# 实测同一条音频两次，一次译对一次译成「我卖枪了」。所以做确定性替换。
_JA_FIXES: list[tuple[str, str]] = [
    ("売ると", "ウルト"), ("売るの", "ウルト"), ("うると", "ウルト"),
    ("ウルド", "ウルト"), ("うるど", "ウルト"),
    ("スポイク", "スパイク"), ("すぱいく", "スパイク"),
    ("ロテート", "ローテート"), ("ろてーと", "ローテート"),
    ("ロテイト", "ローテート"), ("ろーてーと", "ローテート"),
    ("エコ", "エコー"), ("えこ", "エコー"),
    ("オペレタ", "オペレーター"),
    ("プランク", "フランク"), ("ふらんく", "フランク"),
    ("サイ ト", "サイト"), ("さいと", "サイト"),
]


def fix_ja_terms(text: str) -> str:
    """修正日语 ASR 的常见同音字错误。"""
    if not text:
        return text
    out = text
    for wrong, right in _JA_FIXES:
        if wrong in out and wrong != right:
            out = out.replace(wrong, right)
    return out.replace("エコーー", "エコー")


def pcm_to_wav_b64(pcm: np.ndarray, sr: int = 16000) -> str:
    """float32 [-1,1] → wav(b64)。峰值归一化，小声队友也能识别。"""
    return base64.b64encode(pcm_to_wav(pcm, sr)).decode()


def pcm_to_wav(pcm: np.ndarray, sr: int = 16000) -> bytes:
    a = np.asarray(pcm, dtype=np.float32).reshape(-1)
    if a.size == 0:
        return b""
    peak = float(np.max(np.abs(a))) or 0.0
    if peak > 1e-6:
        a = a / peak * 0.9
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


class CloudASR:
    """线程安全的大模型 ASR 客户端。复用 Session 才会快（实测差 10 倍）。"""

    def __init__(self, cfg_get, log: Callable[[str], None] | None = None):
        self._get = cfg_get
        self.log = log or (lambda *_a, **_k: None)
        self._lock = threading.Lock()
        self._session: requests.Session | None = None
        self.last_error = ""
        self.last_latency = 0.0
        self.warmed = False
        self._sig: tuple = ()            # 端点/密钥指纹，变了就重建 session

    # ---------------- 配置 ----------------
    def _llm(self, key: str) -> str:
        """翻译那栏（translate.llm.*）—— 识别默认跟着它走。"""
        return str(self._get("translate.llm." + key, "") or "").strip()

    def _explicit_base(self) -> str:
        """用户自己填的 base_url（识别专用优先，其次翻译那栏）；都没填返回空。

        ⚠️ 单独拆出来是为了避免 provider ↔ base_url 互相递归。
        """
        own = str(self._get("asr.cloud_base_url", "") or "").strip()
        if own:
            return own.rstrip("/")
        return self._llm("base_url").rstrip("/")

    @property
    def api_key(self) -> str:
        own = str(self._get("asr.cloud_api_key", "") or "").strip()
        return own or self._llm("api_key")

    @property
    def provider(self) -> str:
        want = str(self._get("asr.cloud_provider", "") or "").strip().lower()
        if want in PROVIDERS:
            return want
        return guess_provider(self._explicit_base())

    @property
    def base_url(self) -> str:
        """识别用的地址。优先级从高到低：

        1. asr.cloud_base_url（用户为识别单独填的）
        2. asr.cloud_provider 显式指定 → 该服务商的默认地址
           （不要跟翻译那栏混：翻译可能走通义网关，识别走 DeepSeek）
        3. 都没配 → 跟随 translate.llm.base_url（最常见：一套 key 两用）
        4. 还不行 → 服务商默认地址

        阿里云百炼的原生接口挂在**根域**下
        (/api/v1/services/aigc/multimodal-generation/generation)，
        不能带翻译那栏的 /compatible-mode/v1 后缀，
        否则拼出来是 /compatible-mode/v1/api/v1/services/... → 404。
        """
        own = str(self._get("asr.cloud_base_url", "") or "").strip()
        if own:
            explicit = own.rstrip("/")
            return _origin(explicit) if self.provider == "dashscope" else explicit

        prov_explicit = str(self._get("asr.cloud_provider", "")
                            or "").strip().lower()
        if prov_explicit in PROVIDERS:
            return PROVIDERS[prov_explicit]["base"]

        llm_base = self._llm("base_url").rstrip("/")
        if llm_base:
            return _origin(llm_base) if self.provider == "dashscope" else llm_base
        return PROVIDERS[self.provider]["base"]

    @property
    def follows_llm(self) -> bool:
        """识别是不是在跟着翻译那栏走（界面用来解释「为什么是这个地址」）。"""
        own = str(self._get("asr.cloud_base_url", "") or "").strip()
        if own:
            return False
        prov_explicit = str(self._get("asr.cloud_provider", "")
                            or "").strip().lower()
        if prov_explicit in PROVIDERS:
            return False
        return bool(self._llm("base_url"))

    @property
    def model(self) -> str:
        own = str(self._get("asr.cloud_model", "") or "").strip()
        if own:
            return own
        # 不借用翻译栏的模型名：deepseek-chat / qwen-plus 这类是**聊天**模型，
        # 拿去请求 /audio/transcriptions 只会 400。OpenAI 兼容这边默认 whisper-1，
        # 别的服务（硅基流动 SenseVoice、Groq whisper-large-v3）自己填。
        return PROVIDERS[self.provider].get("model", "")

    def available(self) -> bool:
        return bool(self.api_key)

    def describe(self) -> str:
        """给界面/日志看的简短说明。"""
        p = self.provider
        label = PROVIDERS[p].get("label", p)
        m = self.model
        return f"{label} {m}".strip()

    # ---------------- 会话 ----------------
    def _sess(self) -> requests.Session:
        sig = (self.base_url, self.provider, self.api_key[:8])
        if self._session is None or sig != self._sig:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    pass
            s = requests.Session()
            try:
                from requests.adapters import HTTPAdapter
                ad = HTTPAdapter(pool_connections=2, pool_maxsize=4,
                                 max_retries=1)
                s.mount("https://", ad)
                s.mount("http://", ad)
            except Exception:
                pass
            s.headers.update({"Authorization": f"Bearer {self.api_key}"})
            self._session = s
            self._sig = sig
            self.warmed = False
        return self._session

    def warmup(self) -> bool:
        """建立连接：不然第一次识别要多等 3 秒（TLS 握手）。"""
        if not self.available():
            return False
        try:
            t0 = time.time()
            pcm = (0.05 * np.sin(np.arange(8000, dtype=np.float32) * 0.1))
            self._call(pcm, "ja", timeout=25)
            self.warmed = True
            self.log(f"[云端ASR] {self.describe()} 预热完成 {time.time()-t0:.1f}s")
            return True
        except Exception as exc:
            self.last_error = f"预热失败: {type(exc).__name__}: {str(exc)[:100]}"
            return False

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
            self.warmed = False

    def probe(self) -> tuple[bool, str]:
        """「测一下」按钮用：发一段 0.5 秒正弦，看这家的识别到底通不通。

        返回 (ok, 给用户看的话)。401/404 要说人话，别让用户对着一串 JSON 猜。
        """
        if not self.available():
            return False, "没填密钥（识别栏或翻译栏都空着）"
        try:
            t0 = time.time()
            pcm = 0.05 * np.sin(np.arange(8000, dtype=np.float32) * 0.1)
            self._call(pcm, "en", timeout=25)
            return True, f"{self.describe()} 可用（{time.time() - t0:.1f}s）"
        except Exception as exc:
            return False, _friendly_error(exc, self.provider, self.base_url)

    # ---------------- 识别 ----------------
    def transcribe(self, pcm16k: np.ndarray, language: str | None = None) -> str:
        if not self.available():
            self.last_error = "没有 API key"
            return ""
        audio = np.asarray(pcm16k, dtype=np.float32).reshape(-1)
        if audio.size < 1600:            # < 0.1s
            return ""
        timeout = float(self._get("asr.cloud_timeout", 30) or 30)
        try:
            t0 = time.time()
            text = self._call(audio, language or "", timeout)
            self.last_latency = time.time() - t0
            self.last_error = ""
            return _clean(text)
        except Exception as exc:
            self.last_error = _friendly_error(exc, self.provider, self.base_url)
            return ""

    # ---------------- 协议分派 ----------------
    def _call(self, pcm: np.ndarray, language: str, timeout: float) -> str:
        prov = self.provider
        kind = PROVIDERS[prov]["kind"]
        if kind == "dashscope":
            return self._call_dashscope(pcm, language, timeout)
        return self._call_multipart(pcm, language, timeout)

    def _call_multipart(self, pcm: np.ndarray, language: str,
                        timeout: float) -> str:
        """DeepSeek / OpenAI 兼容：multipart 直接传 wav。"""
        prov = self.provider
        url = self.base_url + PROVIDERS[prov]["path"]
        wav = pcm_to_wav(pcm)
        data: dict = {}
        if self.model:
            data["model"] = self.model
        if language:
            data["language"] = (language or "").lower()[:2]
        with self._lock:
            r = self._sess().post(
                url, files={"file": ("audio.wav", wav, "audio/wav")},
                data=data, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
        # DeepSeek 返回 {request_id, text, duration_ms}
        # OpenAI 返回 {text}
        try:
            d = r.json()
        except Exception:
            return r.text
        if isinstance(d, dict):
            if "text" in d:
                return str(d["text"] or "")
            # 有些服务包在 data 里
            if isinstance(d.get("data"), dict) and "text" in d["data"]:
                return str(d["data"]["text"] or "")
        return ""

    def _call_dashscope(self, pcm: np.ndarray, language: str,
                        timeout: float) -> str:
        """阿里云百炼原生多模态接口（qwen3-asr-flash）。

        这个任务是「专用 asr」，content 里只能放 audio ——
        塞文本提示会 400。语种只能走 parameters.asr_options.language。
        """
        b64 = pcm_to_wav_b64(pcm)
        lang = (language or "").lower()[:2]
        url = self.base_url + PROVIDERS["dashscope"]["path"]
        payload: dict = {
            "model": self.model or DEFAULT_MODEL,
            "input": {"messages": [{"role": "user", "content": [
                {"audio": f"data:audio/wav;base64,{b64}"}]}]},
        }
        if lang in ("ja", "en", "zh"):
            payload["parameters"] = {
                "asr_options": {"language": lang, "enable_lid": False}
            }
        with self._lock:
            r = self._sess().post(url, json=payload, timeout=timeout)
        if r.status_code != 200 and "parameters" in payload:
            payload.pop("parameters")
            with self._lock:
                r = self._sess().post(url, json=payload, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
        d = r.json()
        out = d.get("output", {}).get("choices", [])
        if not out:
            return ""
        msg = out[0].get("message", {})
        c = msg.get("content")
        if isinstance(c, list):
            return " ".join(x.get("text", "") for x in c if isinstance(x, dict))
        return str(c or "")


def _clean(text: str) -> str:
    import re
    t = re.sub(r"\s+", " ", (text or "")).strip()
    t = t.strip(" -—–\"'")
    if re.fullmatch(r"[\W_♪♫\[\]()（）\s]*", t):
        return ""
    return t


def _friendly_error(exc: Exception, provider: str, base_url: str) -> str:
    """把 HTTP 报错翻译成用户能看懂的一句话。"""
    msg = str(exc)
    code = ""
    m = None
    import re
    m = re.match(r"HTTP (\d{3}):", msg)
    if m:
        code = m.group(1)

    host = base_url.split("//")[-1].split("/")[0]

    if code in ("401", "403"):
        if provider == "deepseek":
            return ("这家（DeepSeek）官方没有语音识别接口，密钥再对也没用 —— "
                    "识别请换阿里云百炼 / OpenAI 兼容的服务")
        return f"{host} 拒绝了这把密钥（HTTP {code}）：key 填错，或者这个 key 没开通语音识别"
    if code == "404":
        return (f"{host} 没有这个识别接口（HTTP 404）：地址可能不是 OpenAI 兼容的 /v1，"
                "或者这家根本不提供语音识别")
    if code == "400":
        detail = msg.split(":", 1)[-1].strip()[:120] if ":" in msg else ""
        return f"{host} 说请求不对（HTTP 400）：{detail}"
    if code == "429":
        return f"{host} 限流了（HTTP 429），等一会儿再试或换一家"
    if "Timeout" in msg or "timed out" in msg.lower():
        return f"{host} 连不上或太慢（超时）"
    if "Connection" in msg or "NameResolution" in msg or "SSL" in msg:
        return f"{host} 连不上：检查网络，或者 base_url 写错"
    return msg[:160]