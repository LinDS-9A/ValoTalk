"""语音识别：faster-whisper 封装（懒加载 + CUDA 可用性实测 + 幻觉过滤 + 音量归一化）。"""
from __future__ import annotations

import ctypes
import json
import os
import re
import site
import threading
import time
from pathlib import Path

import numpy as np

from . import callouts
from .config import CACHE_DIR

_MODEL = None
_MODEL_KEY: tuple | None = None
_MODEL_LOCK = threading.Lock()
_BACKEND_CACHE = CACHE_DIR / "asr_backend.json"
_BAD_TTL = 7 * 86400


def _load_bad_backends() -> set[str]:
    """记住上次实测不可用的后端，避免每次启动都白等 CUDA 一把。"""
    try:
        if _BACKEND_CACHE.exists():
            d = json.loads(_BACKEND_CACHE.read_text(encoding="utf-8"))
            if time.time() - float(d.get("t", 0)) < _BAD_TTL:
                return set(d.get("bad", []))
    except Exception:
        pass
    return set()


def _save_bad_backends(bad: set[str]) -> None:
    try:
        _BACKEND_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _BACKEND_CACHE.write_text(
            json.dumps({"t": time.time(), "bad": sorted(bad)}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _inject_cuda_dlls() -> list[str]:
    """把 pip 装的 nvidia-* 的 bin 目录加进 DLL 搜索路径。

    ctranslate2 的 CUDA 后端要 cublas64_12.dll / cudnn*.dll，
    pip 包（nvidia-cublas-cu12 等）装的 DLL 默认不在 PATH 里，必须手动注入。
    """
    found: list[str] = []
    roots: list[Path] = []
    for sp in list(site.getsitepackages()) + [site.getusersitepackages()]:
        roots.append(Path(sp) / "nvidia")
    for nv in roots:
        if not nv.is_dir():
            continue
        for sub in ("cublas", "cudnn", "cuda_runtime", "cudart", "cuda_nvrtc"):
            b = nv / sub / "bin"
            if b.is_dir():
                found.append(str(b))
    for p in found:
        try:
            os.add_dll_directory(p)          # py3.8+ 独立 DLL 搜索路径
        except Exception:
            pass
        os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
    return found


CUDA_DLL_DIRS = _inject_cuda_dlls()

# whisper 在静音/噪声上的常见幻觉
_HALLUCINATIONS = {
    "thank you", "thanks for watching", "thank you for watching",
    "thanks for watching!", "thank you for watching!", "please subscribe",
    "subscribe", "bye", "you", ".", "..", "...",
    "subtitles by the amara.org community",
    "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目", "字幕由amara.org社区提供",
    "字幕志愿者 杨茜茜", "中文字幕由", "amara org", "下次再见",
}


def _clean_text(text: str, language: str) -> str:
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    t = t.strip(" -—–")
    if not t:
        return ""
    low = t.lower().rstrip(".!?。！？ ")
    if low in _HALLUCINATIONS:
        return ""
    if len(t.replace(" ", "")) < 2 and language != "zh":
        return ""
    if re.fullmatch(r"[\W_♪♫\[\]()（）\s]+", t):
        return ""
    return t


def _normalize(audio: np.ndarray) -> np.ndarray:
    """音量归一化到 ~0.85，最多放大 10 倍（小声队友也能听清）。"""
    audio = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-5:
        return audio
    gain = min(10.0, 0.85 / peak)
    return (audio * gain).astype(np.float32)


# 按语种给的提示词，稳住同音字和战术术语
_PROMPTS = {
    "zh": "以下是普通话的句子，请使用简体中文。",
    # 日语同音字极多（敵/適/的 都是 てき），不提示会把「敵」听成「適」
    "ja": "VALORANTのゲーム内ボイスチャット。敵、フランク、サイト、スパイク、"
          "ローテート、エコーなどの用語が出てきます。",
}


class WhisperASR:
    """线程安全的单模型封装。启动时实测 CUDA 是否真的能跑，跑不了自动退 CPU。"""

    def __init__(self, cfg_get):
        self._get = cfg_get
        self._lock = threading.Lock()
        self._model = None
        self.status = "未加载"
        self.device = None
        self.compute_type = None
        self.loaded = False
        self.load_error: str | None = None
        # 自动检测模式下最近一次识别的语种与置信度，供日志/字幕显示
        self.last_language: str = "?"
        self.last_language_prob: float = 0.0

    # ---------------- 加载 ----------------
    def ensure_loaded(self, on_status=None) -> bool:
        global _MODEL, _MODEL_KEY
        if self._model is not None and self.loaded:
            return True

        size = self._get("asr.model", "small")
        want_dev = self._get("asr.device", "auto")
        want_ct = self._get("asr.compute_type", "auto")
        root = Path(self._get("asr.download_root", "models"))

        key = (size, want_dev, want_ct, str(root))
        with _MODEL_LOCK:
            if _MODEL is not None and _MODEL_KEY == key:
                self._model = _MODEL
                self._adopt_from_global()
                return True

            def say(msg: str) -> None:
                self.status = msg
                if on_status:
                    try:
                        on_status(msg)
                    except Exception:
                        pass

            try:
                from faster_whisper import WhisperModel
            except Exception as exc:
                self.status = f"faster-whisper 未安装: {exc}"
                self.load_error = self.status
                return False

            if want_dev == "auto":
                plan = [("cuda", "float16"), ("cpu", "int8")]
            elif want_dev == "cuda":
                plan = [("cuda", want_ct if want_ct != "auto" else "float16"),
                        ("cpu", "int8")]
            else:
                plan = [("cpu", want_ct if want_ct != "auto" else "int8")]

            bad = _load_bad_backends()
            if bad:
                kept = [(d, c) for d, c in plan if d not in bad]
                skipped = [d for d, _c in plan if d in bad]
                if skipped:
                    say(f"跳过已知不可用后端: {', '.join(skipped)}")
                plan = kept or plan[-1:]

            root.mkdir(parents=True, exist_ok=True)
            errors: list[str] = []
            for dev, ct in plan:
                say(f"加载模型 {size} / {dev} / {ct} …")
                try:
                    model = WhisperModel(size, device=dev, compute_type=ct,
                                         download_root=str(root), num_workers=1,
                                         cpu_threads=int(self._get("asr.cpu_threads", 2) or 2))
                except Exception as exc:
                    errors.append(f"{dev}: {_brief(exc)}")
                    continue
                # ★ 必须用非静音信号实测：缺 cuBLAS 时构造不会报错，只有在真跑推理时才炸
                say(f"验证 {dev}/{ct} …")
                if not self._probe(model, dev, errors):
                    say(f"{dev} 不可用，回退")
                    bad.add(dev)
                    _save_bad_backends(bad)
                    model = None
                    continue
                size_ok = True
                if self._get("asr.warmup", True):
                    say(f"预热中（{dev}/{ct}）…")
                _MODEL, _MODEL_KEY = model, key
                self._model = model
                self.device, self.compute_type = dev, ct
                self.loaded = True
                self.load_error = None
                say(f"就绪（{dev} / {ct}）")
                return True

            self.status = "模型加载失败: " + ("; ".join(errors) or "未知")
            self.load_error = self.status
            return False

    def _probe(self, model, dev: str, errors: list[str]) -> bool:
        """用两段非静音信号实测。第一段只为触发 CUDA 库加载与内核初始化，
        第二段才是真正的速度基准 —— 不这么做，用户的第一句会多等 3 秒。"""
        probe = _normalize(
            (0.12 * np.sin(np.arange(32000, dtype=np.float32) * 0.05)).astype(np.float32)
        )
        try:
            for _ in range(2):
                segs, _ = model.transcribe(probe, language="en", beam_size=1,
                                           vad_filter=False)
                list(segs)          # 强制跑完，异常在这抛
            return True
        except Exception as exc:
            errors.append(f"{dev} 推理失败: {_brief(exc)}")
            return False

    def _adopt_from_global(self) -> None:
        ctor = getattr(self, "_ctor_dev", None)
        self.loaded = True
        self.device = self.device or "?"
        if not self.status.startswith("就绪"):
            self.status = f"就绪（{self.device}）"

    def _load_error_hint(self) -> str:
        if "cublas" in (self.load_error or "").lower():
            return "（装 nvidia-cublas-cu12 / nvidia-cudnn-cu12，或把 asr.device 设为 cpu）"
        return ""

    # ---------------- 推理 ----------------
    def transcribe(self, pcm16k: np.ndarray, language: str | None = None) -> str:
        """language 由界面选的服务器决定（港/美=en，日=ja）。"""
        if self._model is None:
            return ""
        audio = _normalize(pcm16k)
        if audio.size < 1600:            # < 0.1s
            return ""
        self.last_language = language or "?"
        self.last_language_prob = 0.0
        try:
            with self._lock:
                segments, _info = self._model.transcribe(
                    audio,
                    language=language or None,
                    beam_size=int(self._get("asr.beam_size", 1) or 1),
                    vad_filter=False,
                    condition_on_previous_text=False,
                    without_timestamps=True,
                    temperature=0.0,
                    # 中文防繁体、日语防同音字（敵/適），都靠这句 prompt
                    initial_prompt=self._prompt_for(language),
                )
                self.last_language = getattr(_info, "language", None) or language or "?"
                self.last_language_prob = float(
                    getattr(_info, "language_probability", 0.0) or 0.0)
                text = " ".join(seg.text for seg in segments)
        except Exception as exc:
            # 运行时崩了（多半是 CUDA 库在第一次计算时才加载）→ 标记失效，下次重建
            self.load_error = f"{type(exc).__name__}: {_brief(exc)}"
            self.loaded = False
            self._model = None
            global _MODEL
            with _MODEL_LOCK:
                _MODEL = None
            return ""
        out = _clean_text(text, language)
        # 英文报点：whisper 在港服口音上会听成音近词（long→law、flank→flak），
        # 这里用发音相似度纠回来。中文/日语不走这层。
        self.last_corrections: list[tuple[str, str]] = []
        if out and callouts.looks_english(out):
            out, self.last_corrections = callouts.fix(out)
        return out

    @staticmethod
    def _prompt_for(language: str | None) -> str | None:
        """按语种返回提示词：中文防繁体、日语防同音字。"""
        if not language:
            return None
        return _PROMPTS.get(language)


def _brief(exc: Exception) -> str:
    s = str(exc)
    return s if len(s) < 160 else s[:160] + "…"