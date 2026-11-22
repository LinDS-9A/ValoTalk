"""恢复 config.json 里被测试污染掉的 LLM api_key。

**key 不硬编码**：从环境变量 RESTORE_KEY 读，或手动编辑 config.json。

原理说明（记下来避免再犯）：
  Config.set(dotted, value, save=False) 只改内存；
  但之后任何 save=True 的操作（_set、shutdown 存坐标等）都会把整个
  _data 写盘 —— 于是内存里的空值被固化。测试必须先备份、后恢复
  （见 tools/_cfg_guard.py）。
"""
import io
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config.json"

KEY = os.environ.get("RESTORE_KEY", "").strip()

d = json.load(io.open(CFG, encoding="utf-8"))
llm = d.setdefault("translate", {}).setdefault("llm", {})
cur = llm.get("api_key", "")
print("当前 api_key 长度:", len(cur))

if cur:
    print("已经是非空，不需要恢复")
    raise SystemExit(0)

if not KEY:
    print("缺少 RESTORE_KEY 环境变量")
    print("用法：")
    print('  $env:RESTORE_KEY = "sk-..."')
    print("  python tools\\restore_config_key.py")
    raise SystemExit(1)

bak = CFG.with_suffix(".json.before-restore")
shutil.copy2(CFG, bak)
print(f"已备份到 {bak.name}")

llm["api_key"] = KEY
io.open(CFG, "w", encoding="utf-8", newline="\n").write(
    json.dumps(d, ensure_ascii=False, indent=2) + "\n")

d2 = json.load(io.open(CFG, encoding="utf-8"))
print("已恢复，新长度:", len(d2["translate"]["llm"].get("api_key", "")))
print("base_url:", d2["translate"]["llm"].get("base_url"))
print("model:", d2["translate"]["llm"].get("model"))