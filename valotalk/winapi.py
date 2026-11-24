"""Windows 原生交互：全局热键轮询、按键注入、窗口样式。

零第三方依赖，全部走 ctypes：不装键盘钩子，避免与游戏输入层互相干扰。
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from collections import deque
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---------------- 按键常量 ----------------
VK = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "capslock": 0x14, "tab": 0x09, "space": 0x20, "enter": 0x0D, "esc": 0x1B,
    "insert": 0x2D, "home": 0x24, "end": 0x23, "delete": 0x2E,
    "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA,
    "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())
for _d in "0123456789":
    VK[_d] = ord(_d)

# 鼠标侧键（后退/前进）。左右中键故意不给 —— 会干扰正常点击。
# GetAsyncKeyState 能直接读到这两个键的状态，所以当热键用是安全的。
VK["mouse4"] = 0x05      # XBUTTON1 侧键（后退）
VK["mouse5"] = 0x06      # XBUTTON2 侧键（前进）
MOUSE_KEYS = {0x05: 0x0001, 0x06: 0x0002}   # vk -> XBUTTON 标识

# 界面上可选的热键（避开字母，免得打字时误触；V 留给游戏开麦）
HOTKEY_CHOICES = [
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "CAPSLOCK", "TAB", "INSERT", "HOME", "END", "DELETE", "PAGEUP", "PAGEDOWN",
    "MOUSE4", "MOUSE5", "`",
]


def vk_of(name: str) -> int:
    key = (name or "").strip().lower()
    if key in VK:
        return VK[key]
    if len(key) == 1:
        return ord(key.upper())
    raise KeyError(f"未知按键: {name}")


# ---------------- 按键注入 ----------------
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100


def _send_key(vk: int, up: bool) -> None:
    scan = user32.MapVirtualKeyW(vk, 0)
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.union.ki = _KEYBDINPUT(
        wVk=0, wScan=scan,
        dwFlags=KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0),
        time=0, dwExtraInfo=None,
    )
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _send_xbutton(xbutton: int, up: bool) -> None:
    """模拟鼠标侧键（游戏的语音键也可以绑侧键）。"""
    inp = _INPUT(type=INPUT_MOUSE)
    mi = _MOUSEINPUT()
    mi.dx = 0
    mi.dy = 0
    mi.mouseData = xbutton
    mi.dwFlags = MOUSEEVENTF_XUP if up else MOUSEEVENTF_XDOWN
    mi.time = 0
    mi.dwExtraInfo = None
    inp.union.mi = mi
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def key_down(name: str) -> None:
    try:
        vk = vk_of(name)
        if vk in MOUSE_KEYS:
            _send_xbutton(MOUSE_KEYS[vk], up=False)
        else:
            _send_key(vk, up=False)
    except Exception:
        pass


def key_up(name: str) -> None:
    try:
        vk = vk_of(name)
        if vk in MOUSE_KEYS:
            _send_xbutton(MOUSE_KEYS[vk], up=True)
        else:
            _send_key(vk, up=True)
    except Exception:
        pass


class VirtualKeyHold:
    """按住某个键一段时间（用于游戏内语音键）。支持重入计数。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._count = 0
        self._key = ""

    def acquire(self, key: str) -> None:
        with self._lock:
            if not key:
                return
            if self._count == 0:
                self._key = key
                key_down(key)
            self._count += 1

    def release(self, settle_ms: int = 0) -> None:
        with self._lock:
            if self._count <= 0:
                return
            self._count -= 1
            if self._count == 0 and self._key:
                if settle_ms > 0:
                    time.sleep(settle_ms / 1000.0)
                key_up(self._key)


# ---------------- 热键轮询 ----------------
# 低级鼠标钩子：GetAsyncKeyState 对 XBUTTON1/2 不可靠（微软文档说它主要管键盘），
# 游戏里按侧键基本读不到。WH_MOUSE_LL 是系统级钩子，在 Raw Input 之前就能拿到事件。
WH_MOUSE_LL = 14
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_QUIT = 0x0012

