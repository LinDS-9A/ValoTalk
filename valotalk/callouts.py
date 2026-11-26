"""报点术语纠正 —— 夹在 ASR 和翻译之间的一层。

为什么需要它
------------
港服队友来自各地，口音很杂。whisper 在真实报点上错得很规律，全是「音近词」：

    To A long   ->  To a law
    One slow    ->  once law
    Retreat     ->  Retail die
    Watch flank ->  Watch flak
    Spike's down->  Spikes down eye

这些错词拿去翻译就是废的（"To a law" 谁知道是 A 大？）。而往 whisper 的
initial_prompt 里塞术语表不但没用，还会把整段识别打崩（实测 11/15 → 0/15），
所以只能在**输出之后**纠。

三条铁律（都是踩出来的）
------------------------
1. **已经是正确术语的词一律不碰**。第一版没这条，"Stick it" 被改成 "Site it"、
   "Eco round" 被改成 "Ace round" —— 越纠越错。
2. **普通英文单词一律不碰**。第一版把 "i love you" 改成了 "a long you"。
3. **拿不准就不改**。漏纠只是没帮上忙，错纠是把对的改错。
"""
from __future__ import annotations

import difflib
import re

# ---------------- 正确术语（出现即视为正确，绝不修改）----------------
VOCAB: tuple[str, ...] = (
    "main", "long", "short", "mid", "heaven", "hell", "nest", "rafters",
    "elbow", "window", "catwalk", "site", "spawn",
    "eco", "save", "buy", "full", "force", "half", "default",
    "rotate", "hold", "push", "retreat", "flank", "trade", "peek",
    "rush", "execute", "retake", "fake", "split", "lurk", "stack",
    "spike", "plant", "planted", "defuse", "defusing", "stick", "tap",
    "low", "lit", "clutch", "ace", "flash", "flashing", "smoke",
    "smoking", "ult", "heal", "cover", "slow", "going", "call",
)

# ---------------- 高频普通词（不许被"纠正"）----------------
COMMON = set("""
a an the this that these those i me my we our you your he she it its
they them their his her am is are was were be been being do does did
done have has had will would can could should must may might shall
and or but if then than so because as of at on in into onto from by
for with without about over under again very really just also too not
no yes ok okay well now here there what when where who how why which
one two three four five six seven eight nine ten first last next
time day night today tomorrow yesterday week month year hour minute
love like want need know think see look hear say tell speak talk ask
answer question play game work go come get make take give find lose
win lose start stop open close buy sell eat drink sleep run walk sit
stand wait help try use put keep leave call read write learn teach
good bad big small long short high low new old young fast slow hard
easy happy sad angry tired hungry busy free full empty hot cold warm
cool nice fine great best worst better worse more less most least
house car phone computer money water food people person man woman boy
girl child friend family mother father brother sister home school
weather cold hot rain snow wind sun sky tree book music movie sport
why how what who when where which whose whom
let get got put set run ran sit sat met bet bit fit hit kit quit
""".split())

# ---------------- 实测得到的固定错法（高置信，直接换）----------------
PHRASE_FIX: dict[str, str] = {
    "to a law": "to A long",
    "to a long": "to A long",
    "too a law": "to A long",
    "once law": "one slow",
    "one law": "one slow",
    "once low": "one slow",
    "retail die": "retreat",
    "retail down": "retreat",
    "watch flak": "watch flank",
    "flak": "flank",
    "spikes down eye": "spike's down",
    "spike down eye": "spike's down",
    "spikes down i": "spike's down",
    "spike down i": "spike's down",
    "spikes down": "spike down",
    "im going in": "I'm going in",
    "i'm going in": "I'm going in",
    "dont look": "don't look",
    "don't look": "don't look",
    # ⚠️ 不要在这里放裸的 "a long" / "a main"：普通英语里
    # "a long time"、"a main course" 到处都是，会被改坏。
    # 位置名的大小写交给翻译模型，这层只管把听岔的词修回来。
}


