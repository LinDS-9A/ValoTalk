"""从切换前的备份恢复 config.json（回到阿里云配置）。

只恢复翻译/识别相关字段，其它（字号、线程数等）保持当前值。
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config.json"
BAK = CFG.with_suffix(".json.bak-switch")

if not BAK.exists():
    print(f"找不到备份 {BAK.name}")
    sys.exit(1)

cur = json.load(io.open(CFG, encoding="utf-8"))
old = json.load(io.open(BAK, encoding="utf-8"))

print("恢复前:")
print("  translate.llm.base_url:", cur.get("translate", {}).get("llm", {}).get("base_url"))
print("  translate.llm.model   :", cur.get("translate", {}).get("llm", {}).get("model"))
print("  asr.cloud_provider    :", repr(cur.get("asr", {}).get("cloud_provider")))

# 只回滚这几项，其余保持现状
cur.setdefault("translate", {}).setdefault("llm", {}).update({
    "base_url": old["translate"]["llm"].get("base_url", ""),
    "model": old["translate"]["llm"].get("model", ""),
    "api_key": old["translate"]["llm"].get("api_key", ""),
})
cur.setdefault("asr", {}).update({
    "cloud_provider": old.get("asr", {}).get("cloud_provider", ""),
    "cloud_base_url": old.get("asr", {}).get("cloud_base_url", ""),
    "cloud_model": old.get("asr", {}).get("cloud_model", ""),
    "cloud_api_key": old.get("asr", {}).get("cloud_api_key", ""),
})

io.open(CFG, "w", encoding="utf-8", newline="\n").write(
    json.dumps(cur, ensure_ascii=False, indent=2) + "\n")

d = json.load(io.open(CFG, encoding="utf-8"))
llm = d["translate"]["llm"]
print("\n恢复后:")
print("  translate.llm.base_url:", llm.get("base_url"))
print("  translate.llm.model   :", llm.get("model"))
k = llm.get("api_key", "")
print("  translate.llm.api_key :", f"{k[:12]}…（{len(k)} 字符）" if k else "(空)")
print("  asr.cloud_provider    :", repr(d["asr"].get("cloud_provider")))
print("  asr.cloud_model       :", repr(d["asr"].get("cloud_model")))