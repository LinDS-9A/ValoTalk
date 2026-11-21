"""验证 OCR 档位的核心数保护：建议值 + 警告日志 + UI 提示。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App
from valotalk.ocr import ChatOCR

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


print("=== 1) 核心数 → 安全上限 ===")
import os
_real = os.cpu_count


def fake_count(n):
    return lambda: n


for cores, expect in ((2, 1), (4, 1), (6, 2), (8, 4), (12, 4), (24, 4)):
    os.cpu_count = fake_count(cores)
    got = ChatOCR.threads_safe_limit()
    print(f"  {cores:2d} 核 → 建议最多 {got} 线程"
          f"（{ChatOCR.SPEED_CHOICES[got]}）")
    check(f"{cores} 核建议 {expect}", got == expect, f"got={got}")
os.cpu_count = _real

print(f"\n  本机 {_real()} 核 → 建议 {ChatOCR.threads_safe_limit()} 线程")

print("\n=== 2) UI 提示带核心数建议 ===")
app = App()
app._running = True
for _ in range(20):
    app.root.update()
    time.sleep(0.06)

hint = app.spd_hint.cget("text")
print(f"  提示文字: {hint}")
real_cores = _real()
if real_cores >= 8:
    check("多核机器不显示限制建议", "建议" not in hint or "≥" in hint, hint)
else:
    check("少核机器显示建议", "建议" in hint, hint)

print("\n=== 3) 超限时打警告日志 ===")
# 记录日志
logs = []
_orig_log = app.log
app.log = lambda msg: (logs.append(str(msg)), _orig_log(msg))

# 模拟 6 核环境
os.cpu_count = fake_count(6)
logs.clear()
app.cb_ocr_speed.set(ChatOCR.SPEED_CHOICES[4])
app._on_ocr_speed_change()
for _ in range(6):
    app.root.update()
    time.sleep(0.05)
os.cpu_count = _real

joined = "\n".join(logs)
print("  日志输出:")
for line in logs:
    print(f"    {line}")
check("提示核心数不足", "⚠" in joined and "核" in joined, joined[:80])
check("给出建议档位", "建议用" in joined, joined[:80])

print("\n=== 4) 多核时不误报 ===")
logs.clear()
app.cb_ocr_speed.set(ChatOCR.SPEED_CHOICES[2])
app._on_ocr_speed_change()
for _ in range(6):
    app.root.update()
    time.sleep(0.05)
logs.clear()
if _real() >= 8:
    app.cb_ocr_speed.set(ChatOCR.SPEED_CHOICES[4])
    app._on_ocr_speed_change()
    for _ in range(6):
        app.root.update()
        time.sleep(0.05)
    joined2 = "\n".join(logs)
    check(f"{_real()} 核选 4 线程不警告", "⚠" not in joined2, joined2[:80])
else:
    print("  本机核数不足，跳过")

app.log = _orig_log

print("\n=== 5) 各档仍然可切换 ===")
for n in (4, 2, 1, 2):
    app.cb_ocr_speed.set(ChatOCR.SPEED_CHOICES[n])
    app._on_ocr_speed_change()
    for _ in range(4):
        app.root.update()
        time.sleep(0.04)
    check(f"可切到 {n} 线程", app.ocr.threads() == n, str(app.ocr.threads()))

app.shutdown()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)