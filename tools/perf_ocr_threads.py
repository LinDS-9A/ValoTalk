"""测 onnxruntime 线程数对 OCR 的影响：总 CPU 才是关键，不是墙钟。

游戏掉帧看的是抢走了多少 CPU，墙钟慢一点无所谓（聊天不紧急）。
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wintypes
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p]


class FILETIME(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


def cpu_seconds() -> float:
    h = k32.GetCurrentProcess()
    a, b, c, d = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    k32.GetProcessTimes(h, ctypes.byref(a), ctypes.byref(b),
                        ctypes.byref(c), ctypes.byref(d))
    return (((c.hi << 32) | c.lo) + ((d.hi << 32) | d.lo)) / 1e7


import numpy as np
import onnxruntime as ort

from valotalk.config import CONFIG
from valotalk import ocr as ocr_mod

region = CONFIG.get("ocr.region", [0, 0, 0, 0])
probe = ocr_mod.ChatOCR(CONFIG.get)
img = probe.grab(region)
if img is None:
    print("抓屏失败:", probe.last_error)
    sys.exit(1)
print(f"测试图 {img.shape[1]}x{img.shape[0]}\n")


def build_and_bench(threads: int, label: str, n=4):
    """重置全局引擎，用指定线程数重建，测耗时。"""
    # 还原 patch，重新打
    if hasattr(ort.InferenceSession.__init__, "__wrapped__"):
        pass
    ocr_mod._OCR_ENGINE = None
    ocr_mod._OCR_ENGINE_KIND = ""
    # 强制 patch 成 N 线程
    orig = getattr(ort.InferenceSession, "_valotalk_orig", None)
    if orig is None:
        # 首次：保存原始
        ort.InferenceSession._valotalk_orig = ort.InferenceSession.__init__
        orig = ort.InferenceSession.__init__

    def patched(self, path_or_bytes, sess_options=None, providers=None,
                provider_options=None, **kwargs):
        if sess_options is None:
            sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = threads
        sess_options.inter_op_num_threads = 1
        sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        return orig(self, path_or_bytes, sess_options, providers,
                    provider_options, **kwargs)

    ort.InferenceSession.__init__ = patched

    eng = ocr_mod._load_rapidocr()
    if eng is None:
        print(f"  {label}: 引擎加载失败")
        return None
    ocr_mod._OCR_ENGINE = eng
    ocr_mod._OCR_ENGINE_KIND = "rapidocr"
    probe._engine = eng
    probe.kind = "rapidocr"

    probe.read_lines(img)      # 预热

    walls, cpus, lines = [], [], None
    for _ in range(n):
        c0 = cpu_seconds()
        t0 = time.perf_counter()
        lines = probe.read_lines(img)
        walls.append((time.perf_counter() - t0) * 1000)
        cpus.append((cpu_seconds() - c0) * 1000)
    w = statistics.median(walls)
    c = statistics.median(cpus)
    print(f"  {label:<16s} 墙钟 {w:6.0f}ms  CPU 总 {c:6.0f}ms  "
          f"并行度 {c/max(w,1):.1f}x  行数 {len(lines)}")
    return c, w, lines


print("onnxruntime 线程数对比（同一张图）：")
out = {}
for n in (1, 2, 4):
    r = build_and_bench(n, f"intra_op={n}")
    if r:
        out[n] = r

if 1 in out and 2 in out:
    c1, w1, _ = out[1]
    c2, w2, _ = out[2]
    print(f"\n1 线程 vs 2 线程：CPU 总 {c1:.0f} vs {c2:.0f} ms "
          f"（{(c2-c1)/max(c2,1)*100:+.0f}%），墙钟 {w1:.0f} vs {w2:.0f} ms")

print("\n按 2000ms 间隔折算平均单核占用：")
for n, (c, w, _) in out.items():
    print(f"  {n} 线程: {c/2000*100:.0f}% 单核")