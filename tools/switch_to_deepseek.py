"""把配置切到 DeepSeek（识别 + 翻译一套 key）。

key 从环境变量 DS_KEY 读，不硬编码、不打日志。
"""
import io
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config.json"
KEY = os.environ.get("DS_KEY", "").strip()

if not KEY:
    print("缺少 DS_KEY 环境变量")
    raise SystemExit(1)

d = json.load(io.open(CFG, encoding="utf-8"))

bak = CFG.with_suffix(".json.bak-switch")
shutil.copy2(CFG, bak)
print(f"已备份到 {bak.name}\n")

# 翻译走 DeepSeek
tr = d.setdefault("translate", {}).setdefault("llm", {})
print("翻译:")
print("  base_url:", tr.get("base_url"), "→ https://api.deepseek.com/v1")
print("  model   :", tr.get("model"), "→ deepseek-flash")
tr["base_url"] = "https://api.deepseek.com/v1"
tr["model"] = "deepseek-flash"
tr["api_key"] = KEY
# DeepSeek 的思考模式由代码里的 thinking:disabled 关掉，这里不用配

# 识别走 DeepSeek ASR
asr = d.setdefault("asr", {})
print("\n识别:")
print("  backend       :", asr.get("backend"), "（保持不变）")
print("  cloud_provider:", repr(asr.get("cloud_provider")), "→ 'deepseek'")
asr["cloud_provider"] = "deepseek"
asr["cloud_base_url"] = ""            # 用 DeepSeek 默认
asr["cloud_model"] = ""               # DeepSeek ASR 不需要模型名
asr["cloud_api_key"] = ""             # 复用 translate.llm.api_key

io.open(CFG, "w", encoding="utf-8", newline="\n").write(
    json.dumps(d, ensure_ascii=False, indent=2) + "\n")

print("\n已写入 config.json")
print("  (DeepSeek ASR 不需要 model，cloud_model 留空)")
print("  (cloud_api_key 留空 → 复用 translate.llm.api_key)")