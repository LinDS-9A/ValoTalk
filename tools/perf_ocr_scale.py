"""测 OCR 缩放对耗时的影响 —— 决定要不要缩图。

聊天框文字本来就不大，缩到 0.7 倍通常还能认对，但计算量少一半。
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wintypes
import statistics
import sys
import time
from pathlib import Path

import numpy as np

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


from PIL import Image

from valotalk.config import CONFIG
from valotalk.ocr import ChatOCR

region = CONFIG.get("ocr.region", [0, 0, 0, 0])
ocr = ChatOCR(CONFIG.get)
img = ocr.grab(region)
if img is None:
    print("抓屏失败:", ocr.last_error)
    sys.exit(1)
print(f"原始 {img.shape[1]}x{img.shape[0]}\n")

# 预热
ocr.read_lines(img)


def resize_bgr(a: np.ndarray, scale: float) -> np.ndarray:
    h, w = a.shape[:2]
    nw = max(8, int(w * scale))
    nh = max(8, int(h * scale))
    # PIL 走 RGB，再转回 BGR
    pil = Image.fromarray(a[:, :, ::-1]).resize((nw, nh), Image.LANCZOS)
    return np.asarray(pil)[:, :, ::-1].copy()


def bench(a: np.ndarray, label: str, n=4):
    walls, cpus, lines = [], [], None
    for _ in range(n):
        c0 = cpu_seconds()
        t0 = time.perf_counter()
        lines = ocr.read_lines(a)
        walls.append((time.perf_counter() - t0) * 1000)
        cpus.append((cpu_seconds() - c0) * 1000)
    w = statistics.median(walls)
    c = statistics.median(cpus)
    print(f"  {label:<22s} {a.shape[1]:4d}x{a.shape[0]:<4d}  "
          f"墙钟 {w:6.0f}ms  CPU {c:6.0f}ms  行数 {len(lines)}")
    return w, c, lines


print("缩放对比：")
base_w, base_c, base_lines = bench(img, "原尺寸 1.00")
results = []
for scale in (0.85, 0.70, 0.55, 0.45):
    small = resize_bgr(img, scale)
    w, c, lines = bench(small, f"缩放 {scale:.2f}")
    same = lines == base_lines
    results.append((scale, w, c, same, lines))

print("\n识别结果一致性：")
for scale, w, c, same, lines in results:
    speedup = base_c / max(c, 1)
    print(f"  缩放 {scale:.2f}: {'一致 ✓' if same else '不一致 ✗'}  "
          f"CPU 快 {speedup:.2f}x")
    if not same:
        print(f"    原文: {base_lines}")
        print(f"    缩放: {lines}")

print(f"\n基线行数 {len(base_lines)}，内容：")
for ln in base_lines:
    print(f"  {ln}")