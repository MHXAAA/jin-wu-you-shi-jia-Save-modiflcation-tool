#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《吾今有世家》存档编辑器 —— 图形界面版。

全部改动都汇聚到同一套引擎（save_editor.py）：
同一份 presets.json、同一套 op、同一条「备份 → 原子替换 → 写后复校 → 记历史」落盘路径。
界面上每个按钮都只是往这套引擎里递一份「待改清单」，真正写文件的那段代码只有一处。

图形界面额外的好处：
  · 改之前一眼看到全部改动清单，确认后才落盘
  · 人物表直接列出每个人的天赋 / 天赋潜力 / 专精 / 熟练度，勾选就能改
  · 存档路径、备份、撤销都是按钮，不用记菜单号
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import history as hist          # noqa: E402
import paths                    # noqa: E402
import save_editor as se        # noqa: E402

APP_TITLE = "《吾今有世家》存档编辑器"
PRESET_FILE = paths.res_file("presets.json")
ITEM_NAME_FILE = paths.res_file("item_names.json")
LAST_PATH_FILE = paths.state_file("last_gui_path.txt")


def load_item_names() -> dict:
    """读取「物品编号 → 名称」对照表。

    存档里 Prop_have 只存数字编号，看着就是 [[\"2\",\"55173235\"], …]，
    根本不知道 2 是粮食还是别的。这张表把编号翻成中文名，
    仓库页才能做成勾选式。

    读不到就返回空表 —— 界面退化成「只能手填编号」，而不是整个程序打不开。
    数据文件缺失、被改坏、编码不对，都不该让用户连界面都进不去。
    """
    try:
        raw = json.loads(ITEM_NAME_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, dict):
        return {}
    out = {}
    for k, v in items.items():
        if str(k).isdigit() and isinstance(v, str) and v.strip():
            out[str(k)] = v.strip()
    return out


ITEM_NAMES = load_item_names()

TALENT_CHOICES = ["（不改）", "无", "文学", "武学", "商业", "艺术"]
TALENT_IDS = {"（不改）": None, "无": 0, "文学": 1, "武学": 2, "商业": 3, "艺术": 4}
TALENT_BY_ID = {v: k for k, v in TALENT_IDS.items() if v is not None}

SKILL_CHOICES = ["（不改）", "自动铺开", "无", "巫", "医", "相", "卜", "媚", "工"]
SKILL_IDS = {"（不改）": None, "自动铺开": se.AUTO_TRAIT, "无": 0,
             "巫": 1, "医": 2, "相": 3, "卜": 4, "媚": 5, "工": 6}
SKILL_BY_ID = {1: "巫", 2: "医", 3: "相", 4: "卜", 5: "媚", 6: "工", 0: "无"}

COLORS = {
    "bg": "#f4f4f6",
    "card": "#ffffff",
    "accent": "#8c2f39",
    "ok": "#1f7a3d",
    "warn": "#a86a00",
    "err": "#b3261e",
}

# 界面上每个按钮会用到哪些预设。名字必须和 presets.json 里的键一字不差 ——
# 曾经这里写成 immortal / clear-bad-status，点下去才弹「没有名为 'immortal' 的预设」。
# 现在启动时先对一遍，测试里也断言一遍，写错名字在打包前后都跑不掉。
REQUIRED_PRESETS = [
    "money", "member-max", "member-immortal", "member-young",
    "member-clear-status", "all-items-max", "add-items", "garrison",
    "retainers-10", "person-traits", "member-all-max", "inventory-cap",
]

# 「一键全改」用的组合。数值一律以 presets.json 为准，这里不覆盖任何参数 ——
# 以前这里自己写死过 copper，配上 only_up 之后一键全改就再也加不了钱。
#
# inventory-cap 是本轮加的：它只把库存上限调高、带 only_up，
# 属于「解决爆仓」的安全项，放进一键全改不会伤到已有数据。
# ⚠ member-all-max【没有】放进来 —— 它会把年龄统一写成 20（包括把幼年成员
#   提到 20 岁），是需求里单独要的一个按钮。塞进「一键全改」会让老用户
#   点一下就把孩子的年龄也改了，所以保持一键全改的语义不变。
ONECLICK = ["money", "member-max", "member-immortal", "member-clear-status",
            "inventory-cap"]


def check_presets(presets: dict) -> list:
    """返回缺失的预设名（空列表 = 全都在）。"""
    return [k for k in REQUIRED_PRESETS if k not in presets]


