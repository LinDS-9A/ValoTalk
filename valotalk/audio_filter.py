"""按进程过滤音频会话：只在游戏进程有声音时才处理识别结果。

用 pycaw 枚举 Windows 音频会话，检查目标进程（如 VALORANT）是否在
播放音频。游戏没在说话时跳过处理，排除 Discord、音乐播放器等干扰。
"""
from __future__ import annotations
import threading
import time
import logging

log = logging.getLogger(__name__)

try:
    from pycaw.pycaw import AudioUtilities
    _HAS_PYCAW = True
except Exception:
    _HAS_PYCAW = False


class ProcessAudioFilter:
    """按进程名监控音频会话，判断游戏是否在播放音频。"""

    def __init__(self, cfg_get):
        self._get = cfg_get
        self._lock = threading.Lock()
        self._last_check = 0.0
        self._cache_active = True      # 缓存：游戏是否在播音频
        self._session = None
        self._proc_name = ""
        self._checked = False

    def _find_session(self):
        """找目标进程的音频会话。找不到返回 None。"""
        if not _HAS_PYCAW:
            return None
        proc = str(self._get("audio.game_process", "") or "").strip().lower()
        if not proc:
            return None
        try:
            sessions = AudioUtilities.GetAllSessions()
        except Exception:
            return None
        for s in sessions:
            p = s.Process
            if p is None:
                continue
            try:
                name = (p.name() or "").lower()
            except Exception:
                continue
            if proc in name:
                return s
        return None

    def is_game_active(self, timeout: float = 0.5) -> bool:
        """游戏进程是否在播放音频。

        结果缓存 timeout 秒，避免频繁 COM 调用。
        没配进程名 / pycaw 不可用 / 找不到会话时返回 True
        （不过滤，宁可多识别也不漏）。
        """
        if not _HAS_PYCAW:
            return True
        proc = str(self._get("audio.game_process", "") or "").strip()
        if not proc:
            return True                      # 没配进程名 → 不过滤

        now = time.time()
        with self._lock:
            if now - self._last_check < timeout:
                return self._cache_active
            self._last_check = now

            if self._session is None or self._proc_name != proc.lower():
                self._session = self._find_session()
                self._proc_name = proc.lower()
                self._checked = self._session is not None

            if self._session is None:
                self._cache_active = True    # 找不到会话 → 不过滤
                return True

            try:
                meter = self._session.SimpleAudioVolume
                level = meter.GetMasterVolume() if meter else 0.0
                muted = meter.GetMute() if meter else False
                self._cache_active = bool(level > 0.01 and not muted)
            except Exception:
                self._cache_active = True    # 查询失败 → 不过滤
            return self._cache_active

    def describe(self) -> str:
        if not _HAS_PYCAW:
            return "pycaw 未安装（不过滤）"
        proc = str(self._get("audio.game_process", "") or "").strip()
        if not proc:
            return "未设置游戏进程（不过滤）"
        if self._session is None:
            return f"未找到进程 {proc}（不过滤）"
        active = "活跃" if self._cache_active else "静音"
        return f"进程 {proc}：{active}"


