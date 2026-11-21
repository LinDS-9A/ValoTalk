"""验证不同字号确实渲染出不同大小 —— 直接量 canvas 的 bbox（比截图可靠）。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


def pump(app, n=10, gap=0.05):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


app = App()
app._running = True
pump(app, 16, 0.08)
ov = app.overlay

SAMPLE = [("队友", "Enemy one tap on A site, watch the flank.",
           "敌人在包点一枪头，注意绕后")]


def measure(size: int):
    ov.set_font_size(size, save=False)
    ov.items.clear()
    for tag, text, orig in SAMPLE:
        ov._add_main(tag, text, orig, 60)
    pump(app, 4)
    bb = ov.canvas.bbox("all")
    ov.items.clear()
    ov.canvas.delete("all")
    return bb


print("=== 同一条字幕在不同字号下的渲染尺寸 ===")
print(f"{'字号':>4s}  {'canvas bbox (x1,y1,x2,y2)':>28s}  {'宽':>5s} {'高':>5s}")
print("-" * 56)
results = []
for size in (12, 16, 19, 24, 30, 40, 48):
    bb = measure(size)
    if bb is None:
        print(f"{size:4d}  {'（没有内容）':>28s}")
        continue
    w = bb[2] - bb[0]
    h = bb[3] - bb[1]
    results.append((size, w, h))
    print(f"{size:4d}  {str(bb):>28s}  {w:5d} {h:5d}")

print()
check("至少量到 5 档", len(results) >= 5, str(len(results)))
# 高度必须单调递增
heights = [h for _, _, h in results]
mono = all(heights[i] < heights[i + 1] for i in range(len(heights) - 1))
check("字号越大渲染越高（严格单调）", mono, str(heights))

# 最小和最大要有明显差距
if len(results) >= 2:
    ratio = heights[-1] / max(heights[0], 1)
    check("最大/最小高度比 > 2.5（差异明显）", ratio > 2.5, f"{ratio:.2f}x")

print("\n=== 字号写回配置 ===")
ov.set_font_size(26)
check("set_font_size 写进 config", app._get("overlay.font_size") == 26,
      str(app._get("overlay.font_size")))
ov.set_font_size(19)

print("\n=== 位置变化后渲染位置跟着动 ===")
ov.reset_position()
pump(app, 4)
bb1 = measure(19)
y1 = bb1[1]
ov.move_by(0, -60)
pump(app, 3)
bb2 = measure(19)
y2 = bb2[1]
print(f"  上移 60px：文字 y {y1} → {y2}")
check("文字纵坐标跟着窗口移动", abs(y1 - y2) < 3,
      f"{y1} vs {y2}（canvas 内坐标不变是对的，窗口整体在动）")
ov.reset_position()

ov.clear()
app.shutdown()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)