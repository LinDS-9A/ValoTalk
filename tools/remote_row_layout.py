"""检查手机遥控那一行的排布：文字、地址、二维码、开关是否互不重叠。"""
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


def pump(app, n=14, gap=0.06):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


app = App()
app._running = True
pump(app, 22, 0.08)
row = app.chk_remote
RX, RY = app.root.winfo_rootx(), app.root.winfo_rooty()


def rel(w):
    return (w.winfo_rootx() - RX, w.winfo_rooty() - RY,
            w.winfo_width(), w.winfo_height())


def dump(tag):
    rx, ry, rw, rh = rel(row)
    print(f"\n--- {tag} ---")
    print(f"  整行 x={rx} y={ry} w={rw} h={rh}")
    items = []
    for nm, w in (("文字", row._label), ("地址", app.remote_lbl),
                  ("二维码", app.btn_remote_qr), ("开关", row.switch)):
        x, y, ww, hh = rel(w)
        shown = bool(w.winfo_manager())
        items.append((x, ww, nm, shown, y, hh))
        print(f"  {nm:6s} x={x:4d} y={y:3d} w={ww:3d} h={hh:2d}  "
              f"{'显示' if shown else '隐藏'}")
    # 重叠检查（只比显示的）
    shown_items = [i for i in items if i[3]]
    shown_items.sort()
    for a, b in zip(shown_items, shown_items[1:]):
        gap = b[0] - (a[0] + a[1])
        ok = gap >= 0
        print(f"    {a[2]} → {b[2]} 间距 {gap}px {'✓' if ok else '✗ 重叠'}")
        check(f"{a[2]}和{b[2]}不重叠", ok, f"gap={gap}")
    # 都在这行里
    right = rx + rw
    for x, ww, nm, shown, _y, _hh in items:
        if shown:
            check(f"{nm} 没超出这行", x + ww <= right + 2,
                  f"{x + ww} vs {right}")


dump("关闭态")

# 打开
app.v_remote.set(True)
app._on_remote_toggle()
pump(app, 34, 0.06)
dump("开启态")

# 关掉复原
app.v_remote.set(False)
app._on_remote_toggle()
pump(app, 14, 0.06)
dump("再关闭")

# 其它行高度没被影响
print("\n其它开关行高度：")
for w in row.master.winfo_children():
    if w.winfo_class() == "Frame" and hasattr(w, "switch"):
        x, y, ww, hh = rel(w)
        label = w._label.cget("text")
        print(f"  {label:22s} h={hh}")

app.shutdown()
print("\n" + "=" * 46)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 46)
sys.exit(0 if failed == 0 else 1)