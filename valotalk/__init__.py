"""ValoTalk —— 无畏契约国际服实时翻译（语音 + 聊天）。

⚠️ 这个文件承担一个额外职责：**老版本更新上来的自愈**。

背景：v2.3.0 及更早版本的 `updater.UPDATE_FILES` 里没有
`profiles.py` / `envcheck.py` / `assets/`（那时它们还不存在）。
老用户点「检查更新」时用的是**他们本地旧版的清单**，所以只会下到
清单里的那 20 个文件，新模块和新资源一个都不会来 —— 而新版 app.py
一 `import profiles` 就崩，用户看到的就是「更新完打不开了」。

修法：在子模块被 import 之前（也就是这里）先检查缺失文件，缺了就
从 CDN 补下载；下载失败则写一份降级实现，至少保证能启动、界面能开。
"""

from __future__ import annotations

import os as _os

__version__ = "3.0.1-beta"

# 这一版是不是测试版（GitHub 上标为 Pre-release）。
# 为什么要单独一个开关：版本号 3.0.1 里没有 beta 字样，界面靠版本号
# 字符串判断「是不是测试版」会失灵。用这个标记统一控制徽章和提示。
PRERELEASE = True

# 老版本更新上来可能缺的文件（旧清单里没有）。
# value = (仓库内相对路径, 降级实现)
_CDN_BASE = "https://cdn.jsdelivr.net/gh/LinDS-9A/ValoTalk"
_MODULE_DIR = _os.path.dirname(_os.path.abspath(__file__))

_FALLBACK_ENVCHECK = '''"""降级版环境检查（自愈时未能下载到正版）。

只保证 app.py 能 import、能启动；不检查依赖版本。
"""
from __future__ import annotations
import sys

MIN_MINOR = 10
MAX_MINOR = 14
DOWNLOAD_URL = "https://www.python.org/downloads/"


def python_state() -> str:
    v = sys.version_info
    return "ok" if MIN_MINOR <= v.minor <= MAX_MINOR else "bad"


def python_problem() -> str:
    return "" if python_state() == "ok" else f"Python 3.{sys.version_info.minor} 不在支持范围"


def missing_deps():
    return []


def describe_python() -> str:
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


def show_blocking_dialog(*a, **kw) -> None:
    return None
'''

_FALLBACK_PROFILES = '''"""降级版模型配置（自愈时未能下载到正版）。

只保证能 import、界面能起来；模型列表为空，用户可去配置页重新添加。
"""
from __future__ import annotations


class Profiles:
    def __init__(self, cfg_get=None, cfg_set=None):
        self._get = cfg_get or (lambda k, d=None: d)
        self._set = cfg_set or (lambda k, v, save=True: None)

    def all(self):
        return []

    def names(self):
        return []

    def get(self, name):
        return None

    def asr_pick(self):
        return {}

    def llm_pick(self):
        return {}

    def add(self, *a, **kw):
        return False

    def update(self, *a, **kw):
        return False

    def remove(self, *a, **kw):
        return False

    def rename(self, old, new=None, save=True):
        return new or old

    def apply_asr(self, save=True):
        return False

    def apply_llm(self, save=True):
        return False

    def apply_all(self, save=True):
        return None

    def migrate(self):
        return False

    def dedupe(self):
        return 0
'''

_NEEDED = {
    "envcheck.py": ("valotalk/envcheck.py", _FALLBACK_ENVCHECK),
    "profiles.py": ("valotalk/profiles.py", _FALLBACK_PROFILES),
}


def _fetch(url: str, timeout: float = 10.0) -> bytes | None:
    try:
        import urllib.request
        req = urllib.request.Request(
            url, headers={"User-Agent": "ValoTalk-Bootstrap/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def _is_degraded(path: str) -> bool:
    """这个文件是不是上次自愈失败时写的降级版。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return "降级版" in f.read(400)
    except Exception:
        return False


def _urls_for(rel: str) -> list[str]:
    """按「当前版本 tag → main」的顺序给出候选 URL。

    为什么要带 @tag：jsdelivr 的 @main 有 CDN 缓存延迟（实测发布后
    几分钟内还拿到旧内容），而 @tag 是首次请求就实时回源。版本号里
    带 beta 也能直接用（GitHub 的 tag 名就是 v3.0.0-beta）。
    """
    return [
        f"{_CDN_BASE}@v{__version__}/{rel}",
        f"{_CDN_BASE}@main/{rel}",
    ]


def _self_heal() -> None:
    """补齐老版本更新后缺失的模块。宁慢勿崩 —— 这里不做任何可能抛的操作。

    降级版会被反复重试：上次网络不通写了降级实现，这次启动接着试，
    直到拿到正式版为止（否则用户会一直用着功能残缺的版本）。
    """
    for name, (rel, fallback) in _NEEDED.items():
        dst = _os.path.join(_MODULE_DIR, name)
        if _os.path.exists(dst) and not _is_degraded(dst):
            continue                       # 已经是正式版，不动
        data = None
        for url in _urls_for(rel):
            data = _fetch(url)
            # 下载回来的东西至少得像样（300 字节以上、含 class 或 def）
            if data and len(data) > 300 and (b"def " in data or b"class " in data):
                break
            data = None
        if data:
            try:
                with open(dst, "wb") as f:
                    f.write(data)
                continue
            except Exception:
                pass
        # 下载不下来就写降级版，保证 import 不炸
        if _os.path.exists(dst):
            continue                       # 已有降级版，别反复覆盖
        try:
            with open(dst, "w", encoding="utf-8") as f:
                f.write(fallback)
        except Exception:
            pass


_self_heal()
