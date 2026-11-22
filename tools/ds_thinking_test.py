"""验证关闭思考模式对 DeepSeek 翻译的影响：延迟 + 是否返回空。"""
import os
import sys
import time

import requests

KEY = os.environ.get("DS_KEY", "")
S = requests.Session()
S.headers.update({"Authorization": f"Bearer {KEY}",
                  "Content-Type": "application/json"})

SYS = (
    "你是 VALORANT 游戏内的实时翻译。把日语队友语音翻成简体中文。\n"
    "术语固定译法：サイト=包点、スパイク=炸弹/包、ウルト=大招、"
    "エコー/エコ=经济局、フランク=绕后、ローテート=转点、"
    "オペレーター/オペ=大狙、カバー=掩护、ラッシュ=一波冲。\n"
    "只输出译文，不要解释，不要加引号。口语化、简短。"
)

TEXTS = [
    "エコだから慎重に。",
    "相手エコだから慎重に。",
    "Aサイトに敵、フランクに注意。",
    "オペレーター持ってる、出ないで。",
]

VARIANTS = [
    ("默认（思考开着）", {}),
    ("thinking disabled", {"thinking": {"type": "disabled"}}),
    ("reasoning_effort none", {"reasoning_effort": "none"}),
]

for name, extra in VARIANTS:
    print(f"\n=== {name} ===")
    times = []
    empties = 0
    for text in TEXTS:
        body = {"model": "deepseek-flash",
                "messages": [{"role": "system", "content": SYS},
                             {"role": "user", "content": text}],
                "temperature": 0, "max_tokens": 120}
        body.update(extra)
        t0 = time.time()
        r = S.post("https://api.deepseek.com/v1/chat/completions",
                   json=body, timeout=60)
        dt = time.time() - t0
        times.append(dt)
        if r.status_code != 200:
            print(f"  {text[:22]:<24s} HTTP {r.status_code} {r.text[:60]}")
            continue
        d = r.json()
        ch = d.get("choices", [{}])[0]
        msg = ch.get("message", {})
        c = (msg.get("content") or "").strip()
        rc = len(msg.get("reasoning_content") or "")
        if not c:
            empties += 1
        print(f"  {text[:22]:<24s} {dt:5.2f}s  finish={ch.get('finish_reason'):<8s} "
              f"thought={rc:3d}ch  {c[:20]!r}")
    print(f"  平均 {sum(times)/len(times):.2f}s，空结果 {empties}/{len(TEXTS)}")