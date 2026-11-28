"""屏幕下方悬浮字幕窗：无边框、置顶、文字背景全透明、可点击穿透。"""
from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass

from . import winapi

TRANSPARENT_KEY = "#010203"   # 用作 colorkey，屏幕上看不见
TAG_COLORS = {
    "队友": "#7DD3FC",        # 天蓝
    "我": "#FCA5A5",          # 浅红
    "聊天": "#FCD34D",        # 琥珀
    "系统": "#94A3B8",
}


@dataclass
class Item:
    tag: str
    text: str
    original: str
    created: float
    ttl: float


class Overlay:
    def __init__(self, root: tk.Tk, cfg_get, cfg_set):
        self.root = root
        self._get = cfg_get
        self._set = cfg_set
        self.items: list[Item] = []
        self._click_through = bool(cfg_get("overlay.click_through", True))
        self._hwnd = 0
        self.on_moved = None        # 拖动结束后的回调（面板刷新坐标用）

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(bg=TRANSPARENT_KEY)
        try:
            self.win.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
        except Exception:
            pass
        self.win.wm_attributes("-topmost", True)
        try:
            self.win.wm_attributes("-alpha", 1.0)
        except Exception:
            pass

        self.canvas = tk.Canvas(self.win, bg=TRANSPARENT_KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self._apply_geometry()
        self.win.update_idletasks()
        self._hwnd = winapi.top_level_hwnd(self.win)
        winapi.set_click_through(self._hwnd, self._click_through)
        winapi.keep_topmost(self._hwnd)

        self._loop()

    # ---------------- 几何 ----------------
    def _apply_geometry(self) -> None:
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        width = int(self._get("overlay.width", 1120) or 1120)
        height = int(self._get("overlay.height", 380) or 380)
        width = min(width, sw - 40)
        height = min(height, max(160, int(sh * 0.42)))
        x = int(self._get("overlay.x", -1))
        y = int(self._get("overlay.y", -1))
        if x < 0:
            x = max(0, (sw - width) // 2)
        if y < 0:
            y = max(0, sh - height - 80)      # 屏幕下方
        self.width, self.height = width, height
        self.win.geometry(f"{width}x{height}+{x}+{y}")
        self.x, self.y = x, y

    def reset_position(self) -> None:
        """重新贴到屏幕下方居中。"""
        self._set("overlay.x", -1, save=False)
        self._set("overlay.y", -1, save=False)
        self._apply_geometry()
        winapi.keep_topmost(self._hwnd)
        self._render()

    # ---------------- 字号 / 位置（面板可调） ----------------
    FONT_MIN = 12
    FONT_MAX = 48

    def font_size(self) -> int:
        try:
            return int(self._get("overlay.font_size", 19) or 19)
        except (TypeError, ValueError):
            return 19

    def set_font_size(self, size: int, save: bool = True) -> int:
        """改字号并立刻重绘。返回实际生效的字号（已钳到 12~48）。"""
        size = max(self.FONT_MIN, min(self.FONT_MAX, int(size)))
        self._set("overlay.font_size", size, save=save)
        self._render()
        return size

    def move_by(self, dx: int = 0, dy: int = 0, save: bool = True) -> tuple[int, int]:
        """按像素微调位置。返回新 (x, y)。"""
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        # 别让字幕整个跑出屏幕：左右至少留 120px 可见，上下留 60px
        nx = max(-self.width + 120, min(sw - 120, self.x + int(dx)))
        ny = max(-60, min(sh - 60, self.y + int(dy)))
        self.win.geometry(f"+{nx}+{ny}")
        self.x, self.y = nx, ny
        self._set("overlay.x", nx, save=False)
        self._set("overlay.y", ny, save=save)
        self._render()
        return nx, ny

    def nudge_up(self, step: int = 20) -> None:
        self.move_by(0, -step)

    def nudge_down(self, step: int = 20) -> None:
        self.move_by(0, +step)

    def nudge_left(self, step: int = 20) -> None:
        self.move_by(-step, 0)

    def nudge_right(self, step: int = 20) -> None:
        self.move_by(+step, 0)

    def preview(self, text: str = "", ttl: float = 2.5) -> None:
        """调字号/位置时给一条临时字幕，让用户立刻看见效果。"""
        if not text:
            text = f"字幕预览 · 字号 {self.font_size()}"
        self.items.append(Item("系统", text, "", time.time(), ttl))
        self._render()
        winapi.keep_topmost(self._hwnd)

    def save_position(self) -> None:
        """把当前位置写盘（拖动结束后调用）。"""
        self._set("overlay.x", self.x, save=False)
        self._set("overlay.y", self.y, save=True)
        if callable(self.on_moved):
            try:
                self.on_moved(self.x, self.y)
            except Exception:
                pass

    # ---------------- 点击穿透 ----------------
    def set_click_through(self, enabled: bool) -> None:
        self._click_through = bool(enabled)
        self._set("overlay.click_through", self._click_through)
        if self._hwnd:
            winapi.set_click_through(self._hwnd, self._click_through)
        self._toast_state()

    def toggle_click_through(self) -> None:
        self.set_click_through(not self._click_through)

    # ---------------- 内容 ----------------
    def add(self, tag: str, text: str, original: str = "", ttl: float | None = None) -> None:
        if not text:
            return
        ttl = float(ttl if ttl is not None else self._get("overlay.ttl_seconds", 30) or 30)
        self.root.after(0, self._add_main, tag, text, original, ttl)

    def _add_main(self, tag: str, text: str, original: str, ttl: float) -> None:
        self.items.append(Item(tag, text, original or "", time.time(), ttl))
        max_lines = int(self._get("overlay.max_lines", 6) or 6)
        if len(self.items) > max_lines:
            self.items = self.items[-max_lines:]
        self._render()
        # 有新字幕时才主动置顶一次，平时交给 3 秒的保底检查
        winapi.keep_topmost(self._hwnd)
        self._last_top = time.time()

    def recent(self, n: int = 5) -> list:
        """最近 n 条字幕（给热键回看用）。"""
        try:
            return list(self.items)[-max(1, n):]
        except Exception:
            return []

    def clear(self) -> None:
        self.root.after(0, self._clear_main)

    def _clear_main(self) -> None:
        self.items.clear()
        self.canvas.delete("all")

    def _toast_state(self) -> None:
        state = "字幕可拖动" if not self._click_through else "字幕已穿透（不挡鼠标）"
        self.root.after(0, lambda: self._add_main("系统", state, "", 3.0))

    # ---------------- 渲染 ----------------
    def _render(self) -> None:
        c = self.canvas
        c.delete("all")
        if not self.items:
            return
        fam = self._get("overlay.font_family", "Microsoft YaHei UI")
        size = int(self._get("overlay.font_size", 26) or 26)
        show_orig = bool(self._get("overlay.show_original", True))
        pad = 10
        wrap = max(120, self.width - pad * 2 - 8)

        # 组装块：每块 (文本, 字体, 颜色)
        blocks: list[tuple[str, tuple, str, int]] = []
        for it in self.items:
            color = TAG_COLORS.get(it.tag, "#FFFFFF")
            head = f"[{it.tag}] " if it.tag else ""
            # 负号 = 像素单位，不受 tk scaling 影响，游戏里所见即所得
            blocks.append((head + it.text, (fam, -size, "bold"), color, 6))
            if show_orig and it.original:
                blocks.append((it.original, (fam, -max(12, size - 8)), "#A9B6C4", 10))

        # 先量高
        measured = []
        for text, font, color, gap in blocks:
            tid = c.create_text(pad, 0, anchor="nw", text=text, font=font,
                                fill=color, width=wrap)
            x1, y1, x2, y2 = c.bbox(tid)
            h = max(1, y2 - y1)
            measured.append((tid, text, font, color, h, gap))

        total = sum(m[4] + m[5] for m in measured)
        # 超出窗口高度：从最早的行开始丢
        while total > self.height - 6 and measured:
            tid = measured[0][0]
            c.delete(tid)
            total -= measured[0][4] + measured[0][5]
            measured.pop(0)
        if not measured:
            return

        y = self.height - total - 2
        bg = bool(self._get("overlay.backdrop", False))
        outline = bool(self._get("overlay.outline", True))
        for tid, text, font, color, h, gap in measured:
            c.move(tid, 0, y)
            if bg:
                x1, y1, x2, y2 = c.bbox(tid)
                rect = c.create_rectangle(
                    x1 - 5, y1 - 2, x2 + 5, y2 + 2,
                    fill="#000000", outline="",
                )
                c.tag_lower(rect, tid)
            elif outline:
                # 无底色时靠描边保证在亮背景上也能看清。
                # 层数可调：8 层最清晰但 canvas item 翻倍，4 层够用且省一半重绘开销
                layers = int(self._get("overlay.outline_layers", 4) or 4)
                offsets = ((-1, 0), (1, 0), (0, -1), (0, 1),
                           (-1, -1), (1, -1), (-1, 1), (1, 1))[:layers]
                for dx, dy in offsets:
                    edge = c.create_text(pad + dx, y + dy, anchor="nw", text=text,
                                         font=font, fill="#000000", width=wrap)
                    c.tag_lower(edge, tid)
            y += h + gap

    # ---------------- 循环：过期清理 ----------------
    def _loop(self) -> None:
        try:
            now = time.time()
            ttl_default = float(self._get("overlay.ttl_seconds", 30) or 30)
            keep = [it for it in self.items if now - it.created < (it.ttl or ttl_default)]
            if len(keep) != len(self.items):
                self.items = keep
                self._render()
            # 置顶检查降到 3 秒一次：SetWindowPos 会打断全屏游戏的合成链路，
            # 频繁调用正是帧率在刷新率上限与 60 之间横跳的来源之一。
            interval = float(self._get("overlay.topmost_interval_s", 3.0) or 3.0)
            if now - getattr(self, "_last_top", 0.0) > interval:
                self._last_top = now
                winapi.keep_topmost(self._hwnd)
        except Exception:
            pass
        self.root.after(500, self._loop)

    # ---------------- 拖动（关闭穿透时可用） ----------------
    def bind_drag(self) -> None:
        def start(e):
            self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

        def move(e):
            if not hasattr(self, "_drag"):
                return
            dx, dy = self._drag
            nx, ny = e.x_root - dx, e.y_root - dy
            self.win.geometry(f"+{nx}+{ny}")
            self.x, self.y = nx, ny

        def end(_e):
            self.save_position()

        for w in (self.canvas, self.win):
            w.bind("<ButtonPress-1>", start)
            w.bind("<B1-Motion>", move)
            w.bind("<ButtonRelease-1>", end)