def load_presets() -> dict:
    return json.loads(Path(PRESET_FILE).read_text(encoding="utf-8"))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1020x740")
        self.minsize(880, 620)
        self.configure(bg=COLORS["bg"])

        self.presets = load_presets()
        missing = check_presets(self.presets)
        if missing:
            # 名字对不上就直接说清楚，别等用户点了按钮才弹「没有名为 xx 的预设」。
            messagebox.showerror(
                APP_TITLE,
                "预设文件 presets.json 不完整，这些预设找不到：\n  "
                + "\n  ".join(missing)
                + f"\n\n预设文件位置：{PRESET_FILE}\n"
                "请确认它就是随程序一起发布的那一份。")
        self.files: list[Path] = []
        self.save_root = None
        self.members: list[dict] = []

        self._build_style()
        self._build_pathbar()
        self._build_notebook()
        self._build_bottom()

        self.after(80, self.autodetect)

    # ------------------------------------------------------------ 外观

    def _build_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("vista")
        except tk.TclError:
            pass
        st.configure("TFrame", background=COLORS["bg"])
        st.configure("Card.TFrame", background=COLORS["card"], relief="flat")
        st.configure("TLabel", background=COLORS["bg"], font=("Microsoft YaHei UI", 10))
        st.configure("Card.TLabel", background=COLORS["card"], font=("Microsoft YaHei UI", 10))
        st.configure("H1.TLabel", background=COLORS["bg"],
                     font=("Microsoft YaHei UI", 13, "bold"), foreground=COLORS["accent"])
        st.configure("H2.TLabel", background=COLORS["card"],
                     font=("Microsoft YaHei UI", 10, "bold"))
        st.configure("Hint.TLabel", background=COLORS["card"],
                     font=("Microsoft YaHei UI", 9), foreground="#666666")
        st.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(10, 5))
        st.configure("Big.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=(14, 9))
        st.configure("Accent.TButton", font=("Microsoft YaHei UI", 11, "bold"),
                     padding=(14, 9))
        st.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10), padding=(16, 8))
        st.configure("Treeview", font=("Microsoft YaHei UI", 9), rowheight=24)
        st.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    # ------------------------------------------------------------ 存档路径栏

    def _build_pathbar(self):
        bar = ttk.Frame(self, padding=(12, 10, 12, 6))
        bar.pack(fill="x")

        ttk.Label(bar, text="存档路径：").pack(side="left")
        self.path_var = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.path_var, font=("Consolas", 9))
        ent.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ent.bind("<Return>", lambda e: self.load_target())

        ttk.Button(bar, text="自动检测", command=self.autodetect).pack(side="left", padx=2)
        ttk.Button(bar, text="浏览…", command=self.browse).pack(side="left", padx=2)
        ttk.Button(bar, text="读取", command=self.load_target).pack(side="left", padx=2)

        self.status_var = tk.StringVar(value="正在找存档…")
        self.status_lbl = ttk.Label(self, textvariable=self.status_var,
                                    font=("Microsoft YaHei UI", 9), background=COLORS["bg"],
                                    wraplength=980, justify="left")
        self.status_lbl.pack(fill="x", padx=14, pady=(0, 6))

    # ------------------------------------------------------------ 选项卡

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self.tab_common = ttk.Frame(self.nb, padding=14)
        self.tab_retain = ttk.Frame(self.nb, padding=14)
        self.tab_member = ttk.Frame(self.nb, padding=14)
        self.tab_store = ttk.Frame(self.nb, padding=14)
        self.tab_tools = ttk.Frame(self.nb, padding=14)
        self.tab_log = ttk.Frame(self.nb, padding=14)

        self.nb.add(self.tab_common, text="常用")
        self.nb.add(self.tab_retain, text="门客")
        self.nb.add(self.tab_member, text="人物与技能")
        self.nb.add(self.tab_store, text="仓库与势力")
        self.nb.add(self.tab_tools, text="工具")
        self.nb.add(self.tab_log, text="改动日志")

        # 切到「仓库与势力」页时顺手把库存上限的现值读出来，
        # 用户一眼就能看到「种类数 > 上限」这个爆仓证据。
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_common()
        self._build_retainers()
        self._build_members()
        self._build_store()
        self._build_tools()

        # 日志页
        self.log_text = tk.Text(self.tab_log, wrap="word", font=("Consolas", 9),
                                bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc",
                                relief="flat", padx=10, pady=8)
        sb = ttk.Scrollbar(self.tab_log, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

    def _on_tab_changed(self, event=None):
        try:
            if self.nb.select() == str(self.tab_store):
                self._refresh_cap_info()
        except Exception:
            pass          # 切页签时读档失败绝不该弹框打断

    def _card(self, parent, title, hint=None):
        """做一张白底卡片，返回内容区 Frame。"""
        outer = ttk.Frame(parent, style="Card.TFrame", padding=12)
        outer.pack(fill="x", pady=(0, 10))
        ttk.Label(outer, text=title, style="H2.TLabel").pack(anchor="w")
        if hint:
            ttk.Label(outer, text=hint, style="Hint.TLabel",
                      wraplength=880, justify="left").pack(anchor="w", pady=(3, 8))
        body = ttk.Frame(outer, style="Card.TFrame")
        body.pack(fill="x")
        return body

    # ------------------------------------------------------------ 常用

    def _build_common(self):
        p = self.tab_common
        ttk.Label(p, text="最常用的几件事", style="H1.TLabel").pack(anchor="w", pady=(0, 8))

        b = self._card(p, "一键全改",
                       "依次做这几件事：铜钱元宝拉满 → 全员属性拉满 "
                       "→ 全员长寿健康易孕 → 清除全员负面状态。\n"
                       "（仓库和兵力在「仓库与势力」页，单独点，免得一次动太多不好排查。）")
        ttk.Button(b, text="★ 一键全改", style="Accent.TButton",
                   command=self.act_oneclick).pack(side="left")

        b = self._card(p, "铜钱与元宝", "默认【只增不减】——你已经比目标值多就跳过，不会把你的钱改少。")
        ttk.Button(b, text="铜钱元宝拉满", command=self.act_money).pack(side="left")

        b = self._card(p, "家族整体强化", "对【所有族人】生效，不是只改家主。")
        for txt, fn in (("全员属性拉满", self.act_member_max),
                        ("全员长寿 + 健康 + 易孕", self.act_immortal),
                        ("全员年轻化（年龄压到 20 上下）", self.act_young),
                        ("清除全员负面状态", self.act_clear_status)):
            ttk.Button(b, text=txt, command=fn).pack(side="left", padx=(0, 6))

        b = self._card(p, "★ 家族成员一键修改（含幼年成员）",
                       "一次作用于【全部族人】，包括还没成年的孩子 —— 幼年成员在存档里就是"
                       "年龄很小、属性只有个位数的那几个。\n"
                       "年龄 → 目标值（双向：孩子会被提到 20 岁，成年人会被压到 20 岁）；"
                       "属性 文/武/商/艺/心情/声誉/魅力/健康/计谋 全部拉满（只升不降）；"
                       "技能 1–6 每人随机分配，天赋潜力一起写满。\n"
                       "刻意不动：天赋类型（那是「你擅长哪一门」，乱改会打乱原有培养方向）、"
                       "第 30 格（实测在每一行都等于年龄，不是体力）、"
                       "以及族人行的「熟练度」格 —— 那一格的位置没有在真机上核对过，"
                       "实测取值只有 0 和 1，而门客那个核对过的熟练度格是完整的 0–100 分布，"
                       "所以默认不写它（想强行写请勾下面的框）。")
        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="年龄：", style="Card.TLabel").pack(side="left")
        self.fam_age = tk.IntVar(value=20)
        ttk.Spinbox(row, from_=0, to=999, textvariable=self.fam_age, width=6).pack(side="left")
        ttk.Label(row, text="  属性值：", style="Card.TLabel").pack(side="left")
        self.fam_value = tk.IntVar(value=100)
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.fam_value, width=6).pack(side="left")
        ttk.Label(row, text="  天赋潜力：", style="Card.TLabel").pack(side="left")
        self.fam_potential = tk.IntVar(value=100)
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.fam_potential,
                    width=6).pack(side="left")
        ttk.Label(row, text="  熟练度：", style="Card.TLabel").pack(side="left")
        self.fam_prof = tk.IntVar(value=100)
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.fam_prof, width=6).pack(side="left")
        ttk.Button(row, text="★ 一键修改全家族", style="Accent.TButton",
                   command=self.act_family_all).pack(side="left", padx=10)

        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x", pady=(6, 0))
        self.fam_force_prof = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="连族人的「熟练度」格也一起写（该格位未经真机核对，"
                                  "实测只有 0/1 两个值，可能不是熟练度 —— 不放心就别勾）",
                        variable=self.fam_force_prof).pack(side="left")

        b = self._card(p, "撤销",
                       "按「修改历史」倒着撤销。撤销前也会先备份当前状态，撤错了还能撤回来。")
        ttk.Button(b, text="↩ 撤销上一次改动", command=self.act_undo).pack(side="left")

    # ------------------------------------------------------------ 门客

    def _build_retainers(self):
        p = self.tab_retain
        ttk.Label(p, text="生成神级门客", style="H1.TLabel").pack(anchor="w", pady=(0, 8))

        b = self._card(p, "批量生成",
                       "四维 999、评分 100、寿命 99。默认天赋和专精【自动铺开】，"
                       "一批人刚好覆盖四种天赋和六种技能（巫医相卜媚工），"
                       "游戏里「需要有【卜】技能的门客」这类功能才用得上。")

        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="数量：", style="Card.TLabel").pack(side="left")
        self.rcount = tk.IntVar(value=10)
        ttk.Spinbox(row, from_=1, to=50, textvariable=self.rcount, width=6).pack(side="left")
        ttk.Label(row, text="   （上限 50，再多存档会暴涨、读档可能超时）",
                  style="Hint.TLabel").pack(side="left")

        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="取名：", style="Card.TLabel").pack(side="left")
        self.rname_mode = tk.StringVar(value="历史谋士")
        ttk.Radiobutton(row, text="历史谋士（诸葛亮、姜子牙…）", value="历史谋士",
                        variable=self.rname_mode).pack(side="left")
        ttk.Radiobutton(row, text="随机（用存档里真实出现过的姓和字）", value="随机",
                        variable=self.rname_mode).pack(side="left", padx=(10, 0))

        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="指定名字：", style="Card.TLabel").pack(side="left")
        self.rnames = tk.StringVar()
        ttk.Entry(row, textvariable=self.rnames, width=52).pack(side="left")
        ttk.Label(row, text=" (可留空；填了就用这些名字，逗号隔开)",
                  style="Hint.TLabel").pack(side="left")

        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 2))
        ttk.Label(row, text="天赋：", style="Card.TLabel").pack(side="left")
        self.rtalent = tk.StringVar(value="自动铺开")
        ttk.Combobox(row, textvariable=self.rtalent, width=12, state="readonly",
                     values=["自动铺开", "无", "文学", "武学", "商业", "艺术"]
                     ).pack(side="left")
        ttk.Label(row, text="  潜力：", style="Card.TLabel").pack(side="left")
        self.rpotential = tk.IntVar(value=100)
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.rpotential, width=6).pack(side="left")
        ttk.Label(row, text="  专精：", style="Card.TLabel").pack(side="left")
        self.rskill = tk.StringVar(value="自动铺开")
        ttk.Combobox(row, textvariable=self.rskill, width=12, state="readonly",
                     values=["自动铺开", "无", "巫", "医", "相", "卜", "媚", "工"]
                     ).pack(side="left")
        ttk.Label(row, text="  熟练度：", style="Card.TLabel").pack(side="left")
        self.rprof = tk.IntVar(value=100)
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.rprof, width=6).pack(side="left")

        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="★ 生成", style="Accent.TButton",
                   command=self.act_retainers).pack(side="left")
        ttk.Label(row, text="   生成后到「人物与技能」页就能看到他们",
                  style="Hint.TLabel").pack(side="left")

    # ------------------------------------------------------------ 人物与技能

    def _build_members(self):
        p = self.tab_member
        top = ttk.Frame(p)
        top.pack(fill="x")
        ttk.Label(top, text="人物与技能", style="H1.TLabel").pack(side="left")
        # 人数单独一个标签。以前是往状态栏那行字上拼，结果把「铜钱/元宝/门客/族人」
        # 那行信息覆盖掉了，而且人数还是刷新前的旧值。
        self.member_count_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.member_count_var,
                  background=COLORS["bg"], font=("Microsoft YaHei UI", 9),
                  foreground="#555555").pack(side="left", padx=10)
        ttk.Button(top, text="刷新列表", command=self.refresh_members).pack(side="right")
        self.mfilter = tk.StringVar(value="全部")
        cb = ttk.Combobox(top, textvariable=self.mfilter, width=10, state="readonly",
                          values=["全部", "门客", "族人"])
        cb.pack(side="right", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_members())

        cols = ("name", "kind", "age", "talent", "potential", "skill", "prof")
        heads = ("姓名", "类型", "年龄", "天赋", "天赋潜力", "专精", "熟练度")
        widths = (110, 60, 60, 90, 90, 80, 80)
        box = ttk.Frame(p)
        box.pack(fill="both", expand=True, pady=(8, 8))
        self.tree = ttk.Treeview(box, columns=cols, show="headings", selectmode="extended")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="center")
        vs = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._pull_selection())

        b = self._card(p, "给选中的成员设置",
                       "先在上面选中一行或多行（按住 Ctrl / Shift 多选），再点下面的按钮。\n"
                       "专精和熟练度是【解耦】的：只写专精会出现「面板显示技能名但功能不生效」，"
                       "两个都要写才真的能用。")

        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="天赋：", style="Card.TLabel").pack(side="left")
        self.etalent = tk.StringVar(value="（不改）")
        ttk.Combobox(row, textvariable=self.etalent, width=10, state="readonly",
                     values=TALENT_CHOICES).pack(side="left")
        ttk.Label(row, text="  潜力：", style="Card.TLabel").pack(side="left")
        self.epotential = tk.StringVar(value="")
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.epotential, width=6).pack(side="left")
        ttk.Label(row, text="  专精：", style="Card.TLabel").pack(side="left")
        self.eskill = tk.StringVar(value="（不改）")
        ttk.Combobox(row, textvariable=self.eskill, width=10, state="readonly",
                     values=SKILL_CHOICES).pack(side="left")
        ttk.Label(row, text="  熟练度：", style="Card.TLabel").pack(side="left")
        self.eprof = tk.StringVar(value="")
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.eprof, width=6).pack(side="left")

        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="应用到选中成员", style="Accent.TButton",
                   command=self.act_set_traits_selected).pack(side="left")
        ttk.Button(row, text="应用到全部门客", command=lambda: self.act_set_traits_all("menke")
                   ).pack(side="left", padx=6)
        ttk.Button(row, text="应用到全部族人", command=lambda: self.act_set_traits_all("member")
                   ).pack(side="left")
        ttk.Button(row, text="★ 家族全员一键修改（含幼年）", style="Accent.TButton",
                   command=self.act_family_all).pack(side="left", padx=(14, 0))

    def _pull_selection(self):
        """选中某行时，把它的当前值填进下面的输入框，方便照着改。"""
        sel = self.tree.selection()
        if len(sel) != 1:
            return
        vals = self.tree.item(sel[0], "values")
        if len(vals) < 7:
            return
        self.etalent.set(vals[3] if vals[3] in TALENT_CHOICES else "（不改）")
        self.epotential.set(vals[4])
        self.eskill.set(vals[5] if vals[5] in SKILL_CHOICES else "（不改）")
        self.eprof.set(vals[6])

    # ------------------------------------------------------------ 仓库与势力

    def _build_store(self):
        p = self.tab_store
        ttk.Label(p, text="仓库与势力", style="H1.TLabel").pack(anchor="w", pady=(0, 8))

        # 勾选器的容器先建好，即使名字表读不到也不会 AttributeError
        self.item_vars = {}
        self.item_boxes = {}
        self._owned = set()

        b = self._card(p, "仓库每种物品拉满",
                       "遍历仓库里的每一种物品，把不足的补到目标值。默认【只补不足】："
                       "本来就已经超过目标值的物品原样不动 —— 真实存档里粮食有 5005 万，"
                       "无脑覆盖会一次砍掉 4000 万。")
        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="目标数量：", style="Card.TLabel").pack(side="left")
        self.item_max = tk.IntVar(value=9999999)
        ttk.Spinbox(row, from_=1, to=999999999, textvariable=self.item_max, width=14).pack(side="left")
        self.item_only_up = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="只补不足（不减少已有的）", variable=self.item_only_up
                        ).pack(side="left", padx=10)
        ttk.Button(row, text="★ 全部拉满", style="Accent.TButton",
                   command=self.act_all_items).pack(side="left", padx=6)

        b = self._card(p, "往仓库加物品（勾选式）",
                       "游戏里的物品都在下面列好了，直接勾要加的，不用再去查编号。"
                       "名称是从游戏程序集里提取的对照表 —— 真实存档里出现过的 116 个编号、"
                       "以及物价表里的 32 个编号，全部能对上。")
        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="搜索：", style="Card.TLabel").pack(side="left")
        self.item_filter = tk.StringVar()
        fe = ttk.Entry(row, textvariable=self.item_filter, width=16)
        fe.pack(side="left")
        fe.bind("<Return>", lambda e: self.filter_items())
        ttk.Button(row, text="筛选", command=self.filter_items).pack(side="left", padx=4)
        ttk.Button(row, text="全选", command=lambda: self.check_items(True)).pack(side="left", padx=2)
        ttk.Button(row, text="全不选", command=lambda: self.check_items(False)).pack(side="left", padx=2)
        ttk.Button(row, text="反选", command=self.invert_items).pack(side="left", padx=2)
        self.only_owned = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="只显示仓库已有的", variable=self.only_owned,
                        command=self.filter_items).pack(side="left", padx=8)
        self.item_sel_var = tk.StringVar(value="已选 0 种")
        ttk.Label(row, textvariable=self.item_sel_var, style="Hint.TLabel"
                  ).pack(side="left", padx=4)

        wrap = ttk.Frame(b, style="Card.TFrame")
        wrap.pack(fill="x", pady=(8, 0))
        self.item_canvas = tk.Canvas(wrap, height=200, highlightthickness=0,
                                     background=COLORS["card"])
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.item_canvas.yview)
        self.item_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.item_canvas.pack(side="left", fill="both", expand=True)
        self.item_inner = ttk.Frame(self.item_canvas, style="Card.TFrame")
        self.item_canvas.create_window((0, 0), window=self.item_inner, anchor="nw")
        self.item_inner.bind("<Configure>", lambda e: self.item_canvas.configure(
            scrollregion=self.item_canvas.bbox("all")))
        for w in (self.item_canvas, self.item_inner):
            w.bind("<MouseWheel>", self._item_wheel)

        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="数量：", style="Card.TLabel").pack(side="left")
        self.item_qty = tk.IntVar(value=9999999)
        ttk.Spinbox(row, from_=1, to=999999999, textvariable=self.item_qty,
                    width=12).pack(side="left")
        self.item_mode = tk.StringVar(value="增加")
        ttk.Combobox(row, textvariable=self.item_mode, width=8, state="readonly",
                     values=["增加", "覆盖"]).pack(side="left", padx=6)
        ttk.Button(row, text="★ 加入仓库", style="Accent.TButton",
                   command=self.act_add_items_selected).pack(side="left", padx=6)
        if ITEM_NAMES:
            ttk.Button(row, text="清空勾选", command=lambda: self.check_items(False)
                       ).pack(side="left")
            self._build_item_boxes()
        else:
            ttk.Label(row, text="⚠ item_names.json 没读到，物品名不可用（请重新打包或补上该文件）",
                      style="Hint.TLabel").pack(side="left", padx=8)

        b = self._card(p, "★ 库存上限（仓库满了、买东西存不进去）",
                       "存档里【没有】叫「库存容量」的字段 —— 游戏是从库房建筑算出来的。"
                       "推断的位置是 FamilyData 第 3 项。证据链：仓库里的物品种类数已经"
                       "超过了这个上限，正好就是「仓库满了、买进来的东西存不下」这个症状；"
                       "另一个候选（府邸第 3 项 = 410）比种类数大、不会满，与症状矛盾，已排除。"
                       "种类数之所以能超过上限，是本工具的「加物品」直接往列表里追加、"
                       "绕过了游戏的入库检查。\n"
                       "带【只增不减】：只会把上限调高，比目标值大的不会被改小。"
                       "改完请进游戏看一眼仓库界面的「库存 (@/$)」有没有跟着变；"
                       "没变就用「撤销上一次改动」退回来。")
        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="上限设为：", style="Card.TLabel").pack(side="left")
        self.inv_cap = tk.IntVar(value=9999)
        ttk.Spinbox(row, from_=1, to=99999999, textvariable=self.inv_cap,
                    width=12).pack(side="left")
        ttk.Button(row, text="★ 提高库存上限", style="Accent.TButton",
                   command=self.act_inventory_cap).pack(side="left", padx=8)
        ttk.Button(row, text="刷新当前值", command=self._refresh_cap_info).pack(side="left")
        self.inv_info = tk.StringVar(value="（打开本页或点「刷新当前值」可读出存档里的现值）")
        ttk.Label(b, textvariable=self.inv_info, style="Hint.TLabel",
                  wraplength=880, justify="left").pack(anchor="w", pady=(6, 0))

        b = self._card(p, "兵力", "禁军兵力与士气（兵力只增不减）。")
        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="兵力：", style="Card.TLabel").pack(side="left")
        self.troops = tk.IntVar(value=999999)
        ttk.Spinbox(row, from_=0, to=99999999, textvariable=self.troops, width=12).pack(side="left")
        ttk.Label(row, text="  士气：", style="Card.TLabel").pack(side="left")
        self.morale = tk.IntVar(value=100)
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.morale, width=6).pack(side="left")
        ttk.Button(row, text="设置", command=self.act_garrison).pack(side="left", padx=8)

    # ------------------------------------------------------------ 工具

    def _build_tools(self):
        p = self.tab_tools
        ttk.Label(p, text="工具", style="H1.TLabel").pack(anchor="w", pady=(0, 8))

        b = self._card(p, "存档信息")
        ttk.Button(b, text="查看存档结构（顶层字段）", command=self.act_show_keys).pack(side="left")
        ttk.Button(b, text="查看都有哪些文件", command=self.act_show_files).pack(side="left", padx=6)
        ttk.Button(b, text="打开存档文件夹", command=self.act_open_folder).pack(side="left")

        b = self._card(p, "自定义修改",
                       "格式「字段路径 = 新值」，例如 CGNum.value[0] = 999999999。\n"
                       "字符串槽位永远写字符串（这是本工具最关键的安全阀），不会把数字写进文字栏。")
        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(fill="x")
        self.cpath = tk.StringVar()
        ttk.Entry(row, textvariable=self.cpath, width=38).pack(side="left")
        ttk.Label(row, text=" = ", style="Card.TLabel").pack(side="left")
        self.cvalue = tk.StringVar()
        ttk.Entry(row, textvariable=self.cvalue, width=22).pack(side="left")
        ttk.Button(row, text="改它", command=self.act_custom).pack(side="left", padx=8)

        b = self._card(p, "备份")
        ttk.Button(b, text="只备份，什么都不改", command=self.act_backup_only).pack(side="left")
        ttk.Label(b, text="   备份文件是 GameData.es3.bak-日期时间，和存档放在一起",
                  style="Hint.TLabel").pack(side="left")

    # ------------------------------------------------------------ 底栏

    def _build_bottom(self):
        bar = ttk.Frame(self, padding=(12, 6, 12, 12))
        bar.pack(fill="x")
        self.hint = ttk.Label(bar, text="所有操作都会先备份；改完可以直接在「改动日志」里看清单。",
                              font=("Microsoft YaHei UI", 9), background=COLORS["bg"])
        self.hint.pack(side="left")
        ttk.Button(bar, text="退出", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="撤销上一次改动", command=self.act_undo).pack(side="right", padx=6)

    # ============================================================ 存档定位

    def autodetect(self):
        roots = paths.autodetect_all()
        if not roots:
            self.set_status("没自动找到存档，请点「浏览…」手动选存档文件夹。", "warn")
            return
        # 优先 LocalLow 里那个（Unity 正式存档位置）
        best = None
        for r in roots:
            if "LocalLow" in str(r):
                best = r
                break
        best = best or roots[0]
        self.path_var.set(str(best))
        self.load_target()

    def browse(self):
        d = filedialog.askdirectory(title="选择存档文件夹（里面有 GameData.es3）")
        if d:
            self.path_var.set(d)
            self.load_target()

    def load_target(self):
        raw = self.path_var.get().strip().strip('"')
        if not raw:
            return
        p = Path(raw)
        if not p.exists():
            self.set_status(f"路径不存在：{p}", "err")
            return
        try:
            files = se.find_gamedata(p)
        except Exception as e:
            self.set_status(f"找存档出错：{e}", "err")
            return
        if not files:
            self.set_status(f"这个文件夹里没找到 GameData.es3：{p}", "err")
            return
        self.files = files
        self.save_root = files[0].parent
        try:
            LAST_PATH_FILE.write_text(str(self.save_root), encoding="utf-8", newline="\n")
        except OSError:
            pass
        self._refresh_status()
        self.refresh_members()

    def _refresh_status(self):
        try:
            d = se.Save(self.files[0]).data
            copper = se.get_path(d, "CGNum.value[0]")
            yuanbao = se.get_path(d, "CGNum.value[1]")
            nmenke = len((d.get("MenKe_Now") or {}).get("value") or [])
            nmember = len((d.get("Member_now") or {}).get("value") or [])
            ver = se.get_path(d, "VersionID.value")
        except Exception as e:
            self.set_status(f"读不出存档内容：{e}", "err")
            return
        files_note = "" if len(self.files) == 1 else f"（这个目录下有 {len(self.files)} 个 gamedata，会一起改）"
        self.set_status(
            f"已载入：{self.save_root} {files_note}\n"
            f"铜钱 {copper}   元宝 {yuanbao}   门客 {nmenke} 人   族人 {nmember} 人   版本 {ver}",
            "ok")

    def set_status(self, text, kind="ok"):
        self.status_var.set(text)
        color = {"ok": COLORS["ok"], "warn": COLORS["warn"], "err": COLORS["err"]}.get(kind, "#333")
        self.status_lbl.configure(foreground=color)

    def _need_save(self) -> bool:
        if not self.files:
            messagebox.showwarning(APP_TITLE, "还没选存档。先点「自动检测」或「浏览…」。")
            return False
        return True

    # ============================================================ 落盘（唯一入口）

    def apply(self, jobs, title, confirm=True):
        """所有写操作的唯一出口。

        先在内存里 dry-run 出清单摆给用户看，确认后才真跑；
        真跑时每个文件只备份一次，写后立刻复校 JSON 合法性，最后记历史。
        """
        if not self._need_save():
            return 0

        # ---- 1. 预览 ----
        preview = []
        try:
            sample = se.Save(self.files[0])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                preview = se.run_jobs(sample, jobs, self.presets, dry=True)
            noise = buf.getvalue().strip()
        except Exception as e:
            self.log(f"[出错] {title}\n{e}\n{traceback.format_exc()}")
            messagebox.showerror(APP_TITLE, f"预览时就出错了：\n{e}")
            return 0

        if noise:
            self.log(noise)

        if not preview:
            self.log(f"[{title}] 没有需要改动的内容 —— 可能已经是这些值了。")
            self.set_status("没有需要改动的内容（可能已经是这些值了）。", "warn")
            self.nb.select(self.tab_log)
            return 0

        self.log("=" * 70)
        self.log(f"{title}")
        self.log("=" * 70)
        self.log(f"目标：{self.save_root}")
        self.log(f"预览（第 1 个文件）：{len(preview)} 处改动")
        for c in preview[:40]:
            self.log("  " + str(c).replace("\n", "\n  "))
        if len(preview) > 40:
            self.log(f"  …… 另有 {len(preview) - 40} 处")
        self.nb.select(self.tab_log)

        if confirm and not messagebox.askyesno(
                APP_TITLE, f"{title}\n\n共 {len(preview)} 处改动。\n确定写入吗？\n\n"
                           f"（会先自动备份成 GameData.es3.bak-日期时间）"):
            self.log("  已取消，什么都没改。")
            return 0

        # ---- 2. 真跑 ----
        done = 0
        applied_all = []
        bak = None
        for f in self.files:
            try:
                s = se.Save(f)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    applied = se.run_jobs(s, jobs, self.presets, dry=False)
                if not applied:
                    continue
                bak = s.write(backup=True)
                chk = se.Save(f)                       # 写后复校
                if not isinstance(chk.data, dict):
                    raise RuntimeError("写入后校验失败：文件不再是 JSON 对象")
                se.record_history(s, title, applied, bak)
                applied_all += applied
                done += len(applied)
            except Exception as e:
                self.log(f"[失败] {f.name}: {e}")
                messagebox.showerror(APP_TITLE, f"{f.name} 写失败：\n{e}")

        if done:
            self.log(f"\n[完成] 共修改 {done} 处。备份：{bak.name if bak else '（无）'}")
            self.log("       进游戏看效果；不满意点右下角「撤销上一次改动」。")
            self.set_status(f"已修改 {done} 处。备份 {bak.name if bak else ''}", "ok")
            self.refresh_members()
        return done

    # ============================================================ 常用动作

    def act_oneclick(self):
        # 用上面那一份组合，不在这里另写一遍参数
        self.apply([(k, {}) for k in ONECLICK], "一键全改")

    def act_money(self):
        self.apply([("money", {})], "铜钱元宝拉满")

    def act_member_max(self):
        self.apply([("member-max", {})], "全员属性拉满")

    def act_immortal(self):
        self.apply([("member-immortal", {})], "全员长寿 + 健康 + 易孕")

    def act_young(self):
        self.apply([("member-young", {})], "全员年轻化")

    def act_clear_status(self):
        self.apply([("member-clear-status", {})], "清除负面状态")

    def act_undo(self):
        if not self._need_save():
            return
        try:
            # target 必须是【文件】路径：record_history 存的是 save.path，
            # 传目录进去会一条都匹配不上（这里传的也是 FILES[0]）。
            msg, err = hist.undo(target=str(self.files[0]))
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"撤销失败：\n{e}")
            return
        if err:
            self.log(f"[撤销] {err}")
            messagebox.showwarning(APP_TITLE, str(err))
            return
        self.log(f"[撤销] {msg}")
        messagebox.showinfo(APP_TITLE, str(msg))
        self._refresh_status()
        self.refresh_members()

    # ============================================================ 门客

    def act_retainers(self):
        mode = "history" if self.rname_mode.get() == "历史谋士" else "random"
        tname = self.rtalent.get()
        sname = self.rskill.get()
        ov = {
            "count": self.rcount.get(),
            "names": self.rnames.get(),
            "name_mode": mode,
            "talent": "auto" if tname == "自动铺开" else ("" if tname == "（不改）" else str(TALENT_IDS[tname])),
            "potential": self.rpotential.get(),
            "skill": "auto" if sname == "自动铺开" else ("" if sname == "（不改）" else str(SKILL_IDS[sname])),
            "proficiency": self.rprof.get(),
        }
        self.apply([("retainers-10", ov)], f"生成 {ov['count']} 个神级门客")

    # ============================================================ 人物与技能

    def refresh_members(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        if not self.files:
            return
        try:
            d = se.Save(self.files[0]).data
        except Exception as e:
            self.log(f"[读成员表失败] {e}")
            return
        self.members = se.list_members(d)
        want = self.mfilter.get()
        n = 0
        for m in self.members:
            if want != "全部" and m["kind"] != want:
                continue
            self.tree.insert("", "end", values=(
                m["name"], m["kind"], m["age"],
                TALENT_BY_ID.get(int(m["talent"] or 0), m["talent"]),
                m["potential"],
                SKILL_BY_ID.get(int(m["skill"] or 0), m["skill"]),
                m["proficiency"]))
            n += 1
        nmenke = sum(1 for m in self.members if m["kind"] == "门客")
        nmember = len(self.members) - nmenke
        self.member_count_var.set(
            f"共 {len(self.members)} 人（门客 {nmenke} / 族人 {nmember}）"
            + (f"　当前显示 {n} 行" if want != "全部" else ""))

    def _selected_names(self):
        out = []
        for iid in self.tree.selection():
            v = self.tree.item(iid, "values")
            if v:
                out.append(v[0])
        return out

    def _trait_overrides(self):
        t = self.etalent.get()
        s = self.eskill.get()
        return {
            "talent": "" if t == "（不改）" else str(TALENT_IDS[t]),
            "potential": self.epotential.get().strip(),
            "skill": "" if s == "（不改）" else str(SKILL_IDS[s]),
            "proficiency": self.eprof.get().strip(),
        }

    def act_set_traits_selected(self):
        names = self._selected_names()
        if not names:
            messagebox.showwarning(APP_TITLE, "先在上面选中至少一行。")
            return
        ov = self._trait_overrides()
        ov["scope"] = "all"
        ov["names"] = ",".join(names)
        self.apply([("person-traits", ov)], f"给 {len(names)} 个成员设天赋/专精")

    def act_set_traits_all(self, scope):
        ov = self._trait_overrides()
        ov["scope"] = scope
        ov["names"] = ""
        label = "全部门客" if scope == "menke" else "全部族人"
        self.apply([("person-traits", ov)], f"给{label}设天赋/专精")

    # ============================================================ 仓库与势力

    def act_all_items(self):
        self.apply([("all-items-max", {"value": self.item_max.get(),
                                       "only_up": 1 if self.item_only_up.get() else 0})],
                   "仓库每种物品拉满")

    def act_add_items(self):
        spec = self.items_spec.get().strip()
        if not spec:
            messagebox.showwarning(APP_TITLE, "先填要加的物品，比如 169:10, 170:5")
            return
        mode = "set" if self.item_mode.get() == "覆盖" else "add"
        self.apply([("add-items", {"items": spec, "mode": mode})],
                   f"往仓库加物品（{'覆盖' if mode == 'set' else '累加'}）")

    # ---- 物品勾选器 ----------------------------------------------------

    ITEM_COLS = 4

    def _build_item_boxes(self):
        """把物品名表铺成勾选框。

        285 个勾选框一次性建好、之后只做 grid/grid_remove 显隐，
        不在每次筛选时重建控件 —— 重建会明显卡顿，而且勾选状态会丢。
        """
        self.item_vars = {}
        self.item_boxes = {}
        self._owned = set()
        for n, iid in enumerate(sorted(ITEM_NAMES, key=int)):
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(self.item_inner, text=f"{iid}  {ITEM_NAMES[iid]}",
                                 variable=var, command=self._refresh_item_count)
            cb.grid(row=n // self.ITEM_COLS, column=n % self.ITEM_COLS,
                    sticky="w", padx=(0, 12))
            cb.bind("<MouseWheel>", self._item_wheel)
            self.item_vars[iid] = var
            self.item_boxes[iid] = cb

    def _item_wheel(self, event):
        self.item_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _owned_ids(self) -> set:
        """当前存档仓库里已有的物品编号（用于「只显示已有的」和标记）。"""
        if not self.files:
            return set()
        try:
            data = se.Save(self.files[0]).data
            rows = se.get_path(data, "Prop_have.value")
        except Exception:
            return set()
        return {str(r[0]) for r in rows if isinstance(r, list) and r}

    def filter_items(self):
        """按关键词 / 是否已有 显示或隐藏勾选框，并把可见的重新排布紧实。"""
        if not getattr(self, "item_boxes", None):
            return
        kw = self.item_filter.get().strip()
        want_owned = self.only_owned.get()
        if want_owned:
            self._owned = self._owned_ids()
        shown = 0
        for iid in sorted(ITEM_NAMES, key=int):
            cb = self.item_boxes[iid]
            ok = (not kw) or (kw in ITEM_NAMES[iid]) or (kw in iid)
            if ok and want_owned and iid not in self._owned:
                ok = False
            if ok:
                cb.grid(row=shown // self.ITEM_COLS, column=shown % self.ITEM_COLS,
                        sticky="w", padx=(0, 12))
                shown += 1
            else:
                cb.grid_remove()
        self.item_canvas.configure(scrollregion=self.item_canvas.bbox("all"))
        self.item_canvas.yview_moveto(0)
        self._refresh_item_count()

    def _visible_ids(self) -> list:
        return [iid for iid, cb in self.item_boxes.items() if cb.winfo_manager()]

    def check_items(self, state: bool):
        """全选 / 全不选。作用于【当前可见】的那些 —— 先搜索再全选，
        就能一次勾上「所有酒」这类一组物品，而不是把 285 种全勾上。"""
        if not getattr(self, "item_boxes", None):
            return
        for iid in self._visible_ids():
            self.item_vars[iid].set(state)
        self._refresh_item_count()

    def invert_items(self):
        if not getattr(self, "item_boxes", None):
            return
        for iid in self._visible_ids():
            self.item_vars[iid].set(not self.item_vars[iid].get())
        self._refresh_item_count()

    def _refresh_item_count(self):
        if not getattr(self, "item_vars", None):
            return
        n = sum(1 for v in self.item_vars.values() if v.get())
        total = len(self.item_vars)
        self.item_sel_var.set(f"已选 {n} / {total} 种" + ("" if n else ""))

    def act_add_items_selected(self):
        if not getattr(self, "item_vars", None):
            messagebox.showwarning(APP_TITLE, "物品名表没读到，无法勾选。")
            return
        picked = [iid for iid, v in self.item_vars.items() if v.get()]
        if not picked:
            messagebox.showwarning(APP_TITLE, "还没勾选任何物品。先在上面勾几个，或点「全选」。")
            return
        try:
            qty = int(self.item_qty.get())
        except Exception:
            messagebox.showwarning(APP_TITLE, "数量要填一个整数。")
            return
        spec = ",".join(f"{iid}:{qty}" for iid in sorted(picked, key=int))
        mode = "set" if self.item_mode.get() == "覆盖" else "add"
        # 日志里别把 285 项全打出来，只报个数和几个例子
        head = "、".join(f"{iid} {ITEM_NAMES.get(iid, '')}" for iid in sorted(picked, key=int)[:6])
        more = f" 等 {len(picked)} 种" if len(picked) > 6 else ""
        self.apply([("add-items", {"items": spec, "mode": mode})],
                   f"往仓库加 {len(picked)} 种物品（{'覆盖' if mode == 'set' else '累加'}）"
                   f"：{head}{more} × {qty}")

    # ---- 家族全员一键修改 ----------------------------------------------

    def act_family_all(self):
        self.apply([("member-all-max", {"age": self.fam_age.get(),
                                        "value": self.fam_value.get(),
                                        "potential": self.fam_potential.get(),
                                        "proficiency": self.fam_prof.get(),
                                        "force_prof": 1 if self.fam_force_prof.get() else 0,
                                        "talent_mode": "keep",
                                        "skill_mode": "random"})],
                   "★ 家族全员一键修改（含幼年成员）")

    def act_inventory_cap(self):
        self.apply([("inventory-cap", {"cap": self.inv_cap.get()})], "提高库存上限")

    def act_garrison(self):
        self.apply([("garrison", {"troops": self.troops.get(), "morale": self.morale.get()})],
                   "设置禁军兵力")

    def _refresh_cap_info(self):
        """把存档里的库存上限现值和仓库种类数读出来摆在一起。

        这两个数字并排一看就知道推断对不对：种类数 > 上限 = 仓库满了，
        正是「买东西存不进去」的症状。
        """
        if not self.files:
            self.inv_info.set("还没选存档。先点「自动检测」或「浏览…」。")
            return
        try:
            data = se.Save(self.files[0]).data
            # ⚠ 存档里这一格是【字符串】（'80'），直接和 int 比会抛
            #   TypeError: '>' not supported between 'int' and 'str'。
            #   显示按原样、比较用转出来的数字。
            cap_raw = se.get_path(data, "FamilyData.value[2]")
            try:
                cap = int(float(cap_raw))
            except (TypeError, ValueError):
                cap = None
            rows = se.get_path(data, "Prop_have.value")
            kinds = len(rows)
            total = 0
            for r in rows:
                if isinstance(r, list) and len(r) >= 2:
                    try:
                        total += int(float(r[1]))
                    except (TypeError, ValueError):
                        pass
            full = ""
            if cap is not None:
                full = (" —— 种类数已经超过上限，所以买进来的东西存不下"
                        if kinds > cap else " —— 还没超上限")
            self.inv_info.set(
                f"存档现值：库存上限 = {cap_raw}，仓库里有 {kinds} 种物品"
                f"（合计 {total:,} 件）{full}")
        except Exception as e:
            self.inv_info.set(f"读不出来：{type(e).__name__}: {e}")

    # ============================================================ 工具

    def act_show_keys(self):
        if not self._need_save():
            return
        buf = io.StringIO()

        class _Args:                        # cmd_keys 只用到 target
            target = str(self.files[0])

        with contextlib.redirect_stdout(buf):
            se.cmd_keys(_Args)
        self.log(buf.getvalue())
        self.nb.select(self.tab_log)

    def act_show_files(self):
        if not self._need_save():
            return
        lines = [f"存档目录：{self.save_root}", ""]
        for f in sorted(self.save_root.rglob("*.es3")):
            tag = "  ← 本工具会改" if f in self.files else ""
            lines.append(f"  {f.stat().st_size:>10,}  {f.name}{tag}")
        self.log("\n".join(lines))
        self.nb.select(self.tab_log)

    def act_open_folder(self):
        if not self._need_save():
            return
        try:
            import subprocess
            subprocess.Popen(["explorer", str(self.save_root)])
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))

    def act_custom(self):
        path, val = self.cpath.get().strip(), self.cvalue.get()
        if not path:
            messagebox.showwarning(APP_TITLE, "先填字段路径，例如 CGNum.value[0]")
            return
        self.apply([(se.CUSTOM_JOB, {"path": path, "value": val})], f"自定义修改 {path}")

    def act_backup_only(self):
        if not self._need_save():
            return
        import shutil
        made = []
        for f in self.files:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            bak = f.with_name(f.name + f".bak-{stamp}")
            try:
                shutil.copy2(f, bak)
                made.append(bak)
            except OSError as e:
                self.log(f"[备份失败] {f.name}: {e}")
        if made:
            for b in made:
                self.log(f"已备份：{b}")
            messagebox.showinfo(APP_TITLE, "已备份：\n" + "\n".join(str(b) for b in made))
        else:
            messagebox.showerror(APP_TITLE, "备份失败，详见「改动日志」。")

    # ============================================================ 日志

    def log(self, text):
        self.log_text.insert("end", str(text) + "\n")
        self.log_text.see("end")


def main(argv=None):
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
