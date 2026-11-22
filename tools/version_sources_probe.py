"""对比三个版本源，看谁能立刻反映 v2.2.0。"""
import json
import time
import urllib.request

REPO = "LinDS-9A/ValoTalk"
UA = {"User-Agent": "vt", "Accept": "application/vnd.github+json"}


def probe(name, url, parse):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            data = r.read()
        dt = time.time() - t0
        val = parse(data)
        print(f"  {name:26s} {dt:5.2f}s  → {val}")
        return val
    except urllib.error.HTTPError as e:
        print(f"  {name:26s} {time.time()-t0:5.2f}s  HTTP {e.code}")
        return None
    except Exception as e:
        print(f"  {name:26s} {time.time()-t0:5.2f}s  {type(e).__name__}")
        return None


print("三个版本源对比（期望都看到 2.2.0）：\n")

probe("GitHub API releases/latest",
      f"https://api.github.com/repos/{REPO}/releases/latest",
      lambda b: json.loads(b)["tag_name"])

probe("data.jsdelivr 版本列表",
      f"https://data.jsdelivr.com/v1/packages/gh/{REPO}",
      lambda b: json.loads(b)["versions"][0]["version"])

probe("@main 的 __init__.py",
      f"https://cdn.jsdelivr.net/gh/{REPO}@main/valotalk/__init__.py",
      lambda b: [l for l in b.decode("utf-8", "ignore").splitlines()
                 if "__version__" in l][0].split('"')[1])

probe("@v2.2.0 的 __init__.py",
      f"https://cdn.jsdelivr.net/gh/{REPO}@v2.2.0/valotalk/__init__.py",
      lambda b: [l for l in b.decode("utf-8", "ignore").splitlines()
                 if "__version__" in l][0].split('"')[1])