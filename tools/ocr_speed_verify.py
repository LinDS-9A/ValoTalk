"""验证三档线程数真实生效。

⚠ 必须每个档位用独立子进程 —— 同一进程内反复重建引擎时，
onnxruntime 有全局状态残留，测出来三档耗时一模一样（会误判成「没生效」）。
真正的测量见 ocr_speed_bench.py。
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


print("=== 1) 档位定义 ===")
from valotalk.ocr import ChatOCR

for n in (1, 2, 4):
    print(f"  {n} 线程 → {ChatOCR.SPEED_CHOICES[n]}")
check("三档齐全", len(ChatOCR.SPEED_CHOICES) == 3)
check("默认 2 线程", ChatOCR.DEFAULT_THREADS == 2)

print("\n=== 2) set_threads 自己记住目标值 ===")
from valotalk.config import CONFIG

ocr = ChatOCR(CONFIG.get)
ocr.set_threads(4)
check("设 4 后 threads() 返回 4", ocr.threads() == 4, str(ocr.threads()))
ocr.set_threads(1)
check("设 1 后 threads() 返回 1", ocr.threads() == 1, str(ocr.threads()))
# 非法值回落默认
ocr.set_threads(99)
check("非法值回落默认 2", ocr.threads() == ChatOCR.DEFAULT_THREADS,
      str(ocr.threads()))

print("\n=== 3) 三档真实耗时（独立子进程）===")
print("  这一步要跑 3 个进程，约 1 分钟 …")
out = subprocess.run(
    [sys.executable, "-X", "utf8", str(ROOT / "tools" / "ocr_speed_bench.py")],
    capture_output=True, timeout=900,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
txt = (out.stdout or b"").decode("utf-8", "ignore")
print(txt)

# 从输出里解析并行度
import re
rows = re.findall(r"^\s*(\d)\s+(\d+)ms\s+(\d+)ms\s+([\d.]+)x", txt, re.M)
check("测到 3 档数据", len(rows) == 3, str(rows))
if len(rows) == 3:
    data = {int(r[0]): (int(r[1]), int(r[2]), float(r[3])) for r in rows}
    p1 = data[1][2]
    p2 = data[2][2]
    p4 = data[4][2]
    check("1 线程并行度接近 1", 0.8 <= p1 <= 1.5, f"{p1}x")
    check("2 线程并行度 > 1.8", p2 > 1.8, f"{p2}x")
    check("4 线程并行度 > 3", p4 > 3, f"{p4}x")
    check("并行度随线程数递增", p1 < p2 < p4, f"{p1} < {p2} < {p4}")
    check("CPU 总量随线程数递增",
          data[1][1] < data[2][1] < data[4][1],
          f"{data[1][1]} < {data[2][1]} < {data[4][1]}")

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)