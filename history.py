#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修改历史 —— 记住每次写入改了什么，并能一键撤销。

设计取向：**不额外复制存档**。

Save.write() 在写盘之前本来就会生成一份 `.bak-<时间戳>`，那正是「改动之前的状态」。
所以历史记录只需要存「改了什么 + 对应哪个备份文件」，撤销就是拿那个备份盖回去。
好处是历史记录本身几乎不占空间，也不会和已有的备份机制各存一份、互相打架。

唯一的坑：prune_backups 只保留最近 10 个备份，老备份会被删掉 ——
所以撤销时要检查备份还在不在，不在就明确告诉用户，而不是报个看不懂的错。
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent

# 历史文件放哪。用环境变量 WUJIN_HISTORY 可以改写 ——
# 测试就是靠它把历史重定向到临时文件，免得拿测试垃圾把用户真正的改动记录挤掉
# （历史只保留 30 条，被挤掉的是真记录）。子进程会继承这个变量，
# 所以对 smoke/e2e 这种「父进程起子进程」的用法一样有效。
#
# 打包成 exe 后必须走 state_file()，不能用 HERE：
# onefile 模式下 HERE 指向一个「退出即删」的临时目录，历史会被静默清空。
HISTORY_FILE = Path(os.environ.get("WUJIN_HISTORY") or paths.state_file("history.json"))
HISTORY_KEEP = 30          # 最多记多少条


def _load() -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        d = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _save(entries: list) -> None:
    tmp = HISTORY_FILE.with_name(HISTORY_FILE.name + ".tmp")
    tmp.write_text(json.dumps(entries[-HISTORY_KEEP:], ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(HISTORY_FILE)


def record(target, title: str, changes, backup) -> dict:
    """记一条。backup 是 Save.write() 返回的备份路径（改动前的状态）。"""
    entries = _load()
    e = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target": str(Path(target).resolve()),
        "title": title,
        "count": len(changes),
        "backup": str(backup) if backup else None,
        "changes": [str(c) for c in changes][:60],
    }
    entries.append(e)
    _save(entries)
    return e


def entries(target=None) -> list:
    """列出历史（默认全部；给了 target 就只看这个存档的）。"""
    es = _load()
    if target:
        t = str(Path(target).resolve())
        es = [e for e in es if e.get("target") == t]
    return es


def describe(index: int) -> str:
    es = _load()
    if not (0 <= index < len(es)):
        return ""
    e = es[index]
    return f"{e['time']}  {e['title']}  （{e['count']} 处改动）"


def undo(index: int = -1, target=None):
    """撤销第 index 条改动（默认最后一条）。

    target 给定时，index 是【这个存档自己那串历史】里的序号，
    而不是全局历史的序号 —— 否则多存档混着用时会撤错人。

    返回 (说明文字, 错误文字)，正常时错误为 None。
    """
    all_es = _load()
    if target is not None:
        t = str(Path(target).resolve())
        view = [i for i, x in enumerate(all_es) if x.get("target") == t]
    else:
        view = list(range(len(all_es)))

    if not view:
        return None, "还没有任何修改记录。"

    k = index if index >= 0 else len(view) + index
    if not (0 <= k < len(view)):
        return None, f"没有第 {index} 条记录（一共 {len(view)} 条）。"

    real = view[k]
    e = all_es[real]
    target_path = Path(e["target"])
    backup = Path(e["backup"]) if e.get("backup") else None

    if not target_path.exists():
        return None, f"存档文件已经不在原位了：{target_path}"
    if backup is None:
        return None, f"这一条没有留下备份，没法撤销：{e['title']}"
    if not backup.exists():
        return None, (f"这一条对应的备份已经被清理掉了：\n    {backup.name}\n"
                      f"  （备份只保留最近 10 个）")

    # 撤销本身也要可撤销：先把【现在】的状态存一份
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = target_path.with_name(f"{target_path.name}.bak-{stamp}")
    n = 1
    while safe.exists():
        safe = target_path.with_name(f"{target_path.name}.bak-{stamp}-{n}")
        n += 1
    shutil.copy2(target_path, safe)

    # 原子替换：先写 .tmp 再 replace，中途崩了不会留半个文件
    tmp = target_path.with_name(target_path.name + ".tmp")
    shutil.copy2(backup, tmp)
    tmp.replace(target_path)

    # 这一条及之后（同一个存档）的记录都作废了 —— 它们描述的是另一个分支。
    # 别的存档的记录原样保留。
    kept = [x for i, x in enumerate(all_es)
            if i < real or x.get("target") != e.get("target")]
    _save(kept)

    return (f"已撤销：{e['time']}  {e['title']}\n"
            f"  存档已回到那次改动【之前】的状态\n"
            f"  撤销前的状态也存了一份：{safe.name}"), None
