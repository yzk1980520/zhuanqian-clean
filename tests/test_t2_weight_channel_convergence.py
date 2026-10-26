# -*- coding: utf-8 -*-
"""test_t2_weight_channel_convergence.py — T2 回测/实盘 z-score 权重通道收敛断言 (2026-10-26, 老三)

任务单 T2 (R0): 回测链与实盘链的因子 z-score 权重源收敛到 factor_weights.json (单一真源)。
本测试为读侧消费断言 (§4.1-12 回授断言注册铁律): 写侧动作 = get_backtest_factor_weights()
通道落地 (core/pipeline/config_loader.py + backtest/__init__.py 引擎接线), 读侧断言 = 本文件。

先红后绿判据: 收敛前 config_loader 无 get_backtest_factor_weights → 测试 1 红
(通道缺失); 收敛后两通道同源于 factor_weights.json → 测试 1 绿, 数值零改动由测试 2 守护。
"""
import json
import os
import sys
from pathlib import Path

PROJECT = str(Path(__file__).resolve().parents[1])
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)


def test_backtest_channel_reads_live_single_source():
    """回测 z-score 权重通道必须与实盘通道同源 (factor_weights.json), 逐键相等。"""
    from core.pipeline.config_loader import get_backtest_factor_weights, get_factor_weights
    w_bt = get_backtest_factor_weights()
    w_live = get_factor_weights()
    assert w_bt == w_live, (
        "T2 通道分叉: get_backtest_factor_weights() 与 get_factor_weights() 不一致 — "
        "回测 z-score 权重必须读 factor_weights.json 单一真源, 不得引入第二数值源")
    # 返回浅拷贝: 调用方改写不得污染单一真源缓存
    w_bt["__pollution_probe__"] = 1.0
    assert get_factor_weights().get("__pollution_probe__") is None, (
        "get_backtest_factor_weights() 返回对象污染了 get_factor_weights() 缓存 — 必须返回拷贝")


def test_no_weight_values_introduced_by_channel():
    """通道收敛不得改动权重数值: 回测通道读出的权重必须与 factor_weights.json weights 段逐项相等。
    等价检查脚本在场性 (任务单步骤2 机判项) 一并以存在断言守护。
    """
    from core.pipeline.config_loader import get_backtest_factor_weights, clear_config_cache
    clear_config_cache()
    w_bt = get_backtest_factor_weights()
    clear_config_cache()
    doc = json.loads((Path(PROJECT) / "factor_weights.json").read_text(encoding="utf-8-sig"))
    expected = {k: float(v) for k, v in doc["weights"].items()}
    assert w_bt == expected, (
        "T2 红线违反: 回测 z-score 通道数值与 factor_weights.json weights 段不一致 — "
        "本任务只对齐通道, 不得改动任何权重数值")
    # v2.6 契约: 4 活跃因子 (数值起点由 132d 门禁裁定, 此处只做守护断言)
    active = {k: v for k, v in w_bt.items() if v != 0}
    assert active == {"chg10": 2.0, "overnight_sum20": 1.6, "chg5": 1.4, "momentum_20": 0.5}, (
        "v2.6 活跃因子集合/数值漂移: %s" % active)
    # 证据链在场: 等价检查脚本 (36 股日对, 阈值 0.01)
    p = os.path.join(PROJECT, "scripts", "check_weight_equivalence.py")
    assert os.path.exists(p), "缺少等价检查脚本 %s" % p
    src = open(p, encoding="utf-8").read()
    assert "THRESHOLD = 0.01" in src and "get_backtest_factor_weights" in src
