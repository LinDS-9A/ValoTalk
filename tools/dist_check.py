"""检查 dist/ 目录是否还在（v2.1.3 的 tree 覆盖可能把它弄丢了）。"""
import json, os, urllib.request

TOKEN = os.environ.get("GH_TOKEN", "")

def get(url):
    h = {"User-Agent": "vt", "Accept": "application/vnd.github+json"}
    if TOKEN:
        h["Authorization"] = f"token {TOKEN}"
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)

tree = get("https://api.github.com/repos/LinDS-9A/ValoTalk/git/trees/main?recursive=1")

dist_files = [t["path"] for t in tree["tree"] if t["path"].startswith("dist/")]
print(f"dist/ 下的文件: {dist_files or '（空）'}")
print(f"总文件数: {len([t for t in tree['tree'] if t['type']=='blob'])}")

# 也看看 tag v2.1.2 的 tree
tag = get("https://api.github.com/repos/LinDS-9A/ValoTalk/git/refs/tags/v2.1.2")
sha = tag["object"]["sha"]
commit = get(f"https://api.github.com/repos/LinDS-9A/ValoTalk/git/commits/{sha}")
tree_sha = commit["tree"]["sha"]
t2 = get(f"https://api.github.com/repos/LinDS-9A/ValoTalk/git/trees/{tree_sha}?recursive=1")
dist2 = [t["path"] for t in t2["tree"] if t["path"].startswith("dist/")]
print(f"\nv2.1.2 tag 的 dist/: {dist2 or '（空）'}")
