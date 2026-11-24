"""模型配置库：一套 base_url + api_key 存一条，识别和 LLM 共用。

存的形状（config.json）：

    "models": {
      "profiles": [
        {"name": "阿里云百炼", "base_url": "https://...", "api_key": "sk-..."},
        {"name": "DeepSeek",   "base_url": "https://api.deepseek.com/v1",
         "api_key": "sk-..."}
      ],
      "asr": {"profile": "阿里云百炼", "model": "qwen3-asr-flash", "enabled": true},
      "llm": {"profile": "阿里云百炼", "model": "qwen-plus",        "enabled": true}
    }

为什么用名字而不是下标做索引：列表可以增删，下标会错位；
名字重名时 add() 会自动加后缀。

老配置迁移：首次运行如果 profiles 为空，但 translate.llm 里已有
base_url / api_key，就自动存成第一条，名字按服务商推断。
"""
from __future__ import annotations

from urllib.parse import urlsplit

__all__ = ["Profiles", "guess_name"]

# 按域名猜个名字，给迁移和默认命名用
_NAME_HINTS = [
    ("deepseek", "DeepSeek"),
    ("dashscope", "阿里云百炼"),
    ("aliyun", "阿里云百炼"),
    ("qianwen", "千问"),
    ("siliconflow", "硅基流动"),
    ("openai", "OpenAI"),
    ("groq", "Groq"),
    ("moonshot", "月之暗面"),
    ("bigmodel", "智谱"),
    ("volces", "火山方舟"),
    ("localhost", "本地模型"),
    ("127.0.0.1", "本地模型"),
]


def guess_name(base_url: str) -> str:
    """按 base_url 猜一个可读名字。"""
    low = (base_url or "").lower()
    for key, name in _NAME_HINTS:
        if key in low:
            return name
    try:
        host = urlsplit(base_url).netloc or base_url
        return host.split(":")[0].split(".")[0] or "自定义"
    except Exception:
        return "自定义"


