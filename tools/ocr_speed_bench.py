"""每个线程档位用独立子进程测，避免进程内状态污染。

用法：
  python ocr_speed_bench.py            # 跑全部三档
  python ocr_speed_bench.py 2          # 只跑 2 线程（子进程模式）
"""
from __future__ import annotations
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_one(threads: int, samples: int = 4) -> dict:
    """在子进程里测一档。"""
    code = f"""
import sys, time, statistics
sys.path.insert(0, r"{ROOT}")
import ctypes, ctypes.wintypes as wintypes
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p]
class FT(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]
def cpu_s():
    h = k32.GetCurrentProcess()
    a,b,c,d = FT(),FT(),FT(),FT()
    k32.GetProcessTimes(h, ctypes.byref(a), ctypes.byref(b),
                        ctypes.byref(c), ctypes.byref(d))
    return (((c.hi<<32)|c.lo) + ((d.hi<<32)|d.lo)) / 1e7

from valotalk.config import CONFIG
from valotalk.ocr import ChatOCR
region = CONFIG.get("ocr.region", [0,0,0,0])
ocr = ChatOCR(CONFIG.get)
ocr.set_threads({threads})
img = ocr.grab(region)
if img is None:
    print(json.dumps({{"error": ocr.last_error}})); sys.exit(1)
ocr.read_lines(img)          # 预热（含建引擎）
walls, cpus = [], []
for _ in range({samples}):
    c0 = cpu_s(); t0 = time.perf_counter()
    lines = ocr.read_lines(img)
    walls.append((time.perf_counter()-t0)*1000)
    cpus.append((cpu_s()-c0)*1000)
import json as _j
print(_j.dumps({{"threads": {threads},
                "wall": statistics.median(walls),
                "cpu": statistics.median(cpus),
                "lines": len(lines),
                "size": [int(img.shape[1]), int(img.shape[0])]}}))
"""
    t0 = time.time()
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                          capture_output=True, timeout=600,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    dt = time.time() - t0
    out = (proc.stdout or b"").decode("utf-8", "ignore").strip()
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                d = json.loads(line)
                d["elapsed"] = dt
                return d
            except Exception:
                continue
    err = (proc.stderr or b"").decode("utf-8", "ignore")[-300:]
    return {"error": f"no json; rc={proc.returncode}; {err}"}


def main() -> int:
    if len(sys.argv) > 1:
        # 单档模式（被外部调用时）
        d = run_one(int(sys.argv[1]))
        print(json.dumps(d, ensure_ascii=False))
        return 0

    print("每个档位独立进程测量（避免进程内线程池状态污染）\n")
    print(f"{'线程':>6s}{'墙钟':>10s}{'CPU总量':>11s}{'并行度':>9s}{'行数':>6s}")
    print("-" * 46)
    results = {}
    for n in (1, 2, 4):
        d = run_one(n)
        if "error" in d:
            print(f"{n:6d}  ERROR: {d['error'][:60]}")
            continue
        results[n] = d
        print(f"{n:6d}{d['wall']:9.0f}ms{d['cpu']:10.0f}ms"
              f"{d['cpu']/max(d['wall'],1):8.1f}x{d['lines']:6d}")

    if len(results) >= 2:
        print()
        ns = sorted(results)
        base = results[ns[0]]
        for n in ns[1:]:
            d = results[n]
            print(f"{n} 线程 vs {ns[0]} 线程：墙钟 "
                  f"{base['wall']:.0f}→{d['wall']:.0f}ms "
                  f"({(base['wall']-d['wall'])/base['wall']*100:+.0f}%)，"
                  f"CPU {base['cpu']:.0f}→{d['cpu']:.0f}ms "
                  f"({d['cpu']/max(base['cpu'],1):.1f}x)")
        print(f"\n图片尺寸: {base.get('size')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())