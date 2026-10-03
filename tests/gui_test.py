#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""图形界面测试。

在 %TEMP% 下建一份存档副本当靶子，真建窗口、真跑动作，
把 messagebox 换成自动确认，验证：
  · 界面能建起来、存档能载入、成员表能列出来
  · 每个动作都走同一套落盘逻辑（备份 + 原子写 + 写后复校 + 记历史）
  · 撤销能真的撤回来
  · 引擎报错时界面不崩，只弹错误框

⚠ 全程只动 %TEMP% 下的副本，绝不碰 AppData\LocalLow 里的真存档。
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

ED = Path(r"C:\Users\Administrator\Documents\deepseek-harness\default-workspace\wujin-save-editor")
WS = ED.parent
sys.path.insert(0, str(ED))

# 历史写到临时位置，别污染真历史
os.environ["WUJIN_HISTORY"] = str(Path(tempfile.gettempdir()) / "wujin_gui_hist.json")

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}   {extra}")


T = Path(tempfile.gettempdir()) / "wujin_guitest"
if T.exists():
    shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
SRC = WS / "0" / "GameData.es3"
shutil.copy2(SRC, T / "GameData.es3")
TARGET = T / "GameData.es3"

import gui as G          # noqa: E402
import history as hist   # noqa: E402
import save_editor as se  # noqa: E402

# 把弹窗全部换成自动应答，测试才能无人值守跑完
DIALOGS = []
STATES = {"yes": True}


def rec(kind):
    def f(title=None, message=None, **kw):
        DIALOGS.append((kind, str(message)[:80] if message else ""))
        return STATES["yes"]
    return f


G.messagebox.askyesno = rec("askyesno")
G.messagebox.showinfo = rec("showinfo")
G.messagebox.showwarning = rec("showwarning")
G.messagebox.showerror = rec("showerror")

print("=" * 76)
print("一、界面能建起来")
print("=" * 76)
app = G.App()
check("窗口创建成功", app.winfo_exists() == 1)
check("六个选项卡", len(app.nb.tabs()) == 6)
check("预设加载了", len(app.presets) > 10)
app.autodetect()          # 正常运行时由 after(80) 触发；测试里不等它，直接调
check("自动检测到了存档路径", bool(app.path_var.get()), app.path_var.get())

print()
print("=" * 76)
print("二、载入副本存档")
print("=" * 76)
app.path_var.set(str(T))
app.load_target()
check("识别到 1 个 gamedata", len(app.files) == 1, str(app.files))
check("save_root 正确", app.save_root == T)
check("状态栏显示已载入", "已载入" in app.status_var.get(), app.status_var.get()[:60])

print()
print("=" * 76)
print("三、成员表")
print("=" * 76)
app.refresh_members()
rows = app.tree.get_children()
check("成员表有行", len(rows) > 0, f"{len(rows)} 行")
check("门客+族人都列出来了", len(app.members) >= len(rows))
first = app.tree.item(rows[0], "values")
print(f"  第 1 行：{first}")
check("列了 7 列", len(first) == 7)
app.mfilter.set("门客")
app.refresh_members()
n_mk = len(app.tree.get_children())
app.mfilter.set("族人")
app.refresh_members()
n_mb = len(app.tree.get_children())
app.mfilter.set("全部")
app.refresh_members()
check("按类型筛选有效", n_mk > 0 and n_mb > 0 and n_mk + n_mb == len(app.members),
      f"门客{n_mk} 族人{n_mb} 共{len(app.members)}")

# 状态栏那行「铜钱/元宝/门客/族人/版本」不能被刷新成员表搞丢 ——
# 以前 refresh_members() 往状态栏拼人数，把第二行整行覆盖掉了，人数还是旧的。
status_before = app.status_var.get()
check("状态栏有存档信息（含铜钱和各人数）",
      "铜钱" in status_before and "族人" in status_before, status_before[:70])
app.refresh_members()
check("★ 刷新成员表不会覆盖状态栏的存档信息", app.status_var.get() == status_before,
      f"改成了：{app.status_var.get()[:70]}")
check("人数单独显示，且和实际行数对得上",
      str(len(app.members)) in app.member_count_var.get(), app.member_count_var.get())