class Profiles:
    """配置库的读写门面。线程安全不是重点（只在 UI 线程用）。"""

    def __init__(self, cfg_get, cfg_set):
        self._get = cfg_get
        self._set = cfg_set

    # ---------------- 读 ----------------
    def all(self) -> list[dict]:
        raw = self._get("models.profiles", []) or []
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            out.append({
                "name": str(item.get("name", "") or "").strip(),
                "base_url": str(item.get("base_url", "") or "").strip(),
                "api_key": str(item.get("api_key", "") or "").strip(),
            })
        return out

    def names(self) -> list[str]:
        return [p["name"] for p in self.all() if p["name"]]

    def get(self, name: str) -> dict | None:
        for p in self.all():
            if p["name"] == name:
                return p
        return None

    def asr_pick(self) -> dict:
        return self._get("models.asr", {}) or {}

    def llm_pick(self) -> dict:
        return self._get("models.llm", {}) or {}

    # ---------------- 写 ----------------
    def _save(self, items: list[dict], save: bool = True) -> None:
        self._set("models.profiles", items, save=save)

    def _unique_name(self, want: str, items: list[dict],
                     skip: str = "") -> str:
        base = want.strip() or "配置"
        name = base
        i = 2
        used = {p["name"] for p in items if p["name"] != skip}
        while name in used:
            name = f"{base}{i}"
            i += 1
        return name

    def add(self, name: str, base_url: str, api_key: str,
            save: bool = True) -> str:
        """新增一条，返回最终用的名字（重名会自动加数字后缀）。"""
        items = self.all()
        final = self._unique_name(name or guess_name(base_url), items)
        items.append({"name": final,
                      "base_url": (base_url or "").strip(),
                      "api_key": (api_key or "").strip()})
        self._save(items, save=save)
        return final

    def update(self, name: str, base_url: str, api_key: str,
               save: bool = True) -> bool:
        items = self.all()
        for p in items:
            if p["name"] == name:
                p["base_url"] = (base_url or "").strip()
                p["api_key"] = (api_key or "").strip()
                self._save(items, save=save)
                return True
        return False

    def remove(self, name: str, save: bool = True) -> bool:
        items = self.all()
        left = [p for p in items if p["name"] != name]
        if len(left) == len(items):
            return False
        self._save(left, save=save)
        # 选中它的那两行要跟着改，别指向已删除的
        for kind in ("asr", "llm"):
            pick = self._get(f"models.{kind}", {}) or {}
            if pick.get("profile") == name:
                pick = dict(pick)
                pick["profile"] = left[0]["name"] if left else ""
                self._set(f"models.{kind}", pick, save=save)
        return True

    def rename(self, old: str, new: str, save: bool = True) -> str:
        items = self.all()
        final = self._unique_name(new, items, skip=old)
        for p in items:
            if p["name"] == old:
                p["name"] = final
        self._save(items, save=save)
        for kind in ("asr", "llm"):
            pick = self._get(f"models.{kind}", {}) or {}
            if pick.get("profile") == old:
                pick = dict(pick)
                pick["profile"] = final
                self._set(f"models.{kind}", pick, save=save)
        return final

    # ---------------- 应用 ----------------
    def apply_asr(self, save: bool = True) -> bool:
        """把选中的语音识别配置同步到 asr.cloud_*，让旧代码直接生效。"""
        pick = self.asr_pick()
        prof = self.get(str(pick.get("profile", "") or ""))
        if not prof:
            return False
        self._set("asr.cloud_base_url", prof["base_url"], save=False)
        self._set("asr.cloud_api_key", prof["api_key"], save=False)
        self._set("asr.cloud_model", str(pick.get("model", "") or ""), save=False)
        self._set("asr.backend",
                  "cloud" if pick.get("enabled", True) else "local", save=save)
        return True

    def apply_llm(self, save: bool = True) -> bool:
        """把选中的 LLM 配置同步到 translate.llm.*。"""
        pick = self.llm_pick()
        prof = self.get(str(pick.get("profile", "") or ""))
        if not prof:
            return False
        self._set("translate.llm.base_url", prof["base_url"], save=False)
        self._set("translate.llm.api_key", prof["api_key"], save=False)
        self._set("translate.llm.model", str(pick.get("model", "") or ""),
                  save=False)
        self._set("translate.backend",
                  "llm" if pick.get("enabled", True) else "auto", save=save)
        return True

    def apply_all(self, save: bool = True) -> None:
        self.apply_asr(save=False)
        self.apply_llm(save=save)

    # ---------------- 迁移 ----------------
    def migrate(self) -> bool:
        """老配置 → 新结构。只跑一次，已经有 profiles 就不动。

        去重：地址和密钥都相同的只存一条，别因为识别/翻译分开配过就存两条。
        """
        if self.all():
            return False
        base = str(self._get("translate.llm.base_url", "") or "").strip()
        key = str(self._get("translate.llm.api_key", "") or "").strip()
        if not base and not key:
            return False

        name = self.add(guess_name(base), base, key, save=False)

        # 识别那边如果单独配过**不同**的地址/密钥，才另存一条
        a_base = str(self._get("asr.cloud_base_url", "") or "").strip()
        a_key = str(self._get("asr.cloud_api_key", "") or "").strip()
        asr_name = name
        same = (a_base == base and a_key == key) or (not a_base and not a_key)
        if not same and (a_base or a_key):
            asr_name = self.add(guess_name(a_base or base) + "（识别）",
                                a_base or base, a_key or key, save=False)

        llm_model = str(self._get("translate.llm.model", "") or "").strip()
        a_model = str(self._get("asr.cloud_model", "") or "").strip()
        self._set("models.llm", {"profile": name,
                                 "model": llm_model or "qwen-plus",
                                 "enabled": True}, save=False)
        self._set("models.asr", {"profile": asr_name,
                                 "model": a_model or "qwen3-asr-flash",
                                 "enabled": str(self._get(
                                     "asr.backend", "cloud")).lower() != "local"},
                  save=False)
        self._set("models.profiles", self.all(), save=True)
        return True

    def dedupe(self) -> int:
        """清理重复条目（地址 + 密钥都一样），返回删掉的条数。

        老版本迁移可能留下重复项；顺手把指向被删条目的选择改到保留的那条。
        """
        items = self.all()
        seen: dict[tuple, str] = {}
        keep: list[dict] = []
        remap: dict[str, str] = {}
        for it in items:
            sig = (it["base_url"], it["api_key"])
            if sig in seen:
                remap[it["name"]] = seen[sig]
                continue
            seen[sig] = it["name"]
            keep.append(it)
        if len(keep) == len(items):
            return 0
        self._save(keep)
        for kind in ("asr", "llm"):
            pick = dict(self._get(f"models.{kind}", {}) or {})
            cur = str(pick.get("profile", "") or "")
            if cur in remap:
                pick["profile"] = remap[cur]
                self._set(f"models.{kind}", pick)
        return len(items) - len(keep)