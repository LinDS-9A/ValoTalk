"""查看/修复 config.json 里被测试改动的字段。"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config.json"

d = json.load(io.open(CFG, encoding="utf-8"))
asr = d.get("asr", {})
print("当前:")
print("  asr.lang_teammates =", repr(asr.get("lang_teammates")))
print("  asr.backend        =", repr(asr.get("backend")))
print("  tts.voice          =", repr(d.get("tts", {}).get("voice")))
print("  overlay.font_size  =", repr(d.get("overlay", {}).get("font_size")))
print("  ocr.onnx_threads   =", repr(d.get("ocr", {}).get("onnx_threads")))

if len(sys.argv) > 1 and sys.argv[1] == "--fix":
    changed = []
    if asr.get("lang_teammates") != "en":
        asr["lang_teammates"] = "en"
        changed.append("asr.lang_teammates → en（英服）")
    voice = d.get("tts", {}).get("voice", "")
    if voice and not voice.startswith("en-"):
        d.setdefault("tts", {})["voice"] = "en-US-GuyNeural"
        changed.append("tts.voice → en-US-GuyNeural")
    ov = d.setdefault("overlay", {})
    if ov.get("font_size") != 19:
        changed.append(f"overlay.font_size {ov.get('font_size')} → 19")
        ov["font_size"] = 19
    dc = d.setdefault("asr", {})
    if dc.get("device") not in ("auto", "cuda", "cpu"):
        dc["device"] = "auto"
        changed.append("asr.device → auto")
    if changed:
        io.open(CFG, "w", encoding="utf-8", newline="\n").write(
            json.dumps(d, ensure_ascii=False, indent=2) + "\n")
        print("\n已修正:")
        for c in changed:
            print("  " + c)
    else:
        print("\n不需要修正")