print()
print("=" * 76)
print("四、改铜钱（走完整的落盘路径）")
print("=" * 76)
before_copper = se.get_path(se.Save(TARGET).data, "CGNum.value[0]")
ORIG_COPPER = before_copper          # 留个底，最后一节撤销要拿它对
n_bak0 = len(list(T.glob("*.bak-*")))
DIALOGS.clear()
app.act_money()
after_copper = se.get_path(se.Save(TARGET).data, "CGNum.value[0]")
n_bak1 = len(list(T.glob("*.bak-*")))
check("铜钱被改了", str(after_copper) != str(before_copper), f"{before_copper} → {after_copper}")
check("新产生了备份", n_bak1 == n_bak0 + 1, f"{n_bak0} → {n_bak1}")
check("改完仍是合法 JSON", isinstance(se.Save(TARGET).data, dict))
check("弹了确认框", any(k == "askyesno" for k, _ in DIALOGS), str(DIALOGS))
check("没有错误框", not any(k == "showerror" for k, _ in DIALOGS), str(DIALOGS))
check("日志里有预览清单", "预览" in app.log_text.get("1.0", "end"))

print()
print("=" * 76)
print("五、生成神级门客（带天赋 + 专精 auto 铺开）")
print("=" * 76)
n0 = len(se.get_path(se.Save(TARGET).data, "MenKe_Now.value"))
app.rcount.set(6)
app.rnames.set("甲一,乙二,丙三,丁四,戊五,己六")
app.rname_mode.set("随机")
DIALOGS.clear()
app.act_retainers()
d = se.Save(TARGET).data
rows2 = se.get_path(d, "MenKe_Now.value")
check("门客多了 6 个", len(rows2) == n0 + 6, f"{n0} → {len(rows2)}")
new6 = rows2[n0:]
sk = [str(r[2]).split("|")[6] for r in new6]
pr = [str(r[16]) for r in new6]
ta = [str(r[2]).split("|")[2] for r in new6]
po = [str(r[2]).split("|")[3] for r in new6]
check("专精覆盖全部六种技能", sorted(set(sk)) == ["1", "2", "3", "4", "5", "6"], str(sk))
check("熟练度都是 100", all(x == "100" for x in pr), str(pr))
check("天赋都在 1–4", all(x in ("1", "2", "3", "4") for x in ta), str(ta))
check("天赋潜力都是 100", all(x == "100" for x in po), str(po))
for r in new6:
    se.menke_validate_row(r)
check("新门客都通过 22 格结构校验", True)
check("没弹错误框", not any(k == "showerror" for k, _ in DIALOGS), str(DIALOGS))
app.refresh_members()
check("刷新后成员表变多了", len(app.members) == 15 + 41 + 6, f"{len(app.members)}")

print()
print("=" * 76)
print("六、给选中成员设天赋/专精")
print("=" * 76)
app.refresh_members()
iids = app.tree.get_children()[:3]
app.tree.selection_set(iids)
names = app._selected_names()
check("选到了 3 个人", len(names) == 3, str(names))
app.etalent.set("武学")
app.epotential.set("88")
app.eskill.set("卜")
app.eprof.set("100")
DIALOGS.clear()
app.act_set_traits_selected()
d = se.Save(TARGET).data
seen = 0
for r in se.get_path(d, "MenKe_Now.value") + se.get_path(d, "Member_now.value"):
    seg = str(r[2] if len(r) == 22 else r[4]).split("|")
    if seg[0] in names:
        seen += 1
        if not (seg[2] == "2" and seg[3] == "88" and seg[6] == "4"):
            check(f"{seg[0]} 天赋/专精写对", False, str(seg))
            break
else:
    check("选中的人天赋=武学(2) 潜力=88 专精=卜(4)", seen == 3, f"命中 {seen} 人")
check("没弹错误框", not any(k == "showerror" for k, _ in DIALOGS), str(DIALOGS))

print()
print("=" * 76)
print("七、撤销（历史是钱 → 生成门客 → 改天赋，要能一条条倒着撤）")
print("=" * 76)


def seg_of(name):
    d = se.Save(TARGET).data
    for r in se.get_path(d, "MenKe_Now.value") + se.get_path(d, "Member_now.value"):
        seg = str(r[2] if len(r) == 22 else r[4]).split("|")
        if seg[0] == name:
            return seg
    return None


def menke_count():
    return len(se.get_path(se.Save(TARGET).data, "MenKe_Now.value"))


DIALOGS.clear()
app.act_undo()                                   # 撤掉「改天赋」
seg = seg_of(names[0])
check("撤销后天赋不再是武学(2)", seg is None or seg[2] != "2", str(seg))
check("撤销弹了提示框", any(k == "showinfo" for k, _ in DIALOGS), str(DIALOGS))
check("撤销没弹错误框", not any(k == "showerror" for k, _ in DIALOGS), str(DIALOGS))

app.act_undo()                                   # 撤掉「生成门客」
check("再撤一次，门客数回到 15", menke_count() == 15, f"{menke_count()}")

