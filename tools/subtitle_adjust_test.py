"""字幕大小/位置调节：功能 + 布局 + 边界 验证。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App

OUT = Path(__file__).resolve().parent.parent / "cache"
failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


def pump(app, n=12, gap=0.05):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


app = App()
app._running = True
pump(app, 18, 0.08)

ov = app.overlay

print("=== 1) 字号调节 ===")
start = ov.font_size()
print(f"  初始字号 {start}（面板显示 {app.font_lbl.cget('text')}）")
check("面板数字和实际一致", str(start) == app.font_lbl.cget("text"))

app._adj_font(1)
pump(app, 3)
check("A+ 后字号 +1", ov.font_size() == start + 1, str(ov.font_size()))
check("面板同步更新", app.font_lbl.cget("text") == str(start + 1))
check("写进了配置", app._get("overlay.font_size") == start + 1)

app._adj_font(-1)
pump(app, 3)
check("A− 后回到原值", ov.font_size() == start, str(ov.font_size()))

print("\n=== 2) 字号边界 ===")
ov.set_font_size(999)
check(f"上限钳到 {ov.FONT_MAX}", ov.font_size() == ov.FONT_MAX, str(ov.font_size()))
ov.set_font_size(-50)
check(f"下限钳到 {ov.FONT_MIN}", ov.font_size() == ov.FONT_MIN, str(ov.font_size()))
ov.set_font_size(start)      # 复原

print("\n=== 3) 位置微调 ===")
pump(app, 4)
x0, y0 = ov.x, ov.y
print(f"  初始位置 ({x0}, {y0})")

app._nudge("up")
pump(app, 3)
check("↑ 让 y 减小 20", ov.y == y0 - 20, f"{y0} -> {ov.y}")
check("面板坐标同步", app.pos_lbl.cget("text") == f"{ov.x},{ov.y}")

app._nudge("down")
pump(app, 3)
check("↓ 回到原位", ov.y == y0, str(ov.y))

app._nudge("right")
pump(app, 3)
check("→ 让 x 增加 20", ov.x == x0 + 20, f"{x0} -> {ov.x}")
app._nudge("left")
pump(app, 3)

print("\n=== 4) 位置不会跑出屏幕 ===")
sw = ov.win.winfo_screenwidth()
sh = ov.win.winfo_screenheight()
for _ in range(60):
    ov.move_by(+100, +100, save=False)
pump(app, 3)
print(f"  一直往右下顶到 ({ov.x}, {ov.y})，屏幕 {sw}x{sh}")
check("x 不会超过屏幕右边界", ov.x <= sw - 120 + 1, str(ov.x))
check("y 不会超过屏幕下边界", ov.y <= sh - 60 + 1, str(ov.y))

for _ in range(60):
    ov.move_by(-100, -100, save=False)
pump(app, 3)
print(f"  一直往左上顶到 ({ov.x}, {ov.y})")
check("x 不会跑到屏幕左侧太远", ov.x >= -ov.width + 120 - 1, str(ov.x))
check("y 不会跑到屏幕上方太远", ov.y >= -60 - 1, str(ov.y))

print("\n=== 5) 贴回下方 ===")
ov.reset_position()
pump(app, 4)
check("重置后重新居中/贴底", ov.y > sh * 0.4, str(ov.y))
print(f"  重置后 ({ov.x}, {ov.y})")

print("\n=== 6) 预览字幕 ===")
ov.clear()
pump(app, 3)
before = len(ov.items)
ov.preview("测试预览")
pump(app, 3)
check("预览会加一条字幕", len(ov.items) == before + 1, f"{before} -> {len(ov.items)}")

print("\n=== 7) 面板布局 ===")
RX, RY = app.root.winfo_rootx(), app.root.winfo_rooty()
RW, RH = app.root.winfo_width(), app.root.winfo_height()


def rel(w):
    return (w.winfo_rootx() - RX, w.winfo_rooty() - RY,
            w.winfo_width(), w.winfo_height())


row = app.font_lbl.master
bx, by, bw, bh = rel(row)
print(f"  字幕设置行 x={bx} y={by} w={bw}")
right_edge = max(rel(c)[0] + rel(c)[2] for c in row.winfo_children()
                 if c.winfo_ismapped())
print(f"  子控件最右 {right_edge}，行右边界 {bx + bw}")
check("控件没超出这一行", right_edge <= bx + bw + 2, f"{right_edge} vs {bx + bw}")

# 卡片和日志区
card = row.master
cx, cy, cw, ch = rel(card)
print(f"  卡片 x={cx} y={cy} w={cw} h={ch}")
log_h = app.txt.winfo_height()
print(f"  日志区高 {log_h}px")
check("日志区没被挤没（> 100px）", log_h > 100, f"{log_h}px")
log_bottom = app.txt.winfo_rooty() - RY + app.txt.winfo_height()
check("日志底部没超出窗口", log_bottom <= RH, f"{log_bottom} / {RH}")

ov.clear()
app.shutdown()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)