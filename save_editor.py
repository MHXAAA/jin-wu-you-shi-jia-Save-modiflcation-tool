#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《吾今有世家》存档修改器  —  gamedata

针对版本 V0.7.292 的 gamedata 结构编写，依据的是官方群共享的《存档修改》文档。

三条硬约束（整个工具围绕它们设计）：

  1. gamedata 是 Newtonsoft.Json 序列化产物，每个节点都带 "__type" 元数据。
     这些元数据必须原样保留，工具只做「读 → 改值 → 写回」，绝不重建结构。

  2. 游戏把绝大多数业务数据存成【字符串】：["0","世家姓氏","100",...]。
     把 100 写成数字 100 会让 C# 的 JsonConvert 反序列化失败。
     因此 set 操作默认「按原类型强转」——原来是什么类型就写成什么类型。

  3. 每次写入先自动备份，再原子替换，中途崩溃不会留下半个文件。

用法速览：
    python save_editor.py scan   <存档目录>
    python save_editor.py keys   <gamedata>
    python save_editor.py find   <gamedata> 铜钱
    python save_editor.py members <gamedata>
    python save_editor.py get    <gamedata> CGNum.value[0]
    python save_editor.py set    <gamedata> CGNum.value[0] 999999
    python save_editor.py presets
    python save_editor.py preset <gamedata> money --param copper=1000000 --dry-run

