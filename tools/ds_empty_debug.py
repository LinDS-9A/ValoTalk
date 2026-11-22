"""查「相手エコだから慎重に」翻译返回空的原因。"""
import json
import os
import sys

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

TESTS = [
    "相手エコだから慎重に。",
    "相手エコーだから、慎重に。",
    "エコだから慎重に。",
    "相手は経済局だから慎重に。",
]

for text in TESTS:
    print(f"--- {text} ---")
    body = {"model": "deepseek-flash",
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": text}],
            "temperature": 0, "max_tokens": 120}
    r = S.post("https://api.deepseek.com/v1/chat/completions",
               json=body, timeout=60)
    print(f"  HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  {r.text[:300]}")
        continue
    d = r.json()
    ch = d.get("choices", [{}])[0]
    msg = ch.get("message", {})
    print(f"  content = {msg.get('content')!r}")
    print(f"  finish_reason = {ch.get('finish_reason')}")
    if msg.get("reasoning_content"):
        print(f"  有 reasoning_content（{len(msg['reasoning_content'])} 字符）")
    print(f"  usage = {json.dumps(d.get('usage'), ensure_ascii=False)[:120]}")
    print()