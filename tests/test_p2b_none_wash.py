# -*- coding: utf-8 -*-
"""P2-b TDD: factor_correlation_analysis.py None 洗 0 修复 (K56 §二 独立单)

三处洗 0 (K56 §二 必须一起评估, 防"内存值 vs 文件值"新双源):
  L94  in-memory: `spearman(v1, v2) or 0.0`        → None 洗成 0.0 (内存)
  L104 打印层:    `if c is None: c = 0`            → 终端显示, 非数据, 保留合法
  L113 写入层:    `round(vv, 4) if vv else 0`      → None 洗成 0 (JSON 文件)

  只修 L113 不修 L94 → 内存=0.0 而文件=null, 造新双源 (K56 §二 第3点)。
  L94 + L113 一起修: in-memory 保留 None, 写 JSON 时 None→null, 打印层显示 0。

定性 (K55 §五 + 坐实): 当前 factor_correlation_matrix.json 529 格 0 None/0 个 0.0
  → L94/L113 的 None→0 洗在现数据上**不触发** (spearman 对 ≥100 样本 valid_factors
  几乎不返 None), 是**潜在假绿** (0 暗示"零相关", 未来接消费方时掩盖"不可算")。
  修复是防未来, 不改变现行 JSON 数值 (529 格全非零, round(x,4) 不变)。

seam: spearman() 纯函数行为 (喂受控 None 场景, 不重跑 500 文件)
       + L94/L113 源码不洗断言 (静态, 防回归)
"""
import ast
import json
import os
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = Path(ROOT) / "scripts" / "factor_correlation_analysis.py"


def _extract_spearman():
    """从源码提取 spearman 函数 (纯 math, 无外部依赖), 独立 exec。

    避免 import 全脚本触发顶层 500 文件跑 + 写 JSON 副作用 (R4c#1 先例)。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "spearman":
            fn_src = ast.get_source_segment(src, node)
            ns = {}
            exec(compile(fn_src, "<spearman>", "exec"), ns)
            return ns["spearman"]
    raise AssertionError("spearman 函数未在 factor_correlation_analysis.py 顶层找到")


# ── 行为: spearman 合法 None 输出 (不可算场景) ─────────────────────
def test_spearman_n_below_30_returns_none():
    """n<30 样本 → None (不可算), 不是 0.0。这是 L94 `or 0.0` 洗 0 的源头。"""
    spearman = _extract_spearman()
    xs = [float(i) for i in range(29)]
    ys = [float(i * 2) for i in range(29)]
    assert spearman(xs, ys) is None, "n<30 应返回 None (不可算)"


def test_spearman_zero_variance_returns_none():
    """den≤1e-15 (共线/零方差) → None, 不是 0.0。"""
    spearman = _extract_spearman()
    n = 40
    xs = [1.0] * n
    ys = [float(i) for i in range(n)]
    assert spearman(xs, ys) is None, "零方差 xs 应返回 None (den=0, 不可算)"


# ── 静态: L94 in-memory 不洗 0 (与 L113 一致, 防双源) ─────────────
def test_l94_in_memory_preserves_none():
    """L94: `spearman(v1, v2) or 0.0` 会把 in-memory None 洗成 0.0。

    修后: `spearman(v1, v2)` 保留 None。与 L113 写层 None 一致 (防"内存0.0/文件null"双源)。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "spearman(v1, v2) or 0.0" not in src, (
        "L94 in-memory 仍 `or 0.0` 洗 None→0.0, 与 L113 写层 None→null 不一致 "
        "(K56 §二 第3点: 只修写层不修内存=新双源)"
    )


def test_l113_write_layer_preserves_none():
    """L113: `if vv else 0` 把 None (且 0.0, falsy) 洗成 0 → JSON 无 null。

    修后: `round(vv, 4) if vv is not None else None` → None→null, 0.0→0.0 (正确)。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "round(vv, 4) if vv else 0" not in src, (
        "L113 写层仍 `if vv else 0`, None/0.0 全洗 0, JSON 无 null (假绿: 0 暗示零相关)"
    )
    # 正向: 修后写法存在 (None 保留 + is not None 判定, 不 falsy)
    assert "if vv is not None else None" in src, (
        "L113 未见 `if vv is not None else None` (None→null) 修复"
    )


def test_memory_and_file_none_consistent():
    """K56 §二 第3点守卫: L94 (内存) 与 L113 (文件) 的 None 处理一致。

    两者都必须保留 None (内存 None, 文件 null), 不许一个洗 0 一个保留。
    当前若 L94 已修(保留 None) 但 L113 未修(洗 0), 或反之 → 双源 → 本测试红。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    l94_washed = "spearman(v1, v2) or 0.0" in src        # L94 洗 0 (坏)
    l113_washed = "round(vv, 4) if vv else 0" in src      # L113 洗 0 (坏)
    assert not (l94_washed or l113_washed), (
        f"L94洗0={l94_washed} L113洗0={l113_washed} → 至少一处把 None 洗成 0, "
        f"内存值与文件值语义不一致 (新双源, K56 §二 第3点)"
    )


# ── 回归保护: 现行 JSON 数值不受影响 (529 格全非零, round 不变) ──
def test_rerun_would_not_change_existing_values():
    """修 L113 后, 现行 529 格非零值 round(x,4) 不变 (None 才变 null, 但现无 None)。

    静态验证: 现行 JSON 无 None/0.0 → 修法 (round(vv,4) if vv is not None else None)
    对每个现行值产出与旧法 (round(vv,4) if vv else 0) 相同。
    """
    jp = Path(ROOT) / "data" / "factor_correlation_matrix.json"
    if not jp.exists():
        return  # 未生成过, 无数值可比, 跳过 (合法)
    d = json.loads(jp.read_text(encoding="utf-8-sig"))
    cm = d.get("correlation_matrix", {})
    for row in cm.values():
        for kk, vv in row.items():
            if vv is None:
                continue  # 现无 None
            old = round(vv, 4) if vv else 0
            new = round(vv, 4) if vv is not None else None
            assert old == new, (
                f"修法改变现行值 {kk}={vv}: old={old} new={new} "
                "(若现行 JSON 有 0.0, falsy 洗 0 与 is-not-None 结果不同, 需人工确认)"
            )
