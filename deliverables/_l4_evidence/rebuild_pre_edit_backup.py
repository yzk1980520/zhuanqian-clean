#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 scripts/auto_live_pipeline.py.bak_20261019_laoliu 为真正的"改前原始版"。

背景 (2026-10-19):
  fix-factor-layer 03:41 改前备份 -> 03:46:05 被 fix-live-filter 同名整文件备份
  覆盖 (内容变成本人 A-D 中间态)。本脚本从改后快照反向重建改前原始版:
    1. 还原 fix-live-filter 的 P0-A 三处 (非本人改动, 本人改前不存在);
    2. 逆转本人 6 处 L4 编辑 (纯插入/单行签名替换);
    3. 保留老六 2026-10-18 的 P0/隐患1 修复 (本人改前已在文件里)。
  所有定位用唯一标记 + 断言, 不用绝对行号 (文件被同行实时改写, 行号会漂);
  任一断言失败即中止, 不写盘。输入为快照而非活动文件, 避免重建期间文件继续漂移。
"""
import ast
import difflib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SNAP = REPO / "deliverables" / "_l4_evidence" / "_alp_snapshot_20261019_0407.py.txt"  # 后缀非 .py: 避免仓库扫描型用例(重复定义/代码规范)把它当源码扫
DST = REPO / "scripts" / "auto_live_pipeline.py.bak_20261019_laoliu"
REF = REPO / "scripts" / "auto_live_pipeline.py.bak_20261018_laoliu"  # 老六改前备份, 交叉校验用

lines = SNAP.read_text(encoding="utf-8").splitlines(keepends=True)
ops = []


def find_one(pred, desc):
    idxs = [i for i, l in enumerate(lines) if pred(l)]
    assert len(idxs) == 1, f"[{desc}] 期望唯一命中, 实际 {len(idxs)} 处"
    return idxs[0]


def cut(desc, pred, before, count, after_check=None):
    """删除命中行及其前后相邻行。before=向上删几行, count=从命中行起删几行。"""
    m = find_one(pred, desc)
    lo, hi = m - before, m + count
    assert lo >= 0 and hi <= len(lines), f"[{desc}] 越界"
    if after_check:
        after_check(lines[lo:hi])
    del lines[lo:hi]
    ops.append(f"{desc}: -{hi - lo} 行")


# ── 1. 还原 P0-A (fix-live-filter, 04:01:37 落盘) ──────────────────────
m = find_one(lambda l: l.strip() == "from tdx_data import is_tradable_code, load_name_cache", "P0-A import")
lines[m] = "    from tdx_data import is_tradable_code\n"
ops.append("P0-A import: 还原")


def _chk_name_cache(block):
    assert "名称表" in block[0] and "同一把钥匙" in block[1], "name_cache 注释块不符"
    assert block[3].strip().startswith('print(f"名称表'), "name_cache print 不符"
    assert block[4].strip() == "", "name_cache 后缺空行"


cut("P0-A name_cache 块", lambda l: l.strip() == "name_cache = load_name_cache()",
    before=2, count=3, after_check=_chk_name_cache)  # 2 注释 + 调用 + print + 空行

m = find_one(lambda l: 'if not is_tradable_code(code, name_cache.get(code, "")):' in l, "P0-A call site")
assert "name 必须传" in lines[m - 2] and "D8 老大拍板" in lines[m - 3], "call site 注释块不符"
lines[m - 3:m + 1] = [
    "        # 主板前缀白名单剔除 (Kimi 拍板): 创业板/科创/北证/ETF 不进评分\n",
    "        if not is_tradable_code(code):\n",
]
ops.append("P0-A call site: 还原")

# ── 2. 逆转本人 L4 编辑 ─────────────────────────────────────────────────
m = find_one(lambda l: l.startswith("def _compute_factor_score(inds, factor_weights, exceptions, ic_signs=None):"), "A1 签名")
lines[m] = "def _compute_factor_score(inds, factor_weights, exceptions):\n"
ops.append("A1 签名: 还原")


def _chk_a2(block):
    assert "符号未知(缺失/0)置 0 不启用" in block[1] and "杜绝出现第二条无符号防护的加权路径" in block[2], "A2 docstring 不符"


cut("A2 docstring", lambda l: l.strip().startswith("ic_signs 传入 {name: ic} 时按 IC 符号定权重方向"),
    before=0, count=3, after_check=_chk_a2)


def _chk_a3_unused():
    pass


m = find_one(lambda l: l.strip() == "if ic_signs is not None:", "A3")
_blk = lines[m:m + 7]  # 5 行代码 + 1 空行 + 块后首行(仅校验不删)
assert "apply_ic_sign(factor_weights, ic_signs)" in _blk[1] and "for k in skipped:" in _blk[2], "A3 块不符"
assert _blk[5].strip() == "" and _blk[6].lstrip().startswith("raw_values = {}"), "A3 块后结构不符"
del lines[m:m + 6]
ops.append("A3 ic_signs 块: -6 行")

m = find_one(lambda l: l.strip() == "#  因子层硬开关 + IC 符号处理 (2026-10-19 L4 断裂修复)", "B banner")
assert "──" in lines[m - 1], "B banner 首行不符"
m2 = find_one(lambda l: l.startswith("def run_stock_selection(top_n=10, scan_range=3000, factor_layer=None):"), "B 签名")
assert m2 > m, "B 签名应在 banner 之后"
lines[m - 1:m2 + 1] = ["def run_stock_selection(top_n=10, scan_range=3000):\n"]
ops.append(f"B helpers 块: -{m2 + 3 - m} 行 (banner+3 函数+原签名还原)")

m = find_one(lambda l: l.strip().startswith("5. (2026-10-19 L4) 因子层硬开关 factor_layer_enabled"), "C1 items")
assert "6. (2026-10-19 L4/Task#4)" in lines[m + 2], "C1 item6 不符"
assert lines[m + 4].strip() == "" and lines[m + 5].strip().startswith("参数 factor_layer:"), "C1 结构不符"
del lines[m:m + 4]      # items 5/6 共 4 行
del lines[m:m + 2]      # 本人插入的空行 + 参数 factor_layer 行 (改前 item4 与 """ 相邻, 无空行)
ops.append("C1 docstring items5/6+空行+参数行: -6 行")


