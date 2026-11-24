"""ValoTalk —— 无畏契约国际服实时语音 / 聊天翻译。

链路：
  1) 队友语音：系统声音 loopback → VAD → whisper(en) → 翻译 → 屏幕下方中文字幕
  2) 我说中文：按住 F2 → 麦克风 → whisper(zh) → 翻译成英文 → TTS 送进 VB-Cable → 队友听到
  3) 左下角聊天：截图 → OCR → 逐行翻译 → 同一处字幕
"""
from __future__ import annotations

import os

# 国内下模型走镜像（用户已设置则以用户为准）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import queue
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import ttk

import numpy as np

from . import PRERELEASE, __version__
from . import capture, envcheck, remote, ui_theme as ui, updater, winapi
from .asr import WhisperASR
from .asr_cloud import CloudASR, fix_ja_terms
from .profiles import Profiles
from .config import CONFIG
from .ocr import ChatOCR, LineDiffer, is_player_chat
from .overlay import Overlay
from .translate import VOICE_LINES, Translator
from .tts import TTS

FONT = "Microsoft YaHei UI"

# ---------------- TTS 音色 ----------------
_LOCALE_CN = {
    "en-US": "美", "en-GB": "英", "en-AU": "澳", "en-CA": "加", "en-IE": "爱",
    "en-IN": "印", "en-NZ": "新西", "en-ZA": "南非", "en-PH": "菲", "en-SG": "新加",
    "en-HK": "港", "en-KE": "肯", "en-NG": "尼",
}

# (locale, ShortName, 性别, 性格)
_VOICE_RAW = [
    ("en-US", "AnaNeural", "女", "可爱"),
    ("en-US", "AvaNeural", "女", "有表现力"),
    ("en-US", "AvaMultilingualNeural", "女", "有表现力"),
    ("en-US", "AriaNeural", "女", "自信"),
    ("en-US", "EmmaNeural", "女", "开朗清晰"),
    ("en-US", "EmmaMultilingualNeural", "女", "开朗清晰"),
    ("en-US", "JennyNeural", "女", "亲切体贴"),
    ("en-US", "MichelleNeural", "女", "温和"),
    ("en-US", "AndrewNeural", "男", "温暖可信"),
    ("en-US", "AndrewMultilingualNeural", "男", "温暖可信"),
    ("en-US", "BrianNeural", "男", "随性真诚"),
    ("en-US", "BrianMultilingualNeural", "男", "随性真诚"),
    ("en-US", "ChristopherNeural", "男", "权威沉稳"),
    ("en-US", "EricNeural", "男", "冷静理性"),
    ("en-US", "GuyNeural", "男", "有激情"),
    ("en-US", "RogerNeural", "男", "活泼"),
    ("en-US", "SteffanNeural", "男", "冷静理性"),
    ("en-GB", "LibbyNeural", "女", "亲和"),
    ("en-GB", "MaisieNeural", "女", "亲和"),
    ("en-GB", "SoniaNeural", "女", "亲和"),
    ("en-GB", "RyanNeural", "男", "亲和"),
    ("en-GB", "ThomasNeural", "男", "亲和"),
    ("en-AU", "NatashaNeural", "女", "亲和"),
    ("en-AU", "WilliamMultilingualNeural", "男", "亲和"),
    ("en-CA", "ClaraNeural", "女", "亲和"),
    ("en-CA", "LiamNeural", "男", "亲和"),
    ("en-IE", "EmilyNeural", "女", "亲和"),
    ("en-IE", "ConnorNeural", "男", "亲和"),
    ("en-IN", "NeerjaExpressiveNeural", "女", "有表现力"),
    ("en-IN", "NeerjaNeural", "女", "亲和"),
    ("en-IN", "PrabhatNeural", "男", "亲和"),
    ("en-NZ", "MollyNeural", "女", "亲和"),
    ("en-NZ", "MitchellNeural", "男", "亲和"),
    ("en-ZA", "LeahNeural", "女", "亲和"),
    ("en-ZA", "LukeNeural", "男", "亲和"),
    ("en-PH", "RosaNeural", "女", "亲和"),
    ("en-PH", "JamesNeural", "男", "亲和"),
    ("en-SG", "LunaNeural", "女", "亲和"),
    ("en-SG", "WayneNeural", "男", "亲和"),
    ("en-HK", "YanNeural", "女", "亲和"),
    ("en-HK", "SamNeural", "男", "亲和"),
    ("en-KE", "AsiliaNeural", "女", "亲和"),
    ("en-KE", "ChilembaNeural", "男", "亲和"),
    ("en-NG", "EzinneNeural", "女", "亲和"),
    ("en-NG", "AbeoNeural", "男", "亲和"),
    ("en-TZ", "ImaniNeural", "女", "亲和"),
    ("en-TZ", "ElimuNeural", "男", "亲和"),
    # 日语（日服模式用）
    ("ja-JP", "KeitaNeural", "男", "友好"),
    ("ja-JP", "NanamiNeural", "女", "友好"),
]

VOICE_CATALOG: list[tuple[str, str]] = [
    (
        f"{loc}-{name}",
        f"{name.replace('Neural', '').replace('Multilingual', '·多语')}"
        f" | {_LOCALE_CN.get(loc, loc)} | {g} | {p}",
    )
    for loc, name, g, p in _VOICE_RAW
]
VOICE_BY_LABEL = {label: short for short, label in VOICE_CATALOG}
LABEL_BY_VOICE = {short: label for short, label in VOICE_CATALOG}

# 按语言分组的音色（服务器选择决定用哪一组）
VOICE_CATALOG_BY_LANG: dict[str, list[tuple[str, str]]] = {
    "en": [(s, l) for s, l in VOICE_CATALOG if s.startswith("en-")],
    "ja": [(s, l) for s, l in VOICE_CATALOG if s.startswith("ja-")],
}
DEFAULT_VOICE = {
    "en": "en-US-GuyNeural",
    "ja": "ja-JP-KeitaNeural",
}

# 风格预设：(音色, pitch, rate)，None 表示不覆盖
STYLE_PRESETS: dict[str, tuple[str, str, str] | None] = {
    "原声（不调）": None,
    "萝莉音": ("en-US-AnaNeural", "+35Hz", "+15%"),
    "正太音": ("en-US-BrianNeural", "+25Hz", "+12%"),
    "御姐音": ("en-US-AriaNeural", "-20Hz", "-5%"),
    "大叔音": ("en-US-ChristopherNeural", "-25Hz", "-8%"),
    "气泡音": ("en-US-ChristopherNeural", "-35Hz", "-12%"),
    "青年音": ("en-US-BrianNeural", "+5Hz", "+8%"),
}

PREVIEW_TEXT = "Enemy one tap on A site, watch the flank."

# 游戏服务器（决定队友说什么语言）
# 目前无畏契约只有这几类语音环境，俄服/韩服没有，所以只做英语和日语
SERVER_CHOICES = {
    "港/美服（英语）": "en",
    "日服（日语）": "ja",
}
SERVER_BY_LABEL = dict(SERVER_CHOICES)
LABEL_BY_SERVER = {v: k for k, v in SERVER_CHOICES.items()}


@dataclass
class Job:
    kind: str                 # teammates / me / chat
    pcm: np.ndarray | None = None
    text: str = ""            # chat 已有文本
    detected_lang: str | None = None   # 自动检测出的语种
    asr_backend: str = ""     # cloud / local，用于日志和统计
    t0: float = field(default_factory=time.time)


