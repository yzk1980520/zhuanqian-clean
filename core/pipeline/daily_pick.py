#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日选股任务 - trade_log cron恢复
替代缺失的daily_pick.py

退出码语义 (2026-10-17 W1 定稿, 勿再改成"什么都返回 0"):
  0 = 跑成了 (选股完成)
  1 = 真失败 (缺必要文件 / 缺历史数据 / 选股抛异常)
  3 = 被因子门禁暂停 (因子层已启用 且 gate_passed=False, 一只票都没选)
     —— 原先这里 return 0: 门禁没过却报"成功", 调度层看到 0 判定正常,
        实际零出票。这是把"门禁拦截"伪装成"任务完成"的假绿, 已修。
        调用方要能分辨"跑成 / 真失败 / 被门禁暂停", 所以必须用 3 而不是 0。

========================= 严禁清单 (2026-10-21 立) =========================
1. 严禁把因子门禁改回「无条件检查」。即: 严禁不读 factor_layer_enabled、
   直接判 gate_passed 失败就 return 3。
2. 因子层未启用 (factor_layer_enabled=False / 配置缺省) 时**必须跳过**门禁拦截,
   并把跳过原因显式写进日志与输出 JSON 的 factor_gate 段 —— 可以跳过, 不许静默。
3. 理由: 因子层关着时因子根本不参与选股打分, 此时门禁拦出票是逻辑倒挂 ——
   一个"没在用的因子层"不达标却让整条出票链停摆。门禁仍如实报红(不置绿),
   只是不再阻断出票。
4. 本条由 scripts/guard_assertion_effectiveness.py 的 G22 机器守卫; 判据验
   **执行性语句**(正则匹配真实的 if/赋值/return 行), 注释里写字样骗不过它。
==========================================================================
"""
import json
import sys
from pathlib import Path
from datetime import datetime

# 项目根目录（使用绝对路径）
PROJECT_ROOT = Path("D:/open code/zhuanqian")

def select_picks(top_n=10):
    """选股入口 — 委托 auto_live_pipeline.run_stock_selection (唯一实盘路径, 已接主板白名单剔除)。

    旧实现直接调 tdx_core 里不存在的选股类方法 (cron 崩的根因), 且该路径绕过主板白名单
    → 创业板/科创/北证/ETF 进池。现统一走带剔除的 pipeline。返回 [{code, score, details}]。

    2026-10-19 P0-A 修复连带: run_stock_selection 自 T2a 起返回 (picks, processed)
    二元组, 原先直接 return 整个元组 → 下游 len(picks)==2 且 daily_picks JSON 里
    picks=[list,int] 结构损坏。此处解包只取 picks。
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import auto_live_pipeline
    picks, _processed = auto_live_pipeline.run_stock_selection(top_n=top_n)
    return picks


