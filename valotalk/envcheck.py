"""运行环境检查：Python 版本 + 关键依赖。

为什么要有这个：装依赖失败时报的是
`No matching distribution found for onnxruntime` 这种话，
用户根本看不出问题出在「Python 版本太新」。与其让人对着一堆 pip 输出猜，
不如启动时直接告诉他现在是什么版本、该装什么。

两个用途：
  · 启动前拦一次（`app.main()` 里），版本不对就弹窗说清楚，别让半截异常糊一脸
  · 「关于」页显示当前 Python 版本和状态

依赖真的起不来时还能用环境变量强开：
  set VALOTALK_ALLOW_UNSUPPORTED_PY=1
"""
from __future__ import annotations

import os
import sys

__all__ = [
    "MIN_MINOR", "MAX_MINOR", "python_state", "python_problem",
    "missing_deps", "describe_python", "show_blocking_dialog", "DOWNLOAD_URL",
]

# 3.10 ~ 3.14。
# 上界不是拍脑袋：onnxruntime 目前只发到 cp314 轮子，3.15 上 pip 装到最后一步
# 必失败；ctranslate2 反而有 cp315，所以「看起来能装」，坑更深。
MIN_MINOR = 10
MAX_MINOR = 14

DOWNLOAD_URL = "https://www.python.org/downloads/release/python-3139/"

# 缺了这些就没法跑；名字是 import 名，不是 pip 名
REQUIRED_IMPORTS = (
    "numpy",
    ("requests", "requests"),
    ("soundcard", "soundcard"),
    ("faster_whisper", "faster-whisper"),
    ("edge_tts", "edge-tts"),
    ("mss", "mss"),
    ("cv2", "opencv-python-headless"),
    ("onnxruntime", "onnxruntime"),
)


def python_state(vi: tuple[int, int] | None = None) -> str:
    """'ok' / 'too_old' / 'too_new' —— 纯函数，方便测。"""
    if vi is None:
        vi = sys.version_info[:2]
    major, minor = int(vi[0]), int(vi[1])
    if major != 3:
        return "too_old" if major < 3 else "too_new"
    if minor < MIN_MINOR:
        return "too_old"
    if minor > MAX_MINOR:
        return "too_new"
    return "ok"


def describe_python() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def python_problem(vi: tuple[int, int] | None = None) -> str:
    """没问题返回空串；有问题返回一段能直接给用户看的话。"""
    if vi is None:
        vi = sys.version_info[:2]
    state = python_state(vi)
    if state == "ok":
        return ""
    cur = f"{int(vi[0])}.{int(vi[1])}"
    if state == "too_old":
        return (
            f"当前 Python {cur}，太旧了（需要 3.{MIN_MINOR} ~ 3.{MAX_MINOR}）。\n\n"
            f"装个 Python 3.13，然后删掉项目里的 .venv 目录，\n"
            f"双击 setup.ps1 重装一遍即可。"
        )
    return (
        f"当前 Python {cur} 太新了，装不了依赖（需要 3.{MIN_MINOR} ~ 3.{MAX_MINOR}）。\n\n"
        f"原因：onnxruntime 目前只提供到 cp314 的安装包，\n"
        f"3.{MAX_MINOR + 1} 上 pip 装到最后一步会报\n"
        f"「No matching distribution found for onnxruntime」。\n\n"
        f"换成 Python 3.13 即可：删掉项目里的 .venv 目录 →\n"
        f"装 Python 3.13 → 双击 setup.ps1 重装一遍。"
    )


def missing_deps() -> list[str]:
    """返回缺失依赖的 pip 包名（不是 import 名）。"""
    missing: list[str] = []
    for item in REQUIRED_IMPORTS:
        if isinstance(item, tuple):
            mod, pip_name = item
        else:
            mod, pip_name = item, item
        try:
            __import__(mod)
        except Exception:
            missing.append(pip_name)
    return missing


def show_blocking_dialog(message: str, title: str = "Python 版本不支持") -> None:
    """弹一个模态窗说清楚，顺便给个「打开下载页」的按钮。

    用 tkinter，因为这时候还没窗口；canvas 什么的都不该指望。
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        text = (
            message
            + "\n\n当前解释器：\n  " + sys.executable
            + "\n\n要我现在打开 Python 下载页吗？"
        )
        try:
            want = messagebox.askyesno(title, text, parent=root)
        except Exception:
            want = False
        if want:
            import webbrowser
            webbrowser.open(DOWNLOAD_URL)
        root.destroy()
    except Exception:
        # 没有图形环境（比如在 ssh 里跑）就退回控制台
        print("[环境检查] " + message, file=sys.stderr)
        print(f"  当前解释器：{sys.executable}", file=sys.stderr)
        print(f"  Python 下载：{DOWNLOAD_URL}", file=sys.stderr)


def check_or_exit(*, allow_env: str = "VALOTALK_ALLOW_UNSUPPORTED_PY") -> bool:
    """启动前调用：版本不对就弹窗并返回 False（调用方负责退出）。"""
    problem = python_problem()
    if not problem:
        return True
    if os.environ.get(allow_env) == "1":
        print("[环境检查] 版本不受支持，但你设了 " + allow_env + "=1，继续启动", file=sys.stderr)
        return True
    show_blocking_dialog(problem)
    return False