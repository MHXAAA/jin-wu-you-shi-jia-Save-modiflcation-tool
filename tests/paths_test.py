#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路径规则测试。

盯的是这样一件事：**用户的桌面上不该冒出 history.json。**
打包成 exe 放在桌面时，如果还按「状态文件跟 exe 走」，
双击一次就多出三个文件 —— 很讨厌。
放在 U 盘、D:\\工具\\ 这类地方时又要保持便携（体积小、状态跟着走）。

所以规则是：桌面 / 下载夹 / 文档 / Program Files 这类地方 → 改用
%LOCALAPPDATA%\\WujinSaveEditor；其他地方 → 状态就在 exe 旁边。
"""
import sys
from pathlib import Path

ED = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ED))

import paths  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}   {extra}")


print("=" * 70)
print("一、哪些目录算「不该弄乱」")
print("=" * 70)
sensitive = [
    Path(r"C:\Users\Administrator\Desktop"),
    Path(r"C:\Users\Administrator\Downloads"),
    Path(r"C:\Users\Administrator\OneDrive"),
    Path(r"C:\Users\Administrator\Documents"),
    Path(r"C:\Program Files\x"),
    Path(r"C:\Program Files (x86)\x"),
    Path(r"C:\Windows\System32"),
]
for d in sensitive:
    check(f"{d}  →  算敏感目录", paths._is_litter_sensitive(d))

print()
print("二、哪些目录可以放状态文件（保持便携）")
print("=" * 70)
fine = [
    Path(r"E:\吾今有世家修改器"),
    Path(r"D:\工具\wujin"),
    Path(r"C:\Temp\wujin"),
    Path(r"C:\Users\Administrator\AppData\Local\Temp\wujin_exetest"),
]
for d in fine:
    check(f"{d}  →  不算敏感", not paths._is_litter_sensitive(d))

print()
print("=" * 70)
print("三、实际解析出来的状态目录")
print("=" * 70)
sd = paths.state_dir()
print(f"  state_dir() = {sd}")
check("开发模式（脚本在工具目录）下就是工具目录本身", sd == ED, f"{sd} != {ED}")
check("状态目录真的可写", paths._writable(sd))
check("state_file() 拼在状态目录里", paths.state_file("x.json").parent == sd)
check("res_file() 拼在资源目录里", paths.res_file("x").parent == paths.res_dir())
check("presets.json 能在资源目录里找到", paths.res_file("presets.json").exists(),
      str(paths.res_file("presets.json")))
check("状态目录不是桌面", sd.name.lower() != "desktop", str(sd))
check("状态目录不是下载夹", sd.name.lower() != "downloads", str(sd))

print()
print("=" * 70)
print(f"结果：{ok} 通过 / {fail} 失败")
print("=" * 70)
sys.exit(1 if fail else 0)