def _factor_gate_block():
    """因子门禁拦截判定 —— 与「因子层是否启用」解耦 (2026-10-21 修)。

    返回 (blocked: bool, info: dict)。调用方按 blocked 决定是否 return 3。

    为什么要解耦:
      因子层关闭 (factor_layer_enabled=False) 时因子根本不参与选股打分, 此时
      因子门禁却拦住出票 = 逻辑倒挂。真实后果是门禁一红整条出票链停摆, 而停摆
      原因是一个"没在用的因子层"不达标。老大要的是暴露真相, 不是让出票停。
      故: 只有因子层真的启用, 门禁未过才允许拦出票; 关闭时跳过并显式留痕
      (info['skip_reason'] + 日志 + 输出 JSON), 绝不静默。

    ⚠️ 严禁改回"无条件检查 gate_passed"(不读开关直接 return 3) —— 见文件头
       严禁清单; scripts/guard_assertion_effectiveness.py 的 G22 守这条。
    """
    gate_file = PROJECT_ROOT / "data" / "factor_ic" / "factor_gate.json"
    info = {"gate_file": str(gate_file), "skipped": False, "blocked": False}
    if not gate_file.exists():
        info["skipped"] = True
        info["skip_reason"] = "门禁报告不存在 (产出方 scripts/gate_check.py 未跑), 不拦出票"
        return False, info

    with open(gate_file, 'r', encoding='utf-8') as f:
        gate_data = json.load(f)

    effective = gate_data.get('effective_factors', 0)
    gate_passed = gate_data.get('gate_passed', False)
    threshold = gate_data.get('threshold', 8)
    info.update({"effective_factors": effective, "threshold": threshold,
                 "gate_passed": gate_passed})

    # 唯一读口: config_loader.get_factor_layer_enabled() -> (bool, source)
    # 缺省 False (fail-safe); 读失败同样按 False 处理, 但把失败写进 skip_reason,
    # 不做静默兜底。
    try:
        from config_loader import get_factor_layer_enabled
        factor_layer_on, factor_layer_src = get_factor_layer_enabled()
    except Exception as e:
        factor_layer_on = False
        factor_layer_src = f"读取失败按 fail-safe=False 处理: {type(e).__name__}: {e}"
    info["factor_layer_enabled"] = factor_layer_on
    info["factor_layer_source"] = factor_layer_src

    if not factor_layer_on:
        info["skipped"] = True
        info["skip_reason"] = (
            f"因子层未启用 (factor_layer_enabled=False, 来源={factor_layer_src}) "
            f"=> 因子不参与打分, 因子门禁不拦出票 "
            f"(当前 {effective}/{threshold}, gate_passed={gate_passed}; "
            f"门禁仍如实报红, 仅不阻断)"
        )
        return False, info

    if not gate_passed:
        info["blocked"] = True
        info["block_reason"] = (
            f"因子层已启用且门禁未过: {effective}/{threshold} "
            f"(需补 {threshold - effective} 个 valid 因子, 132d 口径)"
        )
        return True, info

    return False, info


