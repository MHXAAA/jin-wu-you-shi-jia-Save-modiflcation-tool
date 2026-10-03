#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「生成神级门客」功能的测试。

覆盖的是真正会毁档的那几件事：
  · 22 格不能多不能少
  · 固定格（8/14/20/21）不许被写坏
  · ID 必须全局唯一，且不能撞上族人/其它人物池里已有的 M-ID
  · 追加门客不能动到 Member_now（族人池）
  · dry-run 绝对不能改内存数据
  · 写盘后「重新序列化 == 磁盘内容」，证明存档格式没被破坏
  · 超量要拒绝，而不是硬写

全程只碰副本 _rtest\\0。
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
RT = Path(tempfile.gettempdir()) / "wujin_tmp_rtest"    # 中间产物丢临时目录
WD = RT / "0"
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


def main():
    if RT.exists():
        shutil.rmtree(RT)
    RT.mkdir(parents=True)
    if SYNTHETIC:
        import make_fixture
        print("[说明] 没找到外部存档副本，用 make_fixture 合成一份来测"
              "（不涉及任何真实存档）")
        WD.mkdir(parents=True)
        data = make_fixture.build()
        # 合成存档里那行门客过不了引擎的 22 格红线（第 8 格等），
        # 直接用引擎自带的合法模板当样板，生成器才拿得到模板。
        data["MenKe_Now"]["value"] = [list(se.MENKE_TEMPLATE)]
        GD.write_text(_dump(data), encoding="utf-8")
    else:
        shutil.copytree(SRC, WD)
    TOP_FIELDS = len(se.Save(GD).data)

    presets = se.load_presets()

    print("=" * 64)
    print("  生成神级门客 · 测试")
    print("=" * 64)

    s = se.Save(GD)
    before_menke = len(se.get_path(s.data, "MenKe_Now.value"))
    before_member = json.dumps(se.get_path(s.data, "Member_now.value"),
                               ensure_ascii=False)
    before_disk = GD.read_bytes()

    # ---- 1. dry-run 不许改内存 ----
    snap = json.dumps(s.data, ensure_ascii=False)
    ch = se.run_jobs(s, [("retainers-10", {"count": "10"})], presets, dry=True)
    check("dry-run 报告了 10 处改动", len(ch) == 10, f"实际 {len(ch)}")
    check("dry-run 没有改动内存数据",
          json.dumps(s.data, ensure_ascii=False) == snap)
    check("dry-run 期间门客数没变",
          len(se.get_path(s.data, "MenKe_Now.value")) == before_menke)

    # ---- 2. 真正写入 ----
    s = se.Save(GD)
    ch = se.run_jobs(s, [("retainers-10", {"count": "10"})], presets, dry=False)
    check("写入报告了 10 处改动", len(ch) == 10, f"实际 {len(ch)}")

    mk = se.get_path(s.data, "MenKe_Now.value")
    check("门客总数 = 原数 + 10", len(mk) == before_menke + 10,
          f"{before_menke} → {len(mk)}")

    new = mk[before_menke:]
    check("新增的每条都是 22 格", all(len(e) == 22 for e in new),
          f"格数 {sorted(set(len(e) for e in new))}")

    # ---- 3. 固定格 / 红线 ----
    check("全部新增的第 8 格在 98~100",
          all(e[8] in ("98", "99", "100") for e in new))
    check("全部新增的第 14 格 = 100",
          all(e[14] == "100" for e in new))
    check("全部新增的第 20 格 = 0", all(e[20] == "0" for e in new))
    check("全部新增的第 21 格 = null", all(e[21] == "null" for e in new))
    check("全部新增的基本信息串是 10 段",
          all(len(str(e[2]).split("|")) == 10 for e in new))
    check("全部新增的基本信息串以 |null 收尾",
          all(str(e[2]).endswith("|null") for e in new))
    check("全部新增的形象码是 4 段",
          all(str(e[1]).count("|") == 3 for e in new))
    check("全部新增的四维都是 999",
          all(e[4] == e[5] == e[6] == e[7] == "999" for e in new))
    check("全部新增的寿命都是 99",
          all(str(e[2]).split("|")[5] == "99" for e in new))
    check("全部新增的年龄都是 21", all(e[3] == "21" for e in new))

    # ---- 4. ID 唯一性（含全存档其它人物池）----
    ids = [str(e[0]) for e in mk]
    check("门客数组内 ID 无重复", len(ids) == len(set(ids)))
    check("新增 ID 都是 M+数字",
          all(str(e[0]).startswith("M") and str(e[0])[1:].isdigit() for e in new))
    check("新增 ID 都是 19 位（不超 long 上限）",
          all(len(str(e[0])) == 20 for e in new),      # 'M' + 19 位
          f"长度集合 {sorted(set(len(str(e[0])) for e in new))}")
    all_ids = se.menke_all_ids(s.data)
    raw_now = json.dumps(s.data, ensure_ascii=False)
    check("新增 ID 不与存档里任何已有 M-ID 冲突",
          all(raw_now.count(str(e[0])) == 1 for e in new),
          f"不同的 ID 数 {len(all_ids)}")

    # ---- 5. 不能动到族人池 ----
    check("Member_now（族人）一个字节都没变",
          json.dumps(se.get_path(s.data, "Member_now.value"),
                     ensure_ascii=False) == before_member)

    # ---- 6. 名字 / 长相不重复 ----
    names = [str(e[2]).split("|")[0] for e in new]
    check("10 个名字互不重复", len(names) == len(set(names)), "、".join(names))
    looks = [e[1] for e in new]
    check("长相各不相同（没用到重复形象码）", len(looks) == len(set(looks)))
    check("性别和形象码成对取自真实组合",
          all((e[1], str(e[2]).split("|")[4]) in se.MENKE_LOOKS for e in new))

    # ---- 7. 写盘后格式完整性 ----
    s.write()
    raw = GD.read_bytes()
    back = se.Save(GD).data
    rt = json.dumps(back, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    check("重新序列化与磁盘内容逐字节一致（存档格式没坏）", raw == rt,
          f"{len(raw)} vs {len(rt)}")
    check("__type 元数据保留", "__type" in back["MenKe_Now"])
    check("顶层字段数没变", len(back) == TOP_FIELDS,
          f"{len(back)}")
    check("文件确实变大了（说明真写进去了）", len(raw) > len(before_disk),
          f"{len(before_disk)} → {len(raw)}")

    # ---- 8. 自定义名字 ----
    s2 = se.Save(GD)
    se.run_jobs(s2, [("retainers-10", {"count": "3", "names": "甲一,乙二,丙三"})],
                presets, dry=False)
    got = [str(e[2]).split("|")[0] for e in se.get_path(s2.data, "MenKe_Now.value")[-3:]]
    check("可以指定名字", got == ["甲一", "乙二", "丙三"], "、".join(got))

    # ---- 9. 超量要拒绝，而不是硬写 ----
    s3 = se.Save(GD)
    n_before = len(se.get_path(s3.data, "MenKe_Now.value"))
    try:
        se.run_jobs(s3, [("retainers-10", {"count": "500"})], presets, dry=False)
        check("超量被拒绝", False, "居然没报错")
    except ValueError as e:
        check("超量被拒绝", "最多" in str(e), str(e)[:50])
        check("拒绝后门客数没变",
              len(se.get_path(s3.data, "MenKe_Now.value")) == n_before)

    # ---- 10. 预留：0 个不该产生改动 ----
    s4 = se.Save(GD)
    ch0 = se.run_jobs(s4, [("retainers-10", {"count": "0"})], presets, dry=False)
    check("count=0 不产生改动", len(ch0) == 0, f"实际 {len(ch0)}")

    shutil.rmtree(RT, ignore_errors=True)
    print("\n" + "=" * 64)
    print(f"通过 {PASS} / {PASS + FAIL}")
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