def _chk_c2_unused():
    pass


m = find_one(lambda l: l.strip() == "factor_layer_on, factor_layer_src = resolve_factor_layer_enabled(factor_layer)", "C2")
_blk = lines[m - 1:m + 6]  # 注释 + 6 行 + 空行 = 8? 实为 7 行: 注释/resolve/print/if/print/权重置空/空行
assert "L4 硬开关" in _blk[0] and "resolve_factor_layer_enabled(factor_layer)" in _blk[1], "C2 块头不符"
assert _blk[5].strip() == "factor_weights = {}", "C2 块尾不符"
assert _blk[6].strip() == "" and lines[m + 6].strip() == "# 加载历史数据", "C2 块后结构不符"
del lines[m - 1:m + 6]
ops.append("C2 开关打印块: -7 行")


def _chk_d_unused():
    pass


m = find_one(lambda l: l.strip() == "ic_signs = load_factor_ic_signs()", "D")
_blk = lines[m - 3:m + 9]  # 3 注释 + 9 行代码 = 12 行
assert "Task#4 符号处理" in _blk[0], "D 块头注释不符"
assert "load_factor_ic_signs()" in _blk[3] and "apply_ic_sign(factor_weights, ic_signs)" in _blk[4], "D 块调用不符"
assert "符号未知 -> 权重置 0 不启用" in _blk[11], "D 块尾不符"
assert lines[m + 9].lstrip().startswith("fw_keys = "), "D 块后应为 fw_keys"
del lines[m - 3:m + 9]
ops.append("D 融合块 Task#4: -12 行")

m = find_one(lambda l: "--factor-layer" in l and "add_argument" in l, "E CLI")
assert "--no-factor-layer" in lines[m + 2] and "add_argument" in lines[m + 2], "E CLI 结构不符"
del lines[m:m + 4]
ops.append("E CLI 参数: -4 行")

m = find_one(lambda l: "run_stock_selection(args.top_n, args.scan_range, factor_layer=args.factor_layer)" in l, "F 调用处")
lines[m] = lines[m].replace("run_stock_selection(args.top_n, args.scan_range, factor_layer=args.factor_layer)",
                            "run_stock_selection(args.top_n, args.scan_range)")
ops.append("F 调用处: 还原")

# ── 3. 校验 ─────────────────────────────────────────────────────────────
text = "".join(lines)
for dead in ["factor_layer", "apply_ic_sign", "ic_signs", "resolve_factor_layer_enabled",
             "load_name_cache", "name_cache", "factor_ic_sign_unknown", "load_factor_ic_signs"]:
    n = text.count(dead)
    assert n == 0, f"重建结果仍含 L4/P0-A 标记 {dead!r} x{n}"
for keep, least in [("_dead_factors", 2), ("factor_dead_universe", 1), ("隐患1", 2),
                    ("config.json -> factor_weights", 1), ("factor_weights_source_note", 1)]:
    n = text.count(keep)
    assert n >= least, f"重建结果丢失老六 10-18 修复标记 {keep!r} (仅 {n})"
ast.parse(text)  # 语法必须合法

ref_text = REF.read_text(encoding="utf-8")
delta = list(difflib.unified_diff(ref_text.splitlines(), text.splitlines(),
                                  fromfile="bak_20261018_laoliu(老六改前)", tofile="重建结果(本人改前)", lineterm=""))
print(f"快照 {len(SNAP.read_text(encoding='utf-8').splitlines())} 行 -> 重建 {len(lines)} 行")
print("操作明细:")
for o in ops:
    print(f"  - {o}")
print(f"\n与老六 10-18 备份的差异 ({len(delta)} 行 diff), 应恰为老六改后修复集:")
print("\n".join(delta))

DST.write_text(text, encoding="utf-8", newline="\n")  # newline="\n": Windows 上 write_text 默认会把 \n 转 \r\n, 原文件是 LF, 必须显式锁定
print(f"\n✅ 已写入 {DST} ({len(lines)} 行)")
