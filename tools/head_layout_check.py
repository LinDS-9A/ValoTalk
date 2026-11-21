"""检查头部加了「检查更新」按钮后是否还放得下（不互相挤压/裁剪）。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App

app = App()
app._running = True
for _ in range(20):
    app.root.update()
    time.sleep(0.05)

RX, RY = app.root.winfo_rootx(), app.root.winfo_rooty()
RW, RH = app.root.winfo_width(), app.root.winfo_height()


def rel(w):
    return (w.winfo_rootx() - RX, w.winfo_rooty() - RY,
            w.winfo_width(), w.winfo_height())


head = app.btn_update.master
hx, hy, hw, hh = rel(head)
print(f"头部区域: x={hx} y={hy} w={hw} h={hh}\n")

print("头部子控件（按 x 排序）:")
items = []
for ch in head.winfo_children():
    x, y, w, h = rel(ch)
    label = ""
    try:
        if ch.winfo_class() == "Label":
            label = ch.cget("text")[:14]
        elif ch.winfo_class() == "Canvas":
            label = getattr(ch, "_text", "")[:14]
    except Exception:
        pass
    items.append((x, ch.winfo_class(), w, h, label))

items.sort()
prev_right = hx
overlap = False
for x, cls, w, h, label in items:
    flag = ""
    if x < prev_right - 2:
        flag = "  <-- 重叠!"
        overlap = True
    print(f"  x={x:4d} w={w:3d} h={h:2d}  {cls:8s} {label}{flag}")
    prev_right = max(prev_right, x + w)

print()
print(f"头部右边界: {hx + hw} / 窗口宽 {RW}")
print(f"子控件最右: {max(x + w for x, _, w, _, _ in items)}")

print("\n关键元素:")
for name, attr in [("版本号", "ver_lbl"), ("检查更新按钮", "btn_update"),
                   ("状态标签", "state_lbl"), ("电平", "meter_lbl")]:
    wd = getattr(app, attr, None)
    if wd is None:
        print(f"  {name}: 缺失")
        continue
    x, y, w, h = rel(wd)
    print(f"  {name:14s} x={x:4d} w={w:3d} 右={x+w:4d}  {'OK' if x + w <= RW else '超出窗口'}")

# 检查按钮和其他元素是否重叠
bx, _, bw, _ = rel(app.btn_update)
sx, _, sw, _ = rel(app.state_lbl)
vx, _, vw, _ = rel(app.ver_lbl)
print()
print(f"版本号右边界 {vx+vw} <= 按钮左 {bx} ? {vx + vw <= bx}")
print(f"按钮右边界 {bx+bw} <= 状态左 {sx} ? {bx + bw <= sx}")

app.shutdown()
print("\n" + ("布局 OK ✅" if not overlap and bx + bw <= sx else "布局有问题 ❌"))