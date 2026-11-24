"""游戏内左下角聊天框 OCR：截屏 → 识别 → 只取新增行。"""
from __future__ import annotations

import re
import threading
from collections import deque

import numpy as np

try:
    import mss
    _MSS_FACTORY = getattr(mss, "MSS", None) or getattr(mss, "mss", None)
except Exception:  # pragma: no cover
    mss = None
    _MSS_FACTORY = None

_OCR_ENGINE = None
_OCR_ENGINE_KIND = ""
_OCR_THREADS = 0                  # 当前 patch 生效的线程数


def _limit_onnx_threads(n: int = 1, force: bool = False) -> None:
    """onnxruntime 默认 intra_op_num_threads=0 即「有多少核用多少核」。

    线程数是个真实的取舍（同一张 566x212 的聊天截图实测）：

      1 线程 → 墙钟 829ms，CPU 总量  930ms   ← 省 CPU，但慢
      2 线程 → 墙钟 650ms，CPU 总量 2461ms
      4 线程 → 墙钟 625ms，CPU 总量 5477ms   ← 快一点，CPU 涨 5.9 倍

    多线程只把墙钟压了 200ms，CPU 却成倍涨（同步开销 + 缓存失效）。
    打游戏时 CPU 才是疼的地方，所以默认 1 线程，面板上可切。
    """
    global _OCR_THREADS
    try:
        import onnxruntime as ort
        if getattr(ort.InferenceSession, "_valotalk_patched", False):
            if not force or _OCR_THREADS == n:
                return
            # 已经打过补丁且要换线程数：还原成原始实现再重打
            orig = getattr(ort.InferenceSession, "_valotalk_orig", None)
            if orig is not None:
                ort.InferenceSession.__init__ = orig
            else:
                return

        original = ort.InferenceSession.__init__

        def patched(self, path_or_bytes, sess_options=None, providers=None,
                    provider_options=None, **kwargs):
            if sess_options is None:
                sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = n
            sess_options.inter_op_num_threads = 1
            sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            return original(self, path_or_bytes, sess_options, providers,
                            provider_options, **kwargs)

        patched._valotalk_patched = True
        ort.InferenceSession.__init__ = patched
        ort.InferenceSession._valotalk_orig = original
        _OCR_THREADS = n
    except Exception:
        pass


def reset_engine() -> None:
    """丢掉已建好的引擎，下次 ensure_engine 按新线程数重建。"""
    global _OCR_ENGINE, _OCR_ENGINE_KIND
    _OCR_ENGINE = None
    _OCR_ENGINE_KIND = ""


def _load_rapidocr(threads: int = 1):
    global _OCR_ENGINE, _OCR_ENGINE_KIND
    if _OCR_ENGINE_KIND == "rapidocr" and _OCR_ENGINE is not None:
        return _OCR_ENGINE
    _limit_onnx_threads(threads, force=True)   # 必须在建 session 之前打补丁
    try:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
        _OCR_ENGINE_KIND = "rapidocr"
        return _OCR_ENGINE
    except Exception:
        pass
    try:
        from rapidocr import RapidOCR  # 新版包名
        _OCR_ENGINE = RapidOCR()
        _OCR_ENGINE_KIND = "rapidocr"
        return _OCR_ENGINE
    except Exception:
        return None


def _load_winrt():
    """Windows 自带 OCR（离线、无需模型下载），作为降级。"""
    try:
        import asyncio
        import winrt.windows.media.ocr as ocr  # noqa: F401
        import winrt.windows.graphics.imaging as imaging  # noqa: F401
        import winrt.windows.storage.streams as streams  # noqa: F401
        return True
    except Exception:
        return False


