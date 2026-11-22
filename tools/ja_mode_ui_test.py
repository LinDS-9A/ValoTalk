"""验证日服模式下的 UI 显示（大模型链路标签 / 无 key 提示 / 布局）。

用 config_guard 包住 —— 这个测试会临时清空 api_key 验证提示文案，
而 App 里任何 save=True 的操作都会把内存写盘，不加保护会清掉用户的 key。
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

from valotalk.app import App
from valotalk.config import CONFIG

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


with config_guard():
    app = App()
    app._running = True
    pump(app, 20, 0.08)

    print("=== 1) 英服：本地识别（关掉大模型开关）===")
    CONFIG.set("asr.backend", "local", save=False)
    app.v_big_asr.set(False)
    CONFIG.set("asr.lang_teammates", "en", save=False)
    app._refresh_asr_mode_label("en")
    pump(app, 4)
    txt = app.asr_mode_lbl.cget("text")
    print(f"  标签: {txt!r}")
    check("英服显示本地识别", "本地" in txt, txt)

    print("\n=== 2) 日服：大模型链路（开着）===")
    CONFIG.set("asr.backend", "cloud", save=False)
    app.v_big_asr.set(True)
    CONFIG.set("asr.lang_teammates", "ja", save=False)
    app._refresh_asr_mode_label("ja")
    pump(app, 4)
    txt = app.asr_mode_lbl.cget("text")
    print(f"  标签: {txt!r}")
    check("日服显示云端服务商", "☁" in txt or "大模型" in txt or "百炼" in txt
          or "DeepSeek" in txt, txt)
    check("提到 LLM 翻译", "LLM" in txt, txt)

    print("\n=== 3) 没配 key 时提示 ===")
    CONFIG.set("asr.cloud_api_key", "", save=False)
    CONFIG.set("translate.llm.api_key", "", save=False)
    app.asr_cloud.close()
    app._refresh_asr_mode_label("ja")
    pump(app, 4)
    txt = app.asr_mode_lbl.cget("text")
    print(f"  标签: {txt!r}")
    check("提示没配 key", "key" in txt.lower(), txt)
    check("颜色是橙色", app.asr_mode_lbl.cget("fg") == "#FF9F0A",
          app.asr_mode_lbl.cget("fg"))
    # 顺手看大模型开关旁边的标签
    check("开关旁也提示未配 key",
          "key" in app.big_asr_lbl.cget("text").lower(),
          app.big_asr_lbl.cget("text"))

    print("\n=== 4) 切服务器会刷新标签 ===")
    # 先恢复一个可用的 key（仅内存，guard 兜底）
    CONFIG.set("translate.llm.api_key", "sk-test-fake-for-ui", save=False)
    app.asr_cloud.close()
    CONFIG.set("asr.backend", "cloud", save=False)
    app.v_big_asr.set(True)

    app.cb_server.set("日服（日语）")
    app._on_server_change()
    pump(app, 8)
    t_ja = app.asr_mode_lbl.cget("text")
    print(f"  切到日服: {t_ja!r}")
    check("日服标签有内容", len(t_ja) > 2, t_ja)

    app.cb_server.set("港/美服（英语）")
    app._on_server_change()
    pump(app, 8)
    t_en = app.asr_mode_lbl.cget("text")
    print(f"  切回英服: {t_en!r}")
    check("英服也显示云端（开关开着）",
          "☁" in t_en or "百炼" in t_en or "DeepSeek" in t_en, t_en)

    # 关掉开关，英服应变本地
    app.v_big_asr.set(False)
    app._on_big_asr_toggle()
    pump(app, 6)
    CONFIG.set("asr.lang_teammates", "en", save=False)
    app._refresh_asr_mode_label("en")
    pump(app, 4)
    t_en2 = app.asr_mode_lbl.cget("text")
    print(f"  关开关后英服: {t_en2!r}")
    check("关掉后英服变本地", "本地" in t_en2, t_en2)

    print("\n=== 5) 布局 ===")
    RX = app.root.winfo_rootx()
    RW = app.root.winfo_width()
    for nm, wd in (("大模型开关", app.chk_big_asr), ("开关标签", app.big_asr_lbl),
                   ("服务器标签", app.asr_mode_lbl)):
        x = wd.winfo_rootx() - RX
        w = wd.winfo_width()
        print(f"  {nm:12s} x={x:4d} w={w:3d} 右={x+w:4d} / {RW}")
        check(f"{nm} 在窗口内", x + w <= RW)

    app.shutdown()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)