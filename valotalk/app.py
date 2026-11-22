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

from . import __version__
from . import capture, remote, ui_theme as ui, updater, winapi
from .asr import WhisperASR
from .asr_cloud import CloudASR, fix_ja_terms
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
        self._build_ui()
        self._bind_hotkeys()

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

    # ============================================================ UI
    def _build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"ValoTalk v{__version__} · 无畏契约实时翻译")
        self.root.geometry("980x720")
        self.root.minsize(920, 660)
        self.root.configure(bg=ui.BG)
        ui.make_styles()
        if self._get("ui.panel_on_top", True):
            self.root.attributes("-topmost", True)

        outer = tk.Frame(self.root, bg=ui.BG)
        outer.pack(fill="both", expand=True, padx=14, pady=12)

        # ---------------- 顶部一栏 ----------------
        head = tk.Frame(outer, bg=ui.BG)
        head.pack(fill="x", pady=(0, 10))

        tk.Label(head, text="ValoTalk", bg=ui.BG, fg=ui.TEXT,
                 font=(ui.FONT, 18, "bold")).pack(side="left")
        self.ver_lbl = tk.Label(head, text=f"v{__version__}", bg=ui.BG, fg=ui.TEXT3,
                                font=(ui.FONT, 9), cursor="hand2")
        self.ver_lbl.pack(side="left", padx=(6, 0), pady=(7, 0))
        self.ver_lbl.bind("<Button-1>", lambda _e: self._manual_check_update())
        self.ver_lbl.bind("<Enter>", lambda _e: self.ver_lbl.configure(fg=ui.BLUE))
        self.ver_lbl.bind("<Leave>", lambda _e: self.ver_lbl.configure(fg=ui.TEXT3))

        # 手动检查更新（和启动时自动检查互不干扰）
        self.btn_update = ui.RoundButton(
            head, "检查更新", command=self._manual_check_update,
            width=76, height=24, fill=ui.CARD2, bg=ui.BG, font_size=ui.FS_SMALL)
        self.btn_update.pack(side="left", padx=(8, 0), pady=(3, 0))

        self.state_lbl = tk.Label(head, text="● 未启动", bg=ui.BG, fg=ui.RED,
                                  font=(ui.FONT, 10, "bold"))
        self.state_lbl.pack(side="left", padx=(12, 0))
        self.meter_lbl = tk.Label(head, text="", bg=ui.BG, fg=ui.TEXT2,
                                  font=(ui.FONT, 9))
        self.meter_lbl.pack(side="left", padx=(8, 0))

        ui.RoundButton(head, "▶ 开始", command=self.start, width=86, height=32,
                       fill=ui.BLUE, bold=True, bg=ui.BG).pack(side="right")
        ui.RoundButton(head, "■ 停止", command=self.stop, width=74, height=32,
                       fill=ui.CARD2, bg=ui.BG).pack(side="right", padx=(0, 8))
        mc = ui.RoundCombo(head, ["tiny", "base", "small", "medium"], width=92,
                           height=32, bg=ui.BG)
        mc.set(str(self._get("asr.model", "small")))
        mc.pack(side="right", padx=(0, 6))
        mc.bind_select(self._on_model_change)
        self.model_var = mc.var
        self.cb_model_ui = mc
        tk.Label(head, text="模型", bg=ui.BG, fg=ui.TEXT2,
                 font=(ui.FONT, 9)).pack(side="right", padx=(12, 5))

        # ---------------- 两列主体 ----------------
        main = tk.Frame(outer, bg=ui.BG)
        main.pack(fill="both", expand=True)

        left = tk.Frame(main, bg=ui.BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 7))
        right = tk.Frame(main, bg=ui.BG)
        right.pack(side="left", fill="both", expand=True, padx=(7, 0))

        # ===== 左列：音频设备 =====
        card = ui.RoundCard(left, pad=14)
        card.pack(fill="x", pady=(0, 10))
        body = card.body
        tk.Label(body, text="音频设备", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, 9, "bold"), anchor="w").pack(fill="x", pady=(0, 8))

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
        # 日服会切到大模型链路，标出来让用户知道音频会上传
        self.asr_mode_lbl = tk.Label(row, text="", bg=ui.CARD, fg=ui.TEXT3,
                                     font=(ui.FONT, 8), anchor="w")
        self.asr_mode_lbl.pack(side="left", padx=(6, 0))

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

        # ===== 左列：功能开关 =====
        card2 = ui.RoundCard(left, pad=14)
        card2.pack(fill="both", expand=True)
        b2 = card2.body
        tk.Label(b2, text="功能开关", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))

        self.v_team = tk.BooleanVar(value=True)
        self.v_me = tk.BooleanVar(value=True)
        self.v_chat = tk.BooleanVar(value=True)
        self.v_orig = tk.BooleanVar(value=bool(self._get("overlay.show_original", True)))
        self.v_through = tk.BooleanVar(value=bool(self._get("overlay.click_through", True)))
        self.v_cpu = tk.BooleanVar(value=str(self._get("asr.device", "auto")) == "cpu")
        self.v_remote = tk.BooleanVar(value=bool(self._get("remote.enabled", False)))
        self.v_big_asr = tk.BooleanVar(value=self._use_cloud_asr())

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
            ("大模型识别（更准）", self.v_big_asr, self._on_big_asr_toggle),
            ("手机遥控", self.v_remote, self._on_remote_toggle),
        ]:
            tr = ui.ToggleRow(b2, text, var, command=cb)
            tr.pack(fill="x", pady=1)
            if var is self.v_me:
                self.chk_me = tr
            elif var is self.v_remote:
                self.chk_remote = tr
            elif var is self.v_big_asr:
                self.chk_big_asr = tr

        # 大模型识别：显示当前服务商，没配 key 时提示
        self.big_asr_lbl = tk.Label(
            self.chk_big_asr.extra, text="", bg=ui.CARD, fg=ui.TEXT3,
            font=(ui.FONT, 8), anchor="w")
        self.big_asr_lbl.pack(side="left")
        self.chk_big_asr.pack_extra()

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

        # ===== 右列：快捷键 =====
        card3 = ui.RoundCard(right, pad=14)
        card3.pack(fill="x", pady=(0, 10))
        b3 = card3.body
        tk.Label(b3, text="快捷键（改完立刻生效）", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))

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

        # ===== 右列：聊天区域 & 翻译 =====
        card4 = ui.RoundCard(right, pad=14)
        card4.pack(fill="x", pady=(0, 10))
        b4 = card4.body
        tk.Label(b4, text="聊天区域 & 翻译后端", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))

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

        # ===== 右列：日志 =====
        card5 = ui.RoundCard(right, pad=14)
        card5.pack(fill="both", expand=True)
        b5 = card5.body
        tk.Label(b5, text="运行日志", bg=ui.CARD, fg=ui.TEXT2,
                 font=(ui.FONT, 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))

        log_wrap = tk.Frame(b5, bg=ui.CARD2)
        log_wrap.pack(fill="both", expand=True)
        self.txt = tk.Text(log_wrap, height=6, bg=ui.CARD2, fg=ui.TEXT2,
                           insertbackground=ui.TEXT, font=(ui.FONT, ui.FS_SMALL),
                           relief="flat", bd=0, highlightthickness=0,
                           wrap="word", padx=8, pady=6)
        self.txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_wrap, command=self.txt.yview,
                           style="Vertical.TScrollbar")
        sb.pack(side="right", fill="y")
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.configure(state="disabled")

        self._refresh_devices(initial=True)

        # Windows 11 窗口圆角 + 深色标题栏（Win10 上这两个调用会静默失败）
        try:
            self.root.update_idletasks()
            hwnd = winapi.top_level_hwnd(self.root)
            winapi.set_rounded_window(hwnd, winapi.DWMWCP_ROUND)
            winapi.set_dark_titlebar(hwnd, True)
        except Exception:
            pass

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
        """把当前识别/翻译通道显示在服务器那一行。"""
        lang = lang or str(self._get("asr.lang_teammates", "en") or "en")
        cloud = self._use_cloud_asr(lang)
        ja = lang.startswith("ja")
        if cloud:
            # 显示具体服务商，让用户知道音频发到哪
            who = self.asr_cloud.describe() or "云端"
            txt, color = f"☁ {who} + LLM 翻译", ui.BLUE
            tip = "音频会上传到该服务"
        elif not self.asr_cloud.available():
            txt, color = "本地识别 · 没配 API key", ui.ORANGE
            tip = ""
        elif ja:
            txt, color = "本地识别 + LLM 翻译", ui.TEXT3
            tip = ""
        else:
            txt, color = "本地识别", ui.TEXT3
            tip = ""
        try:
            self.asr_mode_lbl.configure(text=txt, fg=color)
        except Exception:
            pass
        if tip:
            self.log(f"[识别] {txt}（{tip}）")
        self._refresh_big_asr_label()

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

    # ============================================================ 大模型识别
    def _on_big_asr_toggle(self) -> None:
        """「大模型识别」开关：两个服务器都生效。"""
        want = bool(self.v_big_asr.get())
        if want and not self.asr_cloud.available():
            # 没 key 就别让开关停在"开着但用不了"
            self.v_big_asr.set(False)
            self._set("asr.backend", "local")
            self.log("[识别] 没配 LLM API key，无法使用大模型识别")
            self.log("       在「聊天区域 & 翻译后端」里填 LLM 的 base_url / 模型 / 密钥")
            self._refresh_big_asr_label()
            self._refresh_asr_mode_label()
            return

        self._set("asr.backend", "cloud" if want else "local")
        if want:
            self.log("[识别] 已切换到大模型识别（音频会发送到 "
                     f"{self.asr_cloud.describe()}）")
            threading.Thread(target=self._warm_cloud_asr, daemon=True).start()
        else:
            self.log("[识别] 已切换回本地识别（不上传音频）")
        self._refresh_big_asr_label()
        self._refresh_asr_mode_label()

    def _refresh_big_asr_label(self) -> None:
        """开关旁边显示当前服务商 / 提示。"""
        def apply():
            try:
                if not self.asr_cloud.available():
                    self.big_asr_lbl.configure(text="未配 key", fg=ui.ORANGE)
                elif self._use_cloud_asr():
                    self.big_asr_lbl.configure(
                        text=self.asr_cloud.describe(), fg=ui.BLUE)
                else:
                    self.big_asr_lbl.configure(text="用本地 whisper", fg=ui.TEXT3)
            except Exception:
                pass
        self._uiq.put(apply)

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
        """弹二维码 —— 总比让用户在手机上敲 IP 强。"""
        url = self.remote.url
        if not url:
            self.log("[手机] 还没启动，稍等一下")
            return
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
        top.attributes("-topmost", True)
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

        面板上的「大模型识别」开关直接控制，两个服务器都生效：
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
                self.txt.configure(state="normal")
                self.txt.insert("end", line + "\n")
                self.txt.see("end")
                self.txt.configure(state="disabled")
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
    App().run()


if __name__ == "__main__":
    main()