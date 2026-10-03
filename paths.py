#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路径解析 —— 同时支持「直接跑 .py」和「跑打包出来的 .exe」。

为什么需要这个模块
==================

PyInstaller 的 `--onefile` 会把所有东西塞进一个 exe，运行时解压到一个
临时目录（`sys._MEIPASS`），退出时**整个临时目录被删掉**。

于是「文件放在哪」这件事裂成了两种，混用必出 bug：

  · 只读资源（presets.json、icon.ico）
      打进 exe 里了，路径是 `_MEIPASS/xxx`
      —— 用 `Path(__file__).parent` 拿到的是对的地方

  · 可写状态（last_save_path.txt、history.json）
      绝对【不能】写进 `_MEIPASS`：当前这次运行看着一切正常，
      一退出就被连目录一起删了 —— 下次启动「上次用的存档路径」
      和「修改历史」全部消失，而且不报任何错。
      必须写到 **exe 自己所在的目录**。

这个模块把这两者用 res_dir() / state_dir() 明确分开，
调用方不用再自己拼 `Path(__file__)`，也就不会再踩这个坑。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 没打包时，脚本自己所在目录
_SRC_DIR = Path(__file__).resolve().parent

_frozen = getattr(sys, "frozen", False)

#: 是否跑在打包出来的 exe 里
IS_FROZEN = bool(_frozen)


def res_dir() -> Path:
    """只读资源目录：presets.json、icon.ico 这些打进包里的东西在这。"""
    if IS_FROZEN:
        # PyInstaller 一次性解压目录；onedir 模式下也在 exe 旁边
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return _SRC_DIR


def _writable(d: Path) -> bool:
    """真的试着写一下 —— 只看权限位在 Windows 上不可靠。"""
    try:
        d.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(d), prefix=".wtest", delete=True):
            pass
        return True
    except Exception:
        return False


_state_cache: Path | None = None

#: 不该往里面丢状态文件的目录 —— 用户的桌面 / 下载夹不该冒出 history.json。
#: 放在这些地方时改用 %LOCALAPPDATA%\WujinSaveEditor；
#: 放在 U 盘、D:\工具\ 这类地方时仍然「状态跟 exe 走」，保持便携。
_LITTER_SENSITIVE = ("desktop", "downloads", "onedrive", "documents")


def _is_litter_sensitive(d: Path) -> bool:
    if d.name.lower() in _LITTER_SENSITIVE:
        return True
    # Program Files / Windows 这类系统目录也不该放
    windir = os.environ.get("WINDIR", r"C:\Windows").lower()
    pf = os.environ.get("ProgramFiles", r"C:\Program Files").lower()
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)").lower()
    s = str(d).lower()
    return s.startswith(windir) or s.startswith(pf) or s.startswith(pf86)


def _fallback_dir() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WujinSaveEditor"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_dir() -> Path:
    """可写状态目录：last_save_path.txt、history.json 放这。

    优先级：
      1. exe / 脚本自己所在的目录（便携：拷到 U 盘也能记住上次的存档）
      2. 桌面、下载夹、Program Files 这类地方 → 改用
         %LOCALAPPDATA%\\WujinSaveEditor，别把人家的桌面弄乱
      3. 目录不可写（只读介质、系统目录）→ 同样退到上面那个
    """
    global _state_cache
    if _state_cache is not None:
        return _state_cache

    first = Path(sys.executable).resolve().parent if IS_FROZEN else _SRC_DIR

    if not _is_litter_sensitive(first) and _writable(first):
        _state_cache = first
        return first

    _state_cache = _fallback_dir()
    return _state_cache


def state_file(name: str) -> Path:
    """可写状态文件路径。"""
    return state_dir() / name


def res_file(name: str) -> Path:
    """只读资源文件路径。"""
    return res_dir() / name


def autodetect_all() -> list:
    """在常见位置找出【所有】含 GameData.es3 的文件夹，按可信度排序。

    放在 paths.py 而不是菜单里：图形界面和菜单界面都要用它找存档，
    调用方不用自己再写一份。
    """
    home = Path(os.environ.get("USERPROFILE", r"C:\Users\Default"))
    roots = [
        home / "AppData" / "LocalLow",      # Unity 游戏的正式存档位置，最可信
        home / "Documents",
        home / "AppData" / "Roaming",
        home / "Desktop",
    ]
    found = []
    for root in roots:
        if not root.exists():
            continue
        base = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            if len(Path(dirpath).parts) - base > 6:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if not d.startswith(("$", "."))]
            for fn in filenames:
                if fn.lower() == "gamedata.es3":
                    found.append(Path(dirpath))
    seen, out = set(), []
    for p in found:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out
