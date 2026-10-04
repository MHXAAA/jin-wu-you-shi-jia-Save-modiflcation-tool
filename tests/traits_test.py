#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎改动自检：天赋/专精 op。"""
import json
import sys
from pathlib import Path

ED = Path(__file__).resolve().parent.parent          # 本脚本在 tests\ 下
sys.path.insert(0, str(ED))
sys.path.insert(0, str(ED / "tests"))
import save_editor as se   # noqa: E402

# 夹具现场生成，不依赖开发机上的任何路径
import make_fixture        # noqa: E402
make_fixture.main()
COPY = ED / "tests" / "sample-save" / "Z0" / "gamedata"

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name}  {extra}")


print("=" * 78)
print("一、presets.json 合法性")
print("=" * 78)
pres = json.loads((ED / "presets.json").read_text(encoding="utf-8"))
check("能解析", isinstance(pres, dict))
check("有 person-traits", "person-traits" in pres)
check("retainers-10 带 talent 参数", "talent" in pres["retainers-10"]["params"])
check("retainers-10 带 skill 参数", "skill" in pres["retainers-10"]["params"])
print(f"  预设总数：{len([k for k in pres if not k.startswith('_')])}")

print()
print("=" * 78)
print("二、常量与工具函数")
print("=" * 78)
check("TALENT_NAMES 5 项", len(se.TALENT_NAMES) == 5)
check("SKILL_NAMES 7 项", len(se.SKILL_NAMES) == 7)
check("SKILL_NAMES[1]=巫", se.SKILL_NAMES[1] == "巫")
check("SKILL_NAMES[6]=工", se.SKILL_NAMES[6] == "工")
check("门客 prof 列 = 16", se.MEMBER_LAYOUT["MenKe_Now"]["prof"] == 16)
check("族人 prof 列 = 33", se.MEMBER_LAYOUT["Member_now"]["prof"] == 33)
check("族人 info 列 = 4", se.MEMBER_LAYOUT["Member_now"]["info"] == 4)
check("trait_value('') = None", se.trait_value("", 0, 4, "x") is None)
check("trait_value('keep') = None", se.trait_value("keep", 0, 4, "x") is None)
check("trait_value('auto') = AUTO", se.trait_value("auto", 0, 4, "x") is se.AUTO_TRAIT)
check("trait_value('3') = 3", se.trait_value("3", 0, 4, "x") == 3)
try:
    se.trait_value("9", 0, 4, "天赋ID")
    check("超范围要报错", False)
except ValueError as e:
    check("超范围报错", "0–4" in str(e) or "0-4" in str(e))

print()
print("=" * 78)
print("三、list_members 能列出成员")
print("=" * 78)
data = json.loads(COPY.read_text(encoding="utf-8"))
mem = se.list_members(data)
check("列得出成员", len(mem) > 0, f"拿到 {len(mem)}")
kinds = {}
for m in mem:
    kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
print(f"  {kinds}")
check("含门客", kinds.get("门客", 0) > 0)
check("含族人", kinds.get("族人", 0) > 0)
print(f"  例：{mem[0]['name']} {mem[0]['kind']} 天赋={mem[0]['talent']} "
      f"潜力={mem[0]['potential']} 专精={mem[0]['skill']} 熟练度={mem[0]['proficiency']}")

print()
print("=" * 78)
print("四、set_traits dry-run（不改数据）")
print("=" * 78)
before = json.dumps(data, ensure_ascii=False, sort_keys=True)
s = se.Save.__new__(se.Save)
s.data = data
s.path = COPY
ch = se.run_preset(s, "person-traits", pres,
                   {"scope": "menke", "talent": "1", "potential": "100",
                    "skill": "4", "proficiency": "100"}, dry=True)
check("dry-run 有改动记录", len(ch) > 0, f"{len(ch)} 条")
after = json.dumps(data, ensure_ascii=False, sort_keys=True)
check("dry-run 没动内存数据", before == after)
print(f"  改动预览前 3 条：")
for c in ch[:3]:
    print(f"    {c}")

print()
print("=" * 78)
print("五、set_traits 真跑（在内存里，不写盘）")
print("=" * 78)
s2 = se.Save.__new__(se.Save)
s2.data = json.loads(COPY.read_text(encoding="utf-8"))
s2.path = COPY
ch2 = se.run_preset(s2, "person-traits", pres,
                    {"scope": "menke", "talent": "1", "potential": "100",
                     "skill": "4", "proficiency": "100"}, dry=False)
rows = s2.data["MenKe_Now"]["value"]
allok = all(str(r[2]).split("|")[2] == "1" and str(r[2]).split("|")[3] == "100"
            and str(r[2]).split("|")[6] == "4" and str(r[16]) == "100" for r in rows)
check("所有门客天赋=1/潜力=100/专精=4/熟练度=100", allok)
if not allok:
    for r in rows[:3]:
        print(f"    {r[2]}  [16]={r[16]}")
check("信息串仍然 10 段", all(len(str(r[2]).split("|")) == 10 for r in rows))
check("行长仍然 22", all(len(r) == 22 for r in rows))

print()
print("=" * 78)
print("六、add_retainers auto 铺开（在内存里）")
print("=" * 78)
s3 = se.Save.__new__(se.Save)
s3.data = json.loads(COPY.read_text(encoding="utf-8"))
s3.path = COPY
n0 = len(s3.data["MenKe_Now"]["value"])
se.run_preset(s3, "retainers-10", pres,
              {"count": "6", "names": "甲一,乙二,丙三,丁四,戊五,己六",
               "name_mode": "random"}, dry=False)
newrows = s3.data["MenKe_Now"]["value"][n0:]
check("新增 6 人", len(newrows) == 6, f"实际 {len(newrows)}")
sk = [str(r[2]).split("|")[6] for r in newrows]
ta = [str(r[2]).split("|")[2] for r in newrows]
pr = [str(r[16]) for r in newrows]
print(f"  专精ID 铺开 = {sk}")
print(f"  天赋ID 铺开 = {ta}")
print(f"  熟练度      = {pr}")
check("专精覆盖 1–6 全六种", sorted(set(sk)) == ["1", "2", "3", "4", "5", "6"])
check("天赋都在 1–4", all(x in ("1", "2", "3", "4") for x in ta))
check("熟练度都是 100", all(x == "100" for x in pr))
for r in newrows:
    se.menke_validate_row(r)
check("新门客全部通过 22 格校验", True)

print()
print("=" * 78)
print(f"结果：{ok} 通过 / {fail} 失败")
print("=" * 78)
sys.exit(1 if fail else 0)