def is_agent_voice(text: str) -> bool:
    """判断识别文本是否是游戏内特工台词（而非队友语音聊天）。

    特工台词的特征：短、正式、固定句式，不含玩家特有的
    位置/数字/战术词汇。队友报点通常是「数量+位置」「战术动词+位置」。
    """
    if not text or len(text.strip()) < 1:
        return True                       # 空 → 过滤
    s = text.strip().lower()
    s = s.strip(".!?,;: ")

    # ---- 特工语音全集（来源：VALORANT Wiki / 官方语音包）----
    # 分四类：Spike 播报、大招语音、回合/买枪、其他
    agent_exact = {
        # ===== 1. Spike 播报（最高频，最容易被误识别）=====
        "spike spotted", "spike planted", "spike defused",
        "spike dropped", "spike retrieved", "spike ping",
        "i have the spike", "dropping spike", "have the spike",
        "defuse resumed", "defuse time running out",
        "defuse successful", "defusing",
        "spike a", "spike b", "spike c",
        "spike's a", "spike's b", "spike's c",
        "spike spotted a", "spike spotted b", "spike spotted c",
        "spike in attacker spawn", "spike's in attacker spawn",
        "spike in defender spawn",
        "forgotten in spawn",
        # ===== 2. 大招语音（响、清晰、完整句子，最干扰）=====
        # Viper
        "don't get in my way", "welcome to my world",
        # Jett
        "watch this", "get out of my way",
        # Breach
        "off your feet", "let's go",
        # Raze
        "here comes the party", "fire in the hole",
        # Reyna
        "they will cower", "the hunt begins",
        # Phoenix
        "come on, let's go", "jokes over, you're dead",
        "jokes over you're dead",
        # Cypher
        "where is everyone hiding",
        "i know exactly where you are",
        # Omen
        "watch them run", "scatter",
        # Sova
        "i am the hunter", "nowhere to run",
        # Brimstone
        "open up the sky", "prepare for hellfire",
        # Sage
        "you will not kill my allies", "your duty is not over",
        # Harbor
        "let's turn the tide",
        # Astra
        "world divided",
        # Neon
        "oi, i'm pissed", "oi i'm pissed",
        # Fade
        "nightmare take them",
        # Gekko
        "monster on the loose",
        # Chamber
        "you want to play, let's play",
        # Killjoy
        "initiated",
        # Yoru
        "i'll handle this", "i will handle this",
        # Skye
        "i've got your trail",
        # ===== 3. 回合 / 买枪阶段 =====
        "enemy spotted", "multiple enemies spotted",
        "round won", "round lost", "match point",
        "switching sides", "buy phase", "warmup",
        "let's buy", "let's save", "i have extra creds",
        "requested", "not enough credits",
        "barrier down",
        # ===== 4. 其他系统播报 =====
        "clutch", "ace", "flawless", "thrifty", "heroic",
        "reloading", "need backup", "holding",
        "relax", "we got this", "nice", "good job",
        "i got this", "going up", "going down",
        "here we go",
        # ===== 中文版（国服）=====
        "安包已放置", "安包已拆除", "发现敌人", "敌人倒下",
        "回合胜利", "回合失败", "赛点", "拆除中", "已安装安包",
    }
    if s in agent_exact:
        return True

    # ---- 前缀匹配：带位置/变体的播报（"Spike spotted A site" 这类）----
    # ⚠️ 必须排除 "spike down" —— 那是队友报「包掉了」，不是特工语音
    agent_prefix = (
        "spike spotted", "spike planted", "spike defused",
        "spike dropped", "spike retrieved", "spike in ",
        "defuse time running out", "enemy spotted",
        "multiple enemies spotted", "enemies remaining",
        "one enemy remaining", "two enemies remaining",
        "three enemy remaining",
    )
    if any(s.startswith(p) for p in agent_prefix):
        return True

    # ---- 队友报点的特征词（有这些说明是真人说话）----
    teammate_signals = (
        "a long", "b long", "a short", "b short", "a main", "b main",
        "mid", "heaven", "hell", "nest", "rafters", "elbow", "window",
        "catwalk", "site", "spawn",
        "two", "three", "one", "four", "both", "all",
        "rotate", "push", "hold", "retreat", "flank", "trade",
        "peek", "rush", "retake", "fake", "split", "default",
        "watch", "cover", "save", "eco", "force",
        "low", "lit", "one shot", "one tap", "cracked",
        "half", "stick", "tap", "defusing", "plant", "spike",
        "nice call", "nice try", "nt", "wp", "mb",
        "heal", "ult", "need",
    )
    has_signal = any(sig in s for sig in teammate_signals)

    # 短句 + 无报点特征 → 大概率是特工台词
    word_count = len(s.split())
    if word_count <= 3 and not has_signal:
        return True

    return False
