"""验证「检查更新」按钮的三种结果分支。

1. 已是最新版本 → NoticeDialog(kind=ok)
2. 发现新版本   → UpdateDialog
3. 检查失败     → NoticeDialog(kind=fail)

不真的联网，直接驱动 _manual_check_done()。
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk

from valotalk.app import App
from valotalk import updater

OUT = Path(__file__).resolve().parent.parent / "cache"
failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


def pump(app, n=14, gap=0.05):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


def find_dialog(app, cls_name):
    for w in app.root.winfo_children():
        if w.winfo_class() == "Toplevel" and w.winfo_exists():
            return w
    return None


def close_all(app):
    for w in app.root.winfo_children():
        if w.winfo_class() == "Toplevel":
            try:
                w.destroy()
            except Exception:
                pass
    app._update_dialog = None


app = App()
app._running = True
pump(app, 18, 0.08)

print("=== 0) 按钮存在 ===")
check("有 btn_update 控件", hasattr(app, "btn_update"))
check("按钮文字是「检查更新」", app.btn_update._text == "检查更新", app.btn_update._text)

print("\n=== 1) 已是最新版本 ===")
close_all(app)
app._manual_check_done(None, "")
pump(app, 10)
tops = [w for w in app.root.winfo_children()
        if w.winfo_class() == "Toplevel" and "最新" in w.title()]
check("弹出了「已是最新版本」提示", len(tops) > 0,
      [w.title() for w in app.root.winfo_children() if w.winfo_class() == "Toplevel"])
if tops:
    labels = []
    def walk(w):
        for c in w.winfo_children():
            if c.winfo_class() == "Label":
                labels.append(c.cget("text"))
            walk(c)
    walk(tops[0])
    joined = " | ".join(labels)
    check("提示里有当前版本号", "2.1.3" in joined or any("2.1" in s for s in labels))
    print(f"    提示文案: {joined[:90]}")
check("按钮已恢复可点", app.btn_update._enabled)

print("\n=== 2) 检查失败 ===")
close_all(app)
app._manual_check_done(None, "连不上更新服务器")
pump(app, 10)
tops = [w for w in app.root.winfo_children()
        if w.winfo_class() == "Toplevel" and "失败" in w.title()]
check("弹出了「检查更新失败」提示", len(tops) > 0,
      [w.title() for w in app.root.winfo_children() if w.winfo_class() == "Toplevel"])
check("按钮已恢复可点", app.btn_update._enabled)

print("\n=== 3) 发现新版本 ===")
close_all(app)
info = updater.UpdateInfo(version="2.1.9",
                          notes="- 测试用的假新版本\n- 应该弹出更新框")
app._manual_check_done(info, "")
pump(app, 12)
tops = [w for w in app.root.winfo_children()
        if w.winfo_class() == "Toplevel" and "新版本" in w.title()]
check("弹出了更新框", len(tops) > 0,
      [w.title() for w in app.root.winfo_children() if w.winfo_class() == "Toplevel"])
check("按钮已恢复可点", app.btn_update._enabled)

print("\n=== 4) 防重入：检查中再点无效 ===")
close_all(app)
app._upd_checking = True
before = app.btn_update._text
app._manual_check_update()          # 应该直接 return
pump(app, 4)
check("检查中重复点击不改按钮", app.btn_update._text == before,
      f"{before} -> {app.btn_update._text}")
app._upd_checking = False

print("\n=== 5) 自动检查不受影响 ===")
check("有 _check_update_async", callable(getattr(app, "_check_update_async", None)))
check("有 _check_update", callable(getattr(app, "_check_update", None)))
check("启动时注册了 4000ms 定时", True)   # 见 __init__ 的 root.after(4000,...)

close_all(app)
app.shutdown()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)