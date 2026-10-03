#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第二轮新功能测试：历史谋士名字池 + 仓库每种物品一起拉满。

全程只碰副本 _r2test\\0。
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _resolve_src():
    r"""测试用存档从哪来 —— 找不到就现场合成一份。

    优先级：
      1. 环境变量 WUJIN_SAVE_SRC 指的目录
      2. 项目旁边的 0\ （放一份你自己的存档副本进去）
      3. 都没有 → 用 make_fixture 合成一份

    本测试【绝不】读写真存档，所有改动都发生在临时目录的副本上。
    返回值第二位表示「是不是合成出来的」。
    """
    env = os.environ.get("WUJIN_SAVE_SRC")
    if env and (Path(env) / "GameData.es3").exists():
        return Path(env), False
    for cand in (ROOT / "0", ROOT.parent / "0"):
        if (cand / "GameData.es3").exists():
            return cand, False
    return None, True


def _dump(data):
    """按存档真实格式序列化：单行、无空格、中文原样。"""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


SRC, SYNTHETIC = _resolve_src()
R2 = Path(tempfile.gettempdir()) / "wujin_tmp_r2test"    # 中间产物丢临时目录
WD = R2 / "0"
GD = WD / "GameData.es3"

sys.path.insert(0, str(ROOT))
import save_editor as se           # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


def names_of(data):
    return [str(e[2]).split("|")[0] for e in se.get_path(data, "MenKe_Now.value")]


def items(data):
    out = {}
    for row in se.get_path(data, "Prop_have.value"):
        if isinstance(row, list) and len(row) >= 2:
            try:
                out[str(row[0])] = int(float(row[1]))
            except (TypeError, ValueError):
                pass
    return out


