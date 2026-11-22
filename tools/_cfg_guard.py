"""测试用的配置保护器：跑完自动把 config.json 还原。

背景（踩过的坑）：
  Config.set(dotted, value, save=False) 只改内存；
  但只要之后有任何 save=True 的操作（_set、shutdown 存字幕坐标、
  切换开关写 backend…），整个 _data 都会被写盘 ——
  于是测试里临时改的空值被固化，用户的 api_key 就丢了。

用法：
    from tools._cfg_guard import config_guard
    with config_guard():
        CONFIG.set("translate.llm.api_key", "", save=False)
        ... 测试 ...
    # 退出 with 时文件和内存都回到原样
"""
from __future__ import annotations

import copy
from contextlib import contextmanager

from valotalk.config import CONFIG, CONFIG_PATH


@contextmanager
def config_guard():
    """进入时备份内存 + 文件，退出时无条件还原。"""
    file_backup = None
    if CONFIG_PATH.exists():
        try:
            file_backup = CONFIG_PATH.read_bytes()
        except Exception:
            file_backup = None
    data_backup = copy.deepcopy(CONFIG._data)

    try:
        yield CONFIG
    finally:
        # 先还原内存，再写盘（顺序不能反：写盘用的是 _data）
        CONFIG._data = copy.deepcopy(data_backup)
        if file_backup is not None:
            try:
                CONFIG_PATH.write_bytes(file_backup)
            except Exception:
                pass