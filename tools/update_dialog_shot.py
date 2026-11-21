"""更新弹窗外观 + 交互验证（不真更新）。

把版本号伪造成 2.1.3 弹窗，截图，然后销毁。
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App
from valotalk import updater
from valotalk.update_ui import UpdateDialog

OUT = Path(__file__).resolve().parent.parent / "cache"


def pump(app, n=12, gap=0.06):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


def shot(win, path, pad=12):
    import mss
    import numpy as np
    from PIL import Image
    factory = getattr(mss, "MSS", None) or mss.mss
    win.update_idletasks()
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    with factory() as sct:
        g = sct.grab({"left": x - pad, "top": y - pad,
                      "width": w + pad * 2, "height": h + pad * 2})
        arr = np.asarray(g)[:, :, :3][:, :, ::-1]
    Image.fromarray(arr).save(path)
    print(f"  已保存 {path.name}  ({w}x{h})")


def main():
    app = App()
    app._running = True
    pump(app, 16, 0.08)

    # 伪造一个新版本
    info = updater.UpdateInfo(
        version="2.1.3",
        notes=("## 试听卡顿/鬼畜音修复\n"
               "- 播放锁改成类级，同一时间只允许一个播放\n"
               "- sd.play() + sd.wait()，播完才返回\n\n"
               "## LLM 自测误报\n"
               "- test_llm() 绕过缓存和直出表，直接打 LLM 接口"),
    )
    dlg = UpdateDialog(app.root, info, app.updater,
                       on_applied=lambda: print("  [回调] 重启"),
                       log=app.log,
                       on_later=lambda: print("  [回调] 下次再说"))
    pump(app, 18, 0.08)
    shot(dlg.top, OUT / "update_dialog.png")

    # 验证控件状态
    print("\n控件状态:")
    print("  标题:", dlg.top.title())
    print("  立即更新按钮:", dlg.btn_now._text)
    print("  下次再说按钮:", dlg.btn_later._text)
    print("  说明文字长度:", len(dlg.txt.get("1.0", "end").strip()))
    print("  进度条可见:", bool(dlg.prog_wrap.winfo_manager()))
    print("  hint:", dlg.hint.cget("text") or "(空)")

    dlg.top.destroy()
    app.shutdown()


if __name__ == "__main__":
    main()