app.act_undo()                                   # 撤掉「改铜钱」
final_copper = se.get_path(se.Save(TARGET).data, "CGNum.value[0]")
check("第三次撤销，铜钱回到最原始的值", str(final_copper) == str(ORIG_COPPER),
      f"{ORIG_COPPER} → {final_copper}")
check("撤销完仍是合法 JSON", isinstance(se.Save(TARGET).data, dict))

print()
print("=" * 76)
print("八、出错时不崩")
print("=" * 76)
DIALOGS.clear()
app.cpath.set("CGNum.value[999]")        # 不存在的下标
app.cvalue.set("1")
try:
    app.act_custom()
    check("越界路径没让界面崩溃", True)
    check("弹出了错误框", any(k == "showerror" for k, _ in DIALOGS), str(DIALOGS))
except Exception as e:
    check("越界路径没让界面崩溃", False, f"{type(e).__name__}: {e}")

DIALOGS.clear()
app.items_spec.set("")
try:
    app.act_add_items()
    check("空物品规格不崩", True)
    check("提示要填物品", any(k == "showwarning" for k, _ in DIALOGS), str(DIALOGS))
except Exception as e:
    check("空物品规格不崩", False, f"{type(e).__name__}: {e}")

print()
print("=" * 76)
print("九、界面上【每一个按钮】都按一遍（预览不写入），不能有预设名错误")
print("=" * 76)
# 这是最要紧的一节：曾经 gui.py 把预设名写成 immortal / clear-bad-status，
# 界面上点下去才弹「没有名为 'immortal' 的预设」。现在把每个动作都在
# 预览模式（确认框答 No → 只 dry-run、不落盘）下走一遍，名字错立刻现形。
check("gui.py 声明的预设名全都在 presets.json 里",
      G.check_presets(app.presets) == [], str(G.check_presets(app.presets)))

app.files = [TARGET]
app.save_root = T
STATES["yes"] = False                     # 确认框一律答 No → 只预览
app.items_spec.set("169:10")
app.cpath.set("CGNum.value[0]")
app.cvalue.set("123")

ACTIONS = [
    ("一键全改", app.act_oneclick),
    ("铜钱元宝", app.act_money),
    ("全员属性", app.act_member_max),
    ("全员长寿", app.act_immortal),
    ("全员年轻化", app.act_young),
    ("清负面状态", app.act_clear_status),
    ("生成门客", app.act_retainers),
    ("全部门客设天赋", lambda: app.act_set_traits_all("menke")),
    ("全部族人设天赋", lambda: app.act_set_traits_all("member")),
    ("仓库拉满", app.act_all_items),
    ("加物品", app.act_add_items),
    ("禁军兵力", app.act_garrison),
    ("自定义修改", app.act_custom),
]
before_log = app.log_text.get("1.0", "end")
for label, fn in ACTIONS:
    DIALOGS.clear()
    try:
        fn()
    except Exception as e:
        check(f"按钮「{label}」不抛异常", False, f"{type(e).__name__}: {e}")
        continue
    bad = [d for d in DIALOGS if d[0] == "showerror"]
    check(f"按钮「{label}」没有报错", not bad, str(bad))

new_log = app.log_text.get("1.0", "end")[len(before_log):]
check("★ 日志里没有出现过「没有名为」，预设名全部对得上",
      "没有名为" not in new_log and "没有名为" not in app.log_text.get("1.0", "end"),
      [ln for ln in new_log.splitlines() if "没有名为" in ln][:2])
check("确认框答 No 时确实一个字都没写进存档",
      str(se.get_path(se.Save(TARGET).data, "CGNum.value[0]")) == str(final_copper),
      se.get_path(se.Save(TARGET).data, "CGNum.value[0]"))
STATES["yes"] = True

print()
print("=" * 76)
print("十、没有存档时给出提示而不是崩")
print("=" * 76)
app.files = []
DIALOGS.clear()
try:
    app.act_money()
    check("没存档时点了改钱不崩", True)
    check("提示要先选存档", any(k == "showwarning" for k, _ in DIALOGS), str(DIALOGS))
except Exception as e:
    check("没存档时点了改钱不崩", False, f"{type(e).__name__}: {e}")

app.destroy()
print()
print("=" * 76)
print(f"结果：{ok} 通过 / {fail} 失败")
print("=" * 76)

# 收尾：确认真存档没被碰过
REAL = Path.home() / "AppData/LocalLow/S3Studio/House of Legacy/FW/0/GameData.es3"
print(f"\n真存档最后修改时间：{__import__('datetime').datetime.fromtimestamp(REAL.stat().st_mtime)}")
print(f"临时靶场：{T}")

sys.exit(1 if fail else 0)
