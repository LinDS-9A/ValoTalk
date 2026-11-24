"""更新提示弹窗（iOS 风格，和主界面一致）。"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from . import __version__
from . import ui_theme as ui
from .updater import UpdateInfo

__all__ = ["UpdateDialog", "NoticeDialog"]


class NoticeDialog:
    """轻提示框：手动检查更新后告诉用户结果（已是最新 / 检查失败）。

    不做成 messagebox 是为了和主界面配色一致。
    """

    def __init__(self, master: tk.Tk, title: str, message: str,
                 kind: str = "info"):
        self.top = tk.Toplevel(master)
        self.top.title(title)
        self.top.configure(bg=ui.BG)
        self.top.attributes("-topmost", True)
        self.top.resizable(False, False)

        wrap = tk.Frame(self.top, bg=ui.BG)
        wrap.pack(fill="both", expand=True, padx=22, pady=18)

        head = tk.Frame(wrap, bg=ui.BG)
        head.pack(fill="x")

        icon, color = {
            "ok":   ("✓", ui.GREEN),
            "warn": ("⚠", ui.ORANGE),
            "fail": ("✕", ui.RED),
        }.get(kind, ("ℹ", ui.BLUE))

        tk.Label(head, text=icon, bg=ui.BG, fg=color,
                 font=(ui.FONT, 20, "bold")).pack(side="left")
        tk.Label(head, text=title, bg=ui.BG, fg=ui.TEXT,
                 font=(ui.FONT, 13, "bold"), anchor="w").pack(
            side="left", padx=(10, 0))

        tk.Label(wrap, text=message, bg=ui.BG, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS), anchor="w", justify="left",
                 wraplength=330).pack(fill="x", pady=(12, 16))

        row = tk.Frame(wrap, bg=ui.BG)
        row.pack(fill="x")
        ui.RoundButton(row, "确定", command=self.top.destroy,
                       width=88, height=32, fill=ui.BLUE, bold=True,
                       bg=ui.BG).pack(side="right")

        self.top.bind("<Return>", lambda _e: self.top.destroy())
        self.top.bind("<Escape>", lambda _e: self.top.destroy())

        # 居中
        self.top.update_idletasks()
        w = max(self.top.winfo_width(), 380)
        h = max(self.top.winfo_height(), 160)
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 3
        self.top.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        self.top.lift()
        self.top.focus_force()


class UpdateDialog:
    """发现新版本 → 下次再说 / 立即更新。

    下载和覆盖都在后台线程，主线程只刷新界面。
    """

    def __init__(self, master: tk.Tk, info: UpdateInfo, updater,
                 on_applied: Callable[[], None], log: Callable[[str], None],
                 on_later: Callable[[], None] | None = None):
        self.info = info
        self.updater = updater
        self.on_applied = on_applied
        self.log = log
        self.on_later = on_later
        self._busy = False
        self._staging = None
        # worker 线程只写这几个字段，界面由主线程 _tick() 轮询刷新
        # —— 跨线程直接调 tkinter.after() 会丢回调，之前就是卡在「正在下载」
        self._state = "idle"      # idle / downloading / applying / done / failed
        self._err = ""
        self._pct = 0
        self._prog_label = ""
        self._stop_tick = False

        self.top = tk.Toplevel(master)
        self.top.title("发现新版本")
        self.top.configure(bg=ui.BG)
        self.top.attributes("-topmost", True)
        self.top.resizable(False, False)
        self.top.protocol("WM_DELETE_WINDOW", self._later)

        self._build()
        self._center(master)

    # ---------------------------------------------------------------- UI
    def _is_beta(self) -> bool:
        """这个更新是不是测试版。

        优先用 updater 读到的远端标记（info.prerelease）—— 它去远端
        __init__.py 看 PRERELEASE，版本号是纯数字（3.0.1）也能判断准。
        拿不到标记时退回看版本号字符串。
        """
        v = str(getattr(self.info, "version", "") or "").lower()
        if any(k in v for k in ("beta", "alpha", "rc", "pre")):
            return True
        pre = getattr(self.info, "prerelease", None)
        if pre is not None:
            return bool(pre)
        try:
            from . import PRERELEASE
            return bool(PRERELEASE)
        except Exception:
            return False

    def _build(self) -> None:
        pad = 20
        wrap = tk.Frame(self.top, bg=ui.BG)
        wrap.pack(fill="both", expand=True, padx=pad, pady=pad)

        # 标题行
        head = tk.Frame(wrap, bg=ui.BG)
        head.pack(fill="x")
        tk.Label(head, text="🎉", bg=ui.BG, fg=ui.TEXT,
                 font=(ui.FONT, 22)).pack(side="left")
        box = tk.Frame(head, bg=ui.BG)
        box.pack(side="left", padx=(10, 0))
        tk.Label(box, text="发现新版本", bg=ui.BG, fg=ui.TEXT,
                 font=(ui.FONT, 14, "bold"), anchor="w").pack(anchor="w")
        ver_row = tk.Frame(box, bg=ui.BG)
        ver_row.pack(anchor="w")
        tk.Label(ver_row, text=f"v{__version__}  →  v{self.info.version}",
                 bg=ui.BG, fg=ui.BLUE,
                 font=(ui.FONT, ui.FS), anchor="w").pack(side="left")

        # 测试版徽章：老用户从正式版升上来时，得先知道这版是 beta
        if self._is_beta():
            badge = tk.Label(ver_row, text=" 测试版 ", bg=ui.ORANGE,
                             fg="#FFFFFF", font=(ui.FONT, 8, "bold"))
            badge.pack(side="left", padx=(8, 0))

        if self._is_beta():
            warn = tk.Label(
                wrap,
                text="⚠ 这是测试版：界面和功能还在调整，可能不稳定。\n"
                     "  建议先备份当前版本（安装时会自动备份到 cache/update/backup/）。",
                bg=ui.BG, fg=ui.ORANGE, font=(ui.FONT, ui.FS_SMALL),
                justify="left", anchor="w", wraplength=430)
            warn.pack(fill="x", pady=(10, 0))

        # 更新说明
        notes = (self.info.notes or "").strip()
        tk.Label(wrap, text="更新内容", bg=ui.BG, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL, "bold"), anchor="w").pack(
            fill="x", pady=(16, 6))

        txt_wrap = tk.Frame(wrap, bg=ui.CARD)
        txt_wrap.pack(fill="both", expand=True)
        self.txt = tk.Text(txt_wrap, height=9, width=52, bg=ui.CARD, fg=ui.TEXT2,
                           insertbackground=ui.TEXT, font=(ui.FONT, ui.FS_SMALL),
                           relief="flat", bd=0, highlightthickness=0,
                           wrap="word", padx=10, pady=8)
        self.txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(txt_wrap, command=self.txt.yview,
                           style="Vertical.TScrollbar")
        sb.pack(side="right", fill="y")
        self.txt.configure(yscrollcommand=sb.set)

        self.txt.insert("1.0", notes or
                        "这个版本修复了一些问题、优化了体验。\n\n"
                        "（详细说明可在 GitHub Releases 页面查看）")
        self.txt.configure(state="disabled")

        # 进度条（默认隐藏）
        self.prog_wrap = tk.Frame(wrap, bg=ui.BG)
        self.prog = ui.RoundProgress(self.prog_wrap, width=380, height=8, bg=ui.BG)
        self.prog.pack(side="left", fill="x", expand=True)
        self.prog_lbl = tk.Label(self.prog_wrap, text="", bg=ui.BG,
                                 fg=ui.TEXT3, font=(ui.FONT, ui.FS_SMALL),
                                 width=11, anchor="e")
        self.prog_lbl.pack(side="right", padx=(8, 0))

        # 底部按钮
        row = tk.Frame(wrap, bg=ui.BG)
        row.pack(fill="x", pady=(16, 0))
        self.hint = tk.Label(row, text="", bg=ui.BG, fg=ui.TEXT3,
                             font=(ui.FONT, ui.FS_SMALL), anchor="w")
        self.hint.pack(side="left")

        self.btn_now = ui.RoundButton(row, "立即更新", command=self._update_now,
                                      width=104, height=34, fill=ui.BLUE,
                                      bold=True, bg=ui.BG)
        self.btn_now.pack(side="right")
        self.btn_later = ui.RoundButton(row, "下次再说", command=self._later,
                                        width=96, height=34, fill=ui.CARD2,
                                        bg=ui.BG)
        self.btn_later.pack(side="right", padx=(0, 8))

    def _center(self, master: tk.Tk) -> None:
        self.top.update_idletasks()
        w, h = max(self.top.winfo_width(), 480), max(self.top.winfo_height(), 400)
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 3
        self.top.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")

    # ---------------------------------------------------------------- 动作
    def _later(self) -> None:
        if self._busy:
            self.updater.cancel()
            self._stop_tick = True
            self.top.destroy()
            return
        # 记住这个版本，下次启动不再弹（除非有更新的版本）
        if self.on_later:
            try:
                self.on_later()
            except Exception:
                pass
        self.top.destroy()

    def _update_now(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.btn_now.set_text("取消")
        self.btn_later.set_enabled(False)
        self.btn_now.set_command(self._cancel)
        self.prog_wrap.pack(fill="x", pady=(12, 0), before=self.hint.master)
        self.prog.set_value(0)
        self._set_hint("正在下载 …", ui.TEXT2)
        self._state = "downloading"
        self._pct = 0
        self._prog_label = "连接中"
        threading.Thread(target=self._worker, daemon=True).start()
        self._tick()

    def _cancel(self) -> None:
        self.updater.cancel()
        self._set_hint("正在取消 …", ui.TEXT3)

    def _worker(self) -> None:
        """只改字段，绝不碰 tkinter。"""
        def progress(done: int, total: int) -> None:
            self._pct = int(done * 100 / max(total, 1))
            self._prog_label = f"{done}/{total}"

        try:
            staging = self.updater.download(self.info, progress=progress)
            if staging is None:
                self._err = self.updater.last_error or "下载失败"
                self._state = "failed"
                return
            self._pct = 100
            self._prog_label = "校验完成"
            self._state = "applying"
            self.log("[更新] 下载完成，开始覆盖 …")
            if not self.updater.apply(staging):
                self._err = self.updater.last_error or "覆盖失败"
                self._state = "failed"
                return
            self._state = "done"
        except Exception as exc:
            self._err = f"{type(exc).__name__}: {exc}"
            self._state = "failed"

    def _tick(self) -> None:
        """主线程 120ms 刷一次状态。"""
        if self._stop_tick:
            return
        st = self._state
        try:
            if st in ("downloading", "applying"):
                self.prog.set_value(self._pct)
                self.prog_lbl.configure(text=self._prog_label)
                if st == "applying":
                    self._set_hint("正在覆盖文件 …", ui.TEXT2)
            elif st == "done":
                self._applied()
                return
            elif st == "failed":
                self._failed(self._err)
                return
        except Exception:
            pass
        self.top.after(120, self._tick)

    # ---------------------------------------------------------------- 界面回调
    def _set_hint(self, text: str, color: str = ui.TEXT3) -> None:
        try:
            self.hint.configure(text=text, fg=color)
        except Exception:
            pass

    def _failed(self, err: str) -> None:
        self._busy = False
        try:
            self.prog_wrap.pack_forget()
            self.btn_later.set_enabled(True)
            self.btn_now.set_text("重试")
            self.btn_now.set_command(self._update_now)
            self._set_hint("失败：" + err[:40], ui.RED)
        except Exception:
            pass
        self.log(f"[更新] {err}")

    def _applied(self) -> None:
        self._busy = False
        try:
            self.prog.set_value(100)
            self.prog_lbl.configure(text="完成")
            self._set_hint("更新完成，重启后生效", ui.GREEN)
            self.btn_now.set_text("立即重启")
            self.btn_now.set_command(self._restart)
            self.btn_later.set_enabled(True)
            self.txt.configure(state="normal")
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0",
                            f"已更新到 v{self.info.version}，备份保存在 cache/update/backup/。\n\n"
                            "点「立即重启」关闭并重新打开 ValoTalk。")
            self.txt.configure(state="disabled")
        except Exception:
            pass

    def _restart(self) -> None:
        self.top.destroy()
        self.on_applied()