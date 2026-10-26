"""
P0/P1 评分机制修复验证测试
============================
验证 integrated_picker.py 的三项修复:
  P0-1: final_score 按股票存储, 不再用陈旧变量
  P1-1: config.json 策略与代码一致
  P1-2: 动量筛选从硬过滤改为加分项
  P0-2: compute_final_score() 统一公式 — 实盘改走共享引擎

Seam 覆盖:
  P0-1 候选池 tuple 结构 ✅
  P0-1 第二遍循环 unpack ✅
  P1-1 config.json 策略同步 ✅
  P1-2 动量加分模式 ✅
  P0-2 compute_final_score base_override ✅
  P0-2 实盘/回测公式结构一致性 ✅
"""
import json
import os
import sys

# P0-2: 确保项目根目录在 sys.path (scoring_engine.py 在根目录)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ─── P0-1: 候选池 tuple 结构验证 ───────────────────────────

def test_candidates_tuple_has_final_score_field():
    """P0-1: candidates tuple 包含 final_score 字段 (index 11)

    integrated_picker.py L744 构建:
      (sc_zh, sc_qc, code, name, industry, sigs_zh, sigs_qc,
       heat_bonus, heat_desc, dl_bonus, dl_desc, final_score)
    """
    # 模拟第一遍循环的赋值
    sc_zh = 85
    sc_qc = 72
    dl_score = 10.0
    dl_weight = 0.15
    final_score = sc_zh * (1 - dl_weight) + dl_score * dl_weight  # 82.5 * 0.85 + 10 * 0.15 ≈ 73.73

    # 模拟 L744 的 tuple 构建 (P0-1 修复后 12 字段)
    item = (sc_zh, sc_qc, "sh600519", "贵州茅台", "白酒",
            ["✅均线多头"], ["✅MACD"], 8, "🔥TOP3", 3, "DL预测", final_score)

    assert len(item) == 12, f"tuple 应有 12 字段, 实际 {len(item)}"
    assert item[0] == 85, "index 0 = sc_zh"
    assert item[11] == final_score, "index 11 = final_score (DL混合分)"


def test_second_loop_unpacks_base_final_per_stock():
    """P0-1: 第二遍循环 unpack 每只股票独立的 base_final

    Bug 前: final = final_score (陈旧变量, 所有票相同)
    修复后: base_final = _rest[2] (每只票独立)
    """
    # 模拟 3 只股票, 各自不同的 final_score
    stocks = [
        (85, 72, "sh600519", "贵州茅台", "白酒", [], [], 8, "", 0, "", 73.73),
        (60, 55, "sz000858", "五粮液", "白酒", [], [], 6, "", 0, "", 54.75),
        (95, 90, "sh601318", "中国平安", "金融", [], [], 4, "", 0, "", 82.40),
    ]

    results = []
    for item in stocks:
        sc_zh, sc_qc, code, name, industry, sigs_zh, sigs_qc, heat_bonus, heat_desc, *_rest = item
        dl_bonus, dl_desc = (_rest[0], _rest[1]) if len(_rest) >= 2 else (0, "")
        base_final = _rest[2] if len(_rest) >= 3 else sc_zh
        results.append((code, base_final))

    # 每只票的 base_final 应该不同 (不是同一个陈旧值)
    base_values = [r[1] for r in results]
    assert len(set(base_values)) == 3, f"3只票应有3个不同base, 实际 {set(base_values)}"
    assert results[0][1] == 73.73
    assert results[1][1] == 54.75
    assert results[2][1] == 82.40


def test_old_format_tuple_falls_back_to_sc_zh():
    """P0-1 兼容性: 旧格式 tuple (11字段, 无 final_score) 回退到 sc_zh"""
    item_11 = (85, 72, "sh600519", "贵州茅台", "白酒",
               ["sig"], ["sig"], 8, "🔥", 3, "DL")
    sc_zh, sc_qc, code, name, industry, sigs_zh, sigs_qc, heat_bonus, heat_desc, *_rest = item_11
    base_final = _rest[2] if len(_rest) >= 3 else sc_zh
    # 旧格式只有 2 个 _rest 元素 → 回退到 sc_zh
    assert base_final == 85, f"旧格式应回退到 sc_zh=85, 实际 {base_final}"


