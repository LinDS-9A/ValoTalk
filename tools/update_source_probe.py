"""对比各种更新检查来源的时效性和速度。

关键问题：jsdelivr 的 @main 有 CDN 缓存延迟（发布新版后几小时才更新），
所以不能只靠它。这里实测哪个源能立刻看到 v2.1.3。
"""
from __future__ import annotations
import json
import time
import urllib.request

UA = {"User-Agent": "ValoTalk-Probe", "Accept": "*/*"}


def get(url, timeout=20, hdr=None):
    h = dict(UA)
    if hdr:
        h.update(hdr)
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), time.time() - t0, None
    except Exception as e:
        return None, time.time() - t0, f"{type(e).__name__}: {str(e)[:60]}"


TESTS = [
    ("jsdelivr data API",
     "https://data.jsdelivr.com/v1/packages/gh/LinDS-9A/ValoTalk"),
    ("@v2.1.3 (tag URL)",
     "https://cdn.jsdelivr.net/gh/LinDS-9A/ValoTalk@v2.1.3/valotalk/__init__.py"),
    ("@main (branch URL)",
     "https://cdn.jsdelivr.net/gh/LinDS-9A/ValoTalk@main/valotalk/__init__.py"),
    ("GitHub API releases/latest",
     "https://api.github.com/repos/LinDS-9A/ValoTalk/releases/latest"),
]

print("远端应该是 v2.1.3（刚发布）\n")
for name, url in TESTS:
    data, dt, err = get(url)
    if data is None:
        print(f"{name:28s} FAIL {dt:5.1f}s  {err}")
        continue
    summary = ""
    try:
        d = json.loads(data)
    except Exception:
        d = None
    if isinstance(d, dict):
        if "versions" in d:
            vs = [v["version"] for v in d["versions"]][:5]
            summary = f"versions={vs}"
        elif "tag_name" in d:
            summary = f"tag={d['tag_name']} pre={d.get('prerelease')}"
    if not summary:
        txt = data.decode("utf-8", "ignore")
        line = [l for l in txt.splitlines() if "__version__" in l]
        summary = line[0].strip() if line else txt[:60]
    fresh = "2.1.3" in summary
    print(f"{name:28s} OK   {dt:5.1f}s  {'[最新]' if fresh else '[旧]  '} {summary}")