"""翻译层：LLM（OpenAI 兼容）→ Bing → Google → MyMemory 逐级降级。

设计要点：
  * 实时场景最怕慢。每条通道都有短超时，失败立刻换下一条，绝不干等。
  * 游戏喊话 90% 是固定短句，中→英先用短语表直出，比任何机翻都准。
  * 术语用词边界匹配追注，避免 "plant" 里的 "nt" 被当成 "nt=可惜"。
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from collections import OrderedDict

import requests

from . import terms as _terms

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# ---------------- 无畏契约英文术语 → 中文 ----------------
# 词表主体在 terms.py（整理自玩家整理的「打瓦常用英文缩写大全」），
# 这里补几条它没覆盖的高频词。
_EXTRA_TERMS: dict[str, str] = {
    "one tap": "一枪头", "operator": "大狙", "op": "大狙",
    "clutch": "残局", "lit": "打残", "tagged": "打上了",
    "orbs": "能量球", "ult orb": "大招球", "spray": "扫射",
    "boost": "跳人", "on me": "我这边有人", "behind you": "你后面",
    "last one": "还剩一个", "one left": "还剩一个", "low": "残血",
    "cubby": "墙角", "ultimate": "大招", "ult": "大招",
    "smoke": "烟", "flash": "闪光", "nice shot": "好枪",
}
VALORANT_TERMS: dict[str, str] = {**_EXTRA_TERMS, **_terms.TERMS_ZH}

# ---------------- 英文/符号 → 中文：整句直出，绕开机翻 ----------------
# 队友只打一个缩写时（"gg"、"nt"），机翻要么原样吐回来要么译错，这里直接给答案
_DIRECT_EN_ZH: dict[str, str] = dict(_terms.DIRECT_ZH)

# ---------------- 中文喊话 → 英文（整句命中直接出，绕开机翻） ----------------
VOICE_LINES: dict[str, str] = dict(_terms.VOICE)
# 日服模式：中文喊话 → 日语
VOICE_LINES_JA: dict[str, str] = dict(_terms.VOICE_JA)

# 缩写展开：送翻译前先把 "nt" 换成 "nice try"，否则 LLM 会译成「牛逼」
_ABBR_EXPAND: dict[str, str] = {
    "nt": "nice try", "gg": "good game", "wp": "well played",
    "ggwp": "good game well played", "mb": "my bad", "ns": "nice shot",
    "gj": "good job", "ty": "thank you", "thx": "thanks",
    "np": "no problem", "glhf": "good luck have fun", "ez": "easy",
    "dc": "disconnected", "afk": "afk", "omw": "on my way", "brb": "be right back",
}


def expand_abbreviations(text: str) -> str:
    """把句中的游戏缩写展开成完整英文，让机翻/LLM 能正确理解。"""

    def repl(m: re.Match) -> str:
        w = m.group(0)
        return _ABBR_EXPAND.get(w.lower(), w)

    return re.sub(r"\b[A-Za-z]{2,5}\b", repl, text)


# 「英雄 + 伤害数字」报点：Jett 120 / Omen 1
_HERO_DMG_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9\s\-'.]{1,16}?)\s+(\d{1,3})\s*$")
# 防止 "wait 5" 这种被当成残血报点：英雄名必须首字母大写且不是常用词
_STOP_WORDS = {
    "wait", "and", "or", "for", "the", "you", "we", "they", "i", "a", "an",
    "to", "is", "no", "not", "my", "your", "his", "her", "one", "two",
    "three", "go", "come", "get", "let", "just", "now", "then", "here", "there",
}


def _looks_like_hero(name: str) -> bool:
    """只有真正的特工名才算残血报点，避免 "wait 5" 这类误判。"""
    return (name or "").strip().lower() in _terms.AGENT_KEYS


def parse_hero_damage(text: str) -> str:
    """把「Jett 120」「Omen one」翻译成中文报点。不像伤害报点就返回空。"""
    s = (text or "").strip()
    m = _HERO_DMG_RE.match(s)
    if m:
        hero, num = m.group(1).strip(), int(m.group(2))
        if not _looks_like_hero(hero):
            return ""
        if 100 <= num <= 150:
            return f"打了 {hero} {num}（对面残血）"
        if 1 <= num <= 5:
            return f"{hero} 极残（一枪）"
        return ""
    m2 = re.match(r"^\s*([A-Za-z][A-Za-z0-9\s\-'.]{1,16}?)\s+one\s*$", s, re.I)
    if m2:
        hero = m2.group(1).strip()
        if _looks_like_hero(hero):
            return f"{hero} 极残（一枪）"
    return ""

_LLM_SYSTEM = (
    "你是《无畏契约》(VALORANT) 队内语音实时翻译。把用户给的句子翻译成简洁、"
    "口语化、像真人队友喊话的目标语言。只输出译文本身，不要解释、不要引号、"
    "不要加括号注释。\n"
    "必须按下面这套固定译法，不要自创：\n"
    "eco=经济局 half buy=半起 full buy=全起 force buy=强起 save=保枪\n"
    "plant=下包 defuse=拆包 ninja defuse=偷包 stick=强拆 tap=假拆\n"
    "stick it=别松手/按住拆完 half=拆了一半 cover me=掩护我\n"
    "peek=探头 trade=补枪 entry=进点 lurk=单摸 stack=赌点 rotate=转点\n"
    "rush=一波冲 execute=爆点 retake=回防 fake=假打 split=夹击 default=默认控图\n"
    "heaven=二楼 hell=下层 main=大道 short=小道 mid=中路 site=包点\n"
    "rafters=高台 nest=巢室 elbow=弯道 catwalk=长径小道 window=窗口\n"
    "flank=绕后 watch flank=注意背后/防绕后 retreat=撤\n"
    "lit=打残 low=残血 one tap=一枪头 one shot=一枪就死 clutch=残局 op=大狙\n"
    "nt=可惜 wp=打得好 mb=我的锅 afk=挂机 dc=掉线 nice call=好报点\n"
    "报点语序：英文是「数量+位置」（Two B main），中文要倒过来说成"
    "「B大道两个」或「B大两个」，绝不能翻成「两个B大道」。\n"
    "特工名保留英文原文（Jett/Omen/Raze 等），不要音译。\n"
    "如果源文是日语，日式术语按下面译：フランク=绕后/侧翼（不是人名弗兰克）"
    "サイト=包点 スパイク=炸弹 設置=下包 解除=拆包 ローテート=转点 "
    "エコー=经济局 敵=敌人 味方=队友 一人=还剩一个 残り=剩余 上=高处/楼上\n"
    "武器固定译法：Vandal=暴徒（步枪，绝不能译成狙击枪，也不要译成战神）\n"
    "Phantom=幻象 Operator/OP=大狙 Sheriff=神射 Spectre=恶灵 Guardian=捍卫者\n"
    "Marshal=警长 Judge=判官 Bucky=重炮 Classic=制式 Ghost=鬼魅 Frenzy=狂弑\n"
    "Stinger=刺针 Bulldog=斗牛犬 Odin=奥丁 Ares=战神 Knife=小刀\n"
    "段位固定译法：Iron=黑铁 Bronze=青铜 Silver=白银 Gold=黄金 Platinum=铂金\n"
    "Diamond=钻石 Ascendant=超凡入圣 Immortal=神话 Radiant=辐能"
)

_BING_TOKEN_TTL = 600.0


class _LRU:
    def __init__(self, size: int = 4000):
        self.size = max(64, size)
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def put(self, key, value) -> None:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.size:
                self._d.popitem(last=False)


class Translator:
    def __init__(self, cfg_get):
        self._get = cfg_get
        self._cache = _LRU(int(cfg_get("translate.cache_size", 4000) or 4000))
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self._setup_proxy()
        self._last_error = ""
        self.backend_used = ""
        self.last_usage: dict = {}     # 最近一次 LLM 调用的 usage（看缓存命中用）
        self._min_gap = 0.12
        self._last_call = 0.0
        self._rl_lock = threading.Lock()
        self._bing: dict = {}
        self._bing_lock = threading.Lock()

    def _setup_proxy(self) -> None:
        proxy = (self._get("translate.proxy", "") or "").strip()
        if proxy:
            self._session.proxies.update({"http": proxy, "https": proxy})

    # ---------------- 对外 ----------------
    def translate(self, text: str, src: str = "en", dst: str = "zh-CN") -> str:
        text = (text or "").strip().strip('"“”')
        if not text:
            return ""
        key = (text, src, dst)
        hit = self._cache.get(key)
        if hit is not None:
            self.backend_used = "cache"
            return hit

        # 中文喊话直出（最快最准）
        if src == "zh":
            if dst.startswith("en"):
                direct = self._voice_line(text)
                if direct:
                    self.backend_used = "script"
                    self._cache.put(key, direct)
                    return direct
            elif dst.startswith("ja"):
                # 日服模式：中文 → 日语喊话
                direct = self._voice_line(text, VOICE_LINES_JA)
                if direct:
                    self.backend_used = "script"
                    self._cache.put(key, direct)
                    return direct

        # 英文缩写/符号直出：+4=在家挂机、afk=挂机中 这类机翻必错的
        if src == "en" and dst.startswith("zh"):
            direct = _DIRECT_EN_ZH.get(re.sub(r"\s+", "", text).lower())
            if direct:
                self.backend_used = "script"
                self._cache.put(key, direct)
                return direct
            # 「Jett 120」「Omen one」这种残血报点
            dmg = parse_hero_damage(text)
            if dmg:
                self.backend_used = "script"
                self._cache.put(key, dmg)
                return dmg

        self._throttle()
        # 送翻译前把 "nt"/"mb" 这类缩写展开，否则 LLM 会译成「牛逼」这种
        send_text = expand_abbreviations(text) if src == "en" else text
        result = ""
        for backend in self._backend_order(src, dst):
            try:
                result = self._call(backend, send_text, src, dst)
            except Exception as exc:
                self._last_error = f"{backend}: {_short(exc)}"
                result = ""
            if result:
                self.backend_used = backend
                break

        if result:
            result = self._postprocess(result.strip(), src, dst, text)
            if result:
                self._cache.put(key, result)
        return result

    @property
    def last_error(self) -> str:
        return self._last_error

    def test_llm(self) -> tuple[bool, str]:
        """直接打 LLM 接口测连通性，绕过缓存和直出表。

        返回 (成功?, 结果文本)。这是「保存配置」后唯一正确的自测方式 ——
        走 translate() 会命中缓存/喊话表，根本测不到 LLM。
        """
        base = (self._get("translate.llm.base_url", "") or "").strip()
        model = (self._get("translate.llm.model", "") or "").strip()
        key = (self._get("translate.llm.api_key", "") or "").strip()
        if not base or not model or not key:
            return False, "base_url / model / api_key 未填全"
        self._setup_proxy()
        # 用一句肯定不在缓存/直出表里的句子
        probe = "The coordinates are forty-two degrees north."
        try:
            out = self._via_llm(probe, "en", "zh-CN")
        except Exception as exc:
            return False, f"LLM 调用异常: {exc}"
        if out:
            self.backend_used = "llm"
            return True, out
        return False, self._last_error or "LLM 返回空"

    # ---------------- 内部 ----------------
    def _call(self, backend: str, text: str, src: str, dst: str) -> str:
        if backend == "llm":
            return self._via_llm(text, src, dst)
        if backend == "bing":
            return self._via_bing(text, src, dst)
        if backend == "google":
            return self._via_google(text, src, dst)
        if backend == "mymemory":
            return self._via_mymemory(text, src, dst)
        return ""

    def _backend_order(self, src: str = "", dst: str = "") -> list[str]:
        """按配置决定走哪个翻译通道。

        **日语优先 LLM，不掺机翻**：机翻不认识游戏术语（实测 Bing 把
        「オペレーター持ってる」译成「我有接线员，别接电话」，
        「スポイク設置した」译成「已安装吸管」，「フランク」译成「弗兰克」）。
        所以只要 LLM 可用，日→中 / 中→日 就只走 LLM。

        只有在完全没配 LLM 时才退回机翻 —— 没译文比错译文好，但比没有强，
        这种情况下 translate() 会在 last_error 里留下提示。
        """
        want = (self._get("translate.backend", "auto") or "auto").lower()
        llm_ready = bool(self._get("translate.llm.base_url", "")) and bool(
            self._get("translate.llm.model", "")
        )
        base = ["bing", "google", "mymemory"]

        ja_related = src.lower().startswith("ja") or dst.lower().startswith("ja")
        if ja_related:
            return ["llm"] if llm_ready else base

        if want == "llm":
            return (["llm"] if llm_ready else []) + base
        if want == "bing":
            return ["bing"] + base[1:] + (["llm"] if llm_ready else [])
        if want == "google":
            return ["google", "bing", "mymemory"] + (["llm"] if llm_ready else [])
        return (["llm"] if llm_ready else []) + base

    def _throttle(self) -> None:
        with self._rl_lock:
            gap = time.time() - self._last_call
            if gap < self._min_gap:
                time.sleep(self._min_gap - gap)
            self._last_call = time.time()

    def _voice_line(self, text: str, table: dict | None = None) -> str:
        norm = re.sub(r"[\s，。,.!！?？~～]+", "", text)
        for zh, target in (table or VOICE_LINES).items():
            if re.sub(r"[\s，。,.!！?？~～]+", "", zh) == norm:
                return target
        return ""

    def _postprocess(self, out: str, src: str, dst: str, source_text: str) -> str:
        out = re.sub(r"\s+", " ", out).strip()
        if not out:
            return ""
        # 机翻常见的错义补丁（中→英）
        if dst.startswith("en"):
            patches = {
                r"\bbig dump\b": "ult", r"\btake a (big )?dump\b": "use my ult",
                r"\bcover me a bit\b": "cover me", r"\bmiddle road\b": "mid",
            }
            for pat, rep in patches.items():
                out = re.sub(pat, rep, out, flags=re.I)
        # 英→中：补术语注释（词边界，最多 2 条）。LLM 已经译准了，不用再追注
        if (dst.startswith("zh") and self._get("translate.glossary", True)
                and self.backend_used != "llm"):
            out = self._annotate(source_text, out)
        return out

    def _annotate(self, src: str, zh: str) -> str:
        low = src.lower()
        hits: list[tuple[int, str]] = []
        for term, zh_term in VALORANT_TERMS.items():
            pat = r"(?<![a-z])" + re.escape(term) + r"(?![a-z])"
            if re.search(pat, low) and zh_term not in zh:
                hits.append((len(term), f"{term}={zh_term}"))
        if not hits:
            return zh
        hits.sort(key=lambda h: -h[0])          # 长词优先，避免 op 抢 operator
        picked, used = [], set()
        for _n, tag in hits:
            base = tag.split("=")[0]
            if any(base in u or u in base for u in used):
                continue
            used.add(base)
            picked.append(tag)
            if len(picked) >= 2:
                break
        return f"{zh}（{'，'.join(picked)}）" if picked else zh

    # ---------------- Bing（国内可直连） ----------------
    def _bing_params(self) -> dict:
        with self._bing_lock:
            now = time.time()
            if self._bing.get("t", 0) + _BING_TOKEN_TTL > now and self._bing.get("ig"):
                return self._bing
            r = self._session.get("https://cn.bing.com/translator",
                                  timeout=float(self._get("translate.timeout", 5)),
                                  headers={"Referer": "https://cn.bing.com/"})
            html = r.text
            m = re.search(r'params_AbusePreventionHelper\s*=\s*\[\s*(\d+)\s*,\s*"([^"]+)"', html)
            ig = re.search(r'IG:"([^"]+)"', html)
            iid = re.search(r'data-iid="([^"]+)"', html)
            if not (m and ig):
                raise RuntimeError("Bing token 解析失败")
            self._bing = {
                "key": m.group(1), "token": m.group(2),
                "ig": ig.group(1), "iid": iid.group(1) if iid else "translator.5028",
                "t": now,
            }
            return self._bing

    def _bing_lang(self, code: str) -> str:
        c = code.lower()
        if c.startswith("zh"):
            return "zh-Hans"
        return c.split("-")[0]

    def _via_bing(self, text: str, src: str, dst: str) -> str:
        p = self._bing_params()
        url = f"https://cn.bing.com/ttranslatev3?isVertical=1&IG={p['ig']}&IID={p['iid']}"
        data = {
            "fromLang": "auto-detect",
            "to": self._bing_lang(dst),
            "text": text,
            "token": p["token"],
            "key": p["key"],
        }
        r = self._session.post(url, data=data, timeout=float(self._get("translate.timeout", 5)),
                               headers={"Referer": "https://cn.bing.com/translator"})
        if r.status_code != 200:
            with self._bing_lock:
                self._bing = {}
            raise RuntimeError(f"Bing HTTP {r.status_code}")
        js = r.json()
        if isinstance(js, dict) and js.get("statusCode"):
            with self._bing_lock:
                self._bing = {}
            raise RuntimeError(f"Bing {js.get('statusCode')}")
        try:
            return js[0]["translations"][0]["text"]
        except Exception:
            return ""

    # ---------------- Google ----------------
    def _via_google(self, text: str, src: str, dst: str) -> str:
        endpoint = self._get("translate.google_endpoint",
                             "https://translate.googleapis.com/translate_a/single")
        params = {"client": "gtx", "sl": src, "tl": dst, "dt": "t", "q": text}
        url = endpoint + "?" + urllib.parse.urlencode(params)
        r = self._session.get(url, timeout=float(self._get("translate.google_timeout", 3)))
        r.raise_for_status()
        data = r.json()
        if not data or not data[0]:
            return ""
        return "".join(seg[0] for seg in data[0] if seg and seg[0])

    # ---------------- MyMemory（最后兜底） ----------------
    def _via_mymemory(self, text: str, src: str, dst: str) -> str:
        if len(text) > 480:
            text = text[:480]
        pair = f"{src}|{'zh-CN' if dst.startswith('zh') else dst}"
        url = ("https://api.mymemory.translated.net/get?"
               + urllib.parse.urlencode({"q": text, "langpair": pair}))
        r = self._session.get(url, timeout=float(self._get("translate.mymemory_timeout", 6)))
        r.raise_for_status()
        data = r.json()
        out = (data.get("responseData") or {}).get("translatedText") or ""
        if "MYMEMORY WARNING" in out.upper() or "QUOTA" in out.upper():
            return ""
        return out

    # ---------------- LLM ----------------
    def _via_llm(self, text: str, src: str, dst: str) -> str:
        base = (self._get("translate.llm.base_url", "") or "").rstrip("/")
        model = self._get("translate.llm.model", "")
        key = self._get("translate.llm.api_key", "")
        if not base or not model:
            return ""
        url = base + "/chat/completions"
        lang_name = {"en": "英文", "zh": "中文", "ja": "日语"}.get(
            dst.split("-")[0], dst)
        src_name = {"en": "英文", "ru": "俄语", "ja": "日语", "ko": "韩语",
                    "zh": "中文", "es": "西班牙语", "pt": "葡萄牙语",
                    "fr": "法语", "de": "德语", "tr": "土耳其语"}.get(
            (src or "").split("-")[0], "")
        # 队友可能说俄/日/韩，告诉模型源语种，否则它会按英文硬猜
        ask = (f"把这句{src_name}翻译成{lang_name}：" if src_name
               else f"翻译成{lang_name}：")

        # prompt caching：system prompt 每句都要重传（约 560 tokens），
        # 标记成 ephemeral 让服务端缓存它，命中部分按低价计费。
        # 通义本来就会自动缓存（实测不标记也命中 384/561），
        # 标记后能到 448/561，多省一点。不支持该格式的接口会自动降级。
        use_cache = bool(self._get("translate.llm.prompt_cache", True))
        sys_content = ([{"type": "text", "text": _LLM_SYSTEM,
                         "cache_control": {"type": "ephemeral"}}]
                       if use_cache else _LLM_SYSTEM)
        payload = {
            "model": model,
            "temperature": 0.1,
            "max_tokens": 256,
            # DeepSeek 默认开启思考模式：实测思考内容会占满 max_tokens，
            # 导致「正文返回空」（finish_reason=length），而且慢 2.8 倍
            # （1.35s vs 0.48s）。翻译不需要推理，直接关掉。
            # 不认这个参数的接口会 400，下面自动降级重试。
            "thinking": {"type": "disabled"},
            "messages": [
                {"role": "system", "content": sys_content},
                {"role": "user", "content": ask + text},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        timeout = float(self._get("translate.llm.timeout", 10))
        r = self._session.post(url, data=json.dumps(payload), headers=headers,
                               timeout=timeout)
        # 兼容降级：不认 thinking / cache_control 的接口逐个去掉重试
        if r.status_code in (400, 422):
            changed = False
            if "thinking" in payload:
                payload.pop("thinking")
                changed = True
            if use_cache:
                payload["messages"][0]["content"] = _LLM_SYSTEM
                changed = True
            if changed:
                r = self._session.post(url, data=json.dumps(payload),
                                       headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        # 把缓存命中情况记下来，方便在日志里看省钱效果
        usage = data.get("usage", {}) or {}
        self.last_usage = usage
        choice = (data.get("choices") or [{}])[0]
        out = ((choice.get("message") or {}).get("content") or "").strip()
        out = out.strip('"“”')
        # 万一还是被思考吃掉了配额（返回空 + finish_reason=length），
        # 放宽 max_tokens 再来一次，别让用户看到空白
        if not out and choice.get("finish_reason") == "length":
            payload.pop("thinking", None)
            payload["max_tokens"] = 512
            r = self._session.post(url, data=json.dumps(payload),
                                   headers=headers, timeout=timeout)
            if r.status_code == 200:
                d2 = r.json()
                self.last_usage = d2.get("usage", {}) or usage
                out = (((d2.get("choices") or [{}])[0].get("message") or {})
                       .get("content") or "").strip().strip('"“”')
        return out


def _short(exc: Exception) -> str:
    s = str(exc)
    return s if len(s) < 90 else s[:90] + "…"