class ChatOCR:
    def __init__(self, cfg_get):
        self._get = cfg_get
        self._engine = None
        self.kind = ""
        self.last_error = ""
        self._lock = threading.Lock()
        self._threads: int | None = None      # 惰性从 config 读，之后自己记住

    # ---------------- 线程档位 ----------------
    SPEED_CHOICES = {
        1: "省 CPU（829ms）",
        2: "平衡（650ms）",
        4: "最快（625ms）",
    }
    DEFAULT_THREADS = 2

    @staticmethod
    def threads_safe_limit() -> int:
        """按 CPU 核心数给出「不会掉帧」的最大线程数。

        实测（OCR 和模拟游戏同为 Normal，游戏每帧 16.7ms 干 10ms 活）：
          4 核：2 线程就开始丢帧（最长间隔 37ms）
          6 核：4 线程丢 7 帧（最长 41ms）
          8 核：4 线程最长 21ms，不丢帧
          24 核：4 线程 17ms，完全无感

        所以 8 核以下不建议开 4 线程。ValoTalk 本身是 Below Normal 优先级，
        实际会比这个测试更好，但按保守值给建议。
        """
        try:
            import os
            cores = os.cpu_count() or 4
        except Exception:
            cores = 4
        if cores >= 8:
            return 4
        if cores >= 6:
            return 2
        return 1

    def threads(self) -> int:
        if self._threads is not None:
            return self._threads
        try:
            n = int(self._get("ocr.onnx_threads", self.DEFAULT_THREADS)
                    or self.DEFAULT_THREADS)
        except (TypeError, ValueError):
            n = self.DEFAULT_THREADS
        if n not in self.SPEED_CHOICES:
            n = self.DEFAULT_THREADS
        self._threads = n
        return n

    def set_threads(self, n: int) -> bool:
        """切换 OCR 线程数。

        必须自己记住目标值 —— ensure_engine 重建引擎时读 threads()，
        如果只依赖 config，外部没同步写就会用回旧线程数（实测三档耗时
        一模一样，就是这个原因）。
        """
        n = int(n)
        if n not in self.SPEED_CHOICES:
            n = self.DEFAULT_THREADS
        old = self.threads()
        self._threads = n
        _limit_onnx_threads(n, force=True)
        reset_engine()
        self._engine = None
        self.kind = ""
        return n != old

    # ---------------- 引擎 ----------------
    def ensure_engine(self) -> bool:
        if self._engine is not None:
            return True
        want = (self._get("ocr.engine", "auto") or "auto").lower()
        with self._lock:
            if self._engine is not None:
                return True
            if want in ("auto", "rapidocr"):
                eng = _load_rapidocr(self.threads())
                if eng is not None:
                    self._engine, self.kind = eng, "rapidocr"
                    return True
            if want in ("auto", "winrt") and _load_winrt():
                self._engine, self.kind = "winrt", "winrt"
                return True
            self.last_error = "没有可用的 OCR 引擎（pip install rapidocr-onnxruntime）"
            return False

    # ---------------- 截图 ----------------
    def grab(self, region: list[int]) -> np.ndarray | None:
        if _MSS_FACTORY is None:
            self.last_error = "mss 未安装"
            return None
        x1, y1, x2, y2 = region
        if x2 <= x1 or y2 <= y1:
            self.last_error = "聊天区域未设置"
            return None
        try:
            with _MSS_FACTORY() as sct:
                shot = sct.grab({"left": int(x1), "top": int(y1),
                                 "width": int(x2 - x1), "height": int(y2 - y1)})
                arr = np.asarray(shot, dtype=np.uint8)  # BGRA
        except Exception as exc:
            self.last_error = f"截图失败: {exc}"
            return None
        return arr[:, :, :3].copy()  # BGR，正好是 OCR 要的顺序

    # ---------------- 识别 ----------------
    def read_lines(self, img: np.ndarray) -> list[str]:
        if img is None or not self.ensure_engine():
            return []
        min_conf = float(self._get("ocr.min_confidence", 0.5) or 0.5)
        try:
            if self.kind == "rapidocr":
                return self._read_rapidocr(img, min_conf)
            return self._read_winrt(img)
        except Exception as exc:
            self.last_error = f"OCR 失败: {exc}"
            return []

    def _rapidocr_items(self, res) -> list:
        """把两种 rapidocr 的返回格式统一成 [(box, text, score)]。

        - `rapidocr_onnxruntime`（≤1.2，Python ≤3.12）：`(list[[box, text, score]], elapse)`
        - `rapidocr` ≥3.0（Python 3.13 只能装这个）：`RapidOCROutput` 对象，
          字段是**平行列表** `boxes / txts / scores`，且没识别到内容时全是 None
          —— 直接迭代会报 `'RapidOCROutput' object is not iterable`。
        """
        if res is None:
            return []
        if hasattr(res, "boxes") and hasattr(res, "scores"):
            # ⚠️ 这几个字段可能是 numpy.ndarray，`x or []` 会报
            # "truth value of an array is ambiguous"，只能显式判 None
            boxes = getattr(res, "boxes", None)
            txts = getattr(res, "txts", None)
            scores = getattr(res, "scores", None)
            boxes = [] if boxes is None else list(boxes)
            txts = [] if txts is None else list(txts)
            scores = [] if scores is None else list(scores)
            return list(zip(boxes, txts, scores))
        if isinstance(res, tuple):
            res = res[0]
        return list(res) if res is not None else []

    def _read_rapidocr(self, img: np.ndarray, min_conf: float) -> list[str]:
        res = self._engine(img)
        boxes = self._rapidocr_items(res)
        if len(boxes) == 0:
            return []
        rows: list[tuple[float, float, str]] = []
        for item in boxes:
            try:
                box, text, score = item[0], item[1], float(item[2])
            except Exception:
                continue
            if score < min_conf:
                continue
            text = re.sub(r"\s+", " ", str(text)).strip()
            if not text:
                continue
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            rows.append((float(np.mean(ys)), float(np.min(xs)), text))
        return _merge_rows(rows)

    def _read_winrt(self, img: np.ndarray) -> list[str]:
        import asyncio
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter
        import winrt.windows.media.ocr as _ocr  # noqa: F401

        h, w, _ = img.shape
        bgra = np.dstack([img[:, :, 0], img[:, :, 1], img[:, :, 2],
                          np.full((h, w), 255, dtype=np.uint8)])
        raw = bgra.tobytes()

        async def run():
            writer = DataWriter()
            writer.write_bytes(raw)
            buf = writer.detach_buffer()
            bitmap = SoftwareBitmap.create_copy_from_buffer(
                buf, BitmapPixelFormat.BGRA8, w, h
            )
            engine = OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                return []
            result = await engine.recognize_async(bitmap)
            out = []
            for line in result.lines:
                text = re.sub(r"\s+", " ", line.text).strip()
                if text:
                    out.append(text)
            return out

        try:
            return asyncio.run(run())
        except Exception as exc:
            self.last_error = f"winrt OCR: {exc}"
            return []