<gamedata> 也可以直接给存档目录或存档根目录，工具会自动找出全部 Z*/gamedata 文件。
"""

from __future__ import annotations
import json
import random
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import paths                       # 只读资源 vs 可写状态，见 paths.py

# ---------------------------------------------------------------- 输出编码

try:  # Windows 控制台默认 GBK，中文会炸，这里强制 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


# ---------------------------------------------------------------- 路径解析

TOKEN_RE = re.compile(r"\.?([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


def parse_path(path: str) -> list:
    """'CGNum.value[0]' -> ['CGNum', 'value', 0]；'[3][7]' -> [3, 7]"""
    tokens, pos = [], 0
    while pos < len(path):
        m = TOKEN_RE.match(path, pos)
        if not m or m.end() == pos:
            raise ValueError(f"无法解析的路径片段: {path[pos:]!r}  (完整路径 {path!r})")
        tokens.append(m.group(1) if m.group(1) is not None else int(m.group(2)))
        pos = m.end()
    if not tokens:
        raise ValueError(f"空路径: {path!r}")
    return tokens


def resolve(data, tokens: list):
    """按 token 逐层深入，返回 (父容器, 末级 key)。找不到就抛异常。"""
    cur = data
    for i, t in enumerate(tokens[:-1]):
        cur = _step(cur, t, tokens[: i + 1])
    return cur, tokens[-1]


def _step(cur, t, sofar):
    where = "".join(f"[{x}]" if isinstance(x, int) else (f".{x}" if i else x)
                    for i, x in enumerate(sofar))
    if isinstance(t, int):
        if not isinstance(cur, list):
            raise TypeError(f"{where} 期望是列表，实际是 {type(cur).__name__}")
        if t >= len(cur):
            raise IndexError(f"{where} 越界（长度 {len(cur)}）")
        return cur[t]
    if not isinstance(cur, dict):
        raise TypeError(f"{where} 期望是对象，实际是 {type(cur).__name__}")
    if t not in cur:
        raise KeyError(f"{where} 不存在该键")
    return cur[t]


def get_path(data, path: str):
    parent, key = resolve(data, parse_path(path))
    return _step(parent, key, parse_path(path))


def set_path(data, path: str, value) -> None:
    parent, key = resolve(data, parse_path(path))
    if isinstance(key, int):
        parent[key] = value
    else:
        parent[key] = value


# ---------------------------------------------------------------- 类型强转

def coerce_like(old, new_text: str, raw: bool = False):
    """
    把外部给的字符串，按 old 的类型写回去。
    这是本工具最关键的安全阀：字符串槽位永远写字符串。
    """
    if raw:
        return json.loads(new_text)
    if isinstance(old, bool):
        return new_text.strip().lower() in ("1", "true", "yes", "y", "是")
    if isinstance(old, int):
        return int(new_text)
    if isinstance(old, float):
        return float(new_text)
    if isinstance(old, str):
        return new_text
    if old is None:
        # 原来是 null（占位），按字面量猜：整数 → 浮点 → 保持字符串
        for caster in (int, float):
            try:
                return caster(new_text)
            except ValueError:
                pass
        return new_text
    raise TypeError(f"不支持的目标类型 {type(old).__name__}，如确需写入请加 --raw")


# ---------------------------------------------------------------- 存档对象

BACKUP_KEEP = 10        # 每个存档最多保留多少个 .bak- 备份


def prune_backups(path: Path, keep: int = BACKUP_KEEP) -> int:
    """备份太多会堆满存档文件夹，只留最近 keep 个。"""
    baks = sorted(path.parent.glob(path.name + ".bak-*"))
    removed = 0
    for old in baks[:-keep] if len(baks) > keep else []:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


class Save:
    def __init__(self, path):
        path = Path(path)                 # 容忍传字符串进来
        self.path = path
        raw_bytes = path.read_bytes()
        st = path.stat()
        # 记下指纹，写入前再比一次：能发现「游戏还开着、中途又存了一次档」
        self.sig = (st.st_mtime_ns, st.st_size)

        # 编码侦测：不能无脑用 utf-8-sig，因为用该编码「写回」会凭空添加 BOM
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            self.encoding = "utf-8-sig"
        elif raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise RuntimeError(f"{path} 疑似 UTF-16 编码，本工具不支持")
        else:
            self.encoding = "utf-8"

        try:
            raw = raw_bytes.decode(self.encoding)
        except UnicodeDecodeError:
            self.encoding = "gb18030"
            try:
                raw = raw_bytes.decode(self.encoding)
            except UnicodeDecodeError as e:
                raise RuntimeError(f"无法解码 {path}: {e}") from e

        self.pretty = raw.count("\n") > 2          # 原本是格式化过的就保持格式化
        try:
            self.data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"{path}\n不是合法 JSON（第 {e.lineno} 行第 {e.colno} 列）。\n"
                f"如果存档是加密/压缩的，本工具不适用。"
            ) from e

    def render(self, indent=None, ascii_out: bool = False) -> str:
        if indent is None:
            indent = 2 if self.pretty else None
        sep = (",", ": ") if indent else (",", ":")
        return json.dumps(self.data, ensure_ascii=ascii_out, indent=indent,
                          separators=None if indent else sep)

    def changed_on_disk(self) -> bool:
        """读进来之后，文件是否被别的程序改过。"""
        try:
            st = self.path.stat()
        except OSError:
            return True
        return (st.st_mtime_ns, st.st_size) != self.sig

    def write(self, backup: bool = True, indent=None, ascii_out: bool = False):
        # 最重要的保险：如果文件在本次读取之后被别人动过，
        # 说明游戏很可能正在运行（它一存档就会覆盖我们的修改）。直接中止。
        if self.changed_on_disk():
            raise RuntimeError(
                f"{self.path.name} 在你操作期间被改动过——游戏很可能还开着。\n"
                f"  已中止写入，避免覆盖掉游戏刚存的数据。\n"
                f"  请【完全退出游戏】（不是退回主菜单），然后重来一次。"
            )
        text = self.render(indent=indent, ascii_out=ascii_out)
        if backup:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            bak = self.path.with_name(f"{self.path.name}.bak-{stamp}")
            n = 1
            while bak.exists():          # 同一秒内连写两次，别让备份互相覆盖
                bak = self.path.with_name(f"{self.path.name}.bak-{stamp}-{n}")
                n += 1
            shutil.copy2(self.path, bak)
            prune_backups(self.path, BACKUP_KEEP)
        else:
            bak = None
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_bytes(text.encode(self.encoding))
        tmp.replace(self.path)
        st = self.path.stat()
        self.sig = (st.st_mtime_ns, st.st_size)
        return bak


# ---------------------------------------------------------------- 目标展开

def find_gamedata(target: Path) -> list[Path]:
    """文件 / 存档文件夹 / 存档根目录 → gamedata 文件列表"""
    if target.is_file():
        return [target]
    if not target.is_dir():
        raise FileNotFoundError(f"路径不存在: {target}")
    def ok(p: Path) -> bool:
        n = p.name
        return p.is_file() and ".bak-" not in n and not n.endswith(".tmp")

    hits = sorted(p for p in target.rglob("gamedata*") if ok(p))
    if not hits:
        hits = sorted(p for p in target.rglob("*.json") if ok(p))
    if not hits:
        raise FileNotFoundError(f"{target} 下没找到 gamedata 文件")
    return hits


# ---------------------------------------------------------------- 预设

# 预设是【只读资源】，打进 exe 里了 —— 必须用 res_file()。
# 打包成 onefile 后 `Path(__file__)` 指向 PyInstaller 的解压临时目录，
# 拼出来的路径看似能用，但那是「只读资源」的语义；而状态文件走 state_file()。
# 两者混用正是打包后最常见的那个 bug。
PRESET_FILE = paths.res_file("presets.json")
SAFE_FMT = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_presets() -> dict:
    if not PRESET_FILE.exists():
        return {}
    raw = json.loads(PRESET_FILE.read_text(encoding="utf-8"))
    # 以 _ 开头的键是注释（如 _readme），不是预设
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def render_template(tpl: str, params: dict) -> str:
    """把 '{troops}|{morale}' 里的已知占位符替换掉，未知的原样保留。"""
    return SAFE_FMT.sub(lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0), tpl)


class Change:
    __slots__ = ("path", "old", "new")

    def __init__(self, path, old, new):
        self.path, self.old, self.new = path, old, new

    def __str__(self):
        return f"  {self.path}\n      - {self.old!r}\n      + {self.new!r}"


# ================================================================ 门客（MenKe_Now）
#
# 门客和族人是两套【完全独立】的结构，绝不能混写：
#
#   · 族人 Member_now.value[i] —— 43 格，彼此用 M-ID 大量互相引用
#     （子嗣、居所、生平记事、爵位…），牵一发动全身。
#
#   · 门客 MenKe_Now.value[i] —— 22 格，且**完全自包含**：
#     一条门客的 M-ID 在整个存档文件里【只出现一次】，就在 MenKe_Now.value 里，
#     再没有任何别的字段引用它。
#
# 第二点是「凭空生成门客」能成立的唯一依据 —— 只要往 MenKe_Now.value 里追加
# 一条完整的 22 格记录，游戏就会多出一个门客，不需要同步任何别的地方。
# 这一点是在 227KB 的真实存档上逐 ID 全文检索验证过的，不是推测。
#
# 22 格的含义（在真实存档上交叉验证得出，括号里是验证依据）：
#
#   [0]  M-ID        全局唯一，同数组内不可重复
#   [1]  形象码       形如 "5|8|2|19"，与性别配对决定立绘
#   [2]  基本信息串   10 段：姓名|代|天赋|天赋点|性别|寿命|技能|幸运|?|喜好
#                    第 4 段性别 1=男 0=女（丁永超=1、骆素儿=0，与姓名吻合）
#                    第 5 段寿命 60~99（恒大于第 [3] 格年龄）
#                    末段固定 null
#   [3]  年龄         取值 21~60；被批量强化过的 7 条**全部等于 21**
#   [4]  属性一       ≤999（已有存档里被拉到 999）
#   [5]  属性二       ≤999
#   [6]  属性三       ≤999
#   [7]  属性四       ≤999
#   [8]  综合评分     98~100
#   [9]  关联串       形如 "0|null|null"
#   [10] 关联数值     0 / 17 / 21
#   [11] 成长系数     浮点，如 41.75
#   [12] 状态标志     0 或 1
#   [13] 属性五       ≤999
#   [14] 固定 100     真实存档 15 条**全部恒为 100**（⚠ 不是协议文档说的第 [8] 格）
#   [15] 属性六       ≤999
#   [16] 招募来源     0 / 1 / 7
#   [17] 俸禄         真实存档 15 条**全部恒为 -1**
#   [18] 身价数值     1060~3860
#   [19] 岗位类型     8~29
#   [20] 固定 0       真实存档 15 条全部恒为 0
#   [21] 固定 null    真实存档 15 条全部恒为 null
#
# ---- 「神级」模板的来源（关键：没有任何一个值是编出来的）----
#
# 下面这行逐格抄自一份【游戏自己生成、后来被拉到满值】的真实门客记录
# （测试存档里的「杭祺剑」），22 格里除 [0] ID、[1] 形象、[2] 姓名性别寿命外
# 全部原样保留。也就是说写进去的每个数值，游戏都已经成功加载过 ——
# 比照着含义表去「造」值安全得多。

MENKE_TEMPLATE = [
    'M1341854588317278717', '5|8|2|19', '杭祺剑|0|0|0|1|70|0|10|1|null',
    '21', '999', '999', '999', '999', '100', '0|null|null', '0', '100',
    '0', '999', '100', '999', '0', '-1', '3340', '21', '0', 'null',
]

# 真实存档里实际出现过的 (形象码, 性别) 组合。成对取用，绝不单独拼 ——
# 免得出现「男性立绘配女性标记」这种游戏自己从不会生成的状态。
MENKE_LOOKS = [
    ("9|7|2|8", "1"), ("17|25|2|0", "1"), ("6|28|2|6", "1"),
    ("5|26|0|3", "1"), ("5|8|2|19", "1"), ("3|4|0|7", "1"),
    ("1|15|1|18", "0"), ("17|17|2|0", "0"), ("13|6|0|8", "0"),
    ("7|27|2|11", "0"), ("3|19|2|14", "0"), ("3|5|0|8", "0"),
    ("19|19|1|4", "0"), ("14|27|0|19", "0"), ("6|5|2|16", "0"),
]

# 姓氏和名用字全部取自这份存档里真实出现过的人名，保证字体渲染和风格都不出戏
MENKE_SURNAMES = "丁伏华吕孙支朱李杭林纪莫陶马骆"
MENKE_GIVEN = "书佑俭儿凌凤刚剑可妍姝威娜娴婴媚守宗彦思恭惠慕敏敬文昂晨景松枝柳桃梦欢永海温滢炎熙爱猛玉琪璟祖祺竹箐素芳英荷虎超逸雄雨韵鹰"

# 历史谋士 / 名将名字池。
# 前 15 个是主打阵容；用完了（比如一次要 20 个门客）就往后面接着取，
# 再取完才回落到上面的随机取名。名字都不是 2 字就是 3 字，
# 和存档里真实人名的长度一致（李彦敬、庞华嫣 都是 3 字）。
MENKE_HISTORY_NAMES = [
    # —— 主打 15 个 ——
    "诸葛亮", "姜子牙", "张良", "韩信", "萧何",
    "陈平", "周瑜", "司马懿", "郭嘉", "荀彧",
    "贾诩", "庞统", "白起", "李靖", "刘伯温",
    # —— 备用 ——
    "孙武", "吴起", "管仲", "乐毅", "王翦",
    "蒙恬", "霍去病", "卫青", "李牧",
]

# 真实存档里见过的最高寿命（支景雄 = 99）
MENKE_LIFE_MAX = "99"

# 单次生成上限：防止有人手滑填 100000，把存档撑爆导致游戏反序列化超时
MENKE_MAX_PER_RUN = 50


# ---------------------------------------------------------------- 天赋 / 专精
#
# 这四个字段的位置是【读档核对】出来的，不是照抄文档：
# 写进存档 → 进游戏读档 → 面板显示与预期逐项对上，才固化成常量。
#
# 网上流传的那份「第3位/第4位/第12位」说法里，第3、第4位是对的，
# 专精ID 的位置是错的 —— 它说第 12 位，实际在信息串第 7 段；
# 写第 12 位面板纹丝不动，写第 7 段立刻变。
#
# 另外那份文档说「专精ID之后有连续6个熟练度数字」，实测不成立：
#   族人 40 个无专精 vs 李思(专精=6)：只有 [33] 一格干净分离
#   门客 13 个无专精 vs 丁永超/陶凌书：只有 [16] 一格干净分离
# 真要是六个熟练度，不可能只有一个格子在两种布局里都干净分离。
# 所以熟练度是【一个】数字，跟唯一的专精一一对应。
TALENT_NAMES = {0: "无", 1: "文学", 2: "武学", 3: "商业", 4: "艺术"}
SKILL_NAMES = {0: "无", 1: "巫", 2: "医", 3: "相", 4: "卜", 5: "媚", 6: "工"}

# 成员表的布局差异：门客 22 格、族人 43 格，信息串和熟练度都不在同一格，
# 但信息串内部的段号是一致的（天赋=第3段、潜力=第4段、专精=第7段）。
MEMBER_LAYOUT = {
    "MenKe_Now": {
        "label": "门客", "info": 2, "prof": 16,
        "seg_talent": 2, "seg_potential": 3, "seg_skill": 6,
        "verified": True,      # 真机读档确认过
    },
    "Member_now": {
        "label": "族人", "info": 4, "prof": 33,
        "seg_talent": 2, "seg_potential": 3, "seg_skill": 6,
        "verified": False,     # 靠 40:1 样本比对推出，尚未真机确认
    },
}


def menke_all_ids(data) -> set:
    """把存档里出现过的所有 M-ID 都捞出来（不只在门客里），用于查重。

    直接扫 JSON 文本而不是遍历结构 —— 因为 M-ID 还会以 'M354|M544' 这种
    管道串的形式嵌在字段里，遍历结构容易漏掉。
    """
    return set(re.findall(r"M\d{1,25}", json.dumps(data, ensure_ascii=False)))


def menke_new_id(existing: set) -> str:
    """造一个全新的门客 ID：M + 19 位十进制数。

    故意压在 19 位（< 2^63-1 = 9223372036854775807），这样不管游戏内部是按
    有符号还是无符号 64 位整数来解析都不会溢出。真实存档里 19 位和 20 位的 ID
    都有（20 位那个其实已经超过 long 上限了），19 位是更保守的选择。
    """
    while True:
        mid = "M" + str(random.randint(10 ** 18, 9223372036854775807))
        if mid not in existing:
            existing.add(mid)          # 同一个批次里也不许重复
            return mid


def menke_new_name(existing: set) -> str:
    """从真实人名的姓氏/用字池里拼一个新名字，1 或 2 个字的名。"""
    for _ in range(500):
        given = "".join(random.choice(MENKE_GIVEN)
                        for _ in range(random.choice((1, 2))))
        name = random.choice(MENKE_SURNAMES) + given
        if name not in existing:
            existing.add(name)
            return name
    raise RuntimeError("名字池里凑不出不重复的名字了")


def menke_build_row(template: list, name: str, look: str, gender: str,
                    life: str = MENKE_LIFE_MAX, talent=None,
                    potential=None, skill=None, proficiency=None) -> list:
    """照模板造一条门客记录。

    只动这些格：[0] ID、[1] 形象、[2] 里的姓名/性别/寿命/天赋ID/天赋潜力/专精ID、
    [16] 熟练度。传 None 表示「这一项保持模板原值」。
    """
    row = list(template)
    row[1] = look
    parts = str(template[2]).split("|")
    parts[0] = name
    parts[4] = gender          # 性别
    parts[5] = life            # 寿命
    if talent is not None:
        parts[2] = str(talent)         # 第 3 段：天赋类型ID
    if potential is not None:
        parts[3] = str(potential)      # 第 4 段：天赋潜力值
    if skill is not None:
        parts[6] = str(skill)          # 第 7 段：专精显示ID
    row[2] = "|".join(parts)
    if proficiency is not None:
        row[16] = str(proficiency)     # 行[16]：熟练度
    menke_validate_row(row)
    return row


def menke_validate_row(row: list) -> None:
    """把协议文档里列的每一条「改了存档就废」的红线都做成断言。"""
    if not isinstance(row, list) or len(row) != 22:
        raise ValueError(f"门客记录必须是 22 格，现在是 {len(row)} 格")
    if not str(row[0]).startswith("M") or not str(row[0])[1:].isdigit():
        raise ValueError(f"门客 ID 格式不对: {row[0]!r}")
    if len(str(row[2]).split("|")) != 10:
        raise ValueError(f"基本信息串必须 10 段: {row[2]!r}")
    if not str(row[2]).endswith("|null"):
        raise ValueError(f"基本信息串必须以 |null 收尾: {row[2]!r}")
    if row[8] not in ("98", "99", "100"):
        raise ValueError(f"第 8 格应在 98~100，现在是 {row[8]!r}")
    if row[14] != "100":
        raise ValueError(f"第 14 格必须恒为 100，现在是 {row[14]!r}")
    if row[20] != "0":
        raise ValueError(f"第 20 格必须恒为 0，现在是 {row[20]!r}")
    if row[21] != "null":
        raise ValueError(f"第 21 格必须恒为 null，现在是 {row[21]!r}")
    if str(row[1]).count("|") != 3:
        raise ValueError(f"形象码必须是 4 段: {row[1]!r}")


# 「自动铺开」哨兵：天赋在 1–4、专精在 1–6 之间轮着给，
# 这样一次生成的一批人能覆盖全部四种天赋和六种技能。
AUTO_TRAIT = "__auto__"


def trait_value(raw, low, high, label):
    """解析一个天赋/专精参数。返回 None = 这一项不动，AUTO_TRAIT = 自动铺开。"""
    s = str(raw).strip()
    if s == "" or s.lower() in ("keep", "none", "-1", "不变", "不改", "不动"):
        return None
    if s.lower() in ("auto", "自动", AUTO_TRAIT):
        return AUTO_TRAIT
    try:
        v = int(float(s))
    except (TypeError, ValueError):
        raise ValueError(f"{label} 必须是数字（0–{high}），收到 {raw!r}") from None
    if not (low <= v <= high):
        raise ValueError(f"{label} 只能在 {low}–{high} 之间，收到 {v}")
    return v


def list_members(data) -> list:
    """把存档里所有成员摊平成列表，供图形界面显示和勾选。"""
    out = []
    for fname, lay in MEMBER_LAYOUT.items():
        bucket = (data.get(fname) or {}).get("value")
        if not isinstance(bucket, list):
            continue
        for i, row in enumerate(bucket):
            if not isinstance(row, list) or len(row) <= lay["prof"]:
                continue
            seg = str(row[lay["info"]]).split("|")
            if len(seg) < 7:
                continue
            out.append({
                "field": fname, "index": i, "name": seg[0],
                "kind": lay["label"], "id": row[0],
                "age": row[3] if len(row) > 3 else "",
                "gender": seg[4], "life": seg[5],
                "talent": seg[2], "potential": seg[3],
                "skill": seg[6], "proficiency": str(row[lay["prof"]]),
                "verified": lay["verified"],
            })
    return out


def op_set_traits(data, op: dict, params: dict, changes: list, dry: bool) -> int:
    """给成员批量设「天赋」和「专精技能」四件套。

    字段位置见文件顶部注释，四项都在真机读档核对过：写进去后面板逐项按预期变化。
    任何一项传空 / keep / -1 表示「这一项不动」；传 auto 表示自动铺开。

    返回有改动的成员行数。
    """
    talent = trait_value(params.get(op.get("talent_param", "talent"), ""), 0, 4, "天赋ID")
    potential = trait_value(params.get(op.get("potential_param", "potential"), ""), 0, 100, "天赋潜力")
    skill = trait_value(params.get(op.get("skill_param", "skill"), ""), 0, 6, "专精ID")
    proficiency = trait_value(params.get(op.get("prof_param", "proficiency"), ""), 0, 100, "熟练度")

    if all(v is None for v in (talent, potential, skill, proficiency)):
        raise ValueError("天赋/潜力/专精/熟练度四项都是空的，没东西可改")

    want_names = [n.strip() for n in
                  str(params.get(op.get("names_param", "names"), ""))
                  .replace("，", ",").split(",") if n.strip()]

    scope = str(params.get(op.get("scope_param", "scope"), "all")).strip().lower()
    if scope in ("menke", "门客", "1"):
        fields = ["MenKe_Now"]
    elif scope in ("member", "族人", "family", "2"):
        fields = ["Member_now"]
    else:
        fields = list(MEMBER_LAYOUT)

    rows_touched = 0
    k = 0                                   # auto 铺开用的连续计数器，跨表接续
    for fname in fields:
        lay = MEMBER_LAYOUT[fname]
        bucket = (data.get(fname) or {}).get("value")
        if not isinstance(bucket, list):
            continue
        for i, row in enumerate(bucket):
            if not isinstance(row, list) or len(row) <= lay["prof"]:
                continue
            info = str(row[lay["info"]])
            seg = info.split("|")
            if len(seg) < 7:
                continue
            name = seg[0]
            if want_names and name not in want_names:
                continue

            t = (1 + k % 4) if talent is AUTO_TRAIT else talent
            s = (1 + k % 6) if skill is AUTO_TRAIT else skill
            k += 1

            touched = False
            new_seg = list(seg)

            if t is not None and new_seg[lay["seg_talent"]] != str(t):
                new_seg[lay["seg_talent"]] = str(t)
                touched = True
            if potential is not None and new_seg[lay["seg_potential"]] != str(potential):
                new_seg[lay["seg_potential"]] = str(potential)
                touched = True
            if s is not None and new_seg[lay["seg_skill"]] != str(s):
                new_seg[lay["seg_skill"]] = str(s)
                touched = True

            if touched:
                changes.append(Change(f"{fname}.value[{i}][{lay['info']}]（{name}）",
                                      info, "|".join(new_seg)))
                if not dry:
                    row[lay["info"]] = "|".join(new_seg)

            old_p = str(row[lay["prof"]])
            if proficiency is not None and old_p != str(proficiency):
                changes.append(Change(
                    f"{fname}.value[{i}][{lay['prof']}]（{name} 熟练度）",
                    old_p, str(proficiency)))
                if not dry:
                    row[lay["prof"]] = str(proficiency)
                touched = True

            if touched:
                rows_touched += 1

    return rows_touched


def op_add_retainers(data, op: dict, params: dict, changes: list, dry: bool) -> int:
    """往 MenKe_Now.value 里追加 N 条神级门客。"""
    path = op.get("path", "MenKe_Now.value")
    bucket = get_path(data, path)
    if not isinstance(bucket, list):
        raise TypeError(f"{path} 不是列表，无法追加门客")

    count = int(params.get(op.get("count_param", "count"), 10))
    if count <= 0:
        return 0
    if count > MENKE_MAX_PER_RUN:
        raise ValueError(
            f"一次最多生成 {MENKE_MAX_PER_RUN} 个门客（你要 {count} 个）—— "
            f"门客太多会让存档体积暴涨，游戏读档可能超时")
    if len(bucket) + count > MENKE_MAX_PER_RUN * 2:
        raise ValueError(
            f"存档里已经有 {len(bucket)} 个门客，再加 {count} 个会超过 "
            f"{MENKE_MAX_PER_RUN * 2} 的安全上限")

    # 用户可以在菜单里直接指定名字，用逗号分隔
    wanted = [n.strip() for n in str(params.get(op.get("names_param", "names"), ""))
              .replace("，", ",").split(",") if n.strip()]

    # 取名方式：history=历史谋士池 / random=从存档人名的姓氏+用字里随机拼
    name_mode = str(params.get(op.get("mode_param", "name_mode"), "random")).strip().lower()

    # 天赋 / 专精：默认 auto 自动铺开 —— 一批门客分别拿到不同的天赋和技能，
    # 六种技能（巫医相卜媚工）都有人会，游戏里那些「需有【卜】技能的门客」
    # 之类的功能才用得上。传空 / keep 则不设。
    talent = trait_value(params.get(op.get("talent_param", "talent"), "auto"), 0, 4, "天赋ID")
    potential = trait_value(params.get(op.get("potential_param", "potential"), 100), 0, 100, "天赋潜力")
    skill = trait_value(params.get(op.get("skill_param", "skill"), "auto"), 0, 6, "专精ID")
    proficiency = trait_value(params.get(op.get("prof_param", "proficiency"), 100), 0, 100, "熟练度")

    ids = menke_all_ids(data)
    names = set()
    for e in bucket:
        if isinstance(e, list) and len(e) > 2:
            names.add(str(e[2]).split("|")[0])

    # 历史名字池：先剔掉存档里已经有人用掉的（新生成的、以及原有门客/族人）
    pool = [n for n in MENKE_HISTORY_NAMES if n not in names]
    if name_mode.startswith("hist") and len(pool) < count and not wanted:
        print(f"  [提示] 历史名字池剩 {len(pool)} 个，不够 {count} 个，"
              f"多出来的用随机名字补。")

    made = 0
    used = []
    # ⚠ base 必须在循环【外面】取。以前每轮都算 len(bucket) + i，
    #   而 bucket 在非 dry-run 下每轮都变长 —— 等于索引每次跳 2，
    #   形象码和改动路径的下标都会错位。锁死 base 才是对的。
    base = len(bucket)
    for i in range(count):
        if i < len(wanted):
            name = wanted[i]
            names.add(name)
        elif name_mode.startswith("hist") and pool:
            name = pool.pop(0)
            names.add(name)
        else:
            name = menke_new_name(names)
        used.append(name)
        idx = base + i
        look, gender = MENKE_LOOKS[idx % len(MENKE_LOOKS)]
        # auto 铺开：1–4 轮天赋、1–6 轮专精（+1 是为了避开 0=无）
        t = (1 + idx % 4) if talent is AUTO_TRAIT else talent
        s = (1 + idx % 6) if skill is AUTO_TRAIT else skill
        row = menke_build_row(MENKE_TEMPLATE, name, look, gender,
                              talent=t, potential=potential,
                              skill=s, proficiency=proficiency)
        row[0] = menke_new_id(ids)
        menke_validate_row(row)

        changes.append(Change(
            f"{path}[{idx}]", "（空）",
            f"{name}  {row[1]}  性别{row[2].split('|')[4]}  "
            f"寿命{row[2].split('|')[5]}  四维{row[4]}/{row[5]}/{row[6]}/{row[7]}  "
            f"天赋{TALENT_NAMES.get(t, '无')}  "
            f"专精{SKILL_NAMES.get(s, '无')}({row[16]})"))
        if not dry:
            bucket.append(row)
        made += 1

    if used:
        print(f"  名字：{'、'.join(used)}")

    # 收尾自检：格数、ID 唯一、固定格
    if not dry:
        for e in bucket:
            menke_validate_row(e)
        seen = [str(e[0]) for e in bucket]
        if len(seen) != len(set(seen)):
            raise ValueError("门客数组里出现了重复 M-ID，已放弃写入")
    return made


def op_max_all_items(data, op: dict, params: dict, changes: list, dry: bool) -> int:
    """把仓库里【每一种】物品的数量统一拉到指定值。

    默认带 only_up 保护：只补不足的，已经比目标多的【原样不动】。
    这个默认值很要紧 —— 真实存档里粮食本来就有 5005 万，
    无脑「设为 999 万」会把它砍掉 4000 万，正是当年 money 预设踩过的那个坑。
    想强制降下来，把 only_up 传 0。
    """
    path = op.get("path", "Prop_have.value")
    bucket = get_path(data, path)
    if not isinstance(bucket, list):
        raise TypeError(f"{path} 不是列表")

    target = int(float(params.get(op.get("value_param", "value"), 9999999)))
    if target < 0:
        raise ValueError(f"目标数量不能是负数：{target}")
    flag = str(params.get(op.get("only_up_param", "only_up"), "1")).strip().lower()
    only_up = flag not in ("0", "false", "no", "否", "不", "no")

    n = 0
    skipped = 0
    for row in bucket:
        if not (isinstance(row, list) and len(row) >= 2):
            continue
        try:
            cur = int(float(row[1]))
        except (TypeError, ValueError):
            continue                      # 数量不是数字的条目直接不碰
        new = max(cur, target) if only_up else target
        if new == cur:
            skipped += 1
            continue
        changes.append(Change(f"{path}[物品 {row[0]}]", row[1], str(new)))
        if not dry:
            row[1] = str(new)
        n += 1
    if skipped:
        print(f"  （{skipped} 种物品已经达到或超过 {target}，按只增不减保护没动）")
    return n


def parse_item_spec(spec) -> list:
    """把 "169:10, 170:5" 解析成 [("169", 10), ("170", 5)]。

    容错（这几条都是被真实使用踩出来的）：
      · 中文逗号「，」、顿号「、」、全角冒号「：」都认
      · 只写了编号没写数量 → 数量按 1 算
        （以前这种会被 `if ":" in kv` 静默丢掉，用户以为加了其实没加）
      · 数量不是数字 → 明确报错，而不是抛 ValueError 崩一整条栈
    """
    if not spec:
        return []
    if isinstance(spec, dict):
        spec = ",".join(f"{k}:{v}" for k, v in spec.items())
    out = []
    for chunk in str(spec).replace("，", ",").replace("、", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk or "：" in chunk:
            k, _, v = chunk.replace("：", ":").partition(":")
            k, v = k.strip(), v.strip()
        else:
            k, v = chunk, "1"
        if not k:
            continue
        try:
            out.append((str(k), int(float(v))))
        except ValueError:
            raise ValueError(f"「{chunk}」里的数量 {v!r} 不是数字") from None
    return out


def apply_op(data, op: dict, params: dict, changes: list, dry: bool) -> int:
    """执行一条 op。返回实际改动条数。"""
    kind = op.get("type", "set")

    # ---- 特殊：往仓库塞物品 ----
    if kind == "add_items":
        bucket = get_path(data, op["path"])
        if not isinstance(bucket, list):
            raise TypeError(f"{op['path']} 不是列表")
        items = parse_item_spec(params.get("items"))
        if not items:
            raise ValueError('没看懂要加什么。格式是「编号:数量」，多种用逗号隔开，'
                             '例如 169:10, 170:5, 111:1')
        # ⚠ mode 的默认值必须是 add。以前菜单层用 startswith("a") 判断，
        #   中文用户打「增加」会被静默当成 set，表现就是「增加」变成了「调整」。
        m = str(params.get("mode", "add")).strip().lower()
        mode = "set" if m in ("set", "s", "2", "覆盖", "设定", "设成", "调整") else "add"
        n = 0
        for item_id, qty in items:
            item_id = str(item_id)
            found = None
            for row in bucket:
                if isinstance(row, list) and row and str(row[0]) == item_id:
                    found = row
                    break
            if found is None:
                changes.append(Change(f"{op['path']}[新增物品 {item_id}]",
                                      "（仓库里没有）", str(qty)))
                if not dry:                                 # dry-run 绝不改内存数据
                    bucket.append([item_id, str(qty)])      # 原格式：字符串对
            else:
                old = found[1]
                try:
                    newq = str(int(float(old)) + qty) if mode == "add" else str(qty)
                except ValueError:
                    newq = str(qty)
                verb = "累加" if mode == "add" else "覆盖"
                changes.append(Change(f"{op['path']}[物品 {item_id}]（{verb} {qty}）",
                                      old, newq))
                if not dry:
                    found[1] = newq
            n += 1
        return n

    # ---- 特殊：生成神级门客 ----
    if kind == "add_retainers":
        return op_add_retainers(data, op, params, changes, dry)

    # ---- 特殊：仓库每种物品一起拉满 ----
    if kind == "max_all_items":
        return op_max_all_items(data, op, params, changes, dry)

    # ---- 特殊：天赋 + 专精技能 ----
    if kind == "set_traits":
        return op_set_traits(data, op, params, changes, dry)

    # ---- 普通赋值 ----
    raw_text = (str(params[op["from_param"]]) if "from_param" in op
                else render_template(str(op.get("value", "")), params))
    try:
        old = get_path(data, op["path"])
    except (KeyError, IndexError, TypeError) as e:
        if op.get("optional", True):
            print(f"  [跳过] {op['path']} — {e}")
            return 0
        raise

    if "sub" in op:                       # 对分隔串里的第 k 段动手，如基本信息的「寿命」
        delim = op.get("delim", "|")
        parts = str(old).split(delim)
        k = op["sub"]
        if k >= len(parts):
            print(f"  [跳过] {op['path']} 只有 {len(parts)} 段，取不到第 {k} 段")
            return 0
        new = delim.join(parts[:k] + [raw_text] + parts[k + 1:])
        cmp_old = parts[k]
    else:
        new = coerce_like(old, raw_text, raw=op.get("raw", False))
        cmp_old = old

    if new == old:
        return 0

    # ---- 只增不减 / 只减不增 --------------------------------------
    # 「拉满」型预设最大的坑：它是绝对赋值。若玩家本来就有 9.8 亿铜钱，
    # 预设写 100 万反而是在削钱。only_up 让这类操作只升不降。
    if op.get("only_up") or op.get("only_down"):
        a_s, b_s = str(cmp_old), str(raw_text)
        if "cmp_sub" in op:               # 比较复合串里的第 n 段，如 "兵力|士气"
            d = op.get("delim", "|")
            n = op["cmp_sub"]
            aa, bb = a_s.split(d), b_s.split(d)
            a_s = aa[n] if n < len(aa) else ""
            b_s = bb[n] if n < len(bb) else ""
        try:
            a, b = float(a_s), float(b_s)
        except (TypeError, ValueError):
            pass                          # 不是数字就不做比较，照常写
        else:
            if op.get("only_up") and b <= a:
                return 0
            if op.get("only_down") and b >= a:
                return 0

    changes.append(Change(op["path"], old, new))
    if not dry:
        set_path(data, op["path"], new)
    return 1


# 自定义 job 的名字，见 run_jobs()。
CUSTOM_JOB = "__custom__"


def run_jobs(save, jobs, presets: dict, dry: bool = False):
    """
    执行一组「待改清单」。清单里每一项都是 (名字, 覆盖参数)：

      · 普通项 —— 名字是 presets.json 里的预设名，如 ("money", {"copper": "999"})
      · 特例   —— ("__custom__", {"path": "CGNum.value[0]", "value": "999"})
                  直接改某个字段，对应菜单的「自定义修改」

    这样「界面上点出来的需求」和「预设文件里的规则」就是同一种结构，
    两边不用各写一套。
    """
    changes: list = []
    for name, ov in jobs:
        if name == CUSTOM_JOB:
            path, val = ov["path"], str(ov["value"])
            old = get_path(save.data, path)
            new = coerce_like(old, val)
            if str(old) != str(new):
                changes.append(Change(path, old, new))
                if not dry:
                    set_path(save.data, path, new)
            continue
        changes += run_preset(save, name, presets, ov, dry=dry)
    return changes


def run_preset(save: Save, name: str, presets: dict, overrides: dict, dry: bool):
    if name not in presets:
        raise KeyError(f"没有名为 {name!r} 的预设。用 `presets` 子命令看全部。")
    p = presets[name]
    params = dict(p.get("params", {}))
    params.update(overrides)

    changes: list = []
    loops = p.get("foreach")
    if isinstance(loops, str):
        loops = [loops]
    if loops:
        # 支持多层遍历：{i} {j} {k} 分别对应第 1/2/3 层
        names = ("i", "j", "k")

        def walk(level: int, binding: dict):
            if level == len(loops):
                for op in p["ops"]:
                    op_i = dict(op)
                    for n, idx in binding.items():
                        op_i["path"] = op_i["path"].replace("{%s}" % n, str(idx))
                    apply_op(save.data, op_i, params, changes, dry)
                return
            path = loops[level]
            for n, idx in binding.items():
                path = path.replace("{%s}" % n, str(idx))
            container = get_path(save.data, path)
            if not isinstance(container, list):
                return
            for idx in range(len(container)):
                binding[names[level]] = idx
                walk(level + 1, binding)

        walk(0, {})
    else:
        for op in p["ops"]:
            apply_op(save.data, op, params, changes, dry)

    return changes


def disp_width(s: str) -> int:
    """中日韩字符占两个西文字符宽，用它来对齐表格。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, w: int) -> str:
    return s + " " * max(0, w - disp_width(s))


