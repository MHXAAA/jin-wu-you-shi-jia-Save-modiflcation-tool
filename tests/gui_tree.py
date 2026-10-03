#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把图形界面的控件树导成文字，用来核对界面到底长什么样。

本会话的模型看不了截图，所以改成「把界面读出来」：
每个页签里有哪些标签、按钮，文字是什么，一目了然。
顺便也能发现控件漏了、文字写错了这类问题。
"""
import os
import sys
import tempfile
from pathlib import Path

ED = Path(__file__).resolve().parent.parent      # 本脚本在 tests\ 下，上一层才是工具目录
sys.path.insert(0, str(ED))
os.environ.setdefault("WUJIN_HISTORY", str(Path(tempfile.gettempdir()) / "wujin_tree.json"))

import gui as G          # noqa: E402
import tkinter as tk     # noqa: E402

G.messagebox.showerror = lambda *a, **k: None

app = G.App()


def text_of(w):
    try:
        t = w.cget("text")
        return str(t)
    except Exception:
        return ""


def walk(w, depth=0, out=None):
    if out is None:
        out = []
    for child in w.winfo_children():
        if isinstance(child, tk.ttk.Notebook):
            out.append(("  " * depth) + f"[选项卡容器] {len(child.tabs())} 个页签")
            for tab_id in child.tabs():
                name = child.tab(tab_id, "text")
                out.append(("  " * (depth + 1)) + f"── 页签「{name}」")
                walk(child.nametowidget(tab_id), depth + 2, out)
            continue
        cls = child.winfo_class()
        txt = text_of(child)
        if cls in ("TButton",):
            out.append(("  " * depth) + f"[按钮] {txt}")
        elif cls == "Button":
            out.append(("  " * depth) + f"[按钮] {txt}")
        elif cls in ("TLabel", "Label"):
            if txt:
                out.append(("  " * depth) + f"  {txt}")
        elif cls in ("TEntry", "Entry"):
            out.append(("  " * depth) + "  [输入框]")
        elif cls == "TSpinbox":
            out.append(("  " * depth) + f"  [数字框] {txt}")
        elif cls == "TCombobox":
            out.append(("  " * depth) + "  [下拉框]")
        elif cls in ("TRadiobutton", "RadioButton"):
            out.append(("  " * depth) + f"  ( ) {txt}")
        elif cls in ("TCheckbutton", "Checkbutton"):
            out.append(("  " * depth) + f"  [√] {txt}")
        elif cls == "Treeview":
            cols = child.cget("columns")
            heads = [child.heading(c, "text") for c in cols]
            out.append(("  " * depth) + f"  [表格] 列：{' | '.join(heads)}")
        elif cls == "Text":
            out.append(("  " * depth) + "  [日志区]")
        else:
            walk(child, depth, out)
    return out


print("=" * 78)
print(f"  窗口标题：{app.title()}")
print(f"  窗口尺寸：{app.geometry()}   最小尺寸：{app.minsize()}")
print("=" * 78)
app.autodetect()
print(f"  状态栏：{app.status_var.get()}")
print(f"  检测到的存档：{app.path_var.get()}")
print()
for line in walk(app):
    print(line)

print()
print("=" * 78)
print("  成员表实际内容（前 6 行）")
print("=" * 78)
app.path_var.set(str(ED.parent / "0"))
app.load_target()
app.refresh_members()
print("  " + " | ".join(f"{c:^8}" for c in ("姓名", "类型", "年龄", "天赋", "潜力", "专精", "熟练")))
for iid in app.tree.get_children()[:6]:
    print("  " + " | ".join(f"{str(v):^8}" for v in app.tree.item(iid, "values")))
print(f"  …… 共 {len(app.tree.get_children())} 行")

print()
print("=" * 78)
print("  下拉框里的可选项")
print("=" * 78)
print(f"  天赋：{G.TALENT_CHOICES}")
print(f"  专精：{G.SKILL_CHOICES}")
print(f"  门客天赋：自动铺开 / 无 / 文学 / 武学 / 商业 / 艺术")
print(f"  门客专精：自动铺开 / 无 / 巫 / 医 / 相 / 卜 / 媚 / 工")

app.destroy()
print()
print("界面导出完成。")