def main():
    """主函数"""
    print("=" * 70)
    print("📊 每日选股任务 - trade_log cron恢复")
    print("=" * 70)
    print()
    
    # 1. 检查必要文件
    print("【步骤1】检查必要文件...")
    required_files = [
        "backtest.py",
        "tdx_core.py",
        "data/factor_weights_simplified_v7.4.json",
        # 2026-10-17 W1: 因子 IC 权威源已换为 132d 精确口径的
        # data/factor_ic/factor_ic_latest.json (老大拍板), 预检必须指向新权威源。
        # 旧源 data/factor_ic.json 只由 .scratch/ 临时脚本产出且 0 元数据,
        # 已降级为非权威历史快照; 全量守卫(tests/__init__.py、tests/test_system.py)
        # 仍在断言它存在, 所以旧文件不删, 但本预检不再以它为准。
        "data/factor_ic/factor_ic_latest.json",
    ]
    
    missing_files = []
    for f in required_files:
        file_path = PROJECT_ROOT / f
        if file_path.exists():
            print(f"  ✅ {f}")
        else:
            print(f"  ❌ {f} (缺失)")
            missing_files.append(f)
    
    if missing_files:
        print(f"\n❌ 缺少 {len(missing_files)} 个必要文件，无法执行")
        return 1
    
    print()
    
    # 2. 检查历史数据
    print("【步骤2】检查历史数据...")
    history_dir = PROJECT_ROOT / "data" / "history_daily"
    if history_dir.exists():
        stock_files = list(history_dir.glob('*.json'))
        print(f"  ✅ 历史数据: {len(stock_files)} 只股票")
    else:
        print("  ❌ 历史数据目录不存在")
        return 1
    
    print()
    
    # 3. 检查门禁状态
    #    2026-10-21 解耦: 因子层未启用时门禁「如实报红但不拦出票」, 见 _factor_gate_block()。
    print("【步骤3】检查门禁状态...")
    blocked, gate_info = _factor_gate_block()
    print(f"  有效因子: {gate_info.get('effective_factors', 0)}/{gate_info.get('threshold', 8)}")
    print(f"  门禁状态: {'✅ 通过' if gate_info.get('gate_passed') else '❌ 未通过'}"
          f" (门禁判定本身不变, 不因因子层关闭而置绿)")
    print(f"  因子层开关: factor_layer_enabled={gate_info.get('factor_layer_enabled')}"
          f" (来源: {gate_info.get('factor_layer_source', 'n/a')})")
    if gate_info.get("skipped"):
        # 跳过必须可见 —— 静默跳过就是把拦截改头换面成假绿, 与文件头严禁清单冲突。
        print(f"  ⚠️ 因子门禁跳过拦截(非静默): {gate_info.get('skip_reason')}")
    if blocked:
        print(f"\n⚠️  门禁未通过，选股任务暂停")
        print(f"    {gate_info.get('block_reason')}")
        # 2026-10-17 W1: 原为 return 0 —— 门禁拦截却报成功, 调度层无法分辨,
        # 是静默跳过的假绿。改 3 (见文件头退出码语义)。
        print(f"    退出码 3 = 被门禁暂停(非成功、非内部错误), 供调度层区分")
        return 3
    
    print()

    # 3b. 交易时段防护（S6，修复 09-20 永鼎盘后误操作事故）：非交易时段只告警不动仓
    print("【步骤3c】交易时段防护 (is_trading_hours)...")
    from trading_hours import is_trading_hours
    _now = datetime.now()
    _in_session = is_trading_hours(_now)
    print(f"  当前时间: {_now.strftime('%Y-%m-%d %H:%M:%S')} 交易时段: {'✅ 交易中' if _in_session else '⚠️ 非交易时段'}")
    if not _in_session:
        print(f"  ⚠️ 非交易时段 -> dry_run 告警，不写 holdings/trade_log")

    # 3b. 三重解冻条件门禁 (2026-10-08 同步: 读 sync_trial_gate, 任一未绿=交易指令 dry_run 不落仓)
    print("【步骤3b】三重解冻条件 A∧B∧C (sync_trial_gate)...")
    trial_mode = "dry_run"
    trial_status = {}
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import sync_trial_gate
        trial_mode, trial_status = sync_trial_gate.check_trial_gate()
        print(f"  三重门禁: {trial_status.get('verdict', trial_mode)}")
        for cid, c in trial_status.get("conditions", {}).items():
            print(f"    {cid}: {'✅' if c.get('pass') else '❌'} {c.get('detail', '')[:80]}")
    except Exception as e:
        trial_mode = "dry_run"
        trial_status = {"verdict": f"sync_trial_gate 异常兜底 dry_run: {e}"}
        print(f"  ⚠️ {trial_status['verdict']}")
        import traceback; traceback.print_exc()
    if trial_mode != "live_trial":
        print(f"\n⚠️  三重条件未全绿 -> 选股仅出候选池, 交易指令 dry_run(不动 holdings/trade_log)")

    print()

    # 4. 执行选股（交易时段防护：非交易时段只出候选池不动仓）
    print("【步骤4】执行选股...")
    # S6: 非交易时段 dry_run 告警，选股仍出候选池
    _now = datetime.now()
    _in_session = is_trading_hours(_now)
    if not _in_session:
        print(f"  ⚠️ 非交易时段，选股仅出候选池（dry_run 告警）")
    try:
        picks = select_picks(top_n=10)

        print(f"  ✅ 选出 {len(picks)} 只股票")
        
        # 5. 保存结果 (含三重门禁快照: cron 下游消费方据此决定 落仓/dry_run)
        output_file = PROJECT_ROOT / "data" / "daily_picks" / f"{datetime.now().strftime('%Y%m%d')}.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'date': datetime.now().strftime('%Y-%m-%d'),
                'picks': picks,
                'count': len(picks),
                'trial_mode': trial_mode,
                'trial_gate': trial_status,
                'trade_allowed': trial_mode == "live_trial",
                # 2026-10-21 解耦: 门禁状态与"是否因此被拦"一并落盘, 供下游核对,
                # 因子层关闭导致的跳过必须留在产物里, 不能只在 stdout 上飘一下。
                'factor_gate': gate_info,
            }, f, ensure_ascii=False, indent=2)
        
        print(f"  ✅ 结果已保存: {output_file.name} (trade_allowed={trial_mode == 'live_trial'})")
        
    except Exception as e:
        print(f"  ❌ 选股执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print()
    print("=" * 70)
    print("✅ 每日选股任务完成")
    print("=" * 70)
    return 0

if __name__ == "__main__":
    sys.exit(main())
