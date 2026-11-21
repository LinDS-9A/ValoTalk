"""测逐文件下载能优化到多快 —— 决定是否必须依赖 dist/ 的 zip。

对比：
  A. urllib 每次新建连接（现在的实现）
  B. requests.Session 连接复用 + 并发
  C. requests.Session + HTTP/1.1 keep-alive + 并发 6
"""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor

REPO = "LinDS-9A/ValoTalk"
TAG = "v2.1.3"   # 远端已删，但 jsdelivr 还缓存着
FILES = [
    "valotalk/__init__.py", "valotalk/__main__.py", "valotalk/app.py",
    "valotalk/asr.py", "valotalk/capture.py", "valotalk/config.py",
    "valotalk/ocr.py", "valotalk/overlay.py", "valotalk/remote.py",
    "valotalk/terms.py", "valotalk/translate.py", "valotalk/tts.py",
    "valotalk/ui_theme.py", "valotalk/winapi.py", "valotalk/updater.py",
    "valotalk/update_ui.py", "run.bat", "CHANGELOG.md",
]
BASE = f"https://cdn.jsdelivr.net/gh/{REPO}@{TAG}"


def bench_urllib():
    import urllib.request
    total = 0
    t0 = time.time()
    for f in FILES:
        try:
            req = urllib.request.Request(f"{BASE}/{f}",
                                         headers={"User-Agent": "vt"})
            with urllib.request.urlopen(req, timeout=20) as r:
                total += len(r.read())
        except Exception:
            pass
    return time.time() - t0, total


def bench_session_concurrent(workers: int):
    import requests
    from requests.adapters import HTTPAdapter
    s = requests.Session()
    ad = HTTPAdapter(pool_connections=workers, pool_maxsize=workers)
    s.mount("https://", ad)
    s.headers["User-Agent"] = "vt"
    total = 0
    lock = __import__("threading").Lock()

    def one(f):
        nonlocal total
        try:
            r = s.get(f"{BASE}/{f}", timeout=20)
            if r.status_code == 200:
                with lock:
                    total += len(r.content)
        except Exception:
            pass

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, FILES))
    return time.time() - t0, total


print(f"测试 {len(FILES)} 个文件，tag={TAG}\n")

t, n = bench_urllib()
print(f"A. urllib 串行          {t:6.2f}s  {n} B")

for w in (4, 6, 8):
    t, n = bench_session_concurrent(w)
    print(f"B. Session 并发 {w}       {t:6.2f}s  {n} B")