def _skeleton(word: str) -> str:
    """辅音骨架：去元音、归一易混字母，用来比发音。"""
    w = word.lower().replace("'", "").replace("’", "")
    w = (w.replace("ph", "f").replace("ck", "k").replace("qu", "k")
          .replace("x", "ks"))
    out = []
    for i, ch in enumerate(w):
        if ch in "aeiouy":
            continue
        if ch in "cq":
            ch = "k"
        if ch in "bg" and i == len(w) - 1:
            ch = "k"
        if ch in "sz":
            ch = "s"
        if ch in "dt" and i == len(w) - 1:
            ch = "t"
        out.append(ch)
    s = "".join(out)
    s = re.sub(r"(.)\1+", r"\1", s)
    s = re.sub(r"n?k$", "", s) if len(s) > 2 else s
    return s


_VOCAB_SKEL = [(w, _skeleton(w)) for w in VOCAB]
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’]*")
_CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff]")


def looks_english(text: str) -> bool:
    """粗略判断：有拉丁字母、没有中日文字，就当英文报点处理。"""
    if not text:
        return False
    if _CJK_RE.search(text):
        return False
    return bool(_WORD_RE.search(text))


def fix(text: str) -> tuple[str, list[tuple[str, str]]]:
    """把 ASR 文本里的音近错词纠回报点用语。

    返回 (纠正后文本, [(原文, 纠正后), ...])。
    """
    if not text or not _WORD_RE.search(text):
        return text, []

    changes: list[tuple[str, str]] = []
    out = text

    # ---- 第一遍：固定短语（从长到短，避免被短的抢先）----
    keys = sorted(PHRASE_FIX, key=len, reverse=True)
    low = out.lower()
    offsets: list[tuple[int, int, str]] = []
    for k in keys:
        start = 0
        while True:
            i = low.find(k, start)
            if i < 0:
                break
            j = i + len(k)
            # 词边界：别把 "tomato a long" 里的一段吃掉
            lb = i == 0 or not low[i - 1].isalpha()
            rb = j >= len(low) or not low[j].isalpha()
            if lb and rb and not any(s <= i < e or s < j <= e
                                    for s, e, _ in offsets):
                offsets.append((i, j, PHRASE_FIX[k]))
            start = i + 1
    for i, j, rep in sorted(offsets, key=lambda x: -x[0]):
        src = out[i:j]
        # 句首大写别被拉成小写（"Trade me." 不该变成 "trade me."）
        if src[:1].isupper() and rep[:1].islower():
            rep = rep[:1].upper() + rep[1:]
        if src != rep:
            changes.append((src, rep))
        out = out[:i] + rep + out[j:]
    changes.reverse()

    # ---- 第二遍：单个词，只在"看着就不像正常英文"时动手 ----
    def repl(m: re.Match) -> str:
        w = m.group(0)
        low_w = w.lower().strip("'’")
        if len(low_w) < 3:
            return w
        if low_w in COMMON or low_w in VOCAB:
            return w                                  # 铁律 1、2
        if low_w.isdigit():
            return w
        sk = _skeleton(low_w)
        if len(sk) < 2:
            return w
        best_s, best_w = 0.0, None
        for canon, csk in _VOCAB_SKEL:
            s1 = difflib.SequenceMatcher(None, sk, csk).ratio()
            s2 = difflib.SequenceMatcher(None, low_w, canon).ratio()
            score = s1 * 0.6 + s2 * 0.4
            if score > best_s:
                best_s, best_w = score, canon
        # 铁律 3：阈值卡死，宁漏不错
        if best_w and best_s >= 0.86 and \
                difflib.SequenceMatcher(None, sk, _skeleton(best_w)).ratio() >= 0.85:
            changes.append((w, best_w))
            return best_w
        return w

    out = _WORD_RE.sub(repl, out)
    return out, changes
