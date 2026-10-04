#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""新功能测试：物品勾选式选择 + 库存上限 + 家族全员一键修改（含幼年成员）。

这套测试是【自包含】的：夹具由同目录的 make_fixture.py 现场生成，
不依赖开发机上的任何绝对路径，也不依赖真实存档。

全程只动 %TEMP% 下的副本，绝不碰 AppData\LocalLow 里的真实存档。
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

ED = Path(__file__).resolve().parent.parent            # 本脚本在 tests\ 下
WS = ED.parent
sys.path.insert(0, str(ED))
sys.path.insert(0, str(ED / "tests"))

os.environ["WUJIN_HISTORY"] = str(Path(tempfile.gettempdir()) / "wujin_gui_hist.json")
Path(os.environ["WUJIN_HISTORY"]).unlink(missing_ok=True)

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}   {extra}")


# ---- 夹具：现场生成，绝不用开发机上的文件 ----
import make_fixture      # noqa: E402
make_fixture.main()
SAMPLE = ED / "tests" / "sample-save" / "Z0" / "gamedata"

T = Path(tempfile.gettempdir()) / "wujin_checkbox_test"
if T.exists():
    shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
TARGET = T / "GameData.es3"
shutil.copy2(SAMPLE, TARGET)

import gui as G          # noqa: E402
import save_editor as se  # noqa: E402

print("=" * 96)
print("一、物品名表")
print("=" * 96)
check("物品名表已加载", len(G.ITEM_NAMES) > 0, f"实际 {len(G.ITEM_NAMES)}")
check("共 285 种（编号 0–284）", len(G.ITEM_NAMES) == 285, f"实际 {len(G.ITEM_NAMES)}")
check("编号 2 = 粮食", G.ITEM_NAMES.get("2") == "粮食", G.ITEM_NAMES.get("2"))
check("编号 284 = 鸡蛋", G.ITEM_NAMES.get("284") == "鸡蛋", G.ITEM_NAMES.get("284"))
check("编号 0 = 香烛", G.ITEM_NAMES.get("0") == "香烛", G.ITEM_NAMES.get("0"))
check("编号 74 = 盐", G.ITEM_NAMES.get("74") == "盐", G.ITEM_NAMES.get("74"))
check("编号是连续 0..284", sorted(int(k) for k in G.ITEM_NAMES) == list(range(285)))

d0 = se.Save(TARGET).data
have_ids = {str(r[0]) for r in se.get_path(d0, "Prop_have.value")
            if isinstance(r, list) and r}
missing = sorted(have_ids - set(G.ITEM_NAMES), key=int)
check("存档里的每个编号都有名字", not missing, f"缺 {missing}")

print()
print("=" * 96)
print("二、界面能建起来，勾选框齐了")
print("=" * 96)
DIALOGS = []
STATES = {"yes": True}


def rec(kind):
    def f(title=None, message=None, **kw):
        DIALOGS.append((kind, str(message)[:90] if message else ""))
        return STATES["yes"]
    return f


