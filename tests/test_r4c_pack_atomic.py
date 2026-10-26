# -*- coding: utf-8 -*-
"""R4c 打包批 #3/#4/#6 TDD: 数据池派生/研究 artifact 裸 open('w') 改 atomic_dump (K55 §三 批准, #5 拆出停手)

写口选择判据 (K55 §六, 已进 docs/成员写入输出标准 §1.2):
  台账(有读旧+追加/合并语义) → update_json; 可再生覆盖型(无读旧/无条件覆盖/读侧须零改动) → atomic_dump。
  #3/#4/#6 全是"数据池派生/研究 artifact 全量覆盖"(原始=open('w') 无条件覆盖, 不读旧文件) → 用 atomic_dump
  (纯全量替换+原子, 零读侧改动, 行为 100% 等同原裸写; 若误用 update_json 会引入"旧文件损坏→拒写"新副作用)。

TDD 设计: 数据池脚本顶层 import akshare/pandas(网络副作用), 行为 seam 不 import 全脚本。
  S3 静态: 三处写口源码应走 atomic_dump 且无裸 open('w') 直写目标文件 → 改后 3 处全绿
  S1/S2 语义: atomic_dump 全量替换(旧字段不残留) + 与原裸写产出一致(normalize) → 验证判据正确
"""
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 打包批 3 项: (文件, 目标 json 名, 标记 atomic_dump 调用串)
ITEMS = [
    ("auto_data_refresh.py", "akshare_stock_pool.json", 'atomic_dump(mapping, str(DATA_DIR / "akshare_stock_pool.json"))'),   # #3
    ("auto_data_refresh.py", "industry_mapping.json",   'atomic_dump(mapping, str(DATA_DIR / "industry_mapping.json"))'),     # #4
    ("factor_correlation_analysis.py", "factor_correlation_matrix.json",
     'atomic_dump(output, "data/factor_correlation_matrix.json")'),                                                              # #6
]


def _src(rel):
    # 2026-10-24 T051 C4 对齐: auto_data_refresh.py 2026-10-23 S4 基地化归档至
    # archive/scripts-20261023/ (活跃层 scripts/ 不再存在) → 活跃层优先, 归档层兜底
    active = os.path.join(ROOT, "scripts", rel)
    if os.path.exists(active):
        with open(active, encoding="utf-8") as f:
            return f.read()
    archived = os.path.join(ROOT, "archive", "scripts-20261023", rel)
    with open(archived, encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("rel,target,atomic_call", ITEMS)
def test_s3_write_ports_use_atomic_dump_not_bare_open(rel, target, atomic_call):
    """S3(静态): 三处写口均走 atomic_dump, 且无裸 open('w') 直写该目标文件。"""
    src = _src(rel)
    assert atomic_call in src, f"[{rel}] 未走 atomic_dump 写 {target}: 缺 {atomic_call!r}"
    bare = f'open(DATA_DIR / "{target}", "w"'
    bare2 = f'open("data/{target}", "w"'
    assert bare not in src, f"[{rel}] {target} 仍裸 open('w')"
    assert bare2 not in src, f"[{rel}] {target} 仍裸 open('w') (data/ 前缀式)"


def test_atomic_dump_full_replace_semantics(tmp_path):
    """S1/S2(语义, 判据验证): atomic_dump = 全量覆盖非 merge, 旧多余字段不残留, 产出=输入 dict。

    坐实"可再生覆盖型用 atomic_dump"判据: 盘上旧文件含 STALE 字段 → atomic_dump 后不残留。
    不 import 数据脚本(避免 akshare 网络副作用), 直接测 atomic_json.atomic_dump 本身。
    """
    import sys
    sys.path.insert(0, ROOT)
    from atomic_json import atomic_dump
    target = tmp_path / "pool.json"
    target.write_text(json.dumps({"STALE_FIELD": "old", "keep": 1}), encoding="utf-8")
    atomic_dump({"stocks": {"sh600519": {"name": "贵州茅台"}}, "keep": 2}, str(target))
    after = json.loads(target.read_text(encoding="utf-8"))
    assert "STALE_FIELD" not in after, f"全量替换失效: 旧字段残留 → 误用了 merge 语义: {after}"
    assert after["keep"] == 2 and "stocks" in after
    assert not [x for x in os.listdir(tmp_path) if x.endswith(".tmp")], "残留 tmp"


def test_data_pool_targets_no_bare_open_remains_anywhere():
    """S4(打包批收尾): 全 scripts/ 下这三个目标文件名不再有裸 open('w') 残留(排除 .bak)。"""
    import glob
    for rel, target, _ in ITEMS:
        for py in glob.glob(os.path.join(ROOT, "scripts", "*.py")):
            base = os.path.basename(py)
            if ".bak_" in base:
                continue
            if target in ("akshare_stock_pool.json",):
                # 注意: monday_auto_exec.py(#5) 仍裸写 scripts/data/ 同目标名 — #5 拆出停手, 本项只验 #3/#4/#6 归属文件
                if base == "monday_auto_exec.py":
                    continue
            src = _src(base) if os.path.exists(py) else ""
            assert f'open(DATA_DIR / "{target}", "w"' not in src, f"{base} 仍裸写 {target}"
            assert f'open("data/{target}", "w"' not in src, f"{base} 仍裸写 data/{target}"