class App:
    def __init__(self):
        winapi.enable_dpi_awareness()
        winapi.set_low_priority()          # 后台活，别跟游戏抢 CPU
        self.cfg = CONFIG
        self._get = self.cfg.get
        self._set = self.cfg.set
        self.log_lines: list[str] = []

        self.asr = WhisperASR(self._get)
        # 云端大模型 ASR（日服默认用，更准）
        self.asr_cloud = CloudASR(self._get, log=self.log)
        self.translator = Translator(self._get)
        self.tts = TTS(self._get, log=self.log)
        self.ocr = ChatOCR(self._get)
        self.differ = LineDiffer()

        self.asr_q: queue.Queue[Job] = queue.Queue(maxsize=8)
        self.post_q: queue.Queue[Job] = queue.Queue(maxsize=32)
        self._uiq: queue.Queue = queue.Queue()

        # 模型配置库：先把老配置（translate.llm.* / asr.cloud_*）迁进来，
        # 再让识别和翻译按选中的条目生效。
        # ⚠ 必须放在 _uiq 之后 —— log() 要用它
        self.profiles = Profiles(self._get, self._set)
        if self.profiles.migrate():
            self.log("[模型] 已把原有配置存成第一条模型配置")
        # 老版本迁移可能留下重复项（地址 + 密钥都一样），顺手清掉
        dropped = self.profiles.dedupe()
        if dropped:
            self.log(f"[模型] 清理了 {dropped} 条重复的模型配置")
        self.profiles.apply_all(save=False)

        self._sources: dict[str, capture.AudioSource] = {}
        # 开关状态镜像：tkinter 变量只能在主线程读，工作线程一律读这里
        self.flags = {"team": True, "me": True, "chat": True}
        self._seg_team: capture.Segmenter | None = None
        self._seg_me: capture.Segmenter | None = None
        self._me_armed = False
        self._running = False
        self._muted_outgoing = False
        self._chat_stop = threading.Event()
        self._chat_thread: threading.Thread | None = None

        self.hotkeys = winapi.HotkeyWatcher()
        # 手机遥控：游戏 Raw Input 独占键鼠时，热键在游戏里根本收不到。
        # 手机走 WiFi，绕开整条输入通道 —— 按住手机按钮 == 按下 PTT。
        self.remote = remote.RemoteControl(
            on_down=self._ptt_down,
            on_up=self._ptt_up,
            on_clear=self._remote_clear,
            on_mute=self._toggle_mute_outgoing,
            get_state=lambda: {"running": self._running,
                               "muted": self._muted_outgoing},
            log=self.log,
            port=int(self._get("remote.port", 8765) or 8765),
            token=str(self._get("remote.token", "") or ""),
        )
        # 渲染档位必须在建控件之前定好：控件构造时就会按档位画图
        ui.set_mode(str(self._get("ui.render_mode", "glass") or "glass"))
        self._build_ui()
        self._bind_hotkeys()
        # 注意：这几个必须在 _build_ui() 之后初始化 —— _build_ui 末尾会把
        # _frameless 设成 True（去掉标题栏成功时）。放到前面会被覆盖回 False。

        self.overlay = Overlay(self.root, self._get, self._set)
        if not self._get("overlay.click_through", True):
            self.overlay.bind_drag()
        # 拖动结束后刷新面板上的坐标
        self.overlay.on_moved = lambda _x, _y: self._refresh_pos_label()
        # overlay 建好之后才能读到实际坐标
        self._refresh_pos_label()
        # 显示当前识别/翻译通道（日服默认大写大模型链路）
        self._refresh_asr_mode_label()

        # 自动更新：启动后隔 4s 查（别和模型加载抢带宽）
        self.updater = updater.Updater(self._get, log=self.log)
        self._update_dialog = None

        self.root.after(40, self._pump_ui)
        self.root.after(150, self._start_remote)
        # 等游戏进程可查再判权限（游戏没开时 keyinject_blocked 返回 False）
        self.root.after(1800, self._check_permission)
        self.root.after(300, self._autostart)
        self.root.after(4000, self._check_update_async)
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        # 无标题栏状态由 _build_ui 末尾设置（strip_caption 成功才置 True），
        # 这里不能写死 False，否则会把那边的结果覆盖掉。

    # ============================================================ UI
    def _build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"ValoTalk v{__version__} · 无畏契约实时翻译")
        # 无标题栏相关状态：必须在方法开头就建好，后面各处会读
        self._frameless = False        # 末尾 strip_caption 成功才置 True
        self._is_maximized = False
        self._restore_geo = ""
        self._aspect_busy = False
        self._last_region_size = None  # 上次裁圆角时的窗口尺寸
        # 固定 4:3：初始 1024×768，最小 880×660；缩放时由 _lock_aspect 强制比例
        # 高度取 768 是因为配置页卡片叠起来实测需要 ~660px 内容区，
        # 720 高会溢出 30 多像素、底部 dock 被裁。
        self.root.geometry("1024x768")
        self.root.minsize(880, 660)
        self.root.configure(bg=ui.BG)
        ui.make_styles()
        if self._get("ui.panel_on_top", True):
            self.root.attributes("-topmost", True)

        # 4:3 宽高比锁定：判断用户主要在拉宽还是拉高，按变化更大的维度
        # 修正另一个维度，保证 width:height 恒为 4:3
        self._last_w, self._last_h = 960, 720

        def _lock_aspect(_e=None) -> None:
            # 绑定到 root 的 <Configure> 会收到所有子控件的事件（Tk 事件传播），
            # 只处理窗口自身（widget 是 root）的那一次，其余直接忽略。
            if _e is not None and getattr(_e, "widget", None) is not self.root:
                return
            # 最大化时不要锁比例：屏幕是 16:9，硬扳 4:3 会和 SetWindowPos
            # 互相拉扯（Configure → geometry → Configure …），界面直接卡死
            if getattr(self, "_is_maximized", False):
                return
            # 同一轮里被自己 geometry 触发的回调不再递归
            if getattr(self, "_aspect_busy", False):
                return
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            if w < 4 or h < 4:
                return
            if abs(w - self._last_w) >= abs(h - self._last_h):
                want_h = int(round(w * 3 / 4))
                if abs(h - want_h) > 1:
                    self._aspect_busy = True
                    try:
                        self.root.geometry(f"{w}x{want_h}")
                    finally:
                        self.root.after(30, self._clear_aspect_busy)
            else:
                want_w = int(round(h * 4 / 3))
                if abs(w - want_w) > 1:
                    self._aspect_busy = True
                    try:
                        self.root.geometry(f"{want_w}x{h}")
                    finally:
                        self.root.after(30, self._clear_aspect_busy)
            self._last_w, self._last_h = w, h

        self.root.bind("<Configure>", _lock_aspect, add=True)

        # 背景渐变：纯平底色显得死板，竖向渐变有纵深
        self._bg_canvas = tk.Canvas(self.root, highlightthickness=0, bd=0,
                                    bg=ui.BG)
        self._bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._bg_photo = None

        def _paint_bg(_e=None):
            if ui.is_lite():
                # 简约档没有壁纸，整窗一块底色就够，省掉每次改尺寸的缩放
                self._bg_canvas.delete("bg")
                return
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            if w < 4 or h < 4:
                return
            ph = ui.bg_gradient(w, h)
            self._bg_photo = ph
            self._bg_canvas.delete("bg")
            self._bg_canvas.create_image(0, 0, anchor="nw", image=ph, tags="bg")
            self._bg_canvas.tag_lower("bg")

        # add=True：不能替换掉前面 _lock_aspect 的绑定，否则 4:3 锁定会失效
        self.root.bind("<Configure>", _paint_bg, add=True)
        self.root.after(60, _paint_bg)

        # 最底层就是壁纸本身：不叠任何玻璃色，让所有内容都「浮」在它上面。
        # 之前用 glass=True 会给整窗盖一层灰，背景就全被压住了。
        outer = ui.GradientPane(self.root, image=True, radius=ui.WIN_RADIUS)
        outer.pack(fill="both", expand=True, padx=0, pady=0)

        # ---------------- 顶部一栏 ----------------
        # 顶栏是悬浮玻璃。这里权重给到 0.72 —— 里面的 Label 不能透明、
        # 只能用固定底色，玻璃太透的话每块 Label 都会浮出一个白方块。
        head = ui.GradientPane(outer, glass=True, radius=14,
                               layers=((ui.CARD, 0.72),),
                               edge=0.06, highlight=0.16,
                               blur=5.0, edge_color="#B4B4BE")
        head.pack(fill="x", pady=(10, 8), padx=14)

        tk.Label(head, text="ValoTalk", bg=ui.HEAD_BG, fg=ui.TEXT,
                 font=(ui.FONT, 18, "bold")).pack(side="left")
        self.ver_lbl = tk.Label(head, text=f"v{__version__}", bg=ui.HEAD_BG, fg=ui.TEXT3,
                                font=(ui.FONT, 9), cursor="hand2")
        self.ver_lbl.pack(side="left", padx=(6, 0), pady=(7, 0))
        # 测试版标记：标题旁边挂个小橙标，一眼能看出不是正式版
        self._beta_lbl = None
        # PRERELEASE 标记优先：3.0.1 这种纯数字版本号靠字符串判断不出来
        if PRERELEASE or "beta" in __version__.lower() or "rc" in __version__.lower():
            self._beta_lbl = tk.Label(
                head, text=" 测试版 ", bg=ui.ORANGE, fg="#FFFFFF",
                font=(ui.FONT, 8, "bold"), cursor="hand2")
            self._beta_lbl.pack(side="left", padx=(2, 0), pady=(7, 0))
            self._beta_lbl.bind(
                "<Button-1>", lambda _e: self._show_beta_notice())
        self.ver_lbl.bind("<Button-1>", lambda _e: self._manual_check_update())
        self.ver_lbl.bind("<Enter>", lambda _e: self.ver_lbl.configure(fg=ui.BLUE))
        self.ver_lbl.bind("<Leave>", lambda _e: self.ver_lbl.configure(fg=ui.TEXT3))

        # 手动检查更新（和启动时自动检查互不干扰）
        self.btn_update = ui.RoundButton(
            head, "检查更新", command=self._manual_check_update,
            width=76, height=24, fill=ui.CARD2, bg=ui.HEAD_BG, font_size=ui.FS_SMALL)
        self.btn_update.pack(side="left", padx=(8, 0), pady=(3, 0))

        self.state_lbl = tk.Label(head, text="● 未启动", bg=ui.HEAD_BG, fg=ui.RED,
                                  font=(ui.FONT, 10, "bold"))
        self.state_lbl.pack(side="left", padx=(12, 0))
        self.meter_lbl = tk.Label(head, text="", bg=ui.HEAD_BG, fg=ui.TEXT2,
                                  font=(ui.FONT, 9))
        self.meter_lbl.pack(side="left", padx=(8, 0))

        # ---- 窗口按钮（去标题栏后系统按钮没了，自己画三个）----
        # ⚠️ 必须最先 pack：pack(side="right") 是先创建的靠最右边缘，
        # 放到后面创建会被「模型/停止/开始」推到左边去
        self._win_btns = []
        for name, tip, cmd in (
            ("close", "关闭", self._on_close_click),
            ("max", "最大化", self._toggle_maximize),
            ("min", "最小化", self._minimize),
        ):
            b = ui.WinButton(head, name, command=cmd, bg=ui.HEAD_BG)
            b.pack(side="right", padx=(2, 0), pady=(6, 0))
            self._win_btns.append(b)
        # pack 顺序是反的（先 pack 的在最右），列表顺序调回来方便后面取
        self._win_btns.reverse()

        ui.RoundButton(head, "▶ 开始", command=self.start, width=86, height=32,
                       fill=ui.BLUE, bold=True, bg=ui.HEAD_BG).pack(
            side="right", padx=(10, 0))
        ui.RoundButton(head, "■ 停止", command=self.stop, width=74, height=32,
                       fill=ui.CARD2, bg=ui.HEAD_BG).pack(side="right", padx=(0, 8))
        mc = ui.RoundCombo(head, ["tiny", "base", "small", "medium"], width=92,
                           height=32, bg=ui.HEAD_BG)
        mc.set(str(self._get("asr.model", "small")))
        mc.pack(side="right", padx=(0, 6))
        mc.bind_select(self._on_model_change)
        self.model_var = mc.var
        self.cb_model_ui = mc
        tk.Label(head, text="模型", bg=ui.HEAD_BG, fg=ui.TEXT2,
                 font=(ui.FONT, 9)).pack(side="right", padx=(12, 5))

        # ---- 拖动 & 双击最大化 ----
        # 只绑在 head 本身和文字 Label 上；RoundButton/RoundCombo 是 Canvas，
        # 事件到不了这里，不会误触发拖动
        self._drag_off = None
        self._drag_moved = False

        def _drag_start(e):
            if not getattr(self, "_frameless", False):
                return
            self._drag_off = (e.x_root - self.root.winfo_x(),
                              e.y_root - self.root.winfo_y())
            self._drag_moved = False

        def _drag_move(e):
            if not self._drag_off:
                return
            dx = e.x_root - self.root.winfo_x() - self._drag_off[0]
            dy = e.y_root - self.root.winfo_y() - self._drag_off[1]
            if abs(dx) + abs(dy) > 2:
                self._drag_moved = True
            self.root.geometry(
                f"+{e.x_root - self._drag_off[0]}+{e.y_root - self._drag_off[1]}")

        def _drag_end(_e):
            self._drag_off = None

        def _head_dblclick(_e):
            if getattr(self, "_frameless", False):
                self._toggle_maximize()

        for w in (head,):
            w.bind("<Button-1>", _drag_start)
            w.bind("<B1-Motion>", _drag_move)
            w.bind("<ButtonRelease-1>", _drag_end)
            w.bind("<Double-Button-1>", _head_dblclick)

        # head 里的纯文字 Label 也要能拖（它们是 Frame 子控件，不绑就点不动）
        _head_children = list(head.winfo_children())

        def _bind_drag(widgets):
            for w in widgets:
                cls = ""
                try:
                    cls = w.winfo_class()
                except Exception:
                    pass
                if cls == "Label":
                    w.bind("<Button-1>", _drag_start, add="+")
                    w.bind("<B1-Motion>", _drag_move, add="+")
                    w.bind("<ButtonRelease-1>", _drag_end, add="+")
                    w.bind("<Double-Button-1>", _head_dblclick, add="+")

        _bind_drag(_head_children)
        self.root.after(200, lambda: _bind_drag(list(head.winfo_children())))

                # ---------------- 主体：左半功能页 + 右半日志 ----------------
        body = ui.GradientPane(outer, glass=True)
        body.pack(fill="both", expand=True, padx=16, pady=0)

        # 左半：页面 + 底部 dock
        left_pane = ui.GradientPane(body, glass=True)
        left_pane.pack(side="left", fill="both", expand=True, padx=(0, 7))
        self.left_pane = left_pane

        # 右半：运行日志（一直在这儿，不跟着页签切）
        self.log_pane = ui.GradientPane(body, glass=True)
        self.log_pane.pack(side="left", fill="both", expand=True, padx=(7, 0))

        # dock 先 pack，占住左半的底部，页面再填上面
        self._build_dock(left_pane)

        # ---------------- 分页容器（左半里，内容超高时可滚）----------------
        self.page_host, self.page_inner = self._scroll_host(left_pane)

        # 主页：单列（日志已经挪到右边常驻了）
        self.page_home = ui.GradientPane(self.page_inner, glass=True)
        left = ui.GradientPane(self.page_home, glass=True)
        left.pack(fill="both", expand=True)

        # 配置页：单列（左半只有 ~470px，两列会把输入框挤爆）
        self.page_cfg = ui.GradientPane(self.page_inner, glass=True)
        cfg_col = ui.GradientPane(self.page_cfg, glass=True)
        cfg_col.pack(fill="both", expand=True)
        cfg_left = cfg_col
        cfg_right = cfg_col

        # 关于页（与主页/配置页一致，套一层中间 GradientPane 再放卡片）
        self.page_about = ui.GradientPane(self.page_inner, glass=True)
        about_wrap = ui.GradientPane(self.page_about, glass=True)
        about_wrap.pack(fill="both", expand=True)
        self._build_about_page(about_wrap)

        self._show_page("home")
        # 布局稳定后给所有卡片内部着色（营造内部渐变），再补一次防抖动
        self.root.after(120, self._tint_all_cards)
        self.root.after(600, self._tint_all_cards)

        # ===== 主页：一个大玻璃卡片，内部用分隔线分区 =====
        home_card = ui.RoundCard(left, pad=16)
        home_card.pack(fill="both", expand=True)
        # 权限告警显示/隐藏后要刷新整个卡片高度（perm_card 指向它）
        card = home_card

        # ===== 分区：音频设备 =====
        body = self._section(home_card.body, "音频设备", first=True)

        self.cb_game = self._device_row(body, "游戏输出", "audio.game_output_device")
        self.cb_mic = self._device_row(body, "我的麦克风", "audio.mic_device")
        self.cb_tts = self._device_row(body, "TTS 输出", "audio.tts_output_device")

        # 服务器（就放在这里，打开就能看到）
        row = tk.Frame(body, bg=ui.CARD)
        row.pack(fill="x", pady=(6, 0))
        tk.Label(row, text="游戏服务器", bg=ui.CARD, fg=ui.TEXT,
                 font=(ui.FONT, ui.FS_SMALL), width=11, anchor="w").pack(side="left")
        cur_lang = str(self._get("asr.lang_teammates", "en") or "en")
        sc = ui.RoundCombo(row, list(SERVER_CHOICES), width=168, height=30)
        sc.set(LABEL_BY_SERVER.get(cur_lang, "港/美服（英语）"))
        sc.pack(side="left")
        sc.bind_select(self._on_server_change)
        self.cb_server = sc

        # 识别/翻译通道提示：单独一行，塞在服务器下拉右边会被截断
        self.asr_mode_lbl = tk.Label(body, text="", bg=ui.CARD, fg=ui.TEXT3,
                                     font=(ui.FONT, 8), anchor="w")
        self.asr_mode_lbl.pack(fill="x", pady=(4, 0))

        # 音色
        row2 = tk.Frame(body, bg=ui.CARD)
        row2.pack(fill="x", pady=(6, 0))
        tk.Label(row2, text="TTS 音色", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=11, anchor="w").pack(side="left")
        voice_group = VOICE_CATALOG_BY_LANG.get(
            "ja" if cur_lang.startswith("ja") else "en", VOICE_CATALOG)
        labels = [lab for _s, lab in voice_group]
        cur_voice = str(self._get("tts.voice", ""))
        if not cur_voice.startswith(("en-", "ja-")):
            cur_voice = DEFAULT_VOICE["ja" if cur_lang.startswith("ja") else "en"]
            self._set("tts.voice", cur_voice)
        cur_label = LABEL_BY_VOICE.get(cur_voice)
        if cur_label is None:
            cur_label = f"{cur_voice}（自定义）"
            labels = [cur_label] + labels
            VOICE_BY_LABEL[cur_label] = cur_voice
        vc = ui.RoundCombo(row2, labels, width=248, height=30)
        vc.set(cur_label)
        vc.pack(side="left")
        vc.bind_select(self._on_voice_change)
        self.cb_voice = vc
        ui.RoundButton(row2, "试听", command=self._preview_voice, width=56,
                       height=30).pack(side="left", padx=(6, 0))

        # 风格
        row3 = tk.Frame(body, bg=ui.CARD)
        row3.pack(fill="x", pady=(6, 0))
        tk.Label(row3, text="风格预设", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=11, anchor="w").pack(side="left")
        stc = ui.RoundCombo(row3, list(STYLE_PRESETS.keys()), width=168, height=30)
        stc.set("原声（不调）")
        stc.pack(side="left")
        stc.bind_select(self._on_style_change)
        self.cb_style = stc

        row4 = tk.Frame(body, bg=ui.CARD)
        row4.pack(fill="x", pady=(10, 0))
        ui.RoundButton(row4, "刷新", command=self._refresh_devices,
                       width=64, height=28).pack(side="left")
        ui.RoundButton(row4, "自动识别", command=self._autofill_devices,
                       width=84, height=28).pack(side="left", padx=(6, 0))
        ui.RoundButton(row4, "测试 TTS", command=self._test_tts,
                       width=84, height=28).pack(side="left", padx=(6, 0))

        # 权限告警：游戏 High / 我们 Medium 时，模拟的 V 会被系统丢掉
        self.perm_card = card
        self.perm_lbl = tk.Label(body, text="", bg=ui.CARD, fg=ui.RED,
                                 font=(ui.FONT, ui.FS_SMALL), anchor="w",
                                 justify="left", wraplength=330)
        self.perm_lbl.pack(fill="x", pady=(8, 0))
        self.perm_row = tk.Frame(body, bg=ui.CARD)
        ui.RoundButton(self.perm_row, "以管理员重启", command=self._relaunch_admin,
                       width=118, height=28, fill=ui.BLUE, bold=True,
                       bg=ui.CARD).pack(side="left")
        self.perm_row.pack(fill="x", pady=(6, 0))
        # 默认收起：没权限问题时不该占地方
        self.perm_lbl.pack_forget()
        self.perm_row.pack_forget()

        # ===== 分区：功能开关（同一大卡片内，分隔线之上）=====
        b2 = self._section(home_card.body, "功能开关")

        self.v_team = tk.BooleanVar(value=True)
        self.v_me = tk.BooleanVar(value=True)
        self.v_chat = tk.BooleanVar(value=True)
        self.v_orig = tk.BooleanVar(value=bool(self._get("overlay.show_original", True)))
        self.v_through = tk.BooleanVar(value=bool(self._get("overlay.click_through", True)))
        self.v_cpu = tk.BooleanVar(value=str(self._get("asr.device", "auto")) == "cpu")
        self.v_remote = tk.BooleanVar(value=bool(self._get("remote.enabled", False)))

        for text, var, cb in [
            ("队友语音 → 中文字幕", self.v_team,
             lambda: self._set_flag("team", self.v_team.get())),
            (self._me_label(), self.v_me,
             lambda: self._set_flag("me", self.v_me.get())),
            ("左下角聊天翻译", self.v_chat,
             lambda: self._set_flag("chat", self.v_chat.get())),
            ("字幕显示原文", self.v_orig,
             lambda: self._set("overlay.show_original", self.v_orig.get())),
            ("字幕穿透鼠标", self.v_through, self._on_through_toggle),
            ("识别用 CPU（不抢显卡）", self.v_cpu, self._on_cpu_toggle),
            ("手机遥控", self.v_remote, self._on_remote_toggle),
        ]:
            tr = ui.ToggleRow(b2, text, var, command=cb)
            tr.pack(fill="x", pady=1)
            if var is self.v_me:
                self.chk_me = tr
            elif var is self.v_remote:
                self.chk_remote = tr

        # 手机遥控的地址 + 二维码，塞在同一行的文字和开关之间
        self.remote_lbl = tk.Label(self.chk_remote.extra, text="未开启",
                                   bg=ui.CARD, fg=ui.TEXT3,
                                   font=(ui.FONT, 8), anchor="w")
        self.remote_lbl.pack(side="left")
        self.btn_remote_qr = ui.RoundButton(
            self.chk_remote.extra, "二维码", command=self._show_remote_qr,
            width=58, height=22, font_size=8)
        # 关着的时候先不显示，开了才出现（见 _set_remote_ui）
        if self._get("remote.enabled", False):
            self.btn_remote_qr.pack(side="left", padx=(6, 0))
        self.chk_remote.pack_extra()

        # ---- 模型选择：语音识别 / LLM（配置在「配置」页的「模型配置」里加）----
        tk.Frame(b2, bg=ui.CARD3, height=1).pack(fill="x", pady=(8, 5))
        self.pick_ui: dict[str, dict] = {}
        for kind, label in (("asr", "语音识别"), ("llm", "LLM")):
            self.pick_ui[kind] = self._model_picker_row(b2, kind, label)

        # 识别服务挪到「配置」页了（见下方 card_asr）

        # ===== 配置页：一个大玻璃卡片，内部三个分区 =====
        cfg_card = ui.RoundCard(cfg_left, pad=16)
        cfg_card.pack(fill="both", expand=True)

        # ===== 分区：快捷键 =====
        b3 = self._section(cfg_card.body, "快捷键（改完立刻生效）", first=True)

        self.hk_vars: dict[str, tk.StringVar] = {}
        self.hk_combos: dict = {}
        specs = [("ptt", "说中文"), ("toggle_click_through", "穿透"),
                 ("clear_overlay", "清屏"), ("toggle_mute_outgoing", "静音")]
        cur = self._get("hotkeys", {}) or {}
        hk_row = tk.Frame(b3, bg=ui.CARD)
        hk_row.pack(fill="x")
        for key, label in specs:
            cell = tk.Frame(hk_row, bg=ui.CARD)
            cell.pack(side="left", padx=(0, 6))
            tk.Label(cell, text=label, bg=ui.CARD, fg=ui.TEXT2,
                     font=(ui.FONT, ui.FS_SMALL), anchor="w").pack(anchor="w")
            rc = ui.RoundCombo(cell, winapi.HOTKEY_CHOICES, width=96, height=28)
            rc.set(str(cur.get(key, "")).upper())
            rc.pack()
            rc.bind_select(self._apply_hotkeys)
            self.hk_vars[key] = rc.var
            self.hk_combos[key] = rc

        sub = tk.Frame(b3, bg=ui.CARD)
        sub.pack(fill="x", pady=(8, 0))
        ui.RoundButton(sub, "检测按键", command=self._key_probe,
                       width=84, height=28).pack(side="left")
        ui.RoundButton(sub, "字幕贴回下方",
                       command=self._reset_subtitle_pos,
                       width=112, height=28).pack(side="left", padx=(6, 0))

        # ===== 字幕大小 & 位置 =====
        cfg_row = tk.Frame(b3, bg=ui.CARD)
        cfg_row.pack(fill="x", pady=(8, 0))
        tk.Label(cfg_row, text="字幕", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=5, anchor="w").pack(side="left")

        # 字号：A- 19 A+
        ui.RoundButton(cfg_row, "A−", command=lambda: self._adj_font(-1),
                       width=32, height=26).pack(side="left")
        self.font_lbl = tk.Label(cfg_row, text=str(self._get("overlay.font_size", 19)),
                                 bg=ui.CARD, fg=ui.TEXT,
                                 font=(ui.FONT, ui.FS_SMALL, "bold"), width=3)
        self.font_lbl.pack(side="left", padx=(2, 2))
        ui.RoundButton(cfg_row, "A+", command=lambda: self._adj_font(1),
                       width=32, height=26).pack(side="left")

        # 位置：上下左右微调
        tk.Frame(cfg_row, bg=ui.CARD, width=10).pack(side="left")
        for txt, fn, w in (("↑", lambda: self._nudge("up"), 28),
                           ("↓", lambda: self._nudge("down"), 28),
                           ("←", lambda: self._nudge("left"), 28),
                           ("→", lambda: self._nudge("right"), 28)):
            ui.RoundButton(cfg_row, txt, command=fn,
                           width=w, height=26).pack(side="left", padx=(0, 2))

        self.pos_lbl = tk.Label(cfg_row, text="", bg=ui.CARD, fg=ui.TEXT3,
                                font=(ui.FONT, 8))
        self.pos_lbl.pack(side="left", padx=(4, 0))

        # ===== 分区：模型配置（base_url + 密钥，识别和 LLM 共用）=====
        ba = self._section(cfg_card.body, "模型配置")
        tk.Label(ba, text="存一套地址 + 密钥，主页「语音识别」「LLM」里挑着用",
                 bg=ui.CARD, fg=ui.TEXT3, font=(ui.FONT, 8),
                 anchor="w", justify="left").pack(fill="x", pady=(0, 6))

        # 已有配置列表（每条一行：名字 + 域名 + 删）
        self.prof_list = tk.Frame(ba, bg=ui.CARD)
        self.prof_list.pack(fill="x")

        # 新增一行：名字 / 地址 / 密钥 / 添加
        add1 = tk.Frame(ba, bg=ui.CARD)
        add1.pack(fill="x", pady=(6, 0))
        tk.Label(add1, text="名称", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=4,
                 anchor="w").pack(side="left")
        self.e_prof_name = ui.RoundEntry(add1, width=86, height=28,
                                         placeholder="自动起名")
        self.e_prof_name.pack(side="left")
        tk.Label(add1, text="地址", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL)).pack(side="left", padx=(6, 0))
        # 地址给足宽度：https://maas.qianwenaiapi.com/compatible-mode/v1 很长
        self.e_prof_url = ui.RoundEntry(
            add1, width=234, height=28,
            placeholder="https://api.deepseek.com/v1")
        self.e_prof_url.pack(side="left", padx=(4, 0))

        add2 = tk.Frame(ba, bg=ui.CARD)
        add2.pack(fill="x", pady=(6, 0))
        tk.Label(add2, text="密钥", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=5,
                 anchor="w").pack(side="left")
        self.e_prof_key = ui.RoundEntry(add2, width=250, height=28, show="*",
                                        placeholder="sk-xxxxxx")
        self.e_prof_key.pack(side="left")
        ui.RoundButton(add2, "添加", command=self._add_profile,
                       width=56, height=28).pack(side="left", padx=(6, 0))

        self.prof_hint = tk.Label(ba, text="", bg=ui.CARD, fg=ui.TEXT3,
                                  font=(ui.FONT, 8), anchor="w",
                                  justify="left", wraplength=400)
        self.prof_hint.pack(fill="x", pady=(4, 0))

        self._refresh_profile_list()

        # 识别端点自检（保留「测一下」）
        test_row = tk.Frame(ba, bg=ui.CARD)
        test_row.pack(fill="x", pady=(6, 0))
        self.asr_ep_lbl = tk.Label(test_row, text="", bg=ui.CARD, fg=ui.TEXT3,
                                   font=(ui.FONT, 8), anchor="w",
                                   justify="left", wraplength=316)
        self.asr_ep_lbl.pack(side="left")
        ui.RoundButton(test_row, "测一下", command=self._test_cloud_asr,
                       width=56, height=26).pack(side="right")
        self._refresh_asr_endpoint_label()

        # ===== 分区：聊天区域 & 翻译后端 =====
        b4 = self._section(cfg_card.body, "聊天区域 & 翻译后端")

        reg = tk.Frame(b4, bg=ui.CARD)
        reg.pack(fill="x")
        tk.Label(reg, text="聊天区域", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=9, anchor="w").pack(side="left")
        self.region_lbl = tk.Label(reg, text="未设置", bg=ui.CARD, fg=ui.TEXT3,
                                   font=(ui.FONT, ui.FS_SMALL), anchor="w")
        self.region_lbl.pack(side="left", padx=(0, 8))
        ui.RoundButton(reg, "框选", command=self._pick_region,
                       width=56, height=28).pack(side="left")

        # OCR 速度档位：墙钟越短翻译越快，但 CPU 成倍涨
        spd_row = tk.Frame(b4, bg=ui.CARD)
        spd_row.pack(fill="x", pady=(8, 0))
        tk.Label(spd_row, text="OCR 速度", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=9, anchor="w").pack(side="left")
        self.ocr_speed = ChatOCR.SPEED_CHOICES          # {1: "...", 2: "...", 4: "..."}
        labels = [self.ocr_speed[k] for k in sorted(self.ocr_speed)]
        sc = ui.RoundCombo(spd_row, labels, width=132, height=28)
        cur_threads = int(self._get("ocr.onnx_threads",
                                    ChatOCR.DEFAULT_THREADS)
                          or ChatOCR.DEFAULT_THREADS)
        sc.set(self.ocr_speed.get(cur_threads,
                                  self.ocr_speed[ChatOCR.DEFAULT_THREADS]))
        sc.pack(side="left")
        sc.bind_select(self._on_ocr_speed_change)
        self.cb_ocr_speed = sc

        import os as _os
        cores = _os.cpu_count() or 4
        safe = ChatOCR.threads_safe_limit()
        hint = "墙钟越短越快，CPU 占用越高"
        if cores < 8:
            hint += f"（{cores} 核，建议≤「{self.ocr_speed[safe]}」）"
        self.spd_hint = tk.Label(
            b4, text=hint,
            bg=ui.CARD, fg=ui.TEXT3, font=(ui.FONT, 8),
            anchor="w", justify="left")
        self.spd_hint.pack(fill="x", pady=(3, 0))

        tr_row = tk.Frame(b4, bg=ui.CARD)
        tr_row.pack(fill="x", pady=(8, 0))
        tk.Label(tr_row, text="翻译", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=9, anchor="w").pack(side="left")
        self.backend = tk.StringVar(value=self._get("translate.backend", "auto"))
        bc = ui.RoundCombo(tr_row, ["auto", "llm", "bing", "google"], width=88, height=28)
        bc.set(self.backend.get())
        bc.pack(side="left")
        bc.var.trace_add("write", lambda *_: self._set(
            "translate.backend", bc.var.get()))
        self.cb_backend_ui = bc

        # base_url 占一行，model / key / 保存 另起一行（右列窄，挤一行会裁掉按钮）
        llm_row = tk.Frame(b4, bg=ui.CARD)
        llm_row.pack(fill="x", pady=(8, 0))
        tk.Label(llm_row, text="LLM URL", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=9, anchor="w").pack(side="left")
        self.e_base = ui.RoundEntry(llm_row, width=290, height=28,
                                    placeholder="https://api.deepseek.com/v1")
        self.e_base.set(self._get("translate.llm.base_url", ""))
        self.e_base.pack(side="left")

        llm_row2 = tk.Frame(b4, bg=ui.CARD)
        llm_row2.pack(fill="x", pady=(6, 0))
        tk.Label(llm_row2, text="模型", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=9, anchor="w").pack(side="left")
        self.e_model = ui.RoundEntry(llm_row2, width=110, height=28,
                                     placeholder="deepseek-chat")
        self.e_model.set(self._get("translate.llm.model", ""))
        self.e_model.pack(side="left")
        tk.Label(llm_row2, text="密钥", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL)).pack(side="left", padx=(6, 0))
        self.e_key = ui.RoundEntry(llm_row2, width=128, height=28, show="*",
                                   placeholder="sk-xxxxxx")
        self.e_key.set(self._get("translate.llm.api_key", ""))
        self.e_key.pack(side="left", padx=(4, 0))
        ui.RoundButton(llm_row2, "保存", command=self._save_llm,
                       width=56, height=28).pack(side="left", padx=(6, 0))

        # ===== 右半：日志（常驻，不随页签切换）=====
        card5 = ui.RoundCard(self.log_pane, pad=12)
        card5.pack(fill="both", expand=True)
        b5 = card5.body
        tk.Label(b5, text="运行日志", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))

        log_wrap = tk.Frame(b5, bg=ui.CARD, highlightthickness=0, bd=0)
        log_wrap.pack(fill="both", expand=True)
        # 用 Canvas 自绘而不是 tk.Text：Text 的 bg 只能纯色，
        # 会把卡片背后的壁纸挡成一块色板。GlassTextLog 把玻璃图和文字
        # 画在同一个 Canvas 上，日志区域就是真透明的。
        # 日志要长期阅读，比普通卡片多叠一点白（0.32 → 0.52）：
        # 仍然能看到背后图案的轮廓和色调，但文字不会被深色区域吃掉。
        self.txt = ui.GlassTextLog(
            log_wrap, radius=0, layers=((ui.CARD, 0.52),),
            font=(ui.FONT, ui.FS_SMALL), fg=ui.TEXT2, padding=8)
        self.txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_wrap, command=self.txt.yview,
                           style="Vertical.TScrollbar")
        sb.pack(side="right", fill="y")
        self.txt.configure(yscrollcommand=sb.set)

        self._refresh_devices(initial=True)

        # Windows 11 窗口圆角 + 深色标题栏（Win10 上这两个调用会静默失败）
        try:
            self.root.update_idletasks()
            hwnd = winapi.top_level_hwnd(self.root)
            winapi.set_rounded_window(hwnd, winapi.DWMWCP_ROUND)
            winapi.set_dark_titlebar(hwnd, True)
            # 去掉系统标题栏，让界面顶到窗口最上沿（head 那条栏接管标题栏职责）
            if self._get("ui.frameless", True):
                # remove_resize=True：连 WS_THICKFRAME 一起去掉。
                # 那个样式会在窗口四周画一圈 7px 的深色系统边框
                # （实测 RGB≈#2B2B2B），浅色界面上就是顶上那根黑线。
                # 代价是失去系统级边缘拖拽，用 _bind_resize_edges() 补回来。
                if winapi.strip_caption(hwnd, remove_resize=True):
                    self._frameless = True
                winapi.keep_shadow(hwnd)      # 补回阴影和圆角
                winapi.set_border_color(hwnd, ui.BG)   # 顶部残余边框染成底色
            # 大 R 角：DWM 的圆角改不了半径，只能自己裁窗口。
            # 窗口尺寸变了必须重裁，否则圆角会被拉伸成椭圆。
            self._round_hwnd = hwnd
            self._apply_win_radius()
            # 摘掉 WS_THICKFRAME 后系统不再管边缘拖拽，自己补上
            if self._frameless:
                self._bind_resize_edges()

            def _resize_region(_e=None):
                if _e is not None and getattr(_e, "widget", None) is not self.root:
                    return
                self.root.after_idle(self._apply_win_radius)

            self.root.bind("<Configure>", _resize_region, add=True)
        except Exception:
            pass

    def _apply_win_radius(self) -> None:
        """按当前尺寸重裁窗口圆角（SetWindowRgn 不会跟着 resize）。

        ⚠️ 必须按尺寸去重：SetWindowRgn 本身会触发 <Configure>，
        不去重就是「裁 → Configure → 再裁 → …」死循环，窗口会被搞成
        最小化坐标 (-32000,-32000)。
        """
        if not self._get("ui.win_radius", True):
            return
        try:
            hwnd = getattr(self, "_round_hwnd", 0)
            if not hwnd:
                return
            if getattr(self, "_is_maximized", False):
                return
            size = (self.root.winfo_width(), self.root.winfo_height())
            if size[0] < 100 or size[1] < 100:
                return
            if size == getattr(self, "_last_region_size", None):
                return                      # 尺寸没变，别重复裁
            self._last_region_size = size
            if not hasattr(self, "_dpi_scale"):
                self._dpi_scale = self.root.winfo_fpixels("1i") / 96.0
            winapi.round_window_region(hwnd, ui.WIN_RADIUS, self._dpi_scale)
        except Exception:
            pass

    # ============================================================ 窗口控制
    def _bind_resize_edges(self) -> None:
        """自绘窗口的边缘拖拽调整大小。

        为什么需要：去标题栏时连 WS_THICKFRAME 一起摘了（它会画那圈
        7px 深色边框），系统的边缘 resize 就没了。这里在 root 上监听
        鼠标，靠近边缘 6px 时换光标、按住拖动时改 geometry。

        只处理四条边和四个角，中间区域交给各自的控件。
        """
        edge = 6
        state = {"mode": None, "x": 0, "y": 0, "w": 0, "h": 0,
                 "px": 0, "py": 0}

        CURSORS = {
            "l": "size_we", "r": "size_we", "t": "size_ns", "b": "size_ns",
            "tl": "size_nw_se", "br": "size_nw_se",
            "tr": "size_ne_sw", "bl": "size_ne_sw",
            "": "arrow",
        }

        def _hit(e):
            """判断鼠标在哪个边缘/角落上。"""
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            x, y = e.x, e.y
            if x < 0 or y < 0 or x > w or y > h:
                return ""
            on_l = x <= edge
            on_r = x >= w - edge
            on_t = y <= edge
            on_b = y >= h - edge
            if on_t and on_l:
                return "tl"
            if on_t and on_r:
                return "tr"
            if on_b and on_l:
                return "bl"
            if on_b and on_r:
                return "br"
            if on_l:
                return "l"
            if on_r:
                return "r"
            if on_t:
                return "t"
            if on_b:
                return "b"
            return ""

        def _motion(e):
            mode = _hit(e)
            try:
                self.root.configure(cursor=CURSORS.get(mode, "arrow"))
            except Exception:
                pass
            if state["mode"]:
                # 正在拖边缘
                dx = e.x_root - state["px"]
                dy = e.y_root - state["py"]
                x, y, w, h = state["x"], state["y"], state["w"], state["h"]
                m = state["mode"]
                min_w, min_h = 880, 660
                if "l" in m:
                    nw = max(min_w, w - dx)
                    x = x + (w - nw)
                    w = nw
                if "r" in m:
                    w = max(min_w, w + dx)
                if "t" in m:
                    nh = max(min_h, h - dy)
                    y = y + (h - nh)
                    h = nh
                if "b" in m:
                    h = max(min_h, h + dy)
                self.root.geometry(f"{w}x{h}+{x}+{y}")
                state.update(w=w, h=h, x=x, y=y,
                             px=e.x_root, py=e.y_root)

        def _press(e):
            mode = _hit(e)
            if not mode:
                return
            state.update(mode=mode,
                         x=self.root.winfo_x(), y=self.root.winfo_y(),
                         w=self.root.winfo_width(),
                         h=self.root.winfo_height(),
                         px=e.x_root, py=e.y_root)

        def _release(_e=None):
            state["mode"] = None

        self.root.bind("<Motion>", _motion, add="+")
        self.root.bind("<ButtonPress-1>", _press, add="+")
        self.root.bind("<ButtonRelease-1>", _release, add="+")

    def _clear_aspect_busy(self) -> None:
        """4:3 锁定的防递归标记，隔一轮再放开。"""
        self._aspect_busy = False

    def _minimize(self) -> None:
        """最小化。去标题栏后系统按钮没了，走 Win32 而不是 tk 的 iconify，
        因为 tk 的 iconify 在无标题栏窗口上偶尔会把窗口藏到桌面之外。"""
        try:
            hwnd = winapi.top_level_hwnd(self.root)
            winapi.user32.ShowWindow(winapi.wintypes.HWND(hwnd), 6)  # SW_MINIMIZE
        except Exception:
            try:
                self.root.iconify()
            except Exception:
                pass

    def _toggle_maximize(self) -> None:
        """最大化 / 还原。最大化时按「可用区域」算，别盖住任务栏。"""
        try:
            if self._is_maximized:
                self.root.geometry(self._restore_geo or "960x720+120+80")
                self._is_maximized = False
                btns = getattr(self, "_win_btns", [])
                if btns:
                    btns[1]._kind = "max"
                    btns[1]._draw()
                # 还原后尺寸变了，清掉去重标记才会重新裁圆角
                self._last_region_size = None
                self.root.after(80, self._apply_win_radius)
            else:
                self._restore_geo = self.root.geometry()
                # 最大化时撤掉圆角：贴满屏幕还带圆角会露背景，很难看
                try:
                    winapi.round_window_region(
                        getattr(self, "_round_hwnd", 0), 0, 1.0)
                except Exception:
                    pass
                hwnd = winapi.top_level_hwnd(self.root)
                winapi.maximize_to_work_area(hwnd)
                self._is_maximized = True
                btns = getattr(self, "_win_btns", [])
                if btns:
                    btns[1]._kind = "restore"
                    btns[1]._draw()
        except Exception:
            pass

    def _on_close_click(self) -> None:
        self.shutdown()

    # ============================================================ 可滚动容器
    def _scroll_host(self, parent):
        """返回 (容器, 内容框)：内容比可视区高时竖着滚，不需要时滚动条自己藏起来。

        为什么要滚：日志常驻占掉右半边之后，左半只剩 ~470px 宽，
        配置页的卡片叠起来会超出窗口高度（实测 603px vs 可用 571px），
        硬塞就是被裁掉一截。
        """
        # 内部填充容器用直角：圆角由外层 left_pane 承担。若自带圆角，
        # 当 inner 内容没填满视口时，视口圆角外 keep_outside 的浅色背景
        # 会在左下角露出一个三角破绽。
        host = ui.GradientPane(parent, glass=True, radius=0)
        host.pack(fill="both", expand=True)

        canvas = ui.GradientPane(host, glass=True, radius=0)
        inner = ui.GradientPane(canvas, glass=True)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        # 细滚动条：内容比视口高时才出现。之前被整条去掉了，结果内容溢出
        # 时既看不到「还有东西」也没法滚 —— 用户只看到底部被裁掉一截。
        bar = ui.ThinScrollbar(host, command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)

        repaint_pending = {"v": False}

        def schedule_repaint():
            # 简约档没有背景图要对齐，这套「滚动后全树重绘」纯属白烧 CPU；
            # 而且 do() 里的 canvas.update_idletasks() 会被空闲任务反复唤醒，
            # 在简约档下直接表现为滚轮一滚就卡死。整段跳过。
            if ui.is_lite():
                return
            # 滚动后 inner 物理位置变了，让整棵内容树按新位置重新裁剪背景，
            # 于是背景在视口上保持固定，只有卡片（内容）滚动，也不会露底色。
            # 防抖：连续滚轮事件只在几何稳定后重绘一次，避免逐控件闪烁/残影。
            if repaint_pending["v"]:
                return
            repaint_pending["v"] = True

            def do():
                repaint_pending["v"] = False
                if ui.is_lite():
                    return
                try:
                    canvas.update_idletasks()
                    self._repaint_tree(inner)
                except Exception:
                    pass
            try:
                self.root.after(1, do)
            except Exception:
                pass

        def on_yview(first, last):
            # 驱动滚动条滑块，同时让背景在视口固定（内容滚，背景不滚）
            try:
                bar.set(first, last)
            except Exception:
                pass
            schedule_repaint()

        canvas.configure(yscrollcommand=on_yview)
        canvas.pack(side="left", fill="both", expand=True)

        def sync(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 内容溢出才显形；不需要时藏起来，别白占一条
            try:
                need = inner.winfo_reqheight() > canvas.winfo_height() + 2
                if need and not bar.winfo_ismapped():
                    bar.pack(side="right", fill="y", padx=(2, 0))
                elif not need and bar.winfo_ismapped():
                    bar.pack_forget()
            except Exception:
                pass

        def on_canvas(_e):
            canvas.itemconfig(win, width=max(1, canvas.winfo_width()))
            sync()

        def wheel(e):
            if inner.winfo_reqheight() > canvas.winfo_height() + 2:
                canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
                schedule_repaint()

        inner.bind("<Configure>", sync, add=True)
        canvas.bind("<Configure>", on_canvas, add=True)
        # 指针在左半里时接管滚轮；离开就还回去（别抢日志框的滚动）
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        self._page_canvas = canvas
        return host, inner

    def _repaint_tree(self, w) -> None:
        """递归让容器按当前实际位置重新渲染含背景的玻璃图。

        滚动 / 移动后控件位置变化，GradientPane 与 RoundCard 各自重新从
        原始背景图裁剪，背景在屏幕上保持固定，避免露底色或背景错位。

        简约档里没有背景图要"对齐"，整棵树重绘纯属白花 CPU —— 尤其滚动时
        每滚一下就要走一遍，低配机上就是卡顿的来源。直接跳过。
        """
        if ui.is_lite():
            return
        if isinstance(w, ui.GradientPane):
            try:
                w._paint()
            except Exception:
                pass
        if isinstance(w, ui.RoundCard):
            try:
                w._redraw()
                w.tint()
            except Exception:
                pass
        for c in w.winfo_children():
            self._repaint_tree(c)

    # ============================================================ 底部 dock
    # 三个页签：主页 / 配置 / 关于。图标全用 Canvas 画（不依赖字体图标，
    # 换台没有 emoji 字体的机器也不会变成方块）。
    DOCK_ITEMS = (("home", "主页"), ("cfg", "配置"), ("about", "关于"))

    def _build_dock(self, parent) -> None:
        # wrap 只负责占住底部一行并居中 dock：用 image 模式显示原始背景、
        # 不叠玻璃，避免它和圆角 dock 形成两层玻璃。
        # wrap 必须和它所在的容器同色：用 image=True 会直接画壁纸原色，
# 而 left_pane 是叠了灰玻璃的 —— 两者差一层，dock 左右就会露一条蓝带。
        wrap = ui.GradientPane(parent, glass=True, radius=0,
                               layers=ui.PANEL_LAYERS)
        wrap.pack(side="bottom", fill="x", pady=(8, 4))
        # 只放图标，不放文字 —— 高度压到 54，宽度按图标间距算
        self._dock_w = 220
        # dock 本身是一个圆角玻璃悬浮栏：明确的圆角胶囊外形 + 玻璃材质，
        # 圆角外保留原始背景，像卡片一样浮在背景上。
        self.dock = ui.GradientPane(wrap, glass=True, radius=24,
                                    layers=((ui.CARD, 0.66),), edge=0.09,
                                    blur=5.0, edge_color="#9A9AA6",
                                    keep_outside=True,
                                    outside_layers=ui.PANEL_LAYERS,
                                    height=54, width=self._dock_w)
        self.dock.pack(anchor="center")
        self.dock.bind("<Button-1>", self._dock_click)
        self.dock.bind("<Motion>", self._dock_motion)
        self.dock.bind("<Leave>", lambda _e: self._dock_leave())
        self._hover_key = ""
        self._current_page = "home"
        self._draw_dock()

    @staticmethod
    def _round_rect(cv: tk.Canvas, x1, y1, x2, y2, r, **kw):
        """圆角矩形（用平滑多边形近似，Tk 没有原生圆角）。"""
        pts = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return cv.create_polygon(pts, smooth=True, **kw)

    def _dock_geom(self):
        """返回每个图标的中心 x（dock 宽度变了也能自适应）。"""
        total = len(self.DOCK_ITEMS)
        slot = self._dock_w / total
        return [slot * (i + 0.5) for i in range(total)]

    def _draw_dock(self, hover_key: str = "") -> None:
        cv = self.dock
        # 只清前景，保留 GradientPane 自身渲染的透明玻璃底（背景可见）
        cv.delete("dockfg")
        h = 54
        w = self._dock_w

        for (key, _label), cx in zip(self.DOCK_ITEMS, self._dock_geom()):
            active = key == self._current_page
            hover = key == hover_key
            if active:
                # 选中：淡蓝圆角垫片。用矢量多边形而不是图片 ——
                # 图片版 glass_image 的圆角外只能填一个固定色，和 dock
                # 自己的渐变底永远对不上，四角就会露出灰块
                self._round_rect(cv, cx - 24, 7, cx + 24, 47, 14,
                                 fill="#D8E7FF", outline="", tags="dockfg")
            elif hover:
                self._round_rect(cv, cx - 24, 7, cx + 24, 47, 14,
                                 fill="#E8E8EE", outline="", tags="dockfg")

            fg = ui.BLUE if active else (ui.TEXT if hover else ui.TEXT3)
            self._draw_icon(cv, key, cx, 26, fg, active, tag="dockfg")

            # 底部小圆点：放在胶囊内下沿
            if active:
                cv.create_oval(cx - 2.5, 44, cx + 2.5, 49,
                               fill=ui.BLUE, outline="", tags="dockfg")

    def _draw_icon(self, cv: tk.Canvas, key: str, cx: float, cy: float,
                   color: str, active: bool = False, tag: str = "") -> None:
        """三个图标画出各自辨识度：房子 / 滑块 / 圆圈信息。不用外框套娃。"""
        lw = 2.4 if active else 2.0
        s = 11.5                                 # 统一尺寸基准（图标放大）

        if key == "home":
            # 房子：屋顶两笔 + 屋身 U 形 + 短门
            cv.create_line(cx - s, cy - 1, cx, cy - s - 1,
                           fill=color, width=lw, capstyle="round",
                           joinstyle="round", tags=tag)
            cv.create_line(cx, cy - s - 1, cx + s, cy - 1,
                           fill=color, width=lw, capstyle="round",
                           joinstyle="round", tags=tag)
            cv.create_line(cx - s + 2.5, cy - 1.5,
                           cx - s + 2.5, cy + s - 1,
                           fill=color, width=lw, capstyle="round", tags=tag)
            cv.create_line(cx + s - 2.5, cy - 1.5,
                           cx + s - 2.5, cy + s - 1,
                           fill=color, width=lw, capstyle="round", tags=tag)
            cv.create_line(cx - s + 2.5, cy + s - 1,
                           cx + s - 2.5, cy + s - 1,
                           fill=color, width=lw, capstyle="round", tags=tag)
            # 门
            cv.create_line(cx - 2.5, cy + s - 1, cx - 2.5, cy + 2.5,
                           fill=color, width=lw, capstyle="round", tags=tag)
            cv.create_line(cx + 2.5, cy + s - 1, cx + 2.5, cy + 2.5,
                           fill=color, width=lw, capstyle="round", tags=tag)
            cv.create_line(cx - 2.5, cy + 2.5, cx + 2.5, cy + 2.5,
                           fill=color, width=lw, capstyle="round", tags=tag)
        elif key == "cfg":
            # 滑块：三行「横线 + 圆点」，圆点错开位置
            for i, (dy, kx) in enumerate(((-6.5, -3.5), (0, 3.5), (6.5, -1.5))):
                cv.create_line(cx - s, cy + dy, cx + s, cy + dy,
                               fill=color, width=lw, capstyle="round", tags=tag)
                cv.create_oval(cx + kx - 3, cy + dy - 3,
                               cx + kx + 3, cy + dy + 3,
                               fill=ui.CARD, outline=color, width=1.8, tags=tag)
        else:
            # 圆圈 + i（信息比问号更清楚，也不像数字）
            cv.create_oval(cx - s, cy - s, cx + s, cy + s,
                           outline=color, width=lw, tags=tag)
            cv.create_oval(cx - 1.1, cy - 5.4, cx + 1.1, cy - 3.2,
                           fill=color, outline="", tags=tag)
            cv.create_line(cx, cy - 1.2, cx, cy + 5,
                           fill=color, width=lw, capstyle="round", tags=tag)

    def _dock_hit(self, x: float) -> str:
        for (key, _lbl), cx in zip(self.DOCK_ITEMS, self._dock_geom()):
            if abs(x - cx) <= 26:
                return key
        return ""

    def _dock_leave(self) -> None:
        if getattr(self, "_hover_key", ""):
            self._hover_key = ""
            self._draw_dock("")

    def _dock_motion(self, e) -> None:
        key = self._dock_hit(e.x)
        if key != getattr(self, "_hover_key", ""):
            self._hover_key = key
            self._draw_dock(key)
        self.dock.configure(cursor="hand2" if key else "")

    def _dock_click(self, e) -> None:
        key = self._dock_hit(e.x)
        if key:
            self._show_page(key)

    def _show_page(self, key: str) -> None:
        """切页：藏掉其它两页，只 pack 当前页。"""
        pages = {"home": self.page_home, "cfg": self.page_cfg, "about": self.page_about}
        page = pages.get(key)
        if page is None:
            return
        for k, p in pages.items():
            if k != key:
                p.pack_forget()
        if not page.winfo_manager():
            page.pack(fill="both", expand=True)
        self._current_page = key
        # 切页回到顶部，避免沿用上一页的滚动位置；再重绘让背景在视口固定
        try:
            self._page_canvas.yview_moveto(0)
            self.root.after(2, lambda: self._repaint_tree(self._page_canvas))
        except Exception:
            pass
        self._draw_dock(getattr(self, "_hover_key", ""))

    # ============================================================ 关于页
    def _build_about_page(self, parent) -> None:
        # 关于页：一个大玻璃卡片，底部「快捷键速查」作内部分区
        about_card = ui.RoundCard(parent, pad=16)
        about_card.pack(fill="both", expand=True)
        self._about_card = about_card
        b = about_card.body
        title_row = tk.Frame(b, bg=ui.CARD)
        title_row.pack(fill="x")
        tk.Label(title_row, text="ValoTalk", bg=ui.CARD, fg=ui.TEXT,
                 font=(ui.FONT, 16, "bold"), anchor="w").pack(side="left")
        # 测试版徽章：让人一眼知道装的不是正式版
        # PRERELEASE 标记优先：3.0.1 这种纯数字版本号靠字符串判断不出来
        if PRERELEASE or "beta" in __version__.lower() or "rc" in __version__.lower():
            tk.Label(title_row, text=" 测试版 ", bg=ui.ORANGE, fg="#FFFFFF",
                     font=(ui.FONT, 8, "bold")).pack(side="left", padx=(8, 0))
        tk.Label(b, text=f"v{__version__} · 无畏契约实时语音/聊天翻译",
                 bg=ui.CARD, fg=ui.TEXT2, font=(ui.FONT, ui.FS_SMALL),
                 anchor="w").pack(fill="x", pady=(2, 8))

        # 运行环境一行：Python 版本对不对，一眼能看到
        env_row = tk.Frame(b, bg=ui.CARD)
        env_row.pack(fill="x", pady=(0, 8))
        state = envcheck.python_state()
        py_desc = f"Python {envcheck.describe_python()}"
        if state == "ok":
            py_txt, py_fg = f"{py_desc} · 受支持（3.{envcheck.MIN_MINOR} ~ 3.{envcheck.MAX_MINOR}）", ui.TEXT3
        else:
            py_txt = f"{py_desc} · 不受支持！需要 3.{envcheck.MIN_MINOR} ~ 3.{envcheck.MAX_MINOR}"
            py_fg = ui.ORANGE
        tk.Label(env_row, text=py_txt, bg=ui.CARD, fg=py_fg,
                 font=(ui.FONT, 8), anchor="w").pack(side="left")
        ui.RoundButton(env_row, "查依赖", command=self._check_env_deps,
                       width=66, height=24, font_size=8).pack(side="left", padx=(8, 0))

        btn_row = tk.Frame(b, bg=ui.CARD)
        btn_row.pack(fill="x", pady=(0, 8))
        ui.RoundButton(btn_row, "检查更新", command=self._manual_check_update,
                       width=88, height=30).pack(side="left")
        ui.RoundButton(btn_row, "项目主页", command=self._open_github,
                       width=88, height=30).pack(side="left", padx=(6, 0))
        ui.RoundButton(btn_row, "打开配置页", command=lambda: self._show_page("cfg"),
                       width=96, height=30).pack(side="left", padx=(6, 0))

        note = (
            "链路：队友语音 → 语音识别（本地/云端）→ 翻译 → 屏幕字幕；"
            "我说中文 → 翻成目标语言 → TTS 进游戏麦克风。\n"
            "本地识别（faster-whisper）不上传任何音频；"
            "在主页把「语音识别」那一路启用后，音频才会发到你配置的服务。\n"
            "热键在游戏有焦点时收不到（游戏输入独占），要用手机遥控那一路。"
        )
        # wraplength 跟着卡片宽度走，固定值会溢出（左列只有 ~410px）
        self._about_note = tk.Label(
            b, text=note, bg=ui.CARD, fg=ui.TEXT3, font=(ui.FONT, 8),
            justify="left", anchor="w", wraplength=400)
        self._about_note.pack(fill="x")

        def _fit_note(_e=None):
            try:
                w = max(180, b.winfo_width() - 8)
                self._about_note.configure(wraplength=w)
            except Exception:
                pass

        # add=True：保留 RoundCard 的 _sync_height 与 GradientPane 的 _paint，
        # 不能替换，否则卡片高度无法跟随内容、末尾分区会被裁切。
        b.bind("<Configure>", _fit_note, add=True)

        # 分区：快捷键速查（同一大卡片内）
        b2 = self._section(about_card.body, "快捷键速查")
        rows = [
            ("按住（默认 F2）", "说中文 → 队友听到目标语言"),
            ("F3", "字幕窗在「穿透鼠标 / 可拖动」之间切换"),
            ("F4", "清空字幕"),
            ("F5", "临时静音英文输出"),
            ("手机遥控", "局域网网页，绕开游戏的输入独占"),
        ]
        for k, v in rows:
            row = tk.Frame(b2, bg=ui.CARD)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=k, bg=ui.CARD, fg=ui.TEXT2,
                     font=(ui.FONT, ui.FS_SMALL), width=16, anchor="w").pack(side="left")
            tk.Label(row, text=v, bg=ui.CARD, fg=ui.TEXT3,
                     font=(ui.FONT, ui.FS_SMALL), anchor="w").pack(side="left")

        # 分区：外观 / 更新线路
        # 低配机上毛玻璃很吃 CPU（每块面板要裁剪背景 + 模糊 + 超采样），
        # 这里给个一键降档；线路决定「检查更新」看哪一串 release
        b4 = self._section(about_card.body, "外观与更新")
        look_row = tk.Frame(b4, bg=ui.CARD)
        look_row.pack(fill="x", pady=(2, 4))
        tk.Label(look_row, text="界面外观", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=8,
                 anchor="w").pack(side="left")
        self.cb_render = ui.RoundCombo(
            look_row, ["毛玻璃（好看）", "简约（省资源）"],
            width=150, height=28)
        self.cb_render.pack(side="left", padx=(0, 8))
        self.cb_render.set(
            "简约（省资源）" if ui.is_lite() else "毛玻璃（好看）")
        self.cb_render.bind_select(self._on_render_mode_change)
        self._render_hint = tk.Label(
            look_row, text="", bg=ui.CARD, fg=ui.TEXT3,
            font=(ui.FONT, 8), anchor="w")
        self._render_hint.pack(side="left")

        ch_row = tk.Frame(b4, bg=ui.CARD)
        ch_row.pack(fill="x", pady=(0, 4))
        tk.Label(ch_row, text="更新线路", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=8,
                 anchor="w").pack(side="left")
        self.cb_channel = ui.RoundCombo(
            ch_row, ["正式版", "轻量版"], width=150, height=28)
        self.cb_channel.pack(side="left", padx=(0, 8))
        self.cb_channel.set(
            "轻量版" if str(self._get("update.channel", "stable")) == "lite"
            else "正式版")
        self.cb_channel.bind_select(self._on_channel_change)
        self._channel_hint = tk.Label(
            ch_row, text="轻量版还没发布时会自动回落到正式版",
            bg=ui.CARD, fg=ui.TEXT3, font=(ui.FONT, 8), anchor="w")
        self._channel_hint.pack(side="left")

        # 分区：赞助（二维码 + 点击放大，扫不出来的话点一下就行）
        b3 = self._section(about_card.body, "赞助支持")
        sp_row = tk.Frame(b3, bg=ui.CARD)
        sp_row.pack(fill="x", pady=(2, 4))

        self._sponsor_img_small = None
        self._sponsor_img_big = None
        try:
            from PIL import Image as _PILImage
            from PIL import ImageTk as _PILTk
            sp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "assets", "sponsor.png")
            if os.path.exists(sp_path):
                src = _PILImage.open(sp_path).convert("RGB")
                # 等比缩到高 148，显示够大能直接扫；点开是原尺寸
                th = 148
                tw = max(1, int(src.width * th / src.height))
                self._sponsor_img_small = _PILTk.PhotoImage(
                    src.resize((tw, th), _PILImage.LANCZOS))
                self._sponsor_img_big = _PILTk.PhotoImage(src)
                qr = tk.Label(sp_row, image=self._sponsor_img_small,
                              bg=ui.CARD, bd=0, cursor="hand2")
                qr.pack(side="left", padx=(0, 12))
                qr.bind("<Button-1>", lambda _e: self._show_sponsor_big())
        except Exception:
            pass

        sp_txt = tk.Frame(sp_row, bg=ui.CARD)
        sp_txt.pack(side="left", fill="both", expand=True)
        tk.Label(sp_txt, text="如果这个工具有帮到你", bg=ui.CARD,
                 fg=ui.TEXT2, font=(ui.FONT, ui.FS_SMALL),
                 anchor="w").pack(fill="x")
        tk.Label(sp_txt, text="可以请我喝杯奶茶吗 🧋", bg=ui.CARD,
                 fg=ui.TEXT3, font=(ui.FONT, ui.FS_SMALL),
                 anchor="w").pack(fill="x", pady=(1, 4))
        tk.Label(sp_txt, text="微信扫码 · 点图片可放大", bg=ui.CARD,
                 fg=ui.TEXT3, font=(ui.FONT, 8), anchor="w").pack(fill="x")

    # ============================================================ 外观 / 线路
    def _on_render_mode_change(self) -> None:
        """切换界面外观。立即重画，不用重启。"""
        want_lite = "简约" in self.cb_render.get()
        mode = "lite" if want_lite else "glass"
        self._set("ui.render_mode", mode)
        try:
            ui.set_mode(mode)
            self._repaint_all()
            self.log(f"[界面] 已切到{'简约' if want_lite else '毛玻璃'}外观")
        except Exception as e:
            self.log(f"[界面] 切换外观失败：{e}")
        try:
            if self._gamma_hint_alive():
                self._render_hint.configure(
                    text="已立即生效" if want_lite else "")
        except Exception:
            pass

    def _gamma_hint_alive(self) -> bool:
        try:
            return bool(self._render_hint.winfo_exists())
        except Exception:
            return False

    def _repaint_all(self) -> None:
        """按当前档位把整棵界面重画一遍（切档位后调）。"""
        def walk(w):
            if isinstance(w, ui.GradientPane):
                try:
                    w._paint()
                except Exception:
                    pass
            if isinstance(w, ui.RoundCard):
                try:
                    w._redraw()
                    w.tint()
                except Exception:
                    pass
            try:
                if isinstance(w, ui.RoundButton):
                    # RoundButton._draw 必须带颜色（normal / hover 两态）
                    w._draw(w._fill)
                elif isinstance(w, (ui.RoundCombo, ui.RoundEntry, ui.ToggleRow,
                                    ui.WinButton)):
                    w._draw()
            except Exception:
                pass
            for c in w.winfo_children():
                walk(c)

        try:
            walk(self.root)
            # 窗口底色也按档位重来
            self._bg_photo = None
            self.root.event_generate("<Configure>")
        except Exception:
            pass

    def _on_channel_change(self) -> None:
        """切换更新线路：只影响「检查更新」看哪一串 release。"""
        ch = "lite" if "轻量" in self.cb_channel.get() else "stable"
        self._set("update.channel", ch)
        self.log(f"[更新] 线路切到{'轻量版' if ch == 'lite' else '正式版'}")

    def _show_sponsor_big(self) -> None:
        """点赞助码弹原尺寸大图（小图在某些屏幕上扫不出来）。"""
        if not getattr(self, "_sponsor_img_big", None):
            return
        top = tk.Toplevel(self.root)
        top.title("赞助支持 · 谢谢老板打赏")
        top.configure(bg=ui.BG)
        top.transient(self.root)
        try:
            top.attributes("-topmost", True)
        except Exception:
            pass
        lbl = tk.Label(top, image=self._sponsor_img_big, bg="#FFFFFF", bd=0)
        lbl.pack(padx=0, pady=0)
        tk.Label(top, text="按 Esc 或点击图片关闭", bg=ui.BG, fg=ui.TEXT3,
                 font=(ui.FONT, 8)).pack(pady=(0, 8))
        top.bind("<Escape>", lambda _e: top.destroy())
        lbl.bind("<Button-1>", lambda _e: top.destroy())
        # 居中到主窗口
        top.update_idletasks()
        try:
            x = self.root.winfo_rootx() + (self.root.winfo_width()
                                           - top.winfo_width()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height()
                                           - top.winfo_height()) // 2
            top.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass
        top.focus_force()

    def _show_beta_notice(self) -> None:
        """点「测试版」徽章时说明这是什么版本。"""
        try:
            from .update_ui import NoticeDialog
            NoticeDialog(
                self.root, "这是测试版",
                f"当前版本 v{__version__} 是测试版，不是正式版。\n\n"
                "· 界面和功能还在调整，可能有不稳定的地方\n"
                "· 更新时会自动备份到 cache/update/backup/\n"
                "· 遇到问题可以把「运行日志」里的内容发给我\n\n"
                "想回到正式版：从 GitHub 的 Releases 页下载上一个正式版覆盖即可。",
                kind="warn")
        except Exception:
            pass

    def _open_github(self) -> None:
        import webbrowser
        webbrowser.open("https://github.com/LinDS-9A/ValoTalk")

    def _check_env_deps(self) -> None:
        """关于页的「查依赖」：缺哪个包、怎么补，直接说清楚。"""
        def work():
            missing = envcheck.missing_deps()
            if not missing:
                self.log("[环境] 依赖齐全，Python "
                         f"{envcheck.describe_python()} 受支持")
                return
            self.log(f"[环境] 缺 {len(missing)} 个依赖：{'、'.join(missing)}")
            self.log("       删掉 .venv 目录 → 双击 setup.ps1 重装（会自动挑 3.10~3.14 的 Python）")
            st = envcheck.python_state()
            if st != "ok":
                self.log(f"       注意：当前 Python {envcheck.describe_python()} 不受支持，先换 3.13")
        threading.Thread(target=work, daemon=True).start()

    def _device_row(self, parent, label: str, key: str):
        """一行设备选择：标签 + 圆角下拉。"""
        row = tk.Frame(parent, bg=ui.CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, ui.FS_SMALL), width=11, anchor="w").pack(side="left")
        rc = ui.RoundCombo(row, [], width=248, height=30)
        rc.set(self._get(key, "") or "")
        rc.pack(side="left")
        rc.bind_select(lambda: self._set(key, rc.get()))
        return rc

    def _on_model_change(self) -> None:
        size = self.model_var.get()
        self._set("asr.model", size)
        # 换模型必须重建（旧模型还占着内存）
        self.asr._model = None
        self.asr.loaded = False
        import valotalk.asr as asr_mod
        asr_mod._MODEL = None
        asr_mod._MODEL_KEY = None
        self.log(f"模型切换为 {size}，下次识别时重新加载")
        threading.Thread(
            target=lambda: self.asr.ensure_loaded(
                on_status=lambda s: self.log(f"[模型] {s}")),
            daemon=True,
        ).start()

    def _me_label(self) -> str:
        """跟着当前触发键走，改成鼠标侧键后这里也显示 MOUSE4。"""
        key = str(self._get("hotkeys.ptt", "f2") or "f2").upper()
        return f"我说中文 → 英文语音（按住 {key}）"

    def _refresh_me_label(self) -> None:
        try:
            self.chk_me.configure(text=self._me_label())
        except Exception:
            pass

    def _on_cpu_toggle(self) -> None:
        """显卡紧张时完全退出 GPU：识别改走 CPU。"""
        dev = "cpu" if self.v_cpu.get() else "auto"
        self._set("asr.device", dev)
        self.log(f"识别设备切换为 {dev}，重新加载模型 …")
        if dev == "cpu":
            self.log("  提示：CPU 上 small 很慢（RTF≈1.8），建议把右上角模型改成 base 或 tiny")

        def reload():
            self.asr._model = None
            self.asr.loaded = False
            import valotalk.asr as asr_mod
            asr_mod._MODEL = None
            asr_mod._MODEL_KEY = None
            self.asr.ensure_loaded(on_status=lambda s: self.log(f"[模型] {s}"))

        threading.Thread(target=reload, daemon=True).start()

    def _key_probe(self) -> None:
        """按住任意键，看键盘/鼠标到底发出什么。

        键盘走 GetAsyncKeyState 轮询，鼠标侧键额外挂 WH_MOUSE_LL 钩子
        （GetAsyncKeyState 对 XBUTTON 不可靠），两条路都显示出来。
        """
        top = tk.Toplevel(self.root)
        top.title("按键检测")
        top.geometry("460x210")
        top.attributes("-topmost", True)
        ttk.Label(top, text="按住你想用的那个键（含 Fn 组合 / 鼠标侧键）",
                  font=(FONT, 10)).pack(pady=(12, 4))
        big = ttk.Label(top, text="等待按键…", font=(FONT, 16, "bold"),
                        foreground="#7DD3FC")
        big.pack(pady=4)
        hint = ttk.Label(top, text="", style="Hint.TLabel")
        hint.pack(pady=2)
        mouse_lbl = ttk.Label(top, text="鼠标钩子：启动中…", style="Hint.TLabel")
        mouse_lbl.pack(pady=2)

        names = {v: k.upper() for k, v in winapi.VK.items()}
        deadline = time.time() + 30
        last_vk = [0]

        # 侧键钩子：能捕获游戏里的 XBUTTON
        hook = winapi.MouseHook()
        hook_state = {"hits": 0}

        def on_mouse(vk: int, down: bool):
            if not down:
                return
            hook_state["hits"] += 1
            name = "MOUSE4" if vk == 0x05 else "MOUSE5"
            self.root.after(0, lambda: (
                big.configure(text=f"VK 0x{vk:02X}   ({name})"),
                mouse_lbl.configure(text=f"鼠标钩子：捕获到 {name} ✓"),
                hint.configure(text="鼠标侧键可用，去面板把它设成触发键")))

        for vk in (0x05, 0x06):
            hook.bind(vk, on_press=lambda v=vk: on_mouse(v, True))
        hook_ok = hook.start()
        mouse_lbl.configure(
            text=f"鼠标钩子：{'已安装 ✓ 按侧键试试' if hook_ok else '安装失败，见日志'}")

        def poll():
            if not top.winfo_exists():
                hook.stop()
                return
            if time.time() > deadline:
                big.configure(text="超时，已停止")
                hook.stop()
                return
            for vk in range(0x01, 0xFF):
                if winapi.user32.GetAsyncKeyState(vk) & 0x8000:
                    if vk != last_vk[0]:
                        last_vk[0] = vk
                        name = names.get(vk, "?")
                        big.configure(text=f"VK 0x{vk:02X}   ({name})")
                        if vk == 0x71:
                            hint.configure(text="这就是 F2，程序能识别 ✓")
                        elif vk == 0x32:
                            hint.configure(text="这是数字 2！键盘没发出 F2 —— "
                                                "游戏会切枪，程序也认不到")
                        elif 0x70 <= vk <= 0x7B:
                            hint.configure(text="F 区键，可以选")
                        elif vk in (0x05, 0x06):
                            hint.configure(text="鼠标侧键，推荐用在 FPS 里")
                        else:
                            hint.configure(text="")
                    break
                if last_vk[0] == vk:
                    last_vk[0] = 0
            top.after(25, poll)

        def close():
            hook.stop()
            top.destroy()

        ttk.Button(top, text="关闭", command=close).pack(pady=6)
        poll()

    def _set_flag(self, name: str, value: bool) -> None:
        self.flags[name] = bool(value)
        self.log(f"开关 {name} → {'开' if value else '关'}")

    def _refresh_devices(self, initial: bool = False) -> None:
        outs = [d["name"] for d in capture.list_outputs()]
        ins = [d["name"] for d in capture.list_inputs()]
        self.cb_game["values"] = outs
        self.cb_tts["values"] = outs
        self.cb_mic["values"] = ins
        if initial:
            self._autofill_devices(quiet=True)
        self.log(f"设备：{len(outs)} 个输出 / {len(ins)} 个输入")

    def _autofill_devices(self, quiet: bool = False) -> None:
        if not self._get("audio.game_output_device"):
            name = capture.guess_game_output()
            if name:
                self._set("audio.game_output_device", name, save=False)
                self.cb_game.set(name)
        if not self._get("audio.mic_device"):
            ins = capture.list_inputs()
            if ins:
                self._set("audio.mic_device", ins[0]["name"], save=False)
                self.cb_mic.set(ins[0]["name"])
        if not self._get("audio.tts_output_device"):
            name = capture.guess_tts_output()
            if name:
                self._set("audio.tts_output_device", name, save=False)
                self.cb_tts.set(name)
        self.cfg.save()
        if not quiet:
            self.log("已自动识别设备，可在上面手动改。")

    def _refresh_asr_mode_label(self, lang: str = "") -> None:
        """服务器那一行的小字：现在识别走什么、翻译走什么。"""
        lang = lang or str(self._get("asr.lang_teammates", "en") or "en")
        cloud = self._use_cloud_asr(lang)
        # 翻译是 LLM 还是机翻，看 LLM 那一路有没有启用
        llm_pick = self.profiles.llm_pick()
        llm_on = bool(llm_pick.get("enabled", True)) and bool(
            llm_pick.get("profile")) and bool(self._get(
                "translate.llm.api_key", ""))
        ja = lang.startswith("ja")
        trans = "LLM 翻译" if llm_on else (
            "机翻（日服不准）" if ja else "机翻")

        if cloud:
            who = self.asr_cloud.describe() or "云端"
            txt, color = f"☁ {who} + {trans}", ui.BLUE
            tip = "音频会上传到该服务"
        else:
            # 没配 / 没启用 / 云端不可用 —— 都是走本地
            txt, color = f"本地识别 + {trans}", ui.TEXT3
            tip = ""
        try:
            self.asr_mode_lbl.configure(text=txt, fg=color)
        except Exception:
            pass
        if tip:
            self.log(f"[识别] {txt}（{tip}）")

    def _on_server_change(self) -> None:
        label = self.cb_server.get()
        lang = SERVER_BY_LABEL.get(label, "en")
        self._set("asr.lang_teammates", lang)
        self._refresh_voice_group(lang)
        name = {"en": "英语", "ja": "日语"}.get(lang, lang)
        self.log(f"游戏服务器：{label} → 队友语音按{name}识别，"
                 f"我说的中文翻成{name}")
        self._refresh_asr_mode_label(lang)

        # 日服切到大模型链路：云端 ASR + LLM 翻译（机翻不懂日语游戏术语）
        if lang.startswith("ja"):
            if self._use_cloud_asr(lang):
                threading.Thread(target=self._warm_cloud_asr, daemon=True).start()
            else:
                self.log("[提示] 未配置 LLM API key，日服无法使用云端识别与 "
                         "LLM 翻译；机翻对日语术语很不准，建议先填 key")
            self.log("[翻译] 日服模式：只走 LLM，不降级到机翻")

    def _warm_cloud_asr(self) -> None:
        if self.asr_cloud.warmed:
            return
        if self.asr_cloud.warmup():
            self.log(f"[云端ASR] {self.asr_cloud.describe()} 已就绪")
        else:
            self.log(f"[云端ASR] 预热失败：{self.asr_cloud.last_error}")

    def _refresh_voice_group(self, lang: str) -> None:
        """切换服务器时把音色列表换成对应语言的，并自动选默认音色。"""
        group = VOICE_CATALOG_BY_LANG.get(lang) or VOICE_CATALOG
        try:
            self.cb_voice["values"] = [lab for _s, lab in group]
        except Exception:
            return
        cur = str(self._get("tts.voice", ""))
        if not cur.startswith(lang + "-"):
            default = DEFAULT_VOICE.get(lang, group[0][0])
            self._set("tts.voice", default)
            self.cb_voice.set(LABEL_BY_VOICE.get(default, default))
            self.log(f"TTS 音色已切换为 {default}")
        else:
            self.cb_voice.set(LABEL_BY_VOICE.get(cur, cur))

    def _on_voice_change(self) -> None:
        voice = VOICE_BY_LABEL.get(self.cb_voice.get(), "")
        if not voice:
            return
        self._set("tts.voice", voice)
        self.log(f"TTS 音色改为 {voice}（点「试听」听效果）")

    def _on_style_change(self) -> None:
        name = self.cb_style.get()
        preset = STYLE_PRESETS.get(name)
        if preset is None:
            self._set("tts.pitch", "+0Hz")
            self.log("风格预设：原声（音高已复位，音色保持不变）")
            return
        voice, pitch, rate = preset
        self._set("tts.voice", voice)
        self._set("tts.pitch", pitch)
        self._set("tts.rate", rate)
        label = LABEL_BY_VOICE.get(voice, voice)
        self.cb_voice.set(label)
        self.log(f"风格预设：{name} → {voice} 音高 {pitch} 语速 {rate}")

    def _preview_voice(self) -> None:
        """试听：播到你的耳机（不是 Cable），这样能直接听到。"""
        voice = VOICE_BY_LABEL.get(self.cb_voice.get(), self.cb_voice.get())
        self._set("tts.voice", voice)
        out_dev = self._get("audio.game_output_device", "") or self._get(
            "audio.tts_output_device", "")
        if not out_dev:
            self.log("[试听] 没设置输出设备")
            return
        pitch = self._get("tts.pitch", "+0Hz")
        rate = self._get("tts.rate", "+10%")
        self.log(f"[试听] {voice}  音高 {pitch}  语速 {rate}  → {out_dev}")

        def run():
            t0 = time.time()
            pcm = self.tts._via_edge(PREVIEW_TEXT)
            if pcm is None:
                self.log(f"[试听] 合成失败：{self.tts.last_error}")
                return
            sink = capture.SpeakerSink(out_dev)
            okp = sink.play(pcm, 24000)
            self.log(f"[试听] {'完成' if okp else '播放失败：' + sink.last_error}"
                     f"  用时 {time.time()-t0:.1f}s")

        threading.Thread(target=run, daemon=True).start()

    def _save_llm(self) -> None:
        self._set("translate.llm.base_url", self.e_base.get().strip())
        self._set("translate.llm.model", self.e_model.get().strip())
        self._set("translate.llm.api_key", self.e_key.get().strip())
        self.log("LLM 配置已保存，正在自测 …")
        # 识别默认跟着翻译那栏走，保存完把「识别服务」那行也刷一遍
        self._refresh_asr_endpoint_label()
        threading.Thread(target=self._test_translate, daemon=True).start()

    def _test_translate(self) -> None:
        # 先直接测 LLM 接口（绕过缓存/直出表）
        ok, msg = self.translator.test_llm()
        if ok:
            self.log(f"[LLM 自测] ✓ 连通成功: {msg}")
        else:
            self.log(f"[LLM 自测] ✗ 失败: {msg}")
            self.log("   检查 base_url 是否以 /v1 结尾、model 名、api_key")

        # 再跑一遍正常翻译链路，看实际用哪个通道
        try:
            out = self.translator.translate(
                "Rush B, plant the spike behind the box.", "en", "zh-CN")
        except Exception as exc:
            self.log(f"[翻译自测] 异常: {exc}")
            return
        which = self.translator.backend_used
        if out:
            self.log(f"[翻译自测] 通道={which}")
            self.log(f"   英→中: {out}")

    def _on_through_toggle(self) -> None:
        self.overlay.set_click_through(self.v_through.get())
        if not self.v_through.get():
            self.overlay.bind_drag()

    # ============================================================ 热键
    def _apply_hotkeys(self) -> None:
        """界面改了快捷键后立即重建绑定，不用重启。"""
        hk = {k: (v.get() or "").strip().lower() for k, v in self.hk_vars.items()}
        if not all(hk.values()):
            self.log("[快捷键] 有键位为空，已忽略本次修改")
            return
        vals = list(hk.values())
        dup = sorted({v for v in vals if vals.count(v) > 1})
        if dup:
            self.log(f"[快捷键] {', '.join(k.upper() for k in dup)} 被重复绑定，已忽略")
            return
        if "v" in vals:
            self.log("[快捷键] V 是游戏开麦键，占用会冲突，已忽略")
            return
        for k, v in hk.items():
            self._set("hotkeys." + k, v, save=False)
        self.cfg.save()
        self._bind_hotkeys()
        self._refresh_me_label()
        self.log("快捷键已更新：" + "  ".join(f"{k} → {v.upper()}" for k, v in hk.items()))
        self._ui_state(self.state_lbl.cget("text"), self.state_lbl.cget("foreground"))

    def _bind_hotkeys(self) -> None:
        self.hotkeys.reset()
        hk = self._get("hotkeys", {}) or {}
        self.hotkeys.bind("ptt", hk.get("ptt", "f2"),
                          on_press=self._ptt_down, on_release=self._ptt_up)
        self.hotkeys.bind("through", hk.get("toggle_click_through", "f3"),
                          on_press=self._toggle_through_hotkey)
        self.hotkeys.bind("clear", hk.get("clear_overlay", "f4"),
                          on_press=lambda: self.overlay.clear())
        self.hotkeys.bind("mute", hk.get("toggle_mute_outgoing", "f5"),
                          on_press=self._toggle_mute_outgoing)
        self.hotkeys.start()

    def _ptt_down(self) -> None:
        # 按下这一刻从干净缓冲开始 —— 否则上一次残留的音频会混进这句
        # （手机连按两下时尤其明显）
        if self._seg_me is not None:
            try:
                self._seg_me.reset()
            except Exception:
                pass
        self._me_armed = True
        self._ui_state("● 正在听你说…", "#fbbf24")

    def _ptt_up(self) -> None:
        self._me_armed = False
        seg = self._seg_me.flush() if self._seg_me else None
        if seg is not None and self.flags["me"] and not self._muted_outgoing:
            self._submit_asr("me", seg)
        self._ui_state("● 运行中", "#34d399")

    def _toggle_through_hotkey(self) -> None:
        self.root.after(0, lambda: (self.v_through.set(not self.v_through.get()),
                                    self._on_through_toggle()))

    def _toggle_mute_outgoing(self) -> None:
        self._muted_outgoing = not self._muted_outgoing
        self.log("英文语音输出：" + ("已暂停" if self._muted_outgoing else "已恢复"))

    # ============================================================ 手机遥控
    def _remote_clear(self) -> None:
        self._ui_call(self.overlay, "clear")

    def _on_ocr_speed_change(self) -> None:
        """切换 OCR 线程档位。要重建引擎，下次识别会慢一下。"""
        label = self.cb_ocr_speed.get()
        threads = ChatOCR.DEFAULT_THREADS
        for n, text in ChatOCR.SPEED_CHOICES.items():
            if text == label:
                threads = n
                break
        old = int(self._get("ocr.onnx_threads", ChatOCR.DEFAULT_THREADS)
                  or ChatOCR.DEFAULT_THREADS)
        if threads == old:
            return
        self._set("ocr.onnx_threads", threads)
        self.ocr.set_threads(threads)

        import os
        cores = os.cpu_count() or 4
        note = {1: "省 CPU，但每次识别慢一些",
                2: "CPU 和速度折中",
                4: "识别最快，但 CPU 总量涨到 1 线程的 4.8 倍"}.get(threads, "")
        self.log(f"[OCR] 线程 {old} → {threads}（{label}）：{note}")

        # 核心数不够时提醒 —— 实测 6 核开 4 线程会明显掉帧
        safe = ChatOCR.threads_safe_limit()
        if threads > safe:
            self.log(f"[OCR] ⚠ 你的 CPU 是 {cores} 核，{threads} 线程可能让游戏掉帧"
                     f"（实测 6 核会丢 7 帧）；建议用「{ChatOCR.SPEED_CHOICES[safe]}」")
        self.log("[OCR] 引擎重建中，下一句聊天识别会稍慢")

    # ============================================================ 识别服务
    _ASR_PROV_MAP = {
        "跟随翻译": "",
        "阿里云百炼": "dashscope",
        "OpenAI 兼容": "openai",
        "DeepSeek": "deepseek",
    }
    _ASR_PROV_BACK = {v: k for k, v in _ASR_PROV_MAP.items()}

    def _refresh_asr_endpoint_label(self) -> None:
        """小字：实际会打哪个地址、用哪个模型。"""
        def apply():
            try:
                c = self.asr_cloud
                pick = self.profiles.asr_pick()
                if not pick.get("enabled", True):
                    txt, fg = "已停用 → 用本地 faster-whisper 识别", ui.TEXT3
                elif not c.available():
                    txt, fg = "没配密钥：先去上面「模型配置」加一条", ui.ORANGE
                elif c.provider == "openai" and not c.model:
                    txt = f"{c.base_url} → 没填模型名（要写 whisper-1 之类）"
                    fg = ui.ORANGE
                else:
                    txt = f"{c.describe()} → {c.base_url}"
                    fg = ui.TEXT3
                self.asr_ep_lbl.configure(text=txt, fg=fg)
            except Exception:
                pass
        self._uiq.put(apply)

    def _test_cloud_asr(self) -> None:
        if not self.asr_cloud.available():
            self.log("[识别] 没配密钥，先在「翻译」那栏填密钥")
            return
        self.log(f"[识别] 测一下 {self.asr_cloud.describe()} …")

        def work():
            ok, msg = self.asr_cloud.probe()
            self.log(("[识别] ✓ " if ok else "[识别] ✗ ") + msg)
            if ok:
                self.asr_cloud.warmed = True
            self._refresh_asr_endpoint_label()
        threading.Thread(target=work, daemon=True).start()

    # ============================================================ 模型配置库（配置页）
    def _refresh_profile_list(self) -> None:
        """重画「模型配置」里的列表：每条一行，名字 + 域名 + 删。"""
        try:
            for w in self.prof_list.winfo_children():
                w.destroy()
        except Exception:
            return

        items = self.profiles.all()
        if not items:
            tk.Label(self.prof_list, text="还没有配置，在下面填一条",
                     bg=ui.CARD, fg=ui.TEXT3, font=(ui.FONT, 8),
                     anchor="w").pack(fill="x", pady=(0, 2))
            self.prof_hint.configure(text="")
            return

        asr_name = str(self.profiles.asr_pick().get("profile", "") or "")
        llm_name = str(self.profiles.llm_pick().get("profile", "") or "")

        for it in items:
            row = tk.Frame(self.prof_list, bg=ui.CARD2,
                           highlightthickness=0, bd=0)
            row.pack(fill="x", pady=(0, 4))

            name = it["name"]
            mark = ""
            if name == asr_name and name == llm_name:
                mark = "识别+LLM"
            elif name == asr_name:
                mark = "识别"
            elif name == llm_name:
                mark = "LLM"

            tk.Label(row, text=name, bg=ui.CARD2, fg=ui.TEXT,
                     font=(ui.FONT, 8, "bold"), width=11,
                     anchor="w").pack(side="left", padx=(6, 0))

            host = it["base_url"].replace("https://", "").replace("http://", "")
            host = host.split("/")[0]
            tk.Label(row, text=host or "（未填地址）", bg=ui.CARD2, fg=ui.TEXT3,
                     font=(ui.FONT, 8), anchor="w").pack(side="left")

            key_ok = "有 key" if it["api_key"] else "无 key"
            tk.Label(row, text=key_ok, bg=ui.CARD2,
                     fg=ui.GREEN if it["api_key"] else ui.ORANGE,
                     font=(ui.FONT, 8)).pack(side="left", padx=(6, 0))

            if mark:
                tk.Label(row, text=mark, bg=ui.CARD2, fg=ui.BLUE,
                         font=(ui.FONT, 8)).pack(side="left", padx=(6, 0))

            ui.RoundButton(row, "删", width=32, height=20, font_size=8,
                           command=lambda n=name: self._del_profile(n)
                           ).pack(side="right", padx=(4, 4))

        self.prof_hint.configure(
            text=f"共 {len(items)} 条。删除正在用的那条会自动改指第一条。")
        # 列表行是新加的，要按位置重新着色，否则卡片内部那一段还是死色
        self.root.after_idle(self._tint_all_cards)

    def _section(self, parent, title: str, first: bool = False):
        """在大玻璃卡片 body 里开一个功能分区。

        非首区先插一条固定分隔线（_keep_bg 让 tint 不改它的颜色），再放
        分区小标题，返回装内容的普通 Frame。于是一页里所有功能共用一个
        圆角玻璃框，只在内部用分隔线分区，不再是多个独立小卡片。
        """
        if not first:
            sep = tk.Frame(parent, bg=ui.CARD3, height=1)
            sep._keep_bg = True
            sep.pack(fill="x", pady=(12, 10))
        tk.Label(parent, text=title, bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, 9, "bold"), anchor="w").pack(
            fill="x", pady=(0, 8))
        box = tk.Frame(parent, bg=ui.CARD)
        box.pack(fill="x")
        return box

    def _tint_all_cards(self) -> None:
        """把所有玻璃卡片里的子控件按位置重着色（内部渐变）。"""
        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, ui.RoundCard):
                    try:
                        c.tint()
                    except Exception:
                        pass
                walk(c)
        try:
            walk(self.root)
        except Exception:
            pass

    def _add_profile(self) -> None:
        name = self.e_prof_name.get().strip()
        url = self.e_prof_url.get().strip()
        key = self.e_prof_key.get().strip()
        if not url:
            self.log("[模型] 地址不能为空（例 https://api.deepseek.com/v1）")
            return
        if not key:
            self.log("[模型] 密钥不能为空")
            return
        if not url.startswith("http"):
            url = "https://" + url

        final = self.profiles.add(name, url, key)
        self.e_prof_name.set("")
        self.e_prof_url.set("")
        self.e_prof_key.set("")

        # 第一条自动两路都选上
        if len(self.profiles.names()) == 1:
            self._set("models.asr", {"profile": final,
                                     "model": self._default_model_for(url, "asr"),
                                     "enabled": True})
            self._set("models.llm", {"profile": final,
                                     "model": self._default_model_for(url, "llm"),
                                     "enabled": True})
            self.profiles.apply_all(save=False)
            self.asr_cloud.close()

        self._refresh_profile_list()
        self._refresh_model_rows()
        self.log(f"[模型] 已添加「{final}」：{url}")

    def _del_profile(self, name: str) -> None:
        if not self.profiles.remove(name):
            return
        self.profiles.apply_all(save=False)
        self.asr_cloud.close()
        self._refresh_profile_list()
        self._refresh_model_rows()
        self._refresh_asr_mode_label()
        self.log(f"[模型] 已删除「{name}」")

    # ============================================================ 模型选择
    def _model_picker_row(self, parent, kind: str, label: str) -> dict:
        """主页功能区的一行：配置下拉 + 模型输入框 + 启用按钮。

        配置（base_url + api_key）在「配置」页的「模型配置」里添加，
        这里只选哪一条、填模型名、开关它。
        """
        row = tk.Frame(parent, bg=ui.CARD)
        row.pack(fill="x", pady=(0, 2))

        tk.Label(row, text=label, bg=ui.CARD, fg=ui.TEXT,
                 font=(ui.FONT, ui.FS_SMALL), width=6,
                 anchor="w").pack(side="left")

        names = self.profiles.names()
        pick = (self.profiles.asr_pick() if kind == "asr"
                else self.profiles.llm_pick())
        cur = str(pick.get("profile", "") or "")

        combo = ui.RoundCombo(row, names or ["未配置"], width=84, height=24)
        combo.set(cur if cur in names else (names[0] if names else "未配置"))
        combo.pack(side="left")

        # 模型名给足宽度：qwen3-asr-flash 这种长名字别被截断
        entry = ui.RoundEntry(row, width=126, height=24, placeholder="模型名")
        entry.set(str(pick.get("model", "") or ""))
        entry.pack(side="left", padx=(4, 0))
        entry.entry.bind("<Return>", lambda _e: self._on_model_entered(kind))
        entry.entry.bind("<FocusOut>", lambda _e: self._on_model_entered(kind))

        btn = ui.RoundButton(row, "启用", width=46, height=24, font_size=8,
                             command=lambda: self._toggle_model(kind))
        btn.pack(side="left", padx=(4, 0))

        ref = {"combo": combo, "entry": entry, "btn": btn,
               "label": label, "kind": kind}
        combo.bind_select(lambda: self._on_pick_profile(kind))
        self._refresh_model_btn(kind, ref)
        return ref

    def _refresh_model_btn(self, kind: str, ref: dict | None = None) -> None:
        """按钮文字/颜色跟当前启用状态走。"""
        ref = ref or self.pick_ui.get(kind)
        if not ref:
            return
        pick = (self.profiles.asr_pick() if kind == "asr"
                else self.profiles.llm_pick())
        on = bool(pick.get("enabled", True)) and bool(pick.get("profile"))
        try:
            ref["btn"].set_text("已启用" if on else "启用")
            ref["btn"].set_fill(ui.GREEN if on else ui.BLUE)
        except Exception:
            pass

    def _refresh_model_rows(self) -> None:
        """配置库变了（增删改名）之后，把两行的下拉选项同步一次。"""
        names = self.profiles.names()
        for kind in ("asr", "llm"):
            ref = self.pick_ui.get(kind)
            if not ref:
                continue
            pick = (self.profiles.asr_pick() if kind == "asr"
                    else self.profiles.llm_pick())
            cur = str(pick.get("profile", "") or "")
            try:
                ref["combo"].set_values(names or ["未配置"])
                ref["combo"].set(cur if cur in names
                                 else (names[0] if names else "未配置"))
                ref["entry"].set(str(pick.get("model", "") or ""))
            except Exception:
                pass
            self._refresh_model_btn(kind, ref)

    def _on_pick_profile(self, kind: str) -> None:
        """换了一条配置：存下来，并把 model 换成该配置的默认模型名。"""
        ref = self.pick_ui.get(kind)
        if not ref:
            return
        name = ref["combo"].get()
        if name == "未配置":
            return
        prof = self.profiles.get(name)
        if not prof:
            return
        pick = dict(self.profiles.asr_pick() if kind == "asr"
                    else self.profiles.llm_pick())
        if pick.get("profile") != name:
            pick["profile"] = name
            default = self._default_model_for(prof["base_url"], kind)
            pick["model"] = default
            ref["entry"].set(default)
        self._set(f"models.{kind}", pick)
        self._apply_pick(kind)
        self.log(f"[模型] {ref['label']} 换成「{name}」"
                 f"（{prof['base_url'] or '未填地址'}）")

    @staticmethod
    def _default_model_for(base_url: str, kind: str) -> str:
        """按服务商给个默认模型名。"""
        low = (base_url or "").lower()
        if kind == "asr":
            if "deepseek" in low:
                return ""              # DeepSeek 的 ASR 不需要模型名
            if "dashscope" in low or "qianwen" in low or "aliyun" in low:
                return "qwen3-asr-flash"
            return "whisper-1"
        if "deepseek" in low:
            return "deepseek-flash"
        if "dashscope" in low or "qianwen" in low or "aliyun" in low:
            return "qwen-plus"
        return "gpt-4o-mini"

    def _on_model_entered(self, kind: str) -> None:
        """模型名输入框失焦/回车时存下来。"""
        ref = self.pick_ui.get(kind)
        if not ref:
            return
        model = ref["entry"].get().strip()
        pick = dict(self.profiles.asr_pick() if kind == "asr"
                    else self.profiles.llm_pick())
        if str(pick.get("model", "") or "") == model:
            return
        pick["model"] = model
        self._set(f"models.{kind}", pick)
        if pick.get("enabled", True) and pick.get("profile"):
            self._apply_pick(kind)
        self.log(f"[模型] {ref['label']} 模型名 → {model or '（空，用默认）'}")

    def _toggle_model(self, kind: str) -> None:
        """启用 / 停用这一路模型。"""
        ref = self.pick_ui.get(kind)
        if not ref:
            return
        pick = dict(self.profiles.asr_pick() if kind == "asr"
                    else self.profiles.llm_pick())
        name = str(pick.get("profile", "") or "")
        if not name or not self.profiles.get(name):
            self.log(f"[模型] {ref['label']} 还没选配置")
            self.log("       先去「配置」页 →「模型配置」添加一条（地址 + 密钥）")
            return

        want = not bool(pick.get("enabled", True))
        pick["enabled"] = want
        model = ref["entry"].get().strip()
        if model:
            pick["model"] = model
        self._set(f"models.{kind}", pick)
        self._apply_pick(kind)
        self._refresh_model_btn(kind, ref)

        if want:
            self.log(f"[模型] {ref['label']} 已启用：{name} / "
                     f"{pick.get('model') or '默认模型'}")
            if kind == "asr":
                threading.Thread(target=self._warm_cloud_asr,
                                 daemon=True).start()
        else:
            self.log(f"[模型] {ref['label']} 已停用"
                     f"（{'改用本地识别' if kind == 'asr' else '改用机翻兜底'}）")

    def _apply_pick(self, kind: str) -> None:
        """把选中的配置同步到实际生效的配置项，并刷新界面标签。"""
        if kind == "asr":
            if self.profiles.apply_asr():
                self.asr_cloud.close()      # 地址/密钥可能变了，连接要重建
            self._refresh_asr_mode_label()
        else:
            self.profiles.apply_llm()
            self._refresh_asr_mode_label()

    # ============================================================ 手机遥控
    def _on_remote_toggle(self) -> None:
        """功能开关区的「手机遥控当说话键」被切换。"""
        on = bool(self.v_remote.get())
        self._set("remote.enabled", on)
        if on:
            self._set_remote_ui(None)          # 启动中
            threading.Thread(target=self._start_remote, daemon=True).start()
            self.log("[手机] 正在开启遥控 …")
        else:
            self.remote.stop()
            self._set_remote_ui(False)
            self.log("[手机] 遥控已关闭（端口已释放）")

    def _set_remote_ui(self, on: bool | None) -> None:
        """地址行：True=已开 / False=已关 / None=启动中。

        关着时把二维码按钮藏起来，省出位置给地址文字。
        """
        def apply():
            try:
                if on is True:
                    self.remote_lbl.configure(fg=ui.BLUE)
                    if not self.btn_remote_qr.winfo_manager():
                        self.btn_remote_qr.pack(side="left", padx=(6, 0))
                else:
                    self.remote_lbl.configure(
                        text="启动中…" if on is None else "未开启",
                        fg=ui.TEXT3)
                    if self.btn_remote_qr.winfo_manager():
                        self.btn_remote_qr.pack_forget()
            except Exception:
                pass
        self._uiq.put(apply)

    # ============================================================ 字幕大小/位置
    def _adj_font(self, delta: int) -> None:
        cur = self.overlay.font_size()
        new = self.overlay.set_font_size(cur + delta)
        try:
            self.font_lbl.configure(text=str(new))
        except Exception:
            pass
        if new == cur:
            self.log(f"[字幕] 字号已是{'最小' if delta < 0 else '最大'} {new}")
            return
        self.overlay.preview()
        self.log(f"[字幕] 字号 {cur} → {new}")

    def _nudge(self, direction: str) -> None:
        step = 20
        fn = {"up": self.overlay.nudge_up, "down": self.overlay.nudge_down,
              "left": self.overlay.nudge_left, "right": self.overlay.nudge_right}
        fn.get(direction, self.overlay.nudge_down)(step)
        self._refresh_pos_label()
        self.overlay.preview()

    def _reset_subtitle_pos(self) -> None:
        self.overlay.reset_position()
        self._refresh_pos_label()
        self.log("[字幕] 已贴回屏幕下方居中")

    def _refresh_pos_label(self) -> None:
        try:
            self.pos_lbl.configure(text=f"{self.overlay.x},{self.overlay.y}")
        except Exception:
            pass

    def _ensure_remote_token(self) -> str:
        """没设口令就自动生成一个并写回 config。

        为什么默认要口令：宿舍 / 校园 / 咖啡厅的 WiFi 在 Windows 眼里是
        「公用网络」，同一个网段里任何人都能扫到这个端口。口令藏在二维码
        和地址里，本人扫一下就行，不影响使用。
        """
        tok = str(self._get("remote.token", "") or "").strip()
        if tok:
            return tok
        if not self._get("remote.auto_token", True):
            self.log("[手机] 未设口令且关掉了 auto_token —— 同一网段的人都能控制")
            return ""
        import secrets
        tok = secrets.token_urlsafe(9)          # 12 个字符，够用又不长
        self._set("remote.token", tok)
        return tok

    def _start_remote(self) -> None:
        def label(text: str, color: str) -> None:
            def apply():
                try:
                    self.remote_lbl.configure(text=text, foreground=color)
                    if color == ui.BLUE and not self.btn_remote_qr.winfo_manager():
                        self.btn_remote_qr.pack(side="left", padx=(6, 0))
                    elif color != ui.BLUE and self.btn_remote_qr.winfo_manager():
                        self.btn_remote_qr.pack_forget()
                except Exception:
                    pass
            self._uiq.put(apply)

        if not self._get("remote.enabled", False):
            self.v_remote.set(False)
            self._set_remote_ui(False)
            return
        self.remote.token = self._ensure_remote_token()
        url = self.remote.start()
        if url:
            self._set_remote_ui(True)
            # 只显示 ip:port，口令藏在二维码/复制里 —— 全写出来会挤掉按钮
            label(f"{self.remote.ip}:{self.remote.port}", ui.BLUE)
            self.log(f"[手机] 遥控已开启：{self.remote.ip}:{self.remote.port}"
                     f"（点「二维码」扫码，或「复制」拿带口令的完整地址）")
            others = [ip for ip in remote.local_ips() if ip != self.remote.ip]
            if others:
                self.log("[手机] 连不上就换这些地址试：" +
                         "  ".join(f"{ip}:{self.remote.port}" for ip in others))
            self.log("       手机连同一个 WiFi，扫码打开，按住或点一下大圆按钮说话")
            threading.Thread(target=self._check_firewall, daemon=True).start()
        else:
            self.v_remote.set(False)
            self._set("remote.enabled", False)
            label("启动失败", ui.RED)
            self.log(f"[手机] 遥控启动失败：{self.remote.error}")
            self.log("       Windows 防火墙可能挡住了，点「二维码」→「放行防火墙」")

    def _copy_remote(self) -> None:
        url = self.remote.url
        if not url:
            self.log("[手机] 还没启动，稍等一下")
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.log(f"[手机] 已复制：{url}")
        except Exception as e:
            self.log(f"[手机] 复制失败：{e}")

    def _show_remote_qr(self) -> None:
        """弹二维码 —— 总比让用户在手机上敲 IP 强。

        ⚠️ 踩过坑：qrcode 不是标准库，早期没写进 requirements.txt，
        有些环境（例如项目自带的 .venv）里根本没装。那时候这里只是
        `log()` 一句 + 复制网址，用户看到的就是「点二维码没反应」。
        现在改成：缺库就当场装，装不上再明确告诉用户，绝不静默吞掉。
        """
        url = self.remote.url
        if not url:
            self.log("[手机] 还没启动，稍等一下")
            return
        try:
            import qrcode  # noqa: F401
        except Exception:
            self._install_qrcode_then_show(url)
            return
        self._draw_remote_qr(url)

    # ---------------------------------------------------------------- 二维码
    def _install_qrcode_then_show(self, url: str) -> None:
        """缺 qrcode 时后台装一下，装好直接弹二维码。"""
        tip = tk.Toplevel(self.root)
        tip.title("手机遥控")
        tip.configure(bg=ui.BG)
        tip.resizable(False, False)
        try:
            tip.attributes("-topmost", True)
        except Exception:
            pass
        box = tk.Frame(tip, bg=ui.BG)
        box.pack(padx=26, pady=22)
        msg = tk.Label(box, text="正在准备二维码组件…", bg=ui.BG, fg=ui.TEXT,
                       font=(ui.FONT, 11))
        msg.pack()
        sub = tk.Label(box, text="第一次用需要装一个很小的包（qrcode）",
                       bg=ui.BG, fg=ui.TEXT3, font=(ui.FONT, 8))
        sub.pack(pady=(6, 0))
        tip.update_idletasks()
        try:
            x = self.root.winfo_rootx() + (self.root.winfo_width()
                                           - tip.winfo_width()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height()
                                           - tip.winfo_height()) // 3
            tip.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass
        self.log("[手机] 缺 qrcode，正在自动安装…")

        def work():
            ok = False
            err = ""
            try:
                import subprocess
                import sys as _sys
                flags = 0
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    flags = subprocess.CREATE_NO_WINDOW
                r = subprocess.run(
                    [_sys.executable, "-m", "pip", "install", "-q",
                     "qrcode[pil]"],
                    capture_output=True, text=True, timeout=180,
                    creationflags=flags)
                ok = (r.returncode == 0)
                if not ok:
                    err = (r.stderr or r.stdout or "").strip()[-160:]
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            if ok:
                # pip 装完要让 import 系统重新扫一遍目录，否则还是找不到
                try:
                    import importlib
                    importlib.invalidate_caches()
                    import qrcode  # noqa: F401
                except Exception as e:
                    ok = False
                    err = f"装完仍无法导入：{e}"

            def done():
                try:
                    tip.destroy()
                except Exception:
                    pass
                if ok:
                    self.log("[手机] qrcode 已装好")
                    self._draw_remote_qr(url)
                else:
                    self.log(f"[手机] 自动安装失败：{err}")
                    self._qr_failed(err)

            self._uiq.put(done)

        threading.Thread(target=work, daemon=True).start()

    def _qr_failed(self, err: str) -> None:
        """装不上就明说，并把网址复制好。"""
        self._copy_remote()
        try:
            from .update_ui import NoticeDialog
            NoticeDialog(
                self.root, "二维码组件没装上",
                "生成二维码需要 qrcode 这个包，自动安装没成功。\n\n"
                "手动装一次就行（在项目目录执行）：\n"
                "    .venv\\Scripts\\python.exe -m pip install \"qrcode[pil]\"\n\n"
                f"访问网址已经帮你复制好了，粘到手机浏览器也能用。\n\n"
                f"错误信息：{err or '（无）'}",
                kind="warn")
        except Exception:
            pass

    def _draw_remote_qr(self, url: str) -> None:
        try:
            import qrcode
            from PIL import Image, ImageTk
        except Exception as e:
            self.log(f"[手机] 生成二维码需要 qrcode + Pillow：{e}")
            self._copy_remote()
            return

        top = tk.Toplevel(self.root)
        top.title("手机遥控")
        top.configure(bg=ui.BG)
        top.resizable(False, False)

        qr = qrcode.QRCode(box_size=8, border=1,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#000000", back_color="#FFFFFF").convert("RGB")
        img = img.resize((250, 250), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)

        white = tk.Frame(top, bg="#FFFFFF", padx=12, pady=12)
        white.pack(padx=20, pady=(20, 12))
        lbl = tk.Label(white, image=photo, bg="#FFFFFF", bd=0)
        lbl.image = photo          # 不存引用会被回收，图就白了
        lbl.pack()

        tk.Label(top, text="手机连同一个 WiFi，扫码打开",
                 bg=ui.BG, fg=ui.TEXT2, font=(ui.FONT, 10)).pack()
        tk.Label(top, text=url.replace("http://", ""), bg=ui.BG, fg=ui.BLUE,
                 font=(ui.FONT, 9), wraplength=300, justify="center").pack(pady=(4, 12))

        row = tk.Frame(top, bg=ui.BG)
        row.pack(pady=(0, 8))
        ui.RoundButton(row, "复制网址", command=self._copy_remote,
                       width=104, height=32, bg=ui.BG).pack(side="left")
        ui.RoundButton(row, "放行防火墙", command=self._open_firewall,
                       width=104, height=32, bg=ui.BG).pack(side="left", padx=(8, 0))

        others = [ip for ip in remote.local_ips() if ip != self.remote.ip]
        if others:
            tk.Label(top, text="连不上就换：" +
                     "  ".join(f"{ip}:{self.remote.port}" for ip in others),
                     bg=ui.BG, fg=ui.TEXT3, font=(ui.FONT, 8)).pack(pady=(0, 14))
        else:
            tk.Frame(top, bg=ui.BG, height=14).pack()

        top.update_idletasks()
        w, h = top.winfo_width(), top.winfo_height()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 3
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        # 主窗口是 topmost，这里的 topmost 要放在内容加完、定位之后再设，
        # 否则偶尔会被主窗口压到后面（用户看到的就是「点了没反应」）
        try:
            top.attributes("-topmost", True)
            top.lift()
            top.focus_force()
        except Exception:
            pass


    def _check_firewall(self) -> None:
        """没放行就提醒一句 —— 这是手机连不上最常见的原因。"""
        try:
            if winapi.firewall_rule_exists():
                return
        except Exception:
            return
        self.log("[手机] 防火墙还没放行，手机连不上就点“二维码”→“放行防火墙”")

    def _open_firewall(self) -> None:
        port = self.remote.port or 8765
        if winapi.firewall_rule_exists():
            self.log("[手机] 防火墙规则已存在，不用重复添加")
            return
        if winapi.add_firewall_rule(port):
            self.log(f"[手机] 已弹出 UAC，点“是”即可放行 {port} 端口")
        else:
            self.log("[手机] 放行失败，可以手动用管理员 PowerShell 跑：")
            self.log(f'       netsh advfirewall firewall add rule name="ValoTalk Remote" '
                     f'dir=in action=allow protocol=TCP localport={port}')

    # ============================================================ 启停
    def _autostart(self) -> None:
        self.start()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.differ.reset()
        self._ui_state("● 启动中…", "#fbbf24")

        threading.Thread(target=self._boot_bg, daemon=True).start()
        threading.Thread(target=self._asr_worker, name="asr-worker", daemon=True).start()
        threading.Thread(target=self._post_worker, name="post-worker", daemon=True).start()
        self._start_chat_loop()

    def _boot_bg(self) -> None:
        # 1) 模型
        ok = self.asr.ensure_loaded(on_status=lambda s: self.log(f"[模型] {s}"))
        if not ok:
            self.log("[模型] 加载失败：" + (self.asr.load_error or ""))
            self.log("       先跑 setup.ps1 装依赖，或把 asr.model 改小（base/tiny）。")
        # 1.5) 云端 ASR 预热：不预热的话第一句话要多等 3 秒（TLS 握手）
        lang = str(self._get("asr.lang_teammates", "en") or "en")
        if self._use_cloud_asr(lang):
            if self.asr_cloud.warmup():
                self.log(f"[云端ASR] {self.asr_cloud.describe()} 就绪"
                         f"（音频会发送到该服务识别）")
            else:
                self.log(f"[云端ASR] {self.asr_cloud.last_error}，降级用本地识别")
        # 2) 采集
        self._start_capture()
        # 3) 常用喊话的英文语音先合成好，游戏里命中时零延迟
        self.tts.warmup(sorted(set(VOICE_LINES.values())))
        self._ui_state("● 运行中", "#34d399")

    def _make_segmenter(self, vad: dict):
        """优先 Silero（能区分人声和音效），不可用才退回能量 VAD。"""
        seg = capture.SileroSegmenter(vad)
        if getattr(seg, "ok", False):
            self.log("断句: Silero VAD（只把人声送去做识别）")
            return seg
        self.log("断句: Silero 不可用，退回能量 VAD —— 背景音大时会失准")
        return capture.Segmenter(vad)

    def _start_capture(self) -> None:
        game_dev = self._get("audio.game_output_device", "")
        mic_dev = self._get("audio.mic_device", "")
        sr = int(self._get("audio.capture_samplerate", 48000) or 48000)
        block = int(self._get("audio.block_ms", 30) or 30)
        vad = self._get("audio.vad", {}) or {}

        if game_dev:
            self._seg_team = self._make_segmenter(vad)
            src = capture.AudioSource(game_dev, True, sr, block, self._on_team_audio,
                                      label="game")
            src.start()
            self._sources["game"] = src
            self.log(f"采集队友语音：{game_dev}" + (f"（{src.error}）" if src.error else ""))
        else:
            self.log("未设置游戏输出设备，队友语音字幕不会工作。")

        if mic_dev:
            self._seg_me = self._make_segmenter(vad)
            src = capture.AudioSource(mic_dev, False, sr, block, self._on_mic_audio,
                                      label="mic")
            src.start()
            self._sources["mic"] = src
            self.log(f"采集麦克风：{mic_dev}" + (f"（{src.error}）" if src.error else ""))

        self.log(f"英文语音输出设备：{self._get('audio.tts_output_device', '(未设置)')}")

    def stop(self) -> None:
        self._running = False
        for src in self._sources.values():
            src.stop()
        self._sources.clear()
        self._chat_stop.set()
        self._ui_state("● 已停止", "#f87171")
        self.log("已停止采集。")

    def shutdown(self) -> None:
        try:
            self.stop()
            self.hotkeys.stop()
            self.remote.stop()
            self._set("overlay.x", self.overlay.x, save=False)
            self._set("overlay.y", self.overlay.y, save=True)
        except Exception:
            pass
        self.root.destroy()

    # ============================================================ 采集回调
    def _on_team_audio(self, pcm: np.ndarray) -> None:
        if not self.flags["team"] or self._seg_team is None:
            return
        for seg in self._seg_team.feed(pcm):
            self._submit_asr("teammates", seg)

    def _on_mic_audio(self, pcm: np.ndarray) -> None:
        if self._seg_me is None:
            return
        for seg in self._seg_me.feed(pcm):
            if not self._me_armed or not self.flags["me"]:
                continue
            if self._muted_outgoing:
                continue
            self._submit_asr("me", seg)

    def _submit_asr(self, kind: str, pcm: np.ndarray) -> None:
        job = Job(kind=kind, pcm=pcm)
        try:
            self.asr_q.put_nowait(job)
        except queue.Full:
            try:
                self.asr_q.get_nowait()
                self.asr_q.put_nowait(job)
            except Exception:
                pass

    # ============================================================ 工作线程
    def _asr_worker(self) -> None:
        while True:
            try:
                job = self.asr_q.get()
            except Exception:
                continue
            if job is None:
                continue
            # 队友语音：按界面选定的服区固定语种，不做自动检测
            if job.kind == "teammates":
                lang = str(self._get("asr.lang_teammates", "en") or "en")
                if lang in ("auto", "detect", ""):
                    lang = "en"
            else:
                lang = self._get("asr.lang_me", "zh")

            text = self._transcribe(job, lang)
            if not text:
                continue
            job.text = text
            try:
                self.post_q.put_nowait(job)
            except queue.Full:
                try:
                    self.post_q.get_nowait()
                    self.post_q.put_nowait(job)
                except Exception:
                    pass

    def _use_cloud_asr(self, lang: str = "") -> bool:
        """该不该用大模型（云端）识别。

        主页「语音识别」那一行的启用按钮直接控制，两个服务器都生效：
          cloud → 用云端（前提是配了 key）
          local → 用本地
        兼容老配置：auto 视为 cloud（原来日服自动走云端）。
        """
        want = str(self._get("asr.backend", "cloud") or "cloud").lower()
        if want in ("local", "off", "false"):
            return False
        return self.asr_cloud.available()

    def _transcribe(self, job: Job, lang: str) -> str:
        """按配置选后端。云端失败且允许回退时用本地。"""
        text = ""
        if self._use_cloud_asr(lang):
            text = self.asr_cloud.transcribe(job.pcm, lang)
            if text:
                job.asr_backend = "cloud"
            else:
                err = self.asr_cloud.last_error or "返回空"
                if self._get("asr.cloud_fallback", True):
                    now = time.time()
                    if now - getattr(self, "_cloud_warn_at", 0) > 60:
                        self._cloud_warn_at = now
                        self.log(f"[云端ASR] 失败（{err}），本次改用本地识别")
                else:
                    self.log(f"[云端ASR] 失败：{err}")
                    return ""

        if not text:
            # 本地
            if not self.asr.loaded and not self._reload_asr():
                return ""
            try:
                text = self.asr.transcribe(job.pcm, lang)
            except Exception as exc:
                self.log(f"[识别异常] {exc}")
                return ""
            if text:
                job.asr_backend = "local"

        if not text:
            return ""

        # 日语同音字纠正（ウルト→売ると 这类），云端和本地都适用
        if lang.startswith("ja"):
            fixed = fix_ja_terms(text)
            if fixed != text:
                self.log(f"[纠错] {text} → {fixed}")
                text = fixed

        job.detected_lang = lang if job.asr_backend == "cloud" else \
            (getattr(self.asr, "last_language", None) or lang)
        return text

    def _reload_asr(self) -> bool:
        """失效后重建，最多每 10 秒试一次。"""
        now = time.time()
        if now - getattr(self, "_asr_retry_at", 0) < 10:
            return False
        self._asr_retry_at = now
        self.log("[模型] 重新加载 …")
        ok = self.asr.ensure_loaded(on_status=lambda s: self.log(f"[模型] {s}"))
        if ok:
            self.log("[模型] 已恢复")
        else:
            self.log("[模型] 仍失败：" + (self.asr.load_error or "") + self.asr._load_error_hint())
        return ok

    def _post_worker(self) -> None:
        while True:
            try:
                job = self.post_q.get()
            except Exception:
                continue
            try:
                self._dispatch(job)
            except Exception as exc:
                self.log(f"[处理异常] {exc}")

    def _dispatch(self, job: Job) -> None:
        if job.kind == "teammates":
            if not self.flags["team"]:
                return
            src = job.detected_lang or self._get("asr.lang_teammates", "en") or "en"
            tag = ""
            if job.asr_backend == "cloud":
                tag = "〔云〕"
            zh = self.translator.translate(job.text, src, "zh-CN")
            shown = zh or "（翻译失败）" + job.text
            self.log(f"队友：{job.text} → {zh} {tag}".rstrip())
            self._overlay("队友", shown, job.text if zh else "")
        elif job.kind == "me":
            if not self.flags["me"] or self._muted_outgoing:
                return
            # 我说中文 → 翻成队友听得懂的语言（英服英语 / 日服日语）
            server_lang = str(self._get("asr.lang_teammates", "en") or "en")
            target = "ja" if server_lang.startswith("ja") else "en"
            out = self.translator.translate(job.text, "zh", target)
            if not out:
                self.log(f"[翻译失败] {job.text}")
                return
            self.log(f"我：{job.text} → {out}")
            self._overlay("我", out, job.text)
            self.tts.speak(out)
        elif job.kind == "chat":
            if not self.flags["chat"] or not job.text:
                return
            zh = self.translator.translate(job.text, "en", "zh-CN")
            self.log(f"聊天：{job.text} → {zh or '（失败）'}")
            self._overlay("聊天", zh or job.text, job.text if zh else "")

    # ============================================================ 聊天 OCR
    def _start_chat_loop(self) -> None:
        if self._chat_thread and self._chat_thread.is_alive():
            return
        self._chat_stop.clear()
        self._chat_thread = threading.Thread(target=self._chat_loop, name="chat-ocr",
                                             daemon=True)
        self._chat_thread.start()

    def _chat_loop(self) -> None:
        """聊天框 OCR 轮询。

        空闲退避：聊天框长时间没新内容时把间隔按倍数拉长（最多 4 倍），
        一旦出现新行立刻回到正常节奏。OCR 一次要 930ms CPU（1 线程），
        按 2s 间隔算就是 46% 单核 —— 静止时没必要这么勤。
        """
        miss = 0
        idle = 0                      # 连续几次没有新内容
        while not self._chat_stop.is_set():
            base = max(400, int(self._get("ocr.interval_ms", 2500) or 2500))
            backoff_max = float(self._get("ocr.idle_backoff_max", 4.0) or 4.0)
            # 连续 3 次无新行就开始退避：×2、×3、×4（封顶）
            step = 0 if idle < 3 else min(int(backoff_max), 1 + (idle - 2))
            interval = base * max(1, step)

            region = self._get("ocr.region", [0, 0, 0, 0])
            if not self.flags["chat"] or not region or region[2] <= region[0]:
                time.sleep(0.4)
                continue
            img = self.ocr.grab(region)
            if img is None:
                miss += 1
                if miss in (10, 60):
                    self.log(f"[聊天OCR] {self.ocr.last_error}")
                time.sleep(interval / 1000.0)
                continue
            miss = 0
            lines = self.ocr.read_lines(img)
            fresh = self.differ.push(lines)
            # 只翻玩家说的话；系统广播（下包/回合/上线提示）整行无视
            fresh = [ln for ln in fresh if is_player_chat(ln)]
            if fresh:
                idle = 0                      # 有新消息，回到正常节奏
            else:
                idle += 1
            for ln in fresh[:4]:
                try:
                    self.post_q.put_nowait(Job(kind="chat", text=ln))
                except queue.Full:
                    break
            time.sleep(interval / 1000.0)

    def _pick_region(self) -> None:
        top = tk.Toplevel(self.root)
        top.attributes("-fullscreen", True)
        top.attributes("-alpha", 0.30)
        top.attributes("-topmost", True)
        top.configure(bg="black")
        top.config(cursor="crosshair")
        cv = tk.Canvas(top, bg="black", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.create_text(
            top.winfo_screenwidth() // 2, 60,
            text="拖一个框住左下角聊天框的矩形（Esc 取消）",
            fill="#7DD3FC", font=(FONT, 26, "bold"),
        )
        state = {"sx": 0, "sy": 0, "cx": 0, "cy": 0, "rect": None}

        def press(e):
            state["sx"], state["sy"] = e.x_root, e.y_root
            state["cx"], state["cy"] = e.x, e.y
            state["rect"] = cv.create_rectangle(e.x, e.y, e.x, e.y,
                                                outline="#34d399", width=3)

        def drag(e):
            if state["rect"]:
                cv.coords(state["rect"], state["cx"], state["cy"], e.x, e.y)

        def release(e):
            x1, y1 = min(state["sx"], e.x_root), min(state["sy"], e.y_root)
            x2, y2 = max(state["sx"], e.x_root), max(state["sy"], e.y_root)
            if x2 - x1 > 40 and y2 - y1 > 30:
                self._set("ocr.region", [int(x1), int(y1), int(x2), int(y2)])
                self._update_region_label()
                self.differ.reset()
                self.log(f"聊天区域已设置：({x1},{y1}) - ({x2},{y2})")
            top.destroy()

        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", drag)
        cv.bind("<ButtonRelease-1>", release)
        top.bind("<Escape>", lambda _e: top.destroy())

    def _update_region_label(self) -> None:
        r = self._get("ocr.region", [0, 0, 0, 0]) or [0, 0, 0, 0]
        if r[2] > r[0]:
            self.region_lbl.configure(
                text=f"{r[0]},{r[1]} → {r[2]},{r[3]}（{r[2]-r[0]}×{r[3]-r[1]}）")
        else:
            self.region_lbl.configure(text="未设置")

    # ============================================================ 小工具
    def _test_tts(self) -> None:
        self.log("TTS 测试：I am rotating to B site, watch the flank.")

        def run():
            ok = self.tts.speak("I am rotating to B site, watch the flank.")
            self.log("TTS 测试" + ("成功（游戏应能听到）" if ok else
                                   "失败：" + (self.tts.last_error or "未知")))

        threading.Thread(target=run, daemon=True).start()

    # ============================================================ 权限
    def _check_permission(self) -> None:
        """游戏是 High 完整性级别，我们是 Medium 时模拟按键会被 UIPI 丢掉。

        SendInput 照样返回成功，所以不说出来的话完全看不出问题。
        只能在主线程调用（要动控件）。
        """
        if not winapi.keyinject_blocked():
            self.perm_lbl.pack_forget()
            self.perm_row.pack_forget()
            self.perm_card.refresh()
            return
        self.perm_lbl.configure(
            text="⚠ 未以管理员运行：模拟的 V 会被系统丢弃，队友听不到英文")
        self.perm_lbl.pack(fill="x", pady=(8, 0))
        self.perm_row.pack(fill="x", pady=(6, 0))
        self.perm_card.refresh()
        self.log("⚠ 权限不足：游戏跑在 High 完整性级别，本程序是 Medium。")
        self.log("   Windows 会静默丢弃跨级别的模拟按键 —— 英文送不进游戏。")
        self.log("   点「以管理员重启」，或右键 run.bat → 以管理员身份运行。")

    def _relaunch_admin(self) -> None:
        self.log("正在以管理员身份重启 …")
        if winapi.relaunch_as_admin():
            self.shutdown()
        else:
            self.log("提权被取消。可以手动：右键 run.bat → 以管理员身份运行")

    # ============================================================ 自动更新
    def _check_update_async(self) -> None:
        if not self._get("update.check_on_start", True):
            return
        threading.Thread(target=self._check_update, name="update-check",
                         daemon=True).start()

    def _check_update(self) -> None:
        """启动时的自动检查：只在有新版本时弹窗，其它情况静默。"""
        try:
            info = self.updater.check()
        except Exception as exc:
            self.log(f"[更新] 检查失败：{exc}")
            return
        if info is None:
            if self.updater.last_error:
                self.log(f"[更新] {self.updater.last_error}")
            return
        # 「下次再说」记住过的版本不再打扰，直到出现更新的版本
        skipped = str(self._get("update.skipped_version", "") or "")
        if skipped and updater.parse_version(skipped) >= updater.parse_version(info.version):
            return
        self.log(f"[更新] 发现新版本 v{info.version}（当前 v{__version__}）")
        self.root.after(0, lambda: self._show_update_dialog(info))

    def _show_update_dialog(self, info) -> None:
        from .update_ui import UpdateDialog
        if self._update_dialog is not None:
            try:
                if self._update_dialog.top.winfo_exists():
                    return
            except Exception:
                pass
        self._update_dialog = UpdateDialog(
            self.root, info, self.updater,
            on_applied=self._restart_for_update,
            log=self.log,
            on_later=lambda: self._set("update.skipped_version", info.version),
        )

    def _restart_for_update(self) -> None:
        """更新完成后重启：优先用 run.bat（它会自己处理提权）。"""
        run_bat = Path(__file__).resolve().parent.parent / "run.bat"
        self.log("[更新] 正在重启 …")
        try:
            if run_bat.exists():
                subprocess.Popen(["cmd", "/c", str(run_bat)],
                                 cwd=str(run_bat.parent),
                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            else:
                winapi.relaunch_as_admin()
        except Exception as exc:
            self.log(f"[更新] 重启失败：{exc}，请手动重开")
            return
        self.shutdown()

    def _manual_check_update(self) -> None:
        """手动检查更新：忽略 skipped_version，结果一定告诉用户。

        和启动时的自动检查不冲突 —— 自动检查只在有新版本时弹窗，
        静默失败；手动检查一定会给反馈（已是最新 / 发现新版 / 失败）。
        """
        if getattr(self, "_upd_checking", False):
            return
        self._upd_checking = True
        self._ui_call(self.btn_update, "set_enabled", False)
        self._ui_call(self.btn_update, "set_text", "检查中…")
        self.log("[更新] 手动检查 …")
        # 手动检查视为「我主动想知道」，清掉之前压下的忽略项
        self._set("update.skipped_version", "")

        def run():
            try:
                info = self.updater.check()
                err = self.updater.last_error
            except Exception as exc:
                info, err = None, f"{type(exc).__name__}: {exc}"
            self._uiq.put(lambda: self._manual_check_done(info, err))

        threading.Thread(target=run, name="update-manual", daemon=True).start()

    def _manual_check_done(self, info, err: str) -> None:
        self._upd_checking = False
        self._ui_call(self.btn_update, "set_enabled", True)
        self._ui_call(self.btn_update, "set_text", "检查更新")

        if info is not None:
            self.log(f"[更新] 发现新版本 v{info.version}")
            self._show_update_dialog(info)
            return
        if err:
            self.log(f"[更新] 检查失败：{err}")
            from .update_ui import NoticeDialog
            NoticeDialog(
                self.root, "检查更新失败",
                f"{err}\n\n可能是网络问题，稍后再试。也可以到 GitHub Releases "
                f"页面手动下载最新版。", kind="fail")
            return
        self.log(f"[更新] 当前 v{__version__} 已是最新版本")
        from .update_ui import NoticeDialog
        NoticeDialog(
            self.root, "已是最新版本",
            f"当前版本 v{__version__}，没有可用的更新。", kind="ok")

    def _overlay(self, tag: str, text: str, original: str = "") -> None:
        self._ui_call(self.overlay, "add", tag, text, original)

    def _ui_state(self, text: str, color: str) -> None:
        def apply():
            self.state_lbl.configure(text=text, foreground=color)
        self._uiq.put(apply)

    def _ui_call(self, obj, method: str, *args) -> None:
        def apply():
            try:
                getattr(obj, method)(*args)
            except Exception:
                pass
        self._uiq.put(apply)

    def _pump_ui(self) -> None:
        for _ in range(40):
            try:
                fn = self._uiq.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass
        # 采集电平：一眼看出有没有真的在收声音。
        # 200ms 刷一次即可 —— 40ms 一次等于每秒重排 25 次界面，白占资源
        now = time.time()
        if now - getattr(self, "_last_meter", 0.0) > 0.2:
            self._last_meter = now
            try:
                game = self._sources.get("game")
                mic = self._sources.get("mic")
                bar = ""
                for name, src in (("游戏", game), ("麦", mic)):
                    if src is None:
                        bar += f"{name} —  "
                    else:
                        p = src.peak
                        n = 0 if p < 0.005 else (1 if p < 0.02 else 2 if p < 0.06
                                                 else 3 if p < 0.15 else 4)
                        bar += f"{name} {'▁▃▅▇█'[n]}  "
                self.meter_lbl.configure(text=bar)
            except Exception:
                pass
        self.root.after(40, self._pump_ui)

    def log(self, msg: str) -> None:
        line = time.strftime("%H:%M:%S ") + str(msg)
        self.log_lines.append(line)
        if len(self.log_lines) > 800:
            self.log_lines = self.log_lines[-500:]

        def apply():
            try:
                self.txt.append(line)
            except Exception:
                pass

        self._uiq.put(apply)
        try:
            print(line, flush=True)
        except Exception:
            pass

    # ============================================================ 主循环
    def run(self) -> None:
        self._update_region_label()
        self.log("ValoTalk 启动。F2=按住说中文  F3=字幕穿透  F4=清屏  F5=静音英文输出")
        self.root.mainloop()


def main() -> None:
    # 先查 Python 版本：版本不对的话，后面 import 里那堆原生扩展会报
    # "No matching distribution found" 一类的错，用户根本看不出是版本问题。
    if not envcheck.check_or_exit():
        raise SystemExit(2)
    App().run()


if __name__ == "__main__":
    main()