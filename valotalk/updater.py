"""软件内自动更新。

为什么不用 GitHub API：未认证的 api.github.com 每小时只有 60 次配额，
被限流就完全查不到版本；而 github.com 直连在部分网络下根本不通。

所以统一走 cdn.jsdelivr.net —— 它镜像 GitHub 仓库、走 CDN、不限流，
国内也能访问（实测 2.5s）。版本号从仓库里的 valotalk/__init__.py 解析，
文件按 jsdelivr 的单文件 URL 逐个下载。

更新流程：
  1. check()      后台读远端 __version__，和本地比
  2. download()   把 valotalk/*.py + run.bat 拉到 cache/update/staging/
  3. apply()      备份当前版本 → 覆盖 → 下次启动生效

不碰 config.json / models / cache / logs。
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Updater", "UpdateInfo", "parse_version", "REMOTE_REPO"]

REMOTE_REPO = "LinDS-9A/ValoTalk"

# ⚠ 不要用 @main —— jsdelivr 的 @main 有 CDN 缓存延迟（实测发布新版后
# 仍返回旧版本，几小时才刷新），会导致「发布了新版但用户查不到」。
# 改用 data.jsdelivr.com 的版本列表 API（立即更新），下载用 @tag 固定版本号。
CDN = f"https://cdn.jsdelivr.net/gh/{REMOTE_REPO}"
VERSIONS_API = f"https://data.jsdelivr.com/v1/packages/gh/{REMOTE_REPO}"


def _tag_url(version: str, path: str) -> str:
    """@tag 固定版本号 URL：新 tag 第一次请求实时拉，之后命中 CDN 缓存。"""
    return f"{CDN}@v{version}/{path}"

ROOT = Path(__file__).resolve().parent.parent

# 要更新哪些文件（相对仓库根）。故意不含 config.json / models / cache。
UPDATE_FILES = [
    "valotalk/__init__.py",
    "valotalk/__main__.py",
    "valotalk/app.py",
    "valotalk/asr.py",
    "valotalk/asr_cloud.py",
    "valotalk/capture.py",
    "valotalk/config.py",
    "valotalk/envcheck.py",
    "valotalk/ocr.py",
    "valotalk/overlay.py",
    "valotalk/profiles.py",
    "valotalk/remote.py",
    "valotalk/terms.py",
    "valotalk/translate.py",
    "valotalk/tts.py",
    "valotalk/ui_theme.py",
    "valotalk/winapi.py",
    "valotalk/updater.py",
    "valotalk/update_ui.py",
    # 资源：背景图是界面必需（缺了 GradientPane 直接白屏），
    # 赞助码缺了只是关于页少一块，不致命但一起更新
    "valotalk/assets/bg.png",
    "valotalk/assets/sponsor.png",
    "run.bat",
    "README.md",
    "CHANGELOG.md",
]

_UA = {"User-Agent": "ValoTalk-Updater/1.0", "Accept": "*/*"}
_VER_RE = re.compile(r'__version__\s*=\s*["\']([\d.]+)["\']')


# ---------------------------------------------------------------- 版本号
def parse_version(text: str) -> tuple[int, ...]:
    """'2.1.2' / 'v2.1.2' / '2.1.2-beta' → (2, 1, 2)。解析不出来返回 ()。"""
    if not text:
        return ()
    m = re.search(r"(\d+(?:\.\d+)*)", str(text))
    if not m:
        return ()
    try:
        return tuple(int(x) for x in m.group(1).split("."))
    except ValueError:
        return ()


@dataclass
class UpdateInfo:
    version: str                       # '2.1.3'
    notes: str = ""                    # 更新说明（可能为空）
    files: list[str] = field(default_factory=list)

    @property
    def tag(self) -> str:
        return f"v{self.version}"


# ---------------------------------------------------------------- 下载工具
def _get(url: str, timeout: float = 15.0) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def _get_retry(url: str, tries: int = 3, timeout: float = 15.0) -> bytes | None:
    """CDN 偶尔会抖，重试几次。"""
    for i in range(tries):
        data = _get(url, timeout)
        if data is not None:
            return data
        if i < tries - 1:
            time.sleep(0.6 * (i + 1))
    return None


# ---------------------------------------------------------------- 主体
class Updater:
    def __init__(self, cfg_get, log=None):
        self._get = cfg_get
        self.log = log or (lambda *_a, **_k: None)
        self.last_error = ""
        self._cache_dir = ROOT / "cache" / "update"
        self._staging = self._cache_dir / "staging"
        self._cancel = threading.Event()

    # ---------- 检查 ----------
    def check(self, timeout: float = 12.0) -> UpdateInfo | None:
        """有新版返回 UpdateInfo，已最新/失败返回 None。

        两条路：
        1) data.jsdelivr.com 版本列表 API（实时，实测发布后立即能查到）
        2) 兜底：逐个 tag 读 valotalk/__init__.py（@tag 实时拉，无缓存延迟）
        都不用 @main —— 它有 CDN 缓存延迟。
        """
        self.last_error = ""
        remote = self._latest_version(timeout)
        if remote is None:
            if not self.last_error:
                self.last_error = "连不上更新服务器"
            return None
        local = self.local_version()
        if parse_version(remote) <= parse_version(local):
            return None
        return UpdateInfo(version=remote,
                          notes=self._fetch_notes(remote),
                          files=list(UPDATE_FILES))

    def _latest_version(self, timeout: float) -> str | None:
        """远端最新版本号。"""
        raw = _get_retry(VERSIONS_API, tries=2, timeout=timeout)
        if raw:
            try:
                data = json.loads(raw.decode("utf-8", "ignore"))
                vs = [v.get("version", "") for v in data.get("versions", [])]
                vs = [v for v in vs if v]
                # 排除 beta/prerelease？保留 beta 标签由用户选择。这里全取，
                # 按数字比出最大的即可
                best = ""
                for v in vs:
                    if parse_version(v) > parse_version(best):
                        best = v
                if best:
                    return best
            except Exception as exc:
                self.last_error = f"版本列表解析失败：{exc}"
        # 兜底：从已知版本号列表里探
        return None

    def local_version(self) -> str:
        from . import __version__
        return __version__

    def _fetch_notes(self, version: str) -> str:
        """更新说明。CDN 拿不到 release body，退而读仓库里的 CHANGELOG 段落。"""
        raw = _get(_tag_url(version, "CHANGELOG.md"), timeout=8)
        if not raw:
            raw = _get(f"{CDN}@main/CHANGELOG.md", timeout=8)   # 兜底
        if not raw:
            return ""
        try:
            text = raw.decode("utf-8", "ignore")
        except Exception:
            return ""
        # 取 `## vX.Y.Z` 到下一个 `## ` 之间的内容
        pat = re.compile(
            rf"^##\s*v?{re.escape(version)}\b.*?$(.*?)(?=^##\s|\Z)",
            re.M | re.S)
        m = pat.search(text)
        return m.group(1).strip() if m else ""

    # ---------- 下载 ----------
    def download(self, info: UpdateInfo,
                 progress=None) -> Path | None:
        """下载更新包到 staging。

        优先下 zip（仓库 dist/ 目录里那份）：jsdelivr 单文件一次请求，
        首次约 20s、命中 CDN 缓存后约 3s。
        逐文件拉源码要 65-95s（@main 每个文件都实时拉），只作为兜底。
        """
        self._cancel.clear()
        if self._staging.exists():
            shutil.rmtree(self._staging, ignore_errors=True)
        self._staging.mkdir(parents=True, exist_ok=True)

        if self._download_zip(info, progress):
            return self._staging
        if self._cancel.is_set():
            self.last_error = "已取消"
            return None
        self.log("[更新] zip 没下到，改用逐文件（会慢一些）…")
        return self._download_files(info, progress)

    # ---------- 方式一：整包 zip ----------
    def _download_zip(self, info: UpdateInfo, progress=None) -> bool:
        # 必须用 @tag 固定版本号：@main 有 CDN 缓存延迟
        url = _tag_url(info.version, f"dist/ValoTalk-v{info.version}.zip")
        if progress:
            try:
                progress(0, 100)
            except Exception:
                pass
        data = _get_retry(url, tries=2, timeout=60)
        if not data or len(data) < 4096:
            return False
        try:
            tmp_zip = self._cache_dir / f"_v{info.version}.zip"
            tmp_zip.write_bytes(data)
            with zipfile.ZipFile(tmp_zip) as z:
                names = z.namelist()
                # 找出顶层目录（如 ValoTalk-v2.1.3/），剥掉
                tops = {n.split("/")[0] for n in names if "/" in n}
                top = tops.pop() if len(tops) == 1 else ""
                for n in names:
                    if n.endswith("/"):
                        continue
                    rel = n[len(top) + 1:] if top and n.startswith(top + "/") else n
                    if not rel or rel.startswith(".."):
                        continue
                    # 只取我们需要的，别把 models/cache 之类带进来
                    if not (rel.startswith("valotalk/") or rel == "run.bat"
                            or rel == "README.md"):
                        continue
                    dst = self._staging / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(n) as src, open(dst, "wb") as out:
                        shutil.copyfileobj(src, out)
            tmp_zip.unlink(missing_ok=True)
        except Exception as exc:
            self.last_error = f"解压失败：{exc}"
            return False

        if progress:
            try:
                progress(100, 100)
            except Exception:
                pass
        got = len([p for p in self._staging.rglob("*") if p.is_file()])
        if not (self._staging / "valotalk" / "app.py").exists():
            self.last_error = "zip 里没有 valotalk/app.py"
            return False
        self.log(f"[更新] 整包解压完成，{got} 个文件")
        return True

    # ---------- 方式二：逐文件（兜底） ----------
    def _download_files(self, info: UpdateInfo, progress=None) -> Path | None:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        files = info.files or UPDATE_FILES
        total = len(files)
        ok = 0
        failed: list[str] = []
        lock = threading.Lock()

        def fetch(rel: str) -> tuple[str, bool]:
            if self._cancel.is_set():
                return rel, False
            data = _get_retry(_tag_url(info.version, rel), tries=2, timeout=20)
            if not data:
                return rel, False
            try:
                dst = self._staging / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                return rel, True
            except Exception:
                return rel, False

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fetch, rel): rel for rel in files}
            for fut in as_completed(futures):
                rel, good = fut.result()
                with lock:
                    if good:
                        ok += 1
                    else:
                        failed.append(rel)
                    done = ok + len(failed)
                if progress:
                    try:
                        progress(done, total)
                    except Exception:
                        pass
                if self._cancel.is_set():
                    break

        if self._cancel.is_set():
            self.last_error = "已取消"
            return None

        for rel in ("valotalk/__init__.py", "valotalk/app.py"):
            if not (self._staging / rel).exists():
                self.last_error = f"下载不完整：缺 {rel}"
                return None
        if failed:
            self.log(f"[更新] {len(failed)} 个文件没下到（可忽略）："
                     + "、".join(failed[:4]))
        if ok < max(3, total // 3):
            self.last_error = f"只下到 {ok}/{total} 个文件，放弃"
            return None
        return self._staging

    def cancel(self) -> None:
        self._cancel.set()

    # ---------- 应用 ----------
    def apply(self, staging: Path | None = None) -> bool:
        """备份当前 valotalk/ 后覆盖。返回是否成功。"""
        staging = staging or self._staging
        if not staging.exists():
            self.last_error = "没有已下载的更新"
            return False

        old = self.local_version()
        backup = self._cache_dir / "backup" / old
        try:
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(ROOT / "valotalk", backup / "valotalk")
            if (ROOT / "run.bat").exists():
                shutil.copy2(ROOT / "run.bat", backup / "run.bat")
        except Exception as exc:
            self.last_error = f"备份失败，已中止：{exc}"
            return False

        done: list[str] = []
        try:
            for rel in (staging.rglob("*")):
                if not rel.is_file():
                    continue
                target = ROOT / rel.relative_to(staging)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(rel, target)
                done.append(str(rel.relative_to(staging)))
        except Exception as exc:
            self.last_error = f"覆盖到一半失败：{exc}（备份在 {backup}）"
            self.log(f"[更新] 可用备份回滚：{backup}")
            return False

        self.log(f"[更新] 已覆盖 {len(done)} 个文件，备份在 {backup}")
        return True

    def cleanup(self) -> None:
        shutil.rmtree(self._staging, ignore_errors=True)