# ---------------- Raw Input（比钩子可靠，后台也能收） ----------------
WM_INPUT = 0x00FF
RIDEV_INPUTSINK = 0x00000100      # 关键：窗口在后台也能收到输入
RIDEV_DEVNOTIFY = 0x00002000
RIM_TYPEKEYBOARD = 1
RID_INPUT = 0x10000003
RI_KEY_BREAK = 0x01


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("keyboard", RAWKEYBOARD)]


# 声明签名：不声明的话 64 位 LPARAM/HWND 会被当 32 位 int，溢出报错
try:
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                       wintypes.LPVOID,
                                       ctypes.POINTER(wintypes.UINT),
                                       wintypes.UINT]
    user32.GetRawInputData.restype = wintypes.UINT
    user32.RegisterRawInputDevices.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                               wintypes.UINT]
    user32.RegisterRawInputDevices.restype = wintypes.BOOL
except Exception:
    pass


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class RawKeyboardInput:
    """用 Raw Input + RIDEV_INPUTSINK 读键盘。

    和低级钩子不同：窗口**不需要前台**，游戏独占焦点时系统仍会把
    键盘原始事件投递到我们注册的窗口。Vanguard 拦钩子但拦不住这个
    （拦了系统就没法给其它程序派发输入了）。
    """

    CLASS_NAME = "ValoTalkRawInput"

    def __init__(self):
        self._hwnd = 0
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._queue: deque = deque(maxlen=512)
        self._proc = None
        self.error: str | None = None
        self.keys: set[int] = set()          # 当前按下的 VK
        self.dropped = 0

    def drain(self) -> list[tuple[int, bool]]:
        out: list[tuple[int, bool]] = []
        while True:
            try:
                out.append(self._queue.popleft())
            except IndexError:
                break
        return out

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return bool(self._hwnd)
        self._thread = threading.Thread(target=self._run, name="raw-input",
                                        daemon=True)
        self._thread.start()
        time.sleep(0.15)
        return bool(self._hwnd)

    def stop(self) -> None:
        if self._hwnd:
            try:
                user32.PostMessageW(self._hwnd, WM_QUIT, 0, 0)
            except Exception:
                pass
            self._hwnd = 0
        self._thread = None

    def _run(self) -> None:
        k32 = ctypes.WinDLL("kernel32")
        self._tid = k32.GetCurrentThreadId()
        hinst = k32.GetModuleHandleW(None)
        self._proc = _WNDPROC(self._wndproc)

        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = self.CLASS_NAME
        user32.RegisterClassExW(ctypes.byref(wc))     # 已注册会返回 0，无妨

        # 隐藏窗口，只用来收 WM_INPUT
        self._hwnd = user32.CreateWindowExW(
            0, self.CLASS_NAME, "ValoTalkRaw", 0,
            0, 0, 0, 0, None, None, hinst, None)
        if not self._hwnd:
            self.error = f"CreateWindowEx 失败 err={ctypes.get_last_error()}"
            return

        dev = RAWINPUTDEVICE()
        dev.usUsagePage = 0x01          # Generic Desktop
        dev.usUsage = 0x06              # Keyboard
        dev.dwFlags = RIDEV_INPUTSINK   # ← 后台也收
        dev.hwndTarget = self._hwnd
        ok = user32.RegisterRawInputDevices(ctypes.byref(dev), 1,
                                            ctypes.sizeof(RAWINPUTDEVICE))
        if not ok:
            self.error = f"RegisterRawInputDevices 失败 err={ctypes.get_last_error()}"
            return

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, msg, w_param, l_param):
        if msg == WM_INPUT:
            try:
                self._on_input(l_param)
            except Exception:
                pass
            # 处理完必须调 DefWindowProc，否则系统会一直重发
        return user32.DefWindowProcW(hwnd, msg, w_param, l_param)

    def _on_input(self, l_param) -> None:
        size = wintypes.UINT(0)
        user32.GetRawInputData(l_param, RID_INPUT, None, ctypes.byref(size),
                               ctypes.sizeof(RAWINPUTHEADER))
        if size.value == 0:
            return
        buf = ctypes.create_string_buffer(size.value)
        got = user32.GetRawInputData(l_param, RID_INPUT, buf, ctypes.byref(size),
                                     ctypes.sizeof(RAWINPUTHEADER))
        if got == 0xFFFFFFFF:
            return
        raw = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
        if raw.header.dwType != RIM_TYPEKEYBOARD:
            return
        vk = int(raw.keyboard.VKey)
        up = bool(raw.keyboard.Flags & RI_KEY_BREAK)
        if vk in (0, 0xFF):
            return                      # 假键，忽略
        if len(self._queue) >= self._queue.maxlen:
            self.dropped += 1
        self._queue.append((vk, not up))
        if up:
            self.keys.discard(vk)
        else:
            self.keys.add(vk)


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_LowLevelMouseProc = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

