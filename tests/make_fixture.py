#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按《存档修改》文档里给出的 gamedata 片段，合成一份结构一致的测试存档。

用途：验证 save_editor.py 的读写/强转/备份逻辑。
注意：它验证的是【工具】，不是字段索引。真实索引必须用你手上的实档核对。
"""
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "sample-save"

T = "System.Collections.Generic.List`1[[System.String, mscorlib, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089]], mscorlib"
TI = "System.Collections.Generic.List`1[[System.Int32, mscorlib, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089]], mscorlib"
I32 = "System.Int32, mscorlib"
S = "System.String, mscorlib"


def L(vals, t=T):
    return {"__type": t, "value": vals}


def LL(rows, t=T):
    return {"__type": t, "value": rows}


def member(idx, name, gen, age, lifespan=99, attrs=None):
    """43 元素，字段顺序完全照抄文档 Member_now 的逐项注释。

    attrs 用来造幼年成员：真实存档里没成年的那几位，属性都是个位数
    （文/武/商/艺 小于 10），年龄也只有两三岁。夹具里必须有这样的人，
    「家族一键修改要包含幼年成员」才有东西可测。
    """
    a = attrs or ("60", "55", "40", "30")
    return [
        f"M{idx}",                     # 0 人物编号
        "19|29|2|19",                  # 1 形象
        "null",                        # 2 子嗣
        "0|null|null|1",               # 3 居所
        f"{name}|{gen}|0|0|1|{lifespan}|0|100|94|10",  # 4 姓名|代|天赋|天赋点|性别|寿命|技能|幸运|?|喜好
        "1",                           # 5 性格/脸
        str(age),                      # 6 年龄
        a[0], a[1], a[2], a[3],        # 7-10 文武商艺
        "70",                          # 11 心情
        "0@0@0@-1@-1|0",               # 12 身份/职务
        "0",                           # 13 功名
        "0|0",                         # 14 爵位|封地
        "0",                           # 15 状态
        "100",                         # 16 声誉
        "0", "0",                      # 17-18
        "null",                        # 19 研习
        "80",                          # 20 魅力
        "100",                         # 21 健康
        "1" if idx == 0 else "0",      # 22 家主
        "null",                        # 23 特殊标签
        "null",                        # 24 近期记事
        "-1",                          # 25 怀孕月份
        "0",                           # 26 婚姻
        "45",                          # 27 计谋
        "0",                           # 28
        "null|null|null",              # 29 装备
        str(age),                      # 30 实测与第 6 格（年龄）恒等，是镜像格
        "0|0|0|0|0|0|0",               # 31 每月加成
        "0|0|0|0|0|0",                 # 32
        "0",                           # 33 技能点
        "0",                           # 34 孕率
        "0",                           # 35
        "null",                        # 36 生平记事
        "null", "null", "0",           # 37-39
        "0",                           # 40 学派
        "-1|0|0",                      # 41 族人职责
        "0|0",                         # 42
    ]


def build():
    return {
        "TaskOrderData_Now": {
            "__type": "System.Collections.Generic.List`1[[System.Collections.Generic.List`1[["
                       "System.Int32, mscorlib, Version=4.0.0.0, Culture=neutral, "
                       "PublicKeyToken=b77a5c561934e089]], mscorlib, Version=4.0.0.0, Culture=neutral, "
                       "PublicKeyToken=b77a5c561934e089]],mscorlib",
            "value": [[str(i), "0"] for i in range(80)],
        },
        "KingCityData_now": L(["120000|100", "-2|左翊卫将军(四品)", "-2|右翊卫将军(四品)", "国库", "null", "0"]),
        "ShiJia_king": L(["皇族的姓氏", "24", "关系", "9", "null", "1@1.4|0@0.7"]),
        "ShiJia_Now": LL([
            ["0", "世家姓氏", "3", "100", "20", "4|0", "1", "500", "1@1.9|0@0.7", "0", "8"],
            ["1", "另一世家", "2", "80", "15", "3|1", "2", "300", "0@1.2", "1", "7"],
        ]),
        "Cun_now": LL([[], [["0|9.6", "4", "150", "90", "8", "61"]]]),
        "Member_First": L(["M0", "姓名", "14|20|2|15", "5", "0@0@0|0", "1", "19"]),
        # 门客 22 格。第 8 格和第 20 格都是固定格，真实存档里恒在各自范围
        # （8 → 98~100，20 → 恒为 0）。这两格以前随手写成 80 / 0.2，
        # 「固定格不许被写坏」那条自检当然过不去。
        "MenKe_Now": LL([["M13391844375253937876", "19|29|2|19", "门客名|6|0|0|0|99|0|1|11|null",
                          "30", "100", "100", "100", "100", "99", "0|B7627|null", "0", "100", "1",
                          "60", "100", "20", "0", "-1", "3000", "20", "0", "null"]]),
        "CGNum": L(["0", "0", "0", "0"]),
        # FamilyData 第 3 格是库存上限（字符串）。这里设成 20，比仓库里的 60 种小
        # —— 正好是「爆仓、买东西存不进去」的现场，方便测库存上限功能。
        "FamilyData": L(["4|4", "家族姓氏", "20", "0", "0", "0", "0", "0", "null", "0"]),
        "Time_now": {
            "__type": TI,
            "value": [1, 1, 1],
        },
        # 仓库里放 60 种东西：数量太少的话，「每种物品一起拉满」「仓库容量」这类
        # 自检就没有规模可测（以前只有 2 种，测试只能退化成「跳过」）。
        "Prop_have": LL([[str(i), str(1000 + i * 37)] for i in range(60)]),
        "IdIndex": {"__type": TI, "value": [64, 0, 0]},
        "MemberNumWillDead": {"__type": I32, "value": 0},
        "NuLiNum": {"__type": I32, "value": 0},
        "VisionIndex": {"__type": I32, "value": 0},
        "SceneID": {"__type": S, "value": "M|0"},
        "VersionID": {"__type": S, "value": "V0.7.292"},
        # 两位成年人 + 两位幼年成员（属性个位数，年龄两三岁）。
        # 幼年这两位是「家族一键修改要包含幼年成员」这个需求的被测对象。
        "Member_now": LL([
            member(0, "家主", 1, 19),
            member(1, "族人甲", 2, 24),
            member(2, "幼年甲", 3, 3, attrs=("1.7", "1.3", "1.3", "12.9")),
            member(3, "幼年乙", 3, 2, attrs=("0.8", "0.5", "0.5", "5.9")),
        ]),
        "PropPrice_Now": LL([
            ["2|121", "3|98", "4|110", "66|113", "5|105"],
            [],
            ["2|130", "3|90"],
        ]),
        "CityData_now": LL([
            [
                ["14|10000|100|0", "-2|null", "-2|null", "-2|null", "-2|null", "0", "null", "80000",
                 "10", "800000", "500", "500", "52@2|53@5", "10", "400", "0", "0|0|0|0", "0", "0",
                 "0", "1|1", "0", "0", "0|0", "0|0", "0", "0", "100", "262"],
                ["-2|null", "-2|null", "-2|null", "5000", "10", "14|6000|100|90", "null", "150000", "0", "100"],
            ],
        ]),
    }


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    for z in range(13):
        d = OUT / f"Z{z}"
        d.mkdir(parents=True)
        data = build()
        if z > 0:                       # Z1~Z12 是各封地，农庄数据不同即可
            data["Cun_now"] = LL([[], [["1|1", "4", "100", "80", "5", "50"]]])
        # 必须和真实存档一样写【紧凑单行】JSON：引擎的写盘序列化就是
        # json.dumps(..., ensure_ascii=False, separators=(",", ":"))，
        # 夹具要是写成缩进格式，「重新序列化 == 磁盘内容」那条自检永远过不去。
        (d / "gamedata").write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
    print(f"已生成 {OUT}  (Z0 ~ Z12，共 13 个 gamedata)")


if __name__ == "__main__":
    main()