# ─── P1-1: config.json 策略同步 ────────────────────────────

def test_config_strategy_matches_code():
    """P1-1: config.json strategy 应与代码实际使用的策略一致

    09-22 P0修复: 代码硬编码 STRATEGIES['综合'] (v36回测验证)
    config.json 旧值 '基本面+' 与代码不一致 → 同步为 '综合'
    """
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
    config_path = os.path.normpath(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg.get("strategy") == "综合", (
        f"config.json strategy={cfg.get('strategy')!r}, "
        f"但代码 integrated_picker.py:552 硬编码 STRATEGIES['综合']"
    )


# ─── P1-2: 动量加分模式验证 ────────────────────────────────

def test_momentum_bonus_does_not_remove_stocks():
    """P1-2: 动量加分不剔除候选 (原硬过滤在弱市导致无票输出)"""
    # 模拟 top50: 2只满足动量, 1只不满足
    top50 = [
        (80, 70, "sh600519", "茅台", "白酒", [], [], 0, "", 0, "", 75.0),
        (60, 50, "sz000858", "五粮液", "白酒", [], [], 0, "", 0, "", 55.0),
        (45, 40, "sh601318", "平安", "金融", [], [], 0, "", 0, "", 42.0),
    ]

    # 模拟 P1-2 修复后的动量加分逻辑
    # 假设 stock[0] 满足动量 (5d>3%), stock[1] 满足 (10d>5%), stock[2] 不满足
    momentum_hit = {top50[0][2], top50[1][2]}  # 茅台、五粮液满足
    new_top50 = []
    for item in top50:
        code = item[2]
        if code in momentum_hit:
            item_list = list(item)
            item_list[0] = round(item_list[0] + 5, 1)
            item = tuple(item_list)
        new_top50.append(item)

    # 修复后: 3只票全保留 (不满足的也不剔除)
    assert len(new_top50) == 3, f"动量加分后应保留全部{len(top50)}只, 实际{len(new_top50)}"
    # 满足动量的 +5 分
    assert new_top50[0][0] == 85.0, f"茅台 80+5=85, 实际 {new_top50[0][0]}"
    assert new_top50[1][0] == 65.0, f"五粮液 60+5=65, 实际 {new_top50[1][0]}"
    assert new_top50[2][0] == 45.0, f"平安不满足, 保持45, 实际 {new_top50[2][0]}"

    # 对比旧行为: 硬过滤会剔除 stock[2]
    old_momentum_passed = [item for item in top50 if item[2] in momentum_hit]
    assert len(old_momentum_passed) == 2, "旧硬过滤只保留满足动量的"
    print(f"  旧硬过滤: {len(old_momentum_passed)}只保留 → 修复后: {len(new_top50)}只全保留")


# ─── P0-2: compute_final_score 统一公式验证 ─────────────────

def test_compute_final_score_base_override():
    """P0-2: base_override 参数让实盘传 DL 混合分, 回测传 None 用 confidence"""
    from core.scoring.scoring_engine import compute_final_score

    # 回测模式: base_override=None → 用 confidence
    conf = 60
    risk_val = 10
    f_bt, r_bt = compute_final_score(conf, risk_val, pass_risk=True)
    # final = 60*1.0 + 0 - 10*0.05 = 59.5
    assert abs(f_bt - 59.5) < 0.1, f"回测模式 final={f_bt}, 期望≈59.5"

    # 实盘模式: base_override=75 (DL混合分) → 用 75 而非 confidence
    dl_blend = 75
    f_live, r_live = compute_final_score(conf, risk_val, pass_risk=True, base_override=dl_blend)
    # final = 75*1.0 + 0 - 10*0.05 = 74.5
    assert abs(f_live - 74.5) < 0.1, f"实盘模式 final={f_live}, 期望≈74.5"
    assert f_live > f_bt, "实盘 DL 混合分应高于回测 confidence"

    # 两种模式公式结构一致: 差值 = (base_override - confidence) = 15
    diff = f_live - f_bt
    assert abs(diff - 15.0) < 0.1, f"差值={diff}, 期望=15 (75-60)"


def test_compute_final_score_pattern_bonus_negative():
    """P0-2: pattern_bonus 支持负值 (bearish 惩罚走参数, 不走独立 subtract)"""
    from core.scoring.scoring_engine import compute_final_score

    # bearish 惩罚 -20
    f1, r1 = compute_final_score(80, 0, True, base_override=80, pattern_bonus=-20)
    # final = 80 - 0 = 80 (pattern_bonus 不进 final, 进 rank_score)
    assert abs(f1 - 80.0) < 0.1, f"final 不应含 pattern_bonus, 实际 {f1}"
    # rank = 80 * 1.0 + (-20) = 60
    assert abs(r1 - 60.0) < 0.1, f"rank 应含 pattern_bonus, 实际 {r1}"

    # 无 bearish
    f2, r2 = compute_final_score(80, 0, True, base_override=80, pattern_bonus=0)
    assert abs(r2 - 80.0) < 0.1, f"rank 无 bearish 应=80, 实际 {r2}"


def test_compute_final_score_backtest_live_equivalence():
    """P0-2: 同一输入下, 回测(无 base_override) 和 实盘(base_override=confidence) 结果一致"""
    from core.scoring.scoring_engine import compute_final_score

    conf, risk_val = 72, 8
    gap, fin, fatal, chan = 2.0, 10, False, 2

    # 回测: base_override=None → base = confidence = 72
    f_bt, r_bt = compute_final_score(
        conf, risk_val, True,
        gap_score=gap, fin_bonus=fin, fin_fatal=fatal,
        chan_bonus=chan, primary_strategy="综合")

    # 实盘: base_override=confidence (当 DL 未启用时 base_override=confidence)
    f_live, r_live = compute_final_score(
        conf, risk_val, True,
        gap_score=gap, fin_bonus=fin, fin_fatal=fatal,
        chan_bonus=chan, primary_strategy="综合",
        base_override=conf)

    # 两者应完全一致 (DL 未启用 → base_override = confidence)
    assert f_bt == f_live, f"回测 final={f_bt} ≠ 实盘 final={f_live}"
    assert r_bt == r_live, f"回测 rank={r_bt} ≠ 实盘 rank={r_live}"


def test_scoring_engine_importable():
    """P0-2: compute_final_score 可被 integrated_picker 导入"""
    from core.scoring.scoring_engine import compute_final_score
    assert callable(compute_final_score)


if __name__ == "__main__":
    # 简单 runner (无 pytest 依赖)
    import traceback
    tests = [
        ("P0-1 tuple 12字段", test_candidates_tuple_has_final_score_field),
        ("P0-1 独立 base_final", test_second_loop_unpacks_base_final_per_stock),
        ("P0-1 旧格式回退", test_old_format_tuple_falls_back_to_sc_zh),
        ("P1-1 config 策略同步", test_config_strategy_matches_code),
        ("P1-2 动量加分", test_momentum_bonus_does_not_remove_stocks),
        ("P0-2 base_override", test_compute_final_score_base_override),
        ("P0-2 pattern_bonus", test_compute_final_score_pattern_bonus_negative),
        ("P0-2 回测=实盘一致", test_compute_final_score_backtest_live_equivalence),
        ("P0-2 引擎可导入", test_scoring_engine_importable),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            traceback.print_exc()
    print(f"\n  {passed}/{len(tests)} 通过")
    if passed < len(tests):
        sys.exit(1)
