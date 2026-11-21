"""同步 config.example.json 的字段与新默认值。"""
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
p = ROOT / "config.example.json"
d = json.load(io.open(p, encoding="utf-8"))

print("改之前:")
print("  remote =", d.get("remote"))
print("  ocr    =", d.get("ocr"))

d["remote"] = {
    "enabled": False,
    "port": 8765,
    "token": "",
    "auto_token": True,
}
ocr = d.setdefault("ocr", {})
ocr["interval_ms"] = 2500
ocr["idle_backoff_max"] = 4.0
ocr["onnx_threads"] = 2

io.open(p, "w", encoding="utf-8", newline="\n").write(
    json.dumps(d, ensure_ascii=False, indent=2) + "\n")

print("\n改之后:")
print("  remote =", d["remote"])
print("  ocr    =", d["ocr"])