# 显式声明签名：不声明的话 64 位 LPARAM 会被当成 32 位 int，溢出报错
try:
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _LowLevelMouseProc,
                                         wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HANDLE
    user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
except Exception:
    pass


class MouseHook:
    """捕获鼠标侧键（XBUTTON1/2），游戏独占输入时也能拿到。

    ⚠ 低级钩子的回调运行在系统输入链路上：Windows 必须等它返回才继续派发鼠标事件。
    所以回调里只能做「往队列塞一个元组」这种微秒级操作 —— 一旦在里面创建线程或
    调用重逻辑，GIL 被别的线程占住时就会**卡死整个系统的鼠标**。
    真正的处理交给 HotkeyWatcher 的轮询线程消费 self._queue。
    """

    def __init__(self):
        self._proc = None
        self._hook = 0
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._handlers: dict[int, tuple] = {}   # vk -> (on_press, on_release)
        self._queue: deque = deque(maxlen=256)
        self.error: str | None = None
        self.dropped = 0

    def bind(self, vk: int, on_press=None, on_release=None) -> None:
        self._handlers[vk] = (on_press, on_release)

    def drain(self) -> list[tuple[int, bool]]:
        """由轮询线程调用，取走回调塞进来的事件。"""
        out: list[tuple[int, bool]] = []
        while True:
            try:
                out.append(self._queue.popleft())
            except IndexError:
                break
        return out

    def start(self) -> bool:
        if not self._handlers:
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._run, name="mouse-hook", daemon=True)
        self._thread.start()
        time.sleep(0.05)
        return bool(self._hook)

    def stop(self) -> None:
        if self._hook:
            try:
                user32.UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
            self._hook = 0
        if self._tid:
            try:
                user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            except Exception:
                pass
        self._thread = None

    def _run(self) -> None:
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._proc = _LowLevelMouseProc(self._callback)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        if not self._hook:
            self.error = f"SetWindowsHookEx 失败 err={ctypes.get_last_error()}"
            return
        msg = wintypes.MSG()
        # 消息循环，钩子靠它活着。必须用 > 0：GetMessage 返回 -1 是错误
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _callback(self, n_code, w_param, l_param):
        # ★ 系统输入链路上执行：这里只允许塞队列，绝不创建线程、不做字符串处理
        if n_code >= 0 and w_param in (WM_XBUTTONDOWN, WM_XBUTTONUP):
            try:
                info = ctypes.cast(l_param, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                which = (info.mouseData >> 16) & 0xFFFF   # XBUTTON1=1, XBUTTON2=2
                if which == 1 or which == 2:
                    if len(self._queue) >= self._queue.maxlen:
                        self.dropped += 1
                    self._queue.append((0x05 if which == 1 else 0x06,
                                        w_param == WM_XBUTTONDOWN))
            except Exception:
                pass
        return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)


