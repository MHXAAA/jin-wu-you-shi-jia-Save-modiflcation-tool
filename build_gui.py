#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把图形界面版打包成一个独立的 exe。

用法
----
    python build_gui.py

产物
----
    dist\\吾今有世家存档编辑器.exe

    单个文件，约 13 MB，双击就能用，目标电脑不需要装 Python。

为什么要用这个脚本而不是手敲 PyInstaller 命令
--------------------------------------------
有三个坑，踩过一次就够：

1. **`--add-data` 必须用绝对路径。**
   指定了 `--specpath build` 之后，相对路径是按 spec 文件所在目录算的，
   写在命令行里的 `presets.json` 会找不到，构建直接失败 ——
   而且失败信息出现在刷屏的日志中间，很容易以为「构建成功了」，
   结果 `dist\\` 里静静躺着上一次的旧 exe。

2. **`--onefile` 的运行时会解压到 `%TEMP%\\_MEIxxxxxx`，退出时删掉。**
   所以可写状态（历史记录、上次用的存档路径）绝不能写进 `sys._MEIPASS`，
   否则每次退出都丢，而且一声不吭。见 `paths.py` 里的 `res_dir()` / `state_dir()`。

3. **`--windowed` 和 `--console` 必须分成两个构建。**
   图形界面版不能有控制台黑窗，而控制台版需要 stdout。
   这个脚本只负责图形界面版。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "吾今有世家存档编辑器"
ENTRY = "gui.py"

# 只读资源：打进 exe 里，运行时从 sys._MEIPASS 取（见 paths.py）
DATA_FILES = ["presets.json", "icon.ico"]

# 显式声明：PyInstaller 的静态分析看不到这些延迟导入
HIDDEN = ["paths", "history"]

# 明确排掉，能省下几 MB —— 这些东西图形界面版一个都用不上
EXCLUDE = ["unittest", "pydoc", "lib2to3", "test", "distutils",
           "email", "html", "http", "xmlrpc", "pdb", "doctest"]


def main() -> int:
    if shutil.which("pyinstaller") is None:
        print("找不到 pyinstaller。先装一下：")
        print("    pip install pyinstaller")
        return 1

    missing = [f for f in DATA_FILES if not (HERE / f).exists()]
    if missing:
        print(f"缺少资源文件：{missing}")
        return 1

    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",                    # 不要控制台黑窗
        "--clean",
        "--noconfirm",
        "--noupx",
        "--name", NAME,
        "--icon", str(HERE / "icon.ico"),
        "--distpath", str(HERE / "dist"),
        "--workpath", str(HERE / "build" / "work"),
        "--specpath", str(HERE / "build"),
        "--log-level", "WARN",
    ]
    # ★ 绝对路径：见文件头第 1 条
    for f in DATA_FILES:
        args += ["--add-data", f"{HERE / f};."]
    for m in HIDDEN:
        args += ["--hidden-import", m]
    for m in EXCLUDE:
        args += ["--exclude-module", m]
    args.append(str(HERE / ENTRY))

    print("开始构建图形界面版……（第一次要一两分钟）")
    r = subprocess.run(args, cwd=str(HERE))
    if r.returncode != 0:
        print(f"\n构建失败，退出码 {r.returncode}")
        return r.returncode

    out = HERE / "dist" / f"{NAME}.exe"
    if not out.exists():
        print(f"\n构建命令没报错，但 {out} 不存在 —— 多半是上一条坑，"
              f"检查一下 --add-data 的路径。")
        return 1

    print(f"\n构建完成：{out}")
    print(f"  大小 {out.stat().st_size / 1024 / 1024:.1f} MB")
    print("  双击即可运行，目标电脑不需要装 Python。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
