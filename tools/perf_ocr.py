"""测聊天 OCR 单次成本 + 手机遥控线程成本。

OCR 每 2000ms 跑一次，如果单次 1 秒，就是 50% 单核 —— 这是最大头。
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wintypes
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


from valotalk.config import CONFIG
from valotalk.ocr import ChatOCR

region = CONFIG.get("ocr.region", [0, 0, 0, 0])
print(f"OCR 区域 {region}（{region[2]-region[0]}x{region[3]-region[1]}）")
print(f"OCR 间隔 {CONFIG.get('ocr.interval_ms')} ms\n")

ocr = ChatOCR(CONFIG.get)

# 预热一次（onnxruntime 首次会初始化）
print("预热 …")
img = ocr.grab(region)
if img is None:
    print("抓屏失败：", ocr.last_error)
    sys.exit(1)
print(f"抓屏尺寸 {img.size}\n")

ocr.read_lines(img)

print("单次耗时（连续 6 次）：")
wall = []
cpu = []
for i in range(6):
    c0 = cpu_seconds()
    t0 = time.perf_counter()
    lines = ocr.read_lines(img)
    wall.append((time.perf_counter() - t0) * 1000)
    cpu.append((cpu_seconds() - c0) * 1000)
    print(f"  #{i+1}: {wall[-1]:7.1f} ms   CPU {cpu[-1]:7.1f} ms   "
          f"识别 {len(lines)} 行")

import statistics
w_med = statistics.median(wall)
c_med = statistics.median(cpu)
interval = int(CONFIG.get("ocr.interval_ms") or 2000)
duty = c_med / interval * 100
print(f"\n中位数：墙钟 {w_med:.0f} ms   CPU {c_med:.0f} ms")
print(f"按 {interval}ms 间隔算，平均占 {duty:.1f}% 单核")

# 抓屏单独成本
print("\n抓屏单独成本：")
gw, gc = [], []
for _ in range(8):
    c0 = cpu_seconds()
    t0 = time.perf_counter()
    ocr.grab(region)
    gw.append((time.perf_counter() - t0) * 1000)
    gc.append((cpu_seconds() - c0) * 1000)
print(f"  墙钟中位 {statistics.median(gw):.1f} ms   CPU 中位 {statistics.median(gc):.1f} ms")