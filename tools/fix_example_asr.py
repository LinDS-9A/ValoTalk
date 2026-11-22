"""config.example.json 补上云端 ASR 的多服务商字段。"""
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
p = ROOT / "config.example.json"
d = json.load(io.open(p, encoding="utf-8"))

asr = d.setdefault("asr", {})
for k, v in (("backend", "auto"), ("cloud_provider", ""),
             ("cloud_base_url", ""), ("cloud_model", ""),
             ("cloud_api_key", ""), ("cloud_timeout", 30),
             ("cloud_fallback", True)):
    asr[k] = v

io.open(p, "w", encoding="utf-8", newline="\n").write(
    json.dumps(d, ensure_ascii=False, indent=2) + "\n")

print("asr 云端相关字段:")
for k in ("backend", "cloud_provider", "cloud_base_url", "cloud_model",
          "cloud_api_key", "cloud_timeout", "cloud_fallback"):
    print(f"  {k} = {asr[k]!r}")