def cmd_keys(args):
    """
    列出顶层字段。

    「下标层数」这一列是关键：文档里 CityData_now 的 __type 是
    List<List<List<String>>>，所以必须写 value[0][0][0] —— 写成 value[0][0]
    拿到的是整个主城数组，而不是那个 "势力|兵力|士气|友好度" 串。
    层数直接由 __type 里 "List`1" 的出现次数数出来，不靠猜。
    """
    for p in find_gamedata(Path(args.target)):
        save = Save(p)
        print(f"\n=== {p} ===")
        if not isinstance(save.data, dict):
            print(f"  根节点是 {type(save.data).__name__}，非对象")
            continue
        print("  " + pad("字段", 26) + pad("下标层数", 14) + pad("形状", 16) + "元素类型")
        for k, v in save.data.items():
            t = v.get("__type", "") if isinstance(v, dict) else ""
            n = t.count("List`1")
            leaf = ("Int32" if "System.Int32" in t
                    else "String" if "System.String" in t else "?")
            if n == 0:
                lay, etype = "(标量)", leaf
            else:
                lay, etype = "[]" * n, f"List<{leaf}>"
            if isinstance(v, dict) and "value" in v:
                val = v["value"]
                shape = f"len={len(val)}" if isinstance(val, (list, str)) else f"={val!r}"
            else:
                shape = type(v).__name__
            print("  " + pad(k, 26) + pad(lay, 14) + pad(shape, 16) + etype)
        print("\n  注：[] 的个数就是 set/preset 里要写的 [i][j][k] 层数。")

MEMBER_FIELDS = [
    ("0  编号", None), ("1  形象", None), ("2  子嗣", None), ("3  居所", None),
    ("4  基本信息", None), ("5  性格/脸", None), ("6  年龄", None),
    ("7  文", None), ("8  武", None), ("9  商", None), ("10 艺", None),
    ("11 心情", None), ("12 身份/职务", None), ("13 功名", None),
    ("14 爵位/封地", None), ("15 状态", None), ("16 声誉", None),
    ("20 魅力", None), ("21 健康", None), ("22 家主", None),
    ("23 特殊标签", None), ("25 怀孕月", None), ("26 婚姻", None),
    ("27 计谋", None), ("30 体力", None), ("33 技能点", None), ("34 孕率", None),
]

def record_history(save, title, changes, bak) -> None:
    """把这次改动记进历史（供「撤销上一次改动」用）。

    历史模块出任何问题都绝不能连累写盘 —— 数据已经安全落盘了，
    记不上历史只是少了个便利功能，所以这里整段吞异常。
    """
    try:
        import history as hist
        hist.record(save.path, title, changes, bak)
    except Exception as e:                                    # pragma: no cover
        print(f"  （历史记录没写成，不影响存档：{e}）")

