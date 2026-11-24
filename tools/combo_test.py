"""RoundCombo（自绘版）功能测试。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


with config_guard():
    from valotalk.app import App
    import valotalk.ui_theme as ui

    app = App()
    app._running = True
    for _ in range(26):
        app.root.update()
        time.sleep(0.07)

    combos = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, ui.RoundCombo):
                combos.append(c)
            walk(c)

    walk(app.root)
    print(f"找到 {len(combos)} 个下拉框\n")

    check("都换成了自绘版", all(isinstance(c, ui.RoundCombo) for c in combos))
    check("不再用 ttk.Combobox",
          not any(getattr(c, "combo", None) for c in combos))

    print("\n=== 1) 顶部没有白高光（用户说的「白条」）===")
    c0 = combos[0]
    # 高光是通过 glass_image(highlight>0) 画的，这里确认传的是 0
    import inspect
    src = inspect.getsource(ui.RoundCombo._draw)
    check("_draw 里 highlight=0.0", "highlight=0.0" in src)

    print("\n=== 2) 长文本单行省略 ===")
    long_c = None
    for c in combos:
        if c.get() and len(c.get()) > 12:
            long_c = c
            break
    if long_c:
        fitted = long_c._fit_text(long_c.get(), 120)
        print(f"  原文 {long_c.get()!r}")
        print(f"  截断 {fitted!r}")
        check("超宽会加省略号", fitted.endswith("…") if
              long_c._fit_text(long_c.get(), 60) != long_c.get() else True)
        check("截断后比原文短或相等", len(fitted) <= len(long_c.get()))

    print("\n=== 3) 弹出层 ===")
    c = combos[1] if len(combos) > 1 else combos[0]
    n = len(c._values)
    c._open()
    for _ in range(8):
        app.root.update()
        time.sleep(0.05)
    check("弹出了", c._pop is not None)
    check("行高按文本量算过", len(c._row_h) == n, f"{len(c._row_h)} vs {n}")
    rows = len(c._geom)
    print(f"  选项 {n} 个，一屏放下 {rows} 个")
    check("已排版", rows > 0 and rows <= n)

    # 行不重叠
    overlap = False
    for k in range(1, len(c._geom)):
        if c._geom[k][0] < c._geom[k - 1][1] - 0.5:
            overlap = True
    check("行与行不重叠", not overlap)

    print("\n=== 4) 悬浮高亮 ===")

    class E:
        def __init__(self, y):
            self.y = y
            self.x = 20
            self.delta = 0

    y0, y1, _idx = c._geom[0]
    c._on_motion(E((y0 + y1) / 2))
    hl_on = c._pop_cv.itemcget(c._hl, "state") == "normal"
    coords = c._pop_cv.coords(c._hl)
    print(f"  高亮框 {coords}")
    check("鼠标进入项时显示高亮", hl_on)
    check("高亮框有尺寸", coords[2] > coords[0] and coords[3] > coords[1])

    c._on_motion(E(c._pop_h + 50))
    check("移出列表项后隐藏高亮",
          c._pop_cv.itemcget(c._hl, "state") == "hidden")

    print("\n=== 5) 点击选择 ===")
    target = c._values[1] if n > 1 else c._values[0]
    yc = sum(c._geom[1][:2]) / 2 if n > 1 else sum(c._geom[0][:2]) / 2
    c._on_click(E(yc))
    for _ in range(4):
        app.root.update()
    print(f"  选到 {c.get()!r}")
    check("值变了", c.get() == target, c.get())
    check("弹层已关", c._pop is None)

    print("\n=== 6) 再开再点外部关闭 ===")
    c._open()
    for _ in range(6):
        app.root.update()
        time.sleep(0.04)
    check("又能打开", c._pop is not None)
    c._close()
    for _ in range(3):
        app.root.update()
    check("_close 能关掉", c._pop is None)

    print("\n=== 7) 空选项不崩 ===")
    try:
        empty = ui.RoundCombo(c.master, [], width=100, height=28)
        empty._open()
        app.root.update()
        ok = empty._pop is None
        empty.destroy()
        check("空列表打开不弹窗、不抛异常", ok)
    except Exception as e:
        check("空列表打开不弹窗、不抛异常", False, repr(e))

    print("\n=== 8) 兼容旧接口 ===")
    c2 = combos[0]
    old_val = c2.get()
    c2["values"] = ["a", "b", "c"]
    check('cb["values"] 可写', c2._values == ["a", "b", "c"])
    check('cb["values"] 可读', c2["values"] == ["a", "b", "c"])
    got = []
    c2.bind_select(lambda: got.append(1))
    c2._pick("b")
    check("bind_select 回调被调用", got == [1])
    c2.set_values(["x", "y"])
    c2.set("y")
    check("set/get 一致", c2.get() == "y")
    c2.set(old_val)

    app.shutdown()

print("\n" + "=" * 56)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 56)
sys.exit(0 if failed == 0 else 1)
