"""把本地 config.json 的默认值对齐新版本：手机遥控关、OCR 2 线程。"""
import io
import json
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "config.json"
d = json.load(io.open(p, encoding="utf-8"))

print("改之前:")
print("  remote.enabled  =", d.get("remote", {}).get("enabled"))
print("  ocr.onnx_threads =", d.get("ocr", {}).get("onnx_threads"))

d.setdefault("remote", {})["enabled"] = False
d.setdefault("ocr", {})["onnx_threads"] = 2

io.open(p, "w", encoding="utf-8", newline="\n").write(
    json.dumps(d, ensure_ascii=False, indent=2) + "\n")

print("改之后:")
print("  remote.enabled  =", d["remote"]["enabled"])
print("  ocr.onnx_threads =", d["ocr"]["onnx_threads"])