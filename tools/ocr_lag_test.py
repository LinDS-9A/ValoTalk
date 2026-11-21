"""OCR 三档对「卡不卡」的真实影响。

墙钟不是关键 —— 关键是那一段里抢走几个核，以及会不会让别的线程
（游戏渲染、音频）拿不到 CPU。

测法：
  1. 用 SetProcessAffinityMask 把进程限制到 N 个核（模拟不同机型）
  2. 同时跑一个 16.7ms 心跳线程（≈60fps 的帧间隔）
  3. 跑 OCR，统计心跳的**最大偏离**和**掉帧数**

心跳被推迟多少，就代表游戏帧被推迟多少。
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wintypes
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_case(threads: int, cores: int) -> dict:
    """在子进程里：限制核心数 → 起心跳 → 跑 OCR → 报抖动。"""
    code = f'''
import ctypes, ctypes.wintypes as wintypes, json, statistics, sys, threading, time
sys.path.insert(0, r"{ROOT}")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
k32.SetProcessAffinityMask.restype = wintypes.BOOL

# 限制可用核心数：只在低 {cores} 位上跑
mask = (1 << {cores}) - 1
ok = k32.SetProcessAffinityMask(k32.GetCurrentProcess(), mask)
if not ok:
    print(json.dumps({{"error": "SetProcessAffinityMask 失败"}})); sys.exit(1)

from valotalk.config import CONFIG
from valotalk.ocr import ChatOCR

region = CONFIG.get("ocr.region", [0,0,0,0])
ocr = ChatOCR(CONFIG.get)
ocr.set_threads({threads})
img = ocr.grab(region)
if img is None:
    print(json.dumps({{"error": ocr.last_error}})); sys.exit(1)
ocr.read_lines(img)          # 预热

# ---- 心跳线程：每 16.7ms 醒一次，记录实际间隔 ----
beat = []
stop = threading.Event()
def heartbeat():
    target = 1.0 / 60
    prev = time.perf_counter()
    while not stop.is_set():
        time.sleep(target * 0.5)
        now = time.perf_counter()
        beat.append(now - prev)
        prev = now

th = threading.Thread(target=heartbeat, daemon=True)
th.start()
time.sleep(0.5)              # 先跑一段基线

base_n = len(beat)
t0 = time.perf_counter()
ocr.read_lines(img)
ocr_dur = time.perf_counter() - t0
time.sleep(0.5)              # 再跑一段基线
stop.set(); th.join(timeout=1)

iv = [x * 1000 for x in beat]        # 毫秒
base_iv = [x*1000 for x in beat[:base_n]]
tail_iv = [x*1000 for x in beat[-int(len(beat)*0.15):]] if len(beat) > 20 else []

# 心跳延迟 = 间隔偏离目标 16.7ms 的程度
target = 1000/60
def stats(v):
    if not v: return {{}}
    dev = [abs(x - target) for x in v]
    return {{"median": statistics.median(v),
             "p99": sorted(v)[int(len(v)*0.99)] if len(v) > 100 else max(v),
             "max": max(v),
             "max_dev": max(dev)}}

all_s = stats(iv)
base_s = stats(base_iv)
# 掉帧：间隔 > 33.3ms（两帧）算掉一帧
dropped = sum(1 for x in iv if x > 33.3)

print(json.dumps({{
    "threads": {threads},
    "cores": {cores},
    "ocr_ms": ocr_dur * 1000,
    "beats": len(iv),
    "median_ms": all_s.get("median", 0),
    "max_gap_ms": all_s.get("max", 0),
    "max_dev_ms": all_s.get("max_dev", 0),
    "base_max_dev_ms": base_s.get("max_dev", 0),
    "dropped_frames": dropped,
}}))
'''
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                          capture_output=True, timeout=600,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (proc.stdout or b"").decode("utf-8", "ignore")
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                continue
    return {"error": (proc.stderr or b"").decode("utf-8", "ignore")[-200:]}


def main() -> int:
    print("模拟不同核心数下，OCR 对 60fps 心跳的影响")
    print("（心跳被推迟多少 = 游戏帧被推迟多少）\n")
    print(f"{'核心':>4s}{'线程':>5s}{'OCR墙钟':>9s}{'心跳中位':>9s}"
          f"{'最大间隔':>9s}{'偏离基线':>9s}{'掉帧':>6s}")
    print("-" * 55)

    cases = []
    for cores in (4, 6, 8, 24):
        for threads in (1, 2, 4):
            if threads > cores:
                continue
            d = run_case(threads, cores)
            if "error" in d:
                print(f"{cores:4d}{threads:5d}  ERROR {d['error'][:40]}")
                continue
            cases.append(d)
            print(f"{cores:4d}{threads:5d}{d['ocr_ms']:8.0f}ms"
                  f"{d['median_ms']:8.1f}ms{d['max_gap_ms']:8.1f}ms"
                  f"{d['max_dev_ms']:8.1f}ms{d['dropped_frames']:6d}")

    print("\n" + "=" * 55)
    print("读法：")
    print("  心跳中位 ≈16.7ms = 正常；最大间隔超过 33ms 就是肉眼可见的卡")
    print("  偏离基线 = 最大间隔 - 空闲时的最大间隔（越大越可能是 OCR 造成）")
    return 0


if __name__ == "__main__":
    sys.exit(main())