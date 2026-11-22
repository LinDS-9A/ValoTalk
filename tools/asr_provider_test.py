"""验证多服务商支持：provider 判断 + 三种协议 + 端点可达性。

DeepSeek 没有真 key，用假 key 验证请求格式被接受（401 = 通到认证层，
说明 URL 和方法都对；404/405 才说明协议错了）。
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.asr_cloud import (CloudASR, PROVIDERS, guess_provider,
                                pcm_to_wav)
from valotalk.config import CONFIG

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


print("=== 1) provider 自动判断 ===")
cases = [
    ("https://api.deepseek.com/v1", "deepseek"),
    ("https://dashscope.aliyuncs.com", "dashscope"),
    ("https://maas.qianwenaiapi.com/compatible-mode/v1", "dashscope"),
    ("https://api.siliconflow.cn/v1", "openai"),
    ("http://127.0.0.1:8080/v1", "openai"),
    ("", "dashscope"),
]
for url, expect in cases:
    got = guess_provider(url)
    print(f"  {url or '(空)':52s} → {got}")
    check(f"{url or '(空)'} → {expect}", got == expect, got)

print("\n=== 2) 三家默认端点 ===")
for k, v in PROVIDERS.items():
    print(f"  {k:10s} {v['base']:44s} {v['path']:50s} kind={v['kind']}")
    check(f"{k} 有 base/path/kind",
          all(x in v for x in ("base", "path", "kind")))

print("\n=== 3) 假 key 验证 DeepSeek 请求格式 ===")
# 只要不是 404/405，就说明 URL 和方法能被服务端接受
wav = pcm_to_wav(np.zeros(16000, dtype=np.float32))
r = requests.post(
    "https://api.deepseek.com/v1/tools/asr",
    headers={"Authorization": "Bearer sk-FAKE0000000000000000000000000000000000"},
    files={"file": ("audio.wav", wav, "audio/wav")},
    timeout=25)
print(f"  POST /v1/tools/asr → HTTP {r.status_code}")
print(f"  {r.text[:150]}")
check("DeepSeek 端点存在（不是 404/405）", r.status_code not in (404, 405),
      str(r.status_code))

print("\n=== 4) CloudASR 按配置切协议 ===")
_orig = {
    "asr.cloud_provider": CONFIG.get("asr.cloud_provider"),
    "asr.cloud_base_url": CONFIG.get("asr.cloud_base_url"),
    "asr.cloud_model": CONFIG.get("asr.cloud_model"),
    "asr.cloud_api_key": CONFIG.get("asr.cloud_api_key"),
}


def setp(**kw):
    for k, v in kw.items():
        CONFIG.set(k, v, save=False)


setp(**{"asr.cloud_provider": "deepseek", "asr.cloud_base_url": "",
        "asr.cloud_model": ""})
a = CloudASR(CONFIG.get, log=print)
print(f"  provider={a.provider}  base={a.base_url}  model={a.model!r}")
check("识别为 deepseek", a.provider == "deepseek")
check("用 DeepSeek 默认地址", a.base_url == "https://api.deepseek.com/v1",
      a.base_url)
check("DeepSeek 不需要模型名", a.model == "", a.model)
print(f"  描述: {a.describe()}")

setp(**{"asr.cloud_provider": "dashscope", "asr.cloud_model": ""})
b = CloudASR(CONFIG.get, log=print)
print(f"  provider={b.provider}  base={b.base_url}  model={b.model!r}")
check("识别为 dashscope", b.provider == "dashscope")
check("默认模型 qwen3-asr-flash", b.model == "qwen3-asr-flash", b.model)

setp(**{"asr.cloud_provider": "", "asr.cloud_base_url":
        "https://api.siliconflow.cn/v1", "asr.cloud_model": ""})
c = CloudASR(CONFIG.get, log=print)
print(f"  provider={c.provider}  base={c.base_url}  model={c.model!r}")
check("按 base_url 猜成 openai", c.provider == "openai", c.provider)
check("硅基流动地址被采用", "siliconflow" in c.base_url, c.base_url)

# 还原
for k, v in _orig.items():
    CONFIG.set(k, v if v is not None else "", save=False)

print("\n=== 5) 独立 key 优先于翻译 key ===")
setp(**{"asr.cloud_api_key": "sk-asr-own-key"})
d = CloudASR(CONFIG.get)
check("用 asr.cloud_api_key", d.api_key == "sk-asr-own-key", d.api_key[:12])
setp(**{"asr.cloud_api_key": ""})
e = CloudASR(CONFIG.get)
check("留空时复用 translate.llm.api_key", e.api_key == CONFIG.get("translate.llm.api_key"))

print("\n=== 6) 真实 DashScope 识别仍然可用 ===")
setp(**{"asr.cloud_provider": "dashscope", "asr.cloud_base_url": "",
        "asr.cloud_model": "", "asr.cloud_api_key": ""})
f = CloudASR(CONFIG.get, log=print)
print(f"  {f.describe()}")
ok = f.warmup()
check("DashScope 预热成功", ok, f.last_error)
f.close()

for k, v in _orig.items():
    CONFIG.set(k, v if v is not None else "", save=False)

print("\n" + "=" * 52)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 52)
sys.exit(0 if failed == 0 else 1)