with mock.patch.object(G.messagebox, "showinfo", rec("info")), \
     mock.patch.object(G.messagebox, "showwarning", rec("warn")), \
     mock.patch.object(G.messagebox, "showerror", rec("error")), \
     mock.patch.object(G.messagebox, "askyesno", rec("ask")), \
     mock.patch.object(G.App, "autodetect", lambda self: None):
    # ⚠⚠ 上面这一行 autodetect 屏蔽是【必需】的，不是可有可无。
    #   gui.App.__init__ 里有 self.after(80, self.autodetect)。测试里调 app.update()
    #   之后这个定时回调随时会跑，一跑就把 app.files 换成【自动检测到的真实存档】。
    #   曾经因为少了这一行，测试的写入落到了玩家的真实存档上（已从工具自动备份恢复）。
    #   autodetect 是延时回调，单纯把 app.files 赋值放在 update() 之后【挡不住】它 ——
    #   必须从源头把它摘掉。
    app = G.App()
    app.withdraw()
    app.files = [TARGET]
    app.save_root = T
    app.update()

    # 再上一道保险：每次真正写盘前，硬断言目标就是 %TEMP% 下的副本。
    # 万一以后又有什么东西改了 app.files，这里会立刻炸掉，而不是写坏真实存档。
    _real_apply = app.apply

    def guarded_apply(jobs, title, confirm=True):
        assert app.files, "app.files 空了"
        got = Path(app.files[0]).resolve()
        want = TARGET.resolve()
        assert got == want, f"写入目标不是临时副本！实际 {got}，期望 {want}"
        assert str(got).lower().startswith(str(Path(tempfile.gettempdir()).resolve()).lower()), \
            f"写入目标不在 %TEMP% 下：{got}"
        return _real_apply(jobs, title, confirm)

    app.apply = guarded_apply

    check("窗口建起来了", app.winfo_exists() == 1)
    check("写入目标确实是 %TEMP% 下的副本",
          Path(app.files[0]).resolve() == TARGET.resolve(), str(app.files[0]))
    check("勾选框数量 = 物品数", len(app.item_boxes) == len(G.ITEM_NAMES),
          f"{len(app.item_boxes)} vs {len(G.ITEM_NAMES)}")
    check("勾选变量数量一致", len(app.item_vars) == len(G.ITEM_NAMES))
    check("初始一个都没勾", sum(1 for v in app.item_vars.values() if v.get()) == 0)

    print()
    print("=" * 96)
    print("三、搜索筛选")
    print("=" * 96)
    app.item_filter.set("酒")
    app.filter_items()
    vis = sorted(app._visible_ids(), key=int)
    names = [G.ITEM_NAMES[i] for i in vis]
    check("搜「酒」能筛出结果", len(vis) > 3, f"{len(vis)} 个")
    check("筛出来的都含「酒」", all("酒" in n for n in names), names)
    check("筛出来的少于全部", len(vis) < len(G.ITEM_NAMES))
    print(f"        筛出：{'、'.join(names)}")

    app.item_filter.set("黄酒")
    app.filter_items()
    check("精确搜「黄酒」只剩 1 个", len(app._visible_ids()) == 1,
          [G.ITEM_NAMES[i] for i in app._visible_ids()])

    app.item_filter.set("")
    app.filter_items()
    check("清空搜索后全部恢复", len(app._visible_ids()) == len(G.ITEM_NAMES),
          f"{len(app._visible_ids())}")

    print()
    print("=" * 96)
    print("四、全选 / 全不选 / 反选 只作用于可见项")
    print("=" * 96)
    app.item_filter.set("酒")
    app.filter_items()
    wine_ids = set(app._visible_ids())
    app.check_items(True)
    checked = {i for i, v in app.item_vars.items() if v.get()}
    check("筛选后全选 = 只勾上筛出来的", checked == wine_ids,
          f"勾了 {len(checked)}，可见 {len(wine_ids)}")
    check("没被筛到的没被勾上", not (checked - wine_ids))

    app.invert_items()
    check("反选后这批全空", not any(app.item_vars[i].get() for i in wine_ids))
    app.invert_items()
    check("再反选又全勾上", all(app.item_vars[i].get() for i in wine_ids))

    app.check_items(False)
    check("全不选清空", sum(1 for v in app.item_vars.values() if v.get()) == 0)

    app.item_filter.set("")
    app.filter_items()
    app.check_items(True)
    check("无筛选时全选 = 285 个全勾",
          sum(1 for v in app.item_vars.values() if v.get()) == len(G.ITEM_NAMES))
    app.check_items(False)

    print()
    print("=" * 96)
    print("五、「只显示仓库已有的」")
    print("=" * 96)
    app.only_owned.set(True)
    app.filter_items()
    check("筛出的正好是仓库里的编号", set(app._visible_ids()) == have_ids,
          sorted(set(app._visible_ids()) ^ have_ids, key=int)[:8])
    print(f"        仓库里有 {len(have_ids)} 种，界面显示 {len(app._visible_ids())} 个")
    app.only_owned.set(False)
    app.filter_items()

    print()
    print("=" * 96)
    print("六、勾选后真能加进仓库")
    print("=" * 96)
    captured = {}
    real_apply = app.apply

    def spy(jobs, title, confirm=True):
        captured["jobs"] = jobs
        captured["title"] = title
        return real_apply(jobs, title, confirm)

    app.apply = spy

    def qty_of(iid):
        rows = se.get_path(se.Save(TARGET).data, "Prop_have.value")
        for r in rows:
            if isinstance(r, list) and str(r[0]) == iid:
                return r[1]
        return None

    app.item_filter.set("鸡蛋")
    app.filter_items()
    app.check_items(True)
    app.item_qty.set(123456)
    app.item_mode.set("增加")
    before = qty_of("284")
    app.act_add_items_selected()
    check("动作把 add-items 交给了统一落盘入口",
          captured.get("jobs", [{}])[0][0] == "add-items", captured.get("jobs"))
    check("规格串格式正确", captured["jobs"][0][1]["items"] == "284:123456",
          captured["jobs"][0][1]["items"])
    after = qty_of("284")
    if before is None:
        check("鸡蛋是新增进去的", str(after) == "123456", f"{after}")
    else:
        check("鸡蛋新值 = 旧值 + 123456",
              int(float(after)) == int(float(before)) + 123456, f"{before} → {after}")

    fresh = sorted(set(G.ITEM_NAMES) - {str(r[0]) for r in
                                        se.get_path(se.Save(TARGET).data, "Prop_have.value")
                                        if isinstance(r, list) and r}, key=int)[0]
    print(f"        再试仓库里没有的：{fresh} {G.ITEM_NAMES[fresh]}")
    app.item_filter.set(G.ITEM_NAMES[fresh])
    app.filter_items()
    app.check_items(True)
    app.act_add_items_selected()
    check("全新物品被新增进仓库", qty_of(fresh) is not None, qty_of(fresh))

    print()
    print("=" * 96)
    print("七、家庭全员一键修改（含幼年成员）")
    print("=" * 96)
    mn_before = se.get_path(se.Save(TARGET).data, "Member_now.value")
    young = [str(r[6]) for r in mn_before if se._to_float(r[6]) is not None
             and se._to_float(r[6]) < 16]
    check("夹具里确实有幼年成员（否则这条需求测不到）", len(young) >= 2, young)
    print(f"        幼年成员年龄：{young}")
    before33 = [str(r[33]) for r in mn_before]

    app.fam_age.set(20)
    app.fam_value.set(100)
    app.fam_potential.set(100)
    app.fam_prof.set(100)
    captured.clear()
    app.act_family_all()
    check("动作把 member-all-max 交给了统一落盘入口",
          captured.get("jobs", [{}])[0][0] == "member-all-max", captured.get("jobs"))
    ov = captured["jobs"][0][1]
    check("默认不随机天赋（talent_mode=keep）", ov["talent_mode"] == "keep", ov)
    check("技能随机（skill_mode=random）", ov["skill_mode"] == "random", ov)

    mn = se.get_path(se.Save(TARGET).data, "Member_now.value")
    check("全员年龄都是 20", all(str(r[6]) == "20" for r in mn),
          sorted({str(r[6]) for r in mn}))
    check("年龄镜像格（槽 30）也同步了", all(str(r[30]) == "20" for r in mn),
          sorted({str(r[30]) for r in mn}))
    check("★ 幼年成员也被改成 20 了（需求原话：含幼年成员）",
          all(str(mn[i][6]) == "20" for i in range(len(mn_before))
              if se._to_float(mn_before[i][6]) is not None
              and se._to_float(mn_before[i][6]) < 16))
    check("属性全部 ≥100", all(float(r[s]) >= 100 for r in mn for s in se.FAMILY_ATTR_SLOTS))
    skills = {str(r[4]).split("|")[6] for r in mn}
    check("技能都在 1–6", all(1 <= int(s) <= 6 for s in skills), sorted(skills))
    check("潜力都写满", all(str(r[4]).split("|")[3] == "100" for r in mn))
    check("天赋类型没被动（原样保留）",
          [str(r[4]).split("|")[2] for r in mn] ==
          [str(r[4]).split("|")[2] for r in mn_before])
    check("族人熟练度格默认没被碰（该格位未核对过）",
          [str(r[33]) for r in mn] == before33, sorted({str(r[33]) for r in mn}))
    print(f"        技能分布：{sorted(skills)}")

    # 「随机」这件事单独验：同一份数据、不同 seed，结果必须不一样
    seeds = {}
    for sd in (1, 2, 3, 4, 5):
        sp = T / f"seed{sd}.es3"
        shutil.copy2(SAMPLE, sp)
        s = se.Save(sp)
        se.run_preset(s, "member-all-max", app.presets, {"seed": sd}, dry=False)
        s.write(sp)
        seeds[sd] = tuple(str(r[4]).split("|")[6]
                          for r in se.get_path(se.Save(sp).data, "Member_now.value"))
        sp.unlink()
    check("技能是随机的：不同 seed 结果不同", len(set(seeds.values())) > 1, seeds)

    print()
    print("=" * 96)
    print("七之二、强行勾选「连族人熟练度也写」时才写那一格")
    print("=" * 96)
    app.fam_force_prof.set(True)
    captured.clear()
    app.act_family_all()
    check("force_prof 传到了引擎",
          str(captured["jobs"][0][1].get("force_prof")) == "1",
          captured["jobs"][0][1].get("force_prof"))
    mn3 = se.get_path(se.Save(TARGET).data, "Member_now.value")
    check("勾了之后第 33 格才写成 100", all(str(r[33]) == "100" for r in mn3),
          sorted({str(r[33]) for r in mn3}))
    app.fam_force_prof.set(False)

    print()
    print("=" * 96)
    print("七之三、库房容量（爆仓：东西买不进去）")
    print("=" * 96)
    # 游戏文案：「（物品数量：@，库房容量：$）」+「库房容量已满，请在府邸建造或升级库房！」
    # 所以容量在【府邸】数据里，而且比的是【物品数量】，不是物品种类数。
    d_now = se.Save(TARGET).data
    cap_before = str(se.get_path(d_now, "Fudi_now.value[0][2]"))
    cap_copy = str(se.get_path(d_now, "Fudi_now.value[0][4]"))
    kinds = len(se.get_path(d_now, "Prop_have.value"))
    total = sum(int(float(r[1])) for r in se.get_path(d_now, "Prop_have.value")
                if isinstance(r, list) and len(r) >= 2)
    print(f"        存档现值：库房容量 = {cap_before}（副本 {cap_copy}），"
          f"仓库 {kinds} 种、合计 {total:,} 件")
    check("容量与它的副本在夹具里相等", cap_before == cap_copy,
          f"{cap_before} vs {cap_copy}")
    check("物品总数量确实超过容量（这就是爆仓）", total > int(float(cap_before)),
          f"总量 {total} vs 容量 {cap_before}")

    app.nb.select(app.tab_store)
    app._refresh_cap_info()
    info = app.inv_info.get()
    check("界面读出了容量现值", cap_before in info, info)
    check("界面读出了物品总数量", f"{total:,}" in info, info)
    check("界面点明了超过容量", "超过" in info, info)

    fd_before = list(se.get_path(se.Save(TARGET).data, "Fudi_now.value")[0])
    app.inv_cap.set(99999999)
    captured.clear()
    app.act_inventory_cap()
    check("按钮把 inventory-cap 交给了统一落盘入口",
          captured.get("jobs", [{}])[0][0] == "inventory-cap", captured.get("jobs"))
    d_after = se.Save(TARGET).data
    cap_after = str(se.get_path(d_after, "Fudi_now.value[0][2]"))
    cap_after2 = str(se.get_path(d_after, "Fudi_now.value[0][4]"))
    check("容量被提高", cap_after == "99999999", cap_after)
    check("副本一起提高（两个值不会对不上）", cap_after2 == "99999999", cap_after2)
    check("提高后容量已大于物品总数量", int(float(cap_after)) > total,
          f"{cap_after} vs {total}")

    app.inv_cap.set(1)
    app.act_inventory_cap()
    d_low = se.Save(TARGET).data
    check("只增不减：目标值更小时一个字都不改",
          str(se.get_path(d_low, "Fudi_now.value[0][2]")) == "99999999",
          str(se.get_path(d_low, "Fudi_now.value[0][2]")))

    fd_after = list(se.get_path(se.Save(TARGET).data, "Fudi_now.value")[0])
    changed = [i for i in range(min(len(fd_before), len(fd_after)))
               if str(fd_before[i]) != str(fd_after[i])]
    check("府邸那一行只改了第 3、5 项，其余原样", changed == [2, 4],
          f"被改的下标 {changed}")

    print()
    print("=" * 96)
    print("七之四、数量归位（容量抬不动时的真正解法）")
    print("=" * 96)
    app.qty_norm.set(999)
    captured.clear()
    app.act_item_qty_normal()
    check("按钮把 item-qty-normal 交给了统一落盘入口",
          captured.get("jobs", [{}])[0][0] == "item-qty-normal", captured.get("jobs"))
    ov2 = captured["jobs"][0][1]
    check("允许往下压（only_up=0）", str(ov2.get("only_up")) == "0", ov2)
    d_norm = se.Save(TARGET).data
    rows = se.get_path(d_norm, "Prop_have.value")
    qs = [int(float(r[1])) for r in rows if isinstance(r, list) and len(r) >= 2]
    check("每种物品都被改成 999", all(q == 999 for q in qs), sorted(set(qs))[:6])
    new_total = sum(qs)
    check("总数量降到容量以下（爆仓解除）",
          new_total <= int(float(se.get_path(d_norm, "Fudi_now.value[0][2]"))) or
          new_total < total, f"总量 {new_total} vs 原 {total}")
    print(f"        总数量 {total:,} → {new_total:,}")

    print()
    print("=" * 96)
    print("八、出错与取消不崩")
    print("=" * 96)
    DIALOGS.clear()
    app.item_filter.set("")
    app.filter_items()
    app.check_items(False)
    app.act_add_items_selected()
    check("没勾任何物品时弹提示而不是崩",
          any(k == "warn" for k, _ in DIALOGS), str(DIALOGS))

    DIALOGS.clear()
    STATES["yes"] = False
    app.check_items(True)
    app.act_add_items_selected()
    STATES["yes"] = True
    check("取消确认后界面仍然活着", app.winfo_exists() == 1)

    app.destroy()

print()
print("=" * 96)
print(f"结果：{ok} 通过 / {fail} 失败")
print("=" * 96)
shutil.rmtree(T, ignore_errors=True)
print("临时目录已清理；真实存档未被触碰")
sys.exit(1 if fail else 0)
