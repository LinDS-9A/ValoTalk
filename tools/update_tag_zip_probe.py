"""验证 @tag URL 能否下载 dist 里的 zip（tag 是新 URL，不受 CDN 缓存影响）。"""
from __future__ import annotations
import hashlib
import time
import urllib.request

UA = {"User-Agent": "ValoTalk-Probe", "Accept": "*/*"}

for tag in ("v2.1.3", "v2.1.2"):
    url = f"https://cdn.jsdelivr.net/gh/LinDS-9A/ValoTalk@{tag}/dist/ValoTalk-{tag}.zip"
    for attempt in (1, 2):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            print(f"{tag} #{attempt}  {time.time()-t0:5.1f}s  {len(data):7d} B  "
                  f"md5={hashlib.md5(data).hexdigest()[:8]}  "
                  f"{'ZIP' if data[:2]==b'PK' else '不是zip'}")
        except Exception as e:
            print(f"{tag} #{attempt}  {time.time()-t0:5.1f}s  FAIL {type(e).__name__} "
                  f"{str(e)[:60]}")