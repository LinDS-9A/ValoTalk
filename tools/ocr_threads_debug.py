"""调试：patch 到底有没有作用到真实 session 上。"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import onnxruntime as ort

from valotalk import ocr as ocr_mod

print("=== 初始状态 ===")
print(f"  InferenceSession.__init__ = {ort.InferenceSession.__init__}")
print(f"  _OCR_THREADS = {ocr_mod._OCR_THREADS}")

orig = ort.InferenceSession.__init__
calls = []


def tracer(self, path_or_bytes, sess_options=None, providers=None,
           provider_options=None, **kwargs):
    calls.append(sess_options)
    print(f"  [建 session] sess_options={sess_options}, "
          f"传入的 intra={getattr(sess_options, 'intra_op_num_threads', 'N/A')}")
    return orig(self, path_or_bytes, sess_options, providers,
                provider_options, **kwargs)


ort.InferenceSession.__init__ = tracer

print("\n=== 用 2 线程加载引擎 ===")
ocr_mod.reset_engine()
ocr_mod._limit_onnx_threads(2, force=True)
print(f"  patch 后 _OCR_THREADS = {ocr_mod._OCR_THREADS}")
print(f"  InferenceSession.__init__ 是 patched = "
      f"{getattr(ort.InferenceSession.__init__, '_valotalk_patched', False)}")

eng = ocr_mod._load_rapidocr(2)
print(f"  引擎 = {type(eng).__name__ if eng else None}")
print(f"  建 session 次数 = {len(calls)}")
for so in calls:
    print(f"    实际 intra_op_num_threads = "
          f"{getattr(so, 'intra_op_num_threads', 'N/A')}")

# 直接查 session 内部
if eng is not None:
    print("\n=== 引擎内部结构 ===")
    for attr in dir(eng):
        if 'session' in attr.lower() or 'model' in attr.lower():
            try:
                v = getattr(eng, attr)
                print(f"  {attr} = {type(v).__name__}")
            except Exception:
                pass