class HotkeyWatcher:
    """键盘优先走 Raw Input（后台也能收），失败才退回 GetAsyncKeyState 轮询。
    鼠标侧键走低级钩子。"""

    def __init__(self, poll_ms: int = 25):
        self.poll_ms = poll_ms
        self._bindings: dict[str, int] = {}
        self._on_press: dict[str, callable] = {}
        self._on_release: dict[str, callable] = {}
        self._state: dict[str, bool] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.mouse_hook = MouseHook()
        self.raw = RawKeyboardInput()
        self._raw_ok = False
        self._mouse_label_map: dict[int, str] = {}
        # VK -> action 反查表
        self._vk_action: dict[int, str] = {}

    def bind(self, action: str, key: str, on_press=None, on_release=None) -> None:
        if not key:
            return
        try:
            vk = vk_of(key)
        except KeyError:
            return
        if vk in MOUSE_KEYS:
            # 鼠标键不进轮询表，交给钩子
            self.mouse_hook.bind(vk, on_press, on_release)
            self._mouse_labels[vk] = action
            return
        self._bindings[action] = vk
        self._vk_action[vk] = action
        if on_press:
            self._on_press[action] = on_press
        if on_release:
            self._on_release[action] = on_release
        self._state[action] = False

    @property
    def _mouse_labels(self) -> dict[int, str]:
        return self._mouse_label_map

    def start(self) -> None:
        # 只要有键盘绑定或鼠标钩子，就需要轮询线程（鼠标队列也靠它消费）
        if (self._bindings or self.mouse_hook._handlers) and not (
                self._thread and self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="hotkeys", daemon=True)
            self._thread.start()
        if self.mouse_hook._handlers:
            self.mouse_hook.start()
        # Raw Input：后台也能收到游戏里的按键，优先用它
        if self._bindings:
            self._raw_ok = self.raw.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)
        self._thread = None
        self.mouse_hook.stop()
        try:
            self.raw.stop()
        except Exception:
            pass

    def reset(self) -> None:
        """清空所有绑定，用于界面上改键后重建。"""
        self.stop()
        self._bindings.clear()
        self._on_press.clear()
        self._on_release.clear()
        self._state.clear()
        self._mouse_labels.clear()
        self._vk_action.clear()
        self.mouse_hook = MouseHook()
        self.raw = RawKeyboardInput()
        self._raw_ok = False

    def _loop(self) -> None:
        while not self._stop.is_set():
            raw_handled: set[str] = set()

            # ① Raw Input 事件（游戏全屏也能收到）
            if self._raw_ok:
                for vk, down in self.raw.drain():
                    action = self._vk_action.get(vk)
                    if not action:
                        continue
                    was = self._state.get(action, False)
                    if down and not was:
                        self._state[action] = True
                        raw_handled.add(action)
                        cb = self._on_press.get(action)
                        if cb:
                            threading.Thread(target=_safe, args=(cb,), daemon=True).start()
                    elif not down and was:
                        self._state[action] = False
                        raw_handled.add(action)
                        cb = self._on_release.get(action)
                        if cb:
                            threading.Thread(target=_safe, args=(cb,), daemon=True).start()

            # ② 轮询兜底（Raw Input 不可用时；或它漏掉的键）
            for action, vk in list(self._bindings.items()):
                if action in raw_handled:
                    continue
                down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                was = self._state.get(action, False)
                if down and not was:
                    self._state[action] = True
                    cb = self._on_press.get(action)
                    if cb:
                        threading.Thread(target=_safe, args=(cb,), daemon=True).start()
                elif not down and was:
                    self._state[action] = False
                    cb = self._on_release.get(action)
                    if cb:
                        threading.Thread(target=_safe, args=(cb,), daemon=True).start()

            # ③ 消费鼠标钩子塞进来的事件（绝不能在钩子回调里做这件事）
            try:
                _dispatch_mouse_events(self)
            except Exception:
                pass
            time.sleep(self.poll_ms / 1000.0)


def _safe(fn) -> None:
    try:
        fn()
    except Exception:
        pass


def _dispatch_mouse_events(watcher: "HotkeyWatcher") -> None:
    """在轮询线程里消费钩子队列，避免在系统输入链路上做事。"""
    hook = watcher.mouse_hook
    for vk, down in hook.drain():
        pair = hook._handlers.get(vk)
        if not pair:
            continue
        cb = pair[0] if down else pair[1]
        if cb:
            threading.Thread(target=_safe, args=(cb,), daemon=True).start()


# ---------------- 窗口样式 ----------------
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020


