"""测试 is_agent_voice：特工台词应被过滤，队友报点应保留。"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.audio_filter import is_agent_voice

failed = 0

def check(name, expected, actual):
    global failed
    ok = actual == expected
    if ok:
        print(f"  [PASS] {name}  -> {'过滤' if actual else '保留'}")
    else:
        print(f"  [FAIL] {name}  -> {'过滤' if actual else '保留'}（期望{'过滤' if expected else '保留'}）")
        failed += 1

print("=== 应该被过滤的（特工台词/系统播报）===")
AGENTS = [
    # Spike 播报
    "Spike planted",
    "Spike defused",
    "Spike spotted",
    "Spike spotted A",
    "Spike spotted B site",
    "Spike's A",
    "I have the spike",
    "Dropping spike",
    "Defuse resumed",
    "Defuse time running out",
    "Spike's in Attacker spawn",
    # 大招语音（ally / enemy 版本）
    "Don't get in my way!",
    "Welcome to my world!",
    "Watch this!",
    "Get out of my way!",
    "Off your feet!",
    "Here comes the party!",
    "Fire in the hole!",
    "They will cower!",
    "The hunt begins!",
    "Jokes over, you're dead!",
    "Where is everyone hiding?",
    "I know exactly where you are.",
    "Watch them run!",
    "Scatter!",
    "I am the hunter!",
    "Nowhere to run!",
    "Open up the sky!",
    "Prepare for hellfire!",
    "You will not kill my allies.",
    "Your duty is not over!",
    "Let's turn the tide.",
    "World divided.",
    "Oi, I'm pissed.",
    "Nightmare take them",
    "Monster on the loose.",
    "You want to play, let's play.",
    "Initiated.",
    "I'll handle this.",
    "I've got your trail.",
    # 回合 / 买枪
    "Enemy spotted",
    "Multiple enemies spotted",
    "Round won",
    "Match point",
    "Switching sides",
    "Buy phase",
    "Let's buy",
    "Let's save",
    "I have extra creds",
    # 其他
    "Clutch",
    "Ace",
    "Flawless",
    "Reloading",
    "Good job",
    "We got this",
    # 中文
    "安包已放置",
    "回合胜利",
    "发现敌人",
]
for t in AGENTS:
    check(t, True, is_agent_voice(t))

print("\n=== 应该保留的（队友报点）===")
TEAMMATES = [
    "Two B main",
    "Rotate A",
    "He's low",
    "One shot",
    "Watch flank",
    "Trade me",
    "3A Long",
    "Spike down",
    "Stick it",
    "Half defusing",
    "I need heal",
    "My ult is up",
    "Push mid",
    "Hold B",
    "Save your money",
    "Eco round",
    "One mid",
    "Two B Main, spike spotted",
    "Nice call",
    "Watch your back, someone flanking",
]
for t in TEAMMATES:
    check(t, False, is_agent_voice(t))

print("\n=== 边界情况 ===")
check("空字符串", True, is_agent_voice(""))
check("单字", True, is_agent_voice("..."))
check("正常短句", False, is_agent_voice("B long two"))

print(f"\n{'全部通过 ✅' if failed == 0 else f'失败 {failed} 项 ❌'}")
sys.exit(0 if failed == 0 else 1)