def _merge_rows(rows: list[tuple[float, float, str]], y_tol: float = 12.0) -> list[str]:
    """把 y 相近的文本块合并成一行（OCR 常把一行切成几块）。"""
    if not rows:
        return []
    rows.sort(key=lambda r: (r[0], r[1]))
    lines: list[list] = []
    for y, x, text in rows:
        if lines and abs(y - lines[-1][0]) <= y_tol:
            lines[-1][1].append((x, text))
        else:
            lines.append([y, [(x, text)]])
    out = []
    for _y, parts in lines:
        parts.sort(key=lambda p: p[0])
        joined = " ".join(p[1] for p in parts)
        joined = re.sub(r"\s+", " ", joined).strip()
        if joined:
            out.append(joined)
    return out


class LineDiffer:
    """只输出聊天框里新出现的行。"""

    def __init__(self, memory: int = 400):
        self._last: list[str] = []
        self._seen: deque[str] = deque(maxlen=memory)

    def reset(self) -> None:
        self._last = []
        self._seen.clear()

    def push(self, lines: list[str]) -> list[str]:
        lines = [ln for ln in (lines or []) if ln]
        if not lines:
            self._last = []
            return []

        anchor = -1
        if self._last:
            tail = self._last[-1]
            for i in range(len(lines) - 1, -1, -1):
                if lines[i] == tail or _similar(lines[i], tail):
                    anchor = i
                    break

        if anchor >= 0:
            fresh = lines[anchor + 1:]
        elif not self._last:
            fresh = list(lines)
        else:
            # 界面跳变：只取没见过的
            fresh = [ln for ln in lines if ln not in self._seen]

        out = []
        for ln in fresh:
            if ln in self._seen:
                continue
            self._seen.append(ln)
            out.append(ln)
        self._last = lines[-24:]
        return out


def _similar(a: str, b: str) -> bool:
    """OCR 抖动容错：长度相近且前 60% 字符相同就当作同一行。"""
    if not a or not b:
        return False
    if a == b:
        return True
    if abs(len(a) - len(b)) > 3:
        return False
    n = max(1, int(min(len(a), len(b)) * 0.6))
    return a[:n] == b[:n]


# ---------------------------------------------------------------- 聊天行过滤
# 无畏契约聊天框：玩家发言一律是「名字: 内容」，系统广播（下包/回合/击杀播报/
# 好友上线）没有名字前缀。只翻玩家说的，广播整行丢掉。
_CHAT_LINE_RE = re.compile(
    r"^(?:\[[^\]\n]{0,14}\]\s*)?([^:：\n]{1,26}?)\s*[:：]\s*(\S.*)$"
)
_SYSTEM_NAMES = {
    "system", "server", "game", "announcer", "notice", "info", "hint",
    "系统", "服务器", "游戏", "广播", "提示", "通知", "公告",
}

# 冒号前出现这些词，基本是游戏播报被当成了「名字」
_SYSTEM_HINTS = (
    "remaining", "spike", "planted", "defused", "detonat", "round",
    "match", "party", "joined", "left", "warning", "disconnect",
    "overtime", "enemies", "enemy", "ally", "score", "half", "starting",
    "剩余", "回合", "已安装", "已拆除", "加入", "离开", "警告", "比分",
)


def is_player_chat(line: str) -> bool:
    s = (line or "").strip()
    if len(s) < 3:
        return False
    m = _CHAT_LINE_RE.match(s)
    if not m:
        return False
    name = m.group(1).strip()
    if not name or name.lower() in _SYSTEM_NAMES:
        return False
    # 名字不该像个句子：超过 4 个词基本是系统播报被误认
    if len(name.split()) > 4:
        return False
    low = name.lower()
    if any(h in low for h in _SYSTEM_HINTS):
        return False
    return True