def top_level_hwnd(tk_widget) -> int:
    """tkinter 的 winfo_id 只给出子窗口，取父窗口才是真顶层。"""
    hwnd = tk_widget.winfo_id()
    parent = user32.GetParent(hwnd)
    return parent or hwnd


def set_click_through(hwnd: int, enabled: bool) -> None:
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    base = style | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    new_style = (base | WS_EX_TRANSPARENT) if enabled else (base & ~WS_EX_TRANSPARENT)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)


def keep_topmost(hwnd: int) -> None:
    HWND_TOPMOST = -1
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def enable_dpi_awareness() -> None:
    """避免在高 DPI / 全屏下截图坐标错位。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
IDLE_PRIORITY_CLASS = 0x00000040

# Windows 11 的窗口圆角
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3


def set_rounded_window(hwnd: int, mode: int = DWMWCP_ROUND) -> bool:
    """让窗口四角变圆（Windows 11）。Win10 上会失败，忽略即可。"""
    try:
        dwm = ctypes.WinDLL("dwmapi")
        val = ctypes.c_int(mode)
        r = dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                      ctypes.byref(val), ctypes.sizeof(val))
        return r == 0
    except Exception:
        return False


# ---------------- 无标题栏窗口（内容顶到最上沿） ----------------
GWLP_STYLE = -16
WS_CAPTION = 0x00C00000        # WS_BORDER | WS_DLGFRAME，就是那条标题栏
WS_THICKFRAME = 0x00040000     # 可拖动边缘调整大小 + 贴边吸附
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SW_MAXIMIZE = 3
SW_RESTORE = 9
MONITOR_DEFAULTTONEAREST = 2


class _MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int),
                ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int),
                ("cyBottomHeight", ctypes.c_int)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong),
                ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT),
                ("dwFlags", ctypes.c_ulong)]


def strip_caption(hwnd: int) -> bool:
    """去掉系统标题栏，让客户区顶到窗口最上沿。

    只动 WS_CAPTION，保留 WS_THICKFRAME（边缘拖拽 + 贴边吸附）、
    WS_SYSMENU（Alt+F4 / 系统菜单）和最小/最大化位。
    去掉后系统的最小化/还原/关闭按钮会消失，需要自己画。
    """
    try:
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int,
                                          ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos.restype = wintypes.BOOL

        style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWLP_STYLE)
        if not style:
            return False
        # 先改样式（这一步成功了才算数）
        user32.SetWindowLongW(wintypes.HWND(hwnd), GWLP_STYLE,
                              ctypes.c_long(style & ~WS_CAPTION))
        # 再让系统重算边框。这一步失败也无所谓 —— 样式已经改掉了，
        # 窗口下次重绘时会自己收敛，不能因为它抛异常就报「没成功」。
        try:
            user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(0),
                                0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                                | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        except Exception:
            pass
        return True
    except Exception:
        return False


def keep_shadow(hwnd: int) -> bool:
    """让 DWM 继续画窗口阴影和圆角。

    去掉标题栏后 DWM 可能认为这个窗口不需要装饰 —— 阴影会一起没掉，
    窗口就像一块贴纸。DwmExtendFrameIntoClientArea 给它补一个 1px 的
    扩展框，阴影、圆角、淡入淡出动画都会回来。
    """
    try:
        dwm = ctypes.WinDLL("dwmapi")
        m = _MARGINS(1, 1, 1, 1)
        r = dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
        return r == 0
    except Exception:
        return False


def work_area(hwnd: int) -> tuple[int, int, int, int]:
    """窗口所在显示器的可用区域（扣掉任务栏）：(x, y, 宽, 高)。"""
    try:
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE,
                                           ctypes.c_void_p]
        user32.GetMonitorInfoW.restype = wintypes.BOOL

        hmon = user32.MonitorFromWindow(wintypes.HWND(hwnd),
                                        MONITOR_DEFAULTTONEAREST)
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return (0, 0, 0, 0)
        r = mi.rcWork
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        return (0, 0, 0, 0)


def maximize_to_work_area(hwnd: int) -> None:
    """最大化到「可用区域」而不是整块屏幕。

    去标题栏后系统最大化会把任务栏盖住（它按 rcMonitor 算），
    所以自己按 rcWork 算一次。
    """
    x, y, w, h = work_area(hwnd)
    if w <= 0 or h <= 0:
        try:
            user32.ShowWindow(wintypes.HWND(hwnd), SW_MAXIMIZE)
        except Exception:
            pass
        return
    try:
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(0),
                            x, y, w, h,
                            SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    except Exception:
        pass


def round_window_region(hwnd: int, radius: int,
                        dpi_scale: float = 1.0) -> bool:
    """用窗口区域把窗口裁成大圆角。

    为什么不用 DWM：`DWMWA_WINDOW_CORNER_PREFERENCE` 只有「圆 / 小圆 / 不圆」
    三档，实际半径是系统定的（Win11 约 8px），改不了。想要 20px+ 的大 R 角
    只能自己裁剪窗口区域。

    代价：SetWindowRgn 会关掉 DWM 的阴影和抗锯齿，边缘会有 1px 台阶。
    在深色背景 + 大圆角下不明显，配合窗口外一圈背景图基本看不出来。
    """
    try:
        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi.CreateRoundRectRgn.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int]
        gdi.CreateRoundRectRgn.restype = wintypes.HANDLE
        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE,
                                        wintypes.BOOL]
        user32.SetWindowRgn.restype = ctypes.c_int
        user32.GetWindowRect.argtypes = [wintypes.HWND,
                                         ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL

        r = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
            return False
        w = r.right - r.left
        h = r.bottom - r.top
        if w <= 0 or h <= 0:
            return False

        d = max(2, int(radius * 2 * dpi_scale))   # 直径，不是半径
        rgn = gdi.CreateRoundRectRgn(0, 0, w + 1, h + 1, d, d)
        if not rgn:
            return False
        # 成功后区域归系统所有，不要再 DeleteObject
        ok = user32.SetWindowRgn(wintypes.HWND(hwnd), wintypes.HANDLE(rgn),
                                 True)
        return bool(ok)
    except Exception:
        return False


def set_dark_titlebar(hwnd: int, dark: bool = True) -> bool:
    """标题栏深色（Win11 / 新版 Win10）。"""
    try:
        dwm = ctypes.WinDLL("dwmapi")
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        val = ctypes.c_int(1 if dark else 0)
        r = dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                                      ctypes.byref(val), ctypes.sizeof(val))
        return r == 0
    except Exception:
        return False


def set_low_priority() -> bool:
    """把自身降到「低于正常」，让游戏优先拿到 CPU 时间片。

    实时翻译是个后台活，晚几十毫秒无所谓；游戏掉帧才是大问题。
    """
    try:
        k32 = ctypes.WinDLL("kernel32")
        h = k32.GetCurrentProcess()
        return bool(k32.SetPriorityClass(h, BELOW_NORMAL_PRIORITY_CLASS))
    except Exception:
        return False


# ---------------- 权限：模拟按键能不能送进游戏 ----------------
# 无畏契约跑在 High 完整性级别，普通进程是 Medium。
# Windows 的 UIPI 会把 Medium → High 的 SendInput **静默丢弃**，
# 而 SendInput 照样返回 1 —— 也就是说「按了但没生效」在程序里看不出来。
# 唯一解：把自己的完整性级别也提到 High，即「以管理员身份运行」。
SECURITY_MANDATORY_MEDIUM_RID = 0x2000
SECURITY_MANDATORY_HIGH_RID = 0x3000

GAME_EXES = ("valorant.exe", "valorant-win64-shipping.exe")


def is_elevated() -> bool:
    """当前进程是否以管理员（High 完整性）运行。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _integrity_rid(h_process) -> int | None:
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.HANDLE)]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

        class _SIA(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

        class _TML(ctypes.Structure):
            _fields_ = [("Label", _SIA)]

        TOKEN_QUERY = 0x0008
        TokenIntegrityLevel = 25
        tok = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(h_process, TOKEN_QUERY, ctypes.byref(tok)):
            return None
        try:
            size = wintypes.DWORD(0)
            advapi32.GetTokenInformation(tok, TokenIntegrityLevel, None, 0,
                                         ctypes.byref(size))
            buf = ctypes.create_string_buffer(max(size.value, 64))
            if not advapi32.GetTokenInformation(tok, TokenIntegrityLevel, buf,
                                                size, ctypes.byref(size)):
                return None
            tml = ctypes.cast(buf, ctypes.POINTER(_TML)).contents
            if not tml.Label.Sid:
                return None
            cnt = advapi32.GetSidSubAuthorityCount(tml.Label.Sid)[0]
            return int(advapi32.GetSidSubAuthority(tml.Label.Sid, cnt - 1)[0])
        finally:
            kernel32.CloseHandle(tok)
    except Exception:
        return None


def own_integrity_rid() -> int | None:
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        return _integrity_rid(k32.GetCurrentProcess())
    except Exception:
        return None


def game_integrity_rid() -> int | None:
    """正在跑的无畏契约进程的完整性级别；没开或查不到返回 None。"""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]

        class _PE(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
        if not snap or snap == ctypes.c_void_p(-1).value:
            return None
        try:
            pe = _PE()
            pe.dwSize = ctypes.sizeof(_PE)
            ok = k32.Process32FirstW(snap, ctypes.byref(pe))
            while ok:
                if pe.szExeFile.lower() in GAME_EXES:
                    h = k32.OpenProcess(0x1000, False, pe.th32ProcessID)
                    if h:
                        try:
                            rid = _integrity_rid(h)
                            if rid is not None:
                                return rid
                        finally:
                            k32.CloseHandle(h)
                ok = k32.Process32NextW(snap, ctypes.byref(pe))
        finally:
            k32.CloseHandle(snap)
    except Exception:
        return None
    return None


def keyinject_blocked() -> bool:
    """True = 我们比游戏低一级，模拟按键会被 UIPI 丢掉。

    查不到游戏进程（没开）时返回 False，不打扰用户。
    """
    game = game_integrity_rid()
    if game is None:
        return False
    own = own_integrity_rid()
    if own is None:
        own = SECURITY_MANDATORY_HIGH_RID if is_elevated() \
            else SECURITY_MANDATORY_MEDIUM_RID
    return own < game


def relaunch_as_admin() -> bool:
    """以管理员身份重新拉起自己。返回是否成功发起。"""
    try:
        import sys
        import subprocess
        exe = sys.executable
        work_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe,
            f'-X utf8 -m valotalk', work_dir, 1)
        return int(r) > 32
    except Exception:
        return False


# ---------------- 防火墙：手机遥控必须放行 ----------------
FIREWALL_RULE = "ValoTalk Remote"


def firewall_rule_exists(name: str = FIREWALL_RULE) -> bool:
    """规则存在就返回 True。不用管理员权限，查不到也当 False。"""
    try:
        import subprocess
        out = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
            capture_output=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = (out.stdout or b"").decode("gbk", "ignore") + \
               (out.stderr or b"").decode("gbk", "ignore")
        return "No rules match" not in text and "没有与指定标准相匹配的规则" not in text \
            and name in text
    except Exception:
        return False


def add_firewall_rule(port: int, name: str = FIREWALL_RULE) -> bool:
    """弹 UAC 提权加一条入站放行规则。返回是否已发起（不代表用户点了同意）。

    profile 用 any 而不是 private：WiFi 被 Windows 判成「公用网络」时
    private 规则不生效，手机就连不上，还看不出原因。
    真正的访问控制是服务端的局域网来源校验，不是防火墙 profile。
    """
    try:
        inner = (
            f'netsh advfirewall firewall delete rule name="{name}" >nul 2>&1 & '
            f'netsh advfirewall firewall add rule name="{name}" dir=in action=allow '
            f'protocol=TCP localport={port} profile=any enable=yes'
        )
        r = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "cmd.exe", f'/c {inner}', None, 0
        )
        # ShellExecuteW 返回值 >32 表示成功把命令交出去了
        return int(r) > 32
    except Exception:
        return False
