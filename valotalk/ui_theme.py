"""iOS 风格圆角控件库（tkinter + Pillow）。

tkinter 没有原生圆角，这里用 PIL 渲染抗锯齿的圆角图当背景，
控件内容叠在 Canvas 上。配色用 iOS 深色模式那套。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

# ---------------- 配色（iOS 深色模式） ----------------
BG = "#121212"          # 窗口背景（不用纯黑，圆角过渡更柔和）
CARD = "#1C1C1E"        # 卡片
CARD2 = "#2C2C2E"       # 二级卡片 / 输入框
CARD3 = "#3A3A3C"       # 三级 / hover
SEP = "#38383A"         # 分隔线
TEXT = "#FFFFFF"
TEXT2 = "#98989F"       # 次要文字
TEXT3 = "#636366"       # 更弱
BLUE = "#0A84FF"        # 主色
GREEN = "#30D158"       # 开关开
RED = "#FF453A"
YELLOW = "#FFD60A"
ORANGE = "#FF9F0A"

FONT = "Microsoft YaHei UI"
FS = 10                 # 正文字号
FS_SMALL = 9
FS_TITLE = 15

CARD_RADIUS = 16
BTN_RADIUS = 10
PILL_RADIUS = 20

_img_cache: dict[tuple, ImageTk.PhotoImage] = {}


def round_image(w: int, h: int, radius: int, color: str,
                outline: str | None = None, width: int = 1) -> ImageTk.PhotoImage:
    """生成抗锯齿圆角矩形，带缓存。"""
    w, h = max(1, int(w)), max(1, int(h))
    radius = max(0, min(int(radius), min(w, h) // 2))
    key = (w, h, radius, color, outline, width)
    cached = _img_cache.get(key)
    if cached is not None:
        return cached
    scale = 4                                   # 超采样再缩小，边缘更干净
    img = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (0, 0, w * scale - 1, h * scale - 1),
        radius=radius * scale,
        fill=color,
        outline=outline,
        width=width * scale if outline else 0,
    )
    img = img.resize((w, h), Image.LANCZOS)
    photo = ImageTk.PhotoImage(img)
    if len(_img_cache) > 400:                   # 别无限涨
        _img_cache.clear()
    _img_cache[key] = photo
    return photo


class RoundCard(tk.Canvas):
    """圆角卡片容器。子控件放进 .body。"""

    def __init__(self, master, radius: int = CARD_RADIUS, fill: str = CARD,
                 pad: int = 0, **kw):
        super().__init__(master, highlightthickness=0, bd=0, bg=BG, **kw)
        self.radius = radius
        self.fill = fill
        self.pad = pad
        self.body = tk.Frame(self, bg=fill)
        self._win = self.create_window(pad, pad, anchor="nw", window=self.body)
        self._bg_id = None
        self._autosize = True
        self.bind("<Configure>", self._redraw)
        self.body.bind("<Configure>", self._sync_height)

    def _sync_height(self, _event=None) -> None:
        """让画布高度跟着内容走，不用手写固定尺寸。"""
        if not self._autosize:
            return
        need = self.body.winfo_reqheight() + self.pad * 2
        if abs(need - int(self["height"])) > 2:
            self.configure(height=need)

    def _redraw(self, event=None) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        if self._bg_id is not None:
            self.delete(self._bg_id)
        photo = round_image(w, h, self.radius, self.fill)
        self._bg_id = self.create_image(0, 0, anchor="nw", image=photo)
        self.tag_lower(self._bg_id)
        self.itemconfig(self._win, width=max(1, w - self.pad * 2),
                        height=max(1, h - self.pad * 2))
        self._photo = photo                     # 保住引用，别被 GC

    def refresh(self) -> None:
        """往 .body 里动态增删控件之后必须调一次。

        卡片里的 body 高度是画布窗口项**强制**的，新加的控件没有空间就
        不会 map（也不触发 body 的 <Configure>），表现为「加了控件但看不见」。
        这里先放开强制高度，让 body 按自己的需求尺寸重新算，再同步画布。
        """
        try:
            self.itemconfig(self._win, height=0)
            self.update_idletasks()
            need = self.body.winfo_reqheight() + self.pad * 2
            if abs(need - int(self["height"])) > 0:
                self.configure(height=need)
            self.update_idletasks()
            self._redraw()
        except Exception:
            pass


class RoundButton(tk.Canvas):
    """圆角按钮，带 hover / 按下反馈。"""

    def __init__(self, master, text: str, command=None, width: int = 96,
                 height: int = 32, radius: int = BTN_RADIUS,
                 fill: str = CARD2, fg: str = TEXT, hover: str = CARD3,
                 font_size: int = FS, bold: bool = False, bg: str = CARD, **kw):
        # bg 必须是「父容器」的颜色：画布底色和圆角外露出的就是这个色，
        # 写死成窗口背景会在卡片里挖出四个暗角
        super().__init__(master, width=width, height=height,
                         highlightthickness=0, bd=0, bg=bg, **kw)
        self._text = text
        self._command = command
        self._fill = fill
        self._hover = hover
        self._fg = fg
        self._radius = radius
        self._font = (FONT, font_size, "bold") if bold else (FONT, font_size)
        self._enabled = True
        self._draw(fill)
        self.bind("<Enter>", lambda _e: self._draw(self._hover))
        self.bind("<Leave>", lambda _e: self._draw(self._fill))
        self.bind("<ButtonPress-1>", lambda _e: self._draw(self._hover))
        self.bind("<ButtonRelease-1>", self._on_release)

    def _draw(self, color: str) -> None:
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        photo = round_image(w, h, self._radius, color)
        self.create_image(0, 0, anchor="nw", image=photo)
        self._photo = photo
        fg = self._fg if self._enabled else TEXT3
        self.create_text(w // 2, h // 2, text=self._text,
                         fill=fg, font=self._font)

    def _on_release(self, event) -> None:
        self._draw(self._hover)
        inside = 0 <= event.x <= int(self["width"]) and 0 <= event.y <= int(self["height"])
        if inside and self._enabled and self._command:
            self._command()

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw(self._fill)

    def set_enabled(self, ok: bool) -> None:
        self._enabled = bool(ok)
        self._draw(self._fill)

    def set_command(self, command) -> None:
        """换绑点击回调（任务完成后把「更新」换成「重启」这类）。"""
        self._command = command

    def set_fill(self, fill: str) -> None:
        """换底色（开关类按钮用：开启绿、关闭灰）。"""
        self._fill = fill
        self._draw(fill)


class RoundProgress(tk.Canvas):
    """圆角进度条。ttk.Progressbar 在 clam 主题下样式不跟配色走，自己画。"""

    def __init__(self, master, width: int = 420, height: int = 8,
                 fill: str = BLUE, track: str = CARD2, bg: str = BG, **kw):
        super().__init__(master, width=width, height=height,
                         highlightthickness=0, bd=0, bg=bg, **kw)
        # 别用 self._w / self._h —— self._w 是 tkinter 内部的控件路径名，覆盖了会炸
        self._bar_w, self._bar_h = width, height
        self._fill, self._track = fill, track
        self._value = 0.0
        self._track_id = self.create_rectangle(
            0, 0, width, height, fill=track, outline="")
        self._bar_id = self.create_rectangle(
            0, 0, 0, height, fill=fill, outline="")

    def set_value(self, pct: float) -> None:
        self._value = max(0.0, min(100.0, float(pct)))
        w = self._bar_w * self._value / 100.0
        self.coords(self._bar_id, 0, 0, w, self._bar_h)

    def get_value(self) -> float:
        return self._value


class RoundEntry(tk.Frame):
    """圆角输入框：圆角背景 + 无边框 Entry。

    placeholder：水印提示，聚焦时消失、失焦且空时复原。
    """

    def __init__(self, master, width: int = 200, height: int = 30,
                 radius: int = BTN_RADIUS, fill: str = CARD2,
                 show: str = "", bg: str = CARD,
                 placeholder: str = "", **kw):
        super().__init__(master, bg=bg, **kw)
        self._ph = placeholder
        self._show = show
        self._showing_ph = False
        self.canvas = tk.Canvas(self, width=width, height=height,
                                highlightthickness=0, bd=0, bg=bg)
        self.canvas.pack()
        photo = round_image(width, height, radius, fill)
        self.canvas.create_image(0, 0, anchor="nw", image=photo)
        self._photo = photo
        self.entry = tk.Entry(self.canvas, bd=0, relief="flat", bg=fill,
                              fg=TEXT, insertbackground=TEXT,
                              font=(FONT, FS), show=show)
        self.canvas.create_window(10, height // 2, anchor="w", window=self.entry,
                                  width=max(20, width - 20), height=height - 8)
        if self._ph:
            self.entry.bind("<FocusIn>", self._on_focus_in)
            self.entry.bind("<FocusOut>", self._on_focus_out)
            self._apply_ph()

    # -------- 水印 --------
    def _apply_ph(self) -> None:
        self.entry.configure(fg=TEXT3, show="")            # 水印时不能遮码
        self.entry.delete(0, "end")
        self.entry.insert(0, self._ph)
        self._showing_ph = True

    def _clear_ph(self) -> None:
        self.entry.delete(0, "end")
        self.entry.configure(fg=TEXT, show=self._show)
        self._showing_ph = False

    def _on_focus_in(self, _event=None) -> None:
        if self._showing_ph:
            self._clear_ph()

    def _on_focus_out(self, _event=None) -> None:
        if not self._showing_ph and not self.entry.get().strip():
            self._apply_ph()

    # -------- 对外 API（保持与旧版一致）--------
    def get(self) -> str:
        return "" if self._showing_ph else self.entry.get()

    def set(self, text: str) -> None:
        if self._showing_ph:
            self._clear_ph()
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        if not text and self._ph:
            self._apply_ph()


class RoundCombo(tk.Frame):
    """圆角下拉框：圆角背景 + 无边框 Combobox。"""

    def __init__(self, master, values: list[str], width: int = 200,
                 height: int = 30, radius: int = BTN_RADIUS,
                 fill: str = CARD2, readonly: bool = True,
                 bg: str = CARD, **kw):
        super().__init__(master, bg=bg, **kw)
        self.canvas = tk.Canvas(self, width=width, height=height,
                                highlightthickness=0, bd=0, bg=bg)
        self.canvas.pack()
        photo = round_image(width, height, radius, fill)
        self.canvas.create_image(0, 0, anchor="nw", image=photo)
        self._photo = photo

        style = ttk.Style()
        # clam 主题的 Combobox 自带 lightcolor/darkcolor/bordercolor 三个亮边，
        # 只设 borderwidth=0 去不掉，必须把三种颜色都压成同一个填充色
        style.configure("Rounded.TCombobox",
                        fieldbackground=fill, background=fill, foreground=TEXT,
                        arrowcolor=TEXT2, borderwidth=0, relief="flat", padding=0,
                        bordercolor=fill, lightcolor=fill, darkcolor=fill,
                        insertcolor=TEXT)
        style.map("Rounded.TCombobox",
                  fieldbackground=[("readonly", fill), ("active", fill)],
                  background=[("readonly", fill), ("active", fill)],
                  foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", fill)],
                  selectforeground=[("readonly", TEXT)],
                  bordercolor=[("readonly", fill), ("active", fill)],
                  lightcolor=[("readonly", fill), ("active", fill)],
                  darkcolor=[("readonly", fill), ("active", fill)],
                  arrowcolor=[("readonly", TEXT2), ("active", TEXT)])

        self.var = tk.StringVar()
        self.combo = ttk.Combobox(self.canvas, textvariable=self.var, values=values,
                                  state="readonly" if readonly else "normal",
                                  style="Rounded.TCombobox", font=(FONT, FS))
        self.canvas.create_window(10, height // 2, anchor="w", window=self.combo,
                                  width=max(30, width - 20), height=height - 8)
        self._values = list(values)

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)

    def set_values(self, values: list[str]) -> None:
        self._values = list(values)
        self.combo["values"] = self._values

    def bind_select(self, func) -> None:
        self.combo.bind("<<ComboboxSelected>>", lambda _e: func())

    # 兼容 ttk.Combobox 的字典式访问（cb["values"] = [...]）
    def __setitem__(self, key, value):
        if key == "values":
            self.set_values(list(value))
        else:
            self.combo[key] = value

    def __getitem__(self, key):
        return self.combo[key]


class ToggleRow(tk.Frame):
    """iOS 风格开关行：左边文字，右边胶囊开关。

    extra 是文字和开关之间的空位，调用方可以往里塞附加控件
    （比如手机遥控的地址 + 二维码按钮），保持一行。
    """

    def __init__(self, master, text: str, variable: tk.BooleanVar,
                 command=None, bg: str = CARD, **kw):
        super().__init__(master, bg=bg, **kw)
        self.var = variable
        self.command = command
        self._bg = bg
        # 注意：不能叫 _w / _h，那是 tkinter Widget 内部的 widget path
        self._sw, self._sh = 42, 24
        self._label = tk.Label(self, text=text, bg=bg, fg=TEXT,
                               font=(FONT, FS), anchor="w")
        self._label.pack(side="left")
        self.switch = tk.Canvas(self, width=self._sw, height=self._sh,
                                highlightthickness=0, bd=0, bg=bg,
                                cursor="hand2")
        self.switch.pack(side="right", padx=(10, 0))
        # 中间扩展区（默认不占位，有子控件才显形）
        self.extra = tk.Frame(self, bg=bg)
        self._draw()
        self.switch.bind("<Button-1>", self._toggle)
        self._label.bind("<Button-1>", self._toggle)

    def pack_extra(self) -> None:
        """把 extra 插到文字和开关之间。有内容时调一次即可。"""
        if not self.extra.winfo_manager():
            self.extra.pack(side="left", fill="x", expand=True,
                            padx=(10, 0))

    def _draw(self) -> None:
        c = self.switch
        c.delete("all")
        on = bool(self.var.get())
        color = GREEN if on else CARD3
        photo = round_image(self._sw, self._sh, self._sh // 2, color)
        c.create_image(0, 0, anchor="nw", image=photo)
        self._photo = photo
        r = self._sh // 2 - 2
        cx = self._sw - r - 2 if on else r + 2
        knob = round_image(r * 2, r * 2, r, "#FFFFFF")
        c.create_image(cx - r, self._sh // 2 - r, anchor="nw", image=knob)
        self._knob = knob

    def _toggle(self, _event=None) -> None:
        self.var.set(not self.var.get())
        self._draw()
        if self.command:
            self.command()


def make_styles() -> None:
    """全局 ttk 样式：滚动条、日志框等。"""
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Vertical.TScrollbar", background=CARD3, troughcolor=CARD2,
                    bordercolor=CARD2, lightcolor=CARD3, darkcolor=CARD3,
                    arrowcolor=TEXT3, relief="flat", width=8, borderwidth=0)
    style.map("Vertical.TScrollbar",
              background=[("active", TEXT3), ("pressed", TEXT2)],
              arrowcolor=[("active", TEXT2)])