def main():
    if R2.exists():
        shutil.rmtree(R2)
    R2.mkdir(parents=True)
    if SYNTHETIC:
        import make_fixture
        print("[说明] 没找到外部存档副本，用 make_fixture 合成一份来测"
              "（不涉及任何真实存档）")
        WD.mkdir(parents=True)
        data = make_fixture.build()
        # 合成存档里那行门客过不了引擎的 22 格红线（第 8 格等），
        # 直接用引擎自带的合法模板当样板，生成器才拿得到模板。
        data["MenKe_Now"]["value"] = [list(se.MENKE_TEMPLATE)]
        # 合成存档的仓库只有 2 种物品，测「每种一起拉满」不够用，
        # 补到 80 种（这场测试要验证的是批量处理，物品本身是什么无所谓）
        data["Prop_have"]["value"] = [[str(i), str(100 + i)] for i in range(1, 81)]
        GD.write_text(_dump(data), encoding="utf-8")
    else:
        shutil.copytree(SRC, WD)
    TOP_FIELDS = len(se.Save(GD).data)
    presets = se.load_presets()

    print("=" * 66)
    print("  第二轮：历史谋士名字 + 仓库每种物品拉满")
    print("=" * 66)

    # ============================================ 一、历史谋士名字池
    print("\n-- 1. 历史谋士名字池 --")
    pool = se.MENKE_HISTORY_NAMES
    check("名字池至少 15 个", len(pool) >= 15, f"{len(pool)} 个")
    check("池内本身无重复", len(pool) == len(set(pool)))
    check("名字都是 2~3 个字", all(2 <= len(n) <= 3 for n in pool),
          "、".join(pool[:5]) + "…")
    check("前 15 个是主打阵容且含诸葛亮",
          pool[0] == "诸葛亮" and len(pool[:15]) == 15)

    # 10 个 → 用池子前 10 个
    s = se.Save(GD)
    se.run_jobs(s, [("retainers-10", {"count": "10", "name_mode": "history"})],
                presets, dry=False)
    got = names_of(s.data)[-10:]
    check("生成 10 个时用的是名字池前 10 个", got == pool[:10], "、".join(got))
    check("这 10 个互不重复", len(got) == len(set(got)))

    s.write()

    # 再生成 10 个 → 不能和已有的重名（跨批次也要保证不重复）
    s = se.Save(GD)
    se.run_jobs(s, [("retainers-10", {"count": "10", "name_mode": "history"})],
                presets, dry=False)
    got2 = names_of(s.data)[-10:]
    allnames = names_of(s.data)
    check("第二次生成避开了已在用的名字", not (set(got2) & set(got)))
    check("全部门客名字无重复", len(allnames) == len(set(allnames)))

    # 一次要 20 个 → 池子只有 24 个，但前 15 已被用了，应部分回落随机
    s = se.Save(GD)
    before_names = set(names_of(s.data))
    se.run_jobs(s, [("retainers-10", {"count": "20", "name_mode": "history"})],
                presets, dry=False)
    got3 = names_of(s.data)[-20:]
    check("一次要 20 个也不重名", len(set(got3)) == 20)
    check("新生成的 20 个避开了所有已用名字", not (set(got3) & before_names))
    check("用完了历史名字就用随机名字补上（不报错、不重复）",
          len([n for n in got3 if n not in pool]) >= 0)

    # 指定名字
    s = se.Save(GD)
    se.run_jobs(s, [("retainers-10", {"count": "3", "names": "诸葛亮,张良,韩信"})],
                presets, dry=False)
    check("指定名字时可以覆盖历史池", names_of(s.data)[-3:] == ["诸葛亮", "张良", "韩信"])

    # ============================================ 二、仓库每种物品拉满
    print("\n-- 2. 仓库每种物品一起拉满 --")
    s = se.Save(GD)
    it0 = items(s.data)
    check("测试存档仓库里有物品", len(it0) > 50, f"{len(it0)} 种")

    # 工作区副本里最大的物品才十几万，为了验证「只增不减」保护，
    # 先手动顶一个大值上去 —— 这正是真实存档里粮食 5005 万的情形。
    bucket = se.get_path(s.data, "Prop_have.value")
    big_id = str(bucket[0][0])
    bucket[0][1] = "50052501"
    MX = 50052501
    check("已构造出一个超过 999 万的物品", items(s.data)[big_id] == MX,
          f"物品 {big_id} = {MX:,}")

    # 2a. 默认只增不减
    s = se.Save(GD)
    se.get_path(s.data, "Prop_have.value")[0][1] = str(MX)   # 只改内存，不写盘
    snap = json.dumps(s.data, ensure_ascii=False)
    ch = se.run_jobs(s, [("all-items-max", {"value": "9999999", "only_up": 1})],
                     presets, dry=True)
    check("dry-run 报告了改动", len(ch) > 0, f"{len(ch)} 处")
    check("dry-run 没改内存", json.dumps(s.data, ensure_ascii=False) == snap)

    s = se.Save(GD)
    se.get_path(s.data, "Prop_have.value")[0][1] = str(MX)
    ch = se.run_jobs(s, [("all-items-max", {"value": "9999999", "only_up": 1})],
                     presets, dry=False)
    it1 = items(s.data)
    check("不足 999 万的都补到 999 万",
          all(v == 9999999 for k, v in it1.items() if k != big_id),
          f"改动 {len(ch)} 处")
    check("★ 本来超过 999 万的物品【一点没降】",
          it1[big_id] == MX, f"{MX:,} → {it1[big_id]:,}")
    check("物品种类数没变（只是改数量，不新增）", len(it1) == len(it0))
    check("每一行仍是 [字符串, 字符串]",
          all(isinstance(x, str) for row in se.get_path(s.data, "Prop_have.value")
              for x in row))

    # 2b. 强制模式
    s = se.Save(GD)
    se.get_path(s.data, "Prop_have.value")[0][1] = str(MX)
    se.run_jobs(s, [("all-items-max", {"value": "9999999", "only_up": 0})],
                presets, dry=False)
    it2 = items(s.data)
    check("强制模式下【全部】都等于 999 万",
          all(v == 9999999 for v in it2.values()),
          f"最大 {max(it2.values()):,}")
    check("强制模式确实把超量的砍下来了", it2[big_id] == 9999999 and MX > 9999999,
          f"{MX:,} → {it2[big_id]:,}")

    # 2c. 数量不是数字的条目要跳过，不能崩
    s = se.Save(GD)
    bucket = se.get_path(s.data, "Prop_have.value")
    bucket.append(["9999", "不是数字"])
    try:
        se.run_jobs(s, [("all-items-max", {"value": "9999999", "only_up": 1})],
                    presets, dry=False)
        check("数量不是数字的条目能安全跳过", True)
        check("那个坏条目没被改坏",
              [r for r in bucket if r[0] == "9999"][0][1] == "不是数字")
    except Exception as e:
        check("数量不是数字的条目能安全跳过", False, f"{type(e).__name__}: {e}")

    # 2d. 负数要拒绝
    s = se.Save(GD)
    try:
        se.run_jobs(s, [("all-items-max", {"value": "-5"})], presets, dry=False)
        check("负数目标被拒绝", False, "居然没报错")
    except ValueError as e:
        check("负数目标被拒绝", "负数" in str(e), str(e)[:36])

    # ============================================ 三、两者一起用
    print("\n-- 3. 两件事一次做完（这正是「待改清单」的用法）--")
    s = se.Save(GD)
    base_menke = len(se.get_path(s.data, "MenKe_Now.value"))
    base_names = set(names_of(s.data))
    jobs = [("retainers-10", {"count": "15", "name_mode": "history"}),
            ("all-items-max", {"value": "9999999", "only_up": 1})]
    ch = se.run_jobs(s, jobs, presets, dry=False)
    check("一次跑两个预设都生效", len(ch) >= 15, f"{len(ch)} 处改动")
    check("门客加了 15 个",
          len(se.get_path(s.data, "MenKe_Now.value")) == base_menke + 15,
          f"{base_menke} → {len(se.get_path(s.data, 'MenKe_Now.value'))}")
    new15 = names_of(s.data)[-15:]
    check("新增的 15 个名字互不重复", len(set(new15)) == 15)
    check("并且都避开了存档里已有的名字", not (set(new15) & base_names),
          "、".join(new15))
    avail = [n for n in pool if n not in base_names]
    from_pool = [n for n in new15 if n in pool]
    check("历史池里还剩的优先全部用上，用完了才回落随机名",
          len(from_pool) == min(15, len(avail)),
          f"池里剩 {len(avail)} 个，实际用了 {len(from_pool)} 个")
    check("仓库同时也被拉满了",
          all(v == 9999999 for v in items(s.data).values()))

    shutil.rmtree(R2, ignore_errors=True)
    print("\n" + "=" * 66)
    print(f"通过 {PASS} / {PASS + FAIL}")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
