import core.pipeline.atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
系统完整性验证 — 数据源稳定性 + 逻辑链路测试
"""
import sys, os, json, time
from datetime import datetime

if __name__ == "__main__":
    PROJECT = r"D:\open code\zhuanqian"
    sys.path.insert(0, PROJECT)
    os.chdir(PROJECT)
    
    results = {"passed": 0, "failed": 0, "warnings": 0, "tests": []}
    TOTAL_SCORE = 0

def test(name, result, detail=""):
    global TOTAL_SCORE
    status = "✅" if result else "❌"
    if result:
        results["passed"] += 1
        TOTAL_SCORE += 1
    else:
        results["failed"] += 1
    results["tests"].append({"name": name, "passed": result, "detail": detail})
    print(f"  {status} {name}")
    if detail:
        print(f"     {detail}")

def warn(name, detail):
    results["warnings"] += 1
    results["tests"].append({"name": name, "passed": True, "detail": f"⚠️ {detail}"})
    print(f"  ⚠️  {name}")
    print(f"     {detail}")

if __name__ == "__main__":
    print("=" * 68)
    print("  🧪 系统完整性验证 — %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 68)
    
    # ═══════════════════════════════════════════
    #  Phase 1: 数据源稳定性
    # ═══════════════════════════════════════════
    print("\n📡 Phase 1: 数据源稳定性")
    print("-" * 50)

# 1.1 TDX本地日线数据
from core.pipeline.tdx_core import get_tdx_data, VIPDOC
if __name__ == "__main__":
    tdx_exists = os.path.exists(VIPDOC)
    test("TDX数据目录存在", tdx_exists)
    sh_files = []
    if tdx_exists:
        sh_dir = os.path.join(VIPDOC, "sh", "lday")
        sz_dir = os.path.join(VIPDOC, "sz", "lday")
        sh_files = [f for f in os.listdir(sh_dir) if f.endswith(".day")] if os.path.exists(sh_dir) else []
        sz_files = [f for f in os.listdir(sz_dir) if f.endswith(".day")] if os.path.exists(sz_dir) else []
        total_files = len(sh_files) + len(sz_files)
        test("TDX股票日线文件数 > 2000", total_files > 2000, f"沪{len(sh_files)}只 + 深{len(sz_files)}只 = {total_files}只")
    
    # 1.2 上证指数数据
    sh_recs = get_tdx_data("sh000001", 80)
    test("上证指数数据可取", sh_recs and len(sh_recs) > 20, f"取到{len(sh_recs)}条日线")
    if sh_recs:
        from core.pipeline.tdx_core import compute_indicators
        sh_inds = compute_indicators(sh_recs)
        test("上证指数技术指标可计算", sh_inds and sh_inds.get("price", 0) > 0, 
             f"收盘价{sh_inds['price']:.1f} MA20={sh_inds.get('ma20',0):.1f} MA60={sh_inds.get('ma60',0):.1f}")
    
    # 1.3 个股数据
    test_codes = ["sh600887", "sz000333", "sh600519", "sz002415", "sh600036"]
    data_hits = 0
    for code in test_codes:
        recs = get_tdx_data(code, 50)
        if recs and len(recs) >= 20:
            data_hits += 1
    test("个股日线数据(5只测试)", data_hits >= 4, f"命中{data_hits}/5只")

# 1.4 行业映射
from core.pipeline.tdx_core import load_name_cache, load_industry_map
if __name__ == "__main__":
    name_cache = load_name_cache()
    ind_map = load_industry_map()
    test("股票名称缓存加载", len(name_cache) > 2000, f"{len(name_cache)}只")
    test("行业映射加载", len(ind_map) > 1000, f"{len(ind_map)}条")

# 1.5 北向缓存
from northbound_flow import load_cache as load_nb
if __name__ == "__main__":
    nb_data = load_nb()
    test("北向数据缓存", len(nb_data) > 0, f"{len(nb_data)}只标的缓存")
    if nb_data:
        top_nb = sorted(nb_data.items(), key=lambda x: x[1].get("holding_pct", 0), reverse=True)[:3]
        for code, info in top_nb:
            print(f"     北向重仓: {info.get('name','?')}({info.get('holding_pct',0):.1f}%)")

# 1.6 板块热度
from core.pipeline.integrated_picker import load_industry_heat
if __name__ == "__main__":
    heat = load_industry_heat()
    valid_heat = {k: v for k, v in heat.items() if isinstance(v, dict) and "rank" in v}
    test("板块热度数据", len(valid_heat) > 20, f"{len(valid_heat)}个板块")
    if valid_heat:
        top5 = sorted(valid_heat.items(), key=lambda x: x[1]["rank"])[:5]
        for name, info in top5:
            print(f"     热点#{info['rank']}: {name[:10]} (+{info.get('change_pct',0):.1f}%)")
    
    # ═══════════════════════════════════════════
    #  Phase 2: 市场状态引擎
    # ═══════════════════════════════════════════
    print("\n🧠 Phase 2: 市场状态引擎")
    print("-" * 50)

from market_state_engine import assess_market_full, get_strategy_weights, get_position_advice

if __name__ == "__main__":
    m = assess_market_full(use_cache=False)
    test("市场综合评分在0-100范围", 0 <= m["market_score"] <= 100, f"得分: {m['market_score']}/100 — {m['market_label']}")
    test("市场标签有效", m["market_label"] in ["恐慌","弱","震荡","偏暖","强","极强"])
    test("策略权重和为1", abs(sum(m["strategy_weights"].values()) - 1.0) < 0.02, 
         f"权重和={sum(m['strategy_weights'].values()):.3f}")
    test("5个子维度全部有值", len(m["sub_scores"]) == 5, 
         f"维度: {', '.join(m['sub_scores'].keys())}")
    for dim, info in m["sub_scores"].items():
        test(f"  子维度[{dim}]评分有效", 0 <= info["score"] <= 100, f"{info['score']}分")
    
    top3 = sorted(m["strategy_weights"].items(), key=lambda x: -x[1])[:3]
    print(f"  推荐策略TOP3: {', '.join(f'{n}({w*100:.0f}%)' for n,w in top3)}")
    
    # 边界平滑测试
    print("\n  📐 策略权重边界平滑验证:")
    for test_score in [14, 16, 34, 36, 54, 56, 74, 76]:
        w = get_strategy_weights(test_score)
        top = max(w, key=w.get)
        top3_sorted = sorted(w.items(), key=lambda x: -x[1])[:3]
        print(f"    评分{test_score:3d}分 → 主策略:{top:<6s} TOP3:{' '.join(f'{n}({v*100:.0f}%)' for n,v in top3_sorted)}")
    
    # 仓位建议
    pos_ratio, pos_advice = get_position_advice(m["market_score"])
    test("仓位建议有效", 0 < pos_ratio <= 1, f"{pos_advice} ({pos_ratio*100:.0f}%)")
    
    # ═══════════════════════════════════════════
    #  Phase 3: 选股逻辑链路
    # ═══════════════════════════════════════════
    print("\n🎯 Phase 3: 选股逻辑链路")
    print("-" * 50)

from core.pipeline.integrated_picker import run_integrated_picker
from core.pipeline.tdx_core import STRATEGIES

# 验证7个策略全部存在
if __name__ == "__main__":
    test("7个策略全部注册", len(STRATEGIES) >= 7, f"{len(STRATEGIES)}个: {', '.join(STRATEGIES.keys())}")
    
    # 新策略关键因子存在
    for s_name in ["断层", "北向精选"]:
        s = STRATEGIES.get(s_name, {})
        has_gap = "earnings_gap_bonus" in s
        has_nb = "northbound_bonus" in s
        test(f"策略[{s_name}]含专属因子", has_gap and has_nb, 
             f"earnings_gap_bonus={s.get('earnings_gap_bonus','?')} northbound_bonus={s.get('northbound_bonus','?')}")
    
    # 运行完整选股
    print("\n  🏃 运行完整选股流水线...")
    t0 = time.time()
    picker_results, picker_config, _inds = run_integrated_picker(top_n=5, debug=False, dry_run=True)  # 2026-08-13: dry_run防污染trade_log
    elapsed = time.time() - t0
    test("完整选股流水线正常完成", picker_results is not None, f"耗时{elapsed:.1f}s")
    
    if picker_results:
        test("选股结果不为空", len(picker_results) > 0, f"返回{len(picker_results)}只")
        
        top = picker_results[0]
        pass_risk = top[5]
        test("最优标的有完整评分", top[1] > 0 and top[2] > 0, 
             f"综合{top[1]} 全仓{top[2]} 断层{top[13]} 北向{top[16]}")
        
        # 断层检测是否在工作
        gap_hit = sum(1 for r in picker_results if r[13] > 0)
        nb_hit = sum(1 for r in picker_results if r[16] > 0)
        print(f"  Top50中断层命中: {gap_hit}只 | 北向命中: {nb_hit}只")
        
        if top[5]:
            print(f"  🥇 最优: {top[8]} {top[9]} | 综合{top[1]} 断层{top[13]} 北向{top[16]} 风控{top[2]}")
            print(f"     板块热度: {top[7] or '中性'}")
            print(f"     风险系数: {top[3]:+d}")
        else:
            warn("最优标的风控过滤结果", f"综合{top[1]}→全仓{top[2]}(风险{top[3]:+d})未通过风控")
    
    # ═══════════════════════════════════════════
    #  Phase 4: 交易计划逻辑
    # ═══════════════════════════════════════════
    print("\n📋 Phase 4: 交易计划逻辑")
    print("-" * 50)

from risk_rules import generate_trade_plan, evaluate_exit

# 测试不同场景
if __name__ == "__main__":
    scenarios = [
        ("断层+震荡+强信号", {"strategy":"断层","market_score":42,"market_label":"震荡","gap_score":11,"nb_score":8,"confidence":"medium"}),
        ("全仓+强市",       {"strategy":"全仓","market_score":78,"market_label":"强","gap_score":5,"nb_score":3,"confidence":"high"}),
        ("抄底+弱市",       {"strategy":"抄底","market_score":22,"market_label":"弱","gap_score":0,"nb_score":0,"confidence":"low"}),
    ]
    
    for label, params in scenarios:
        plan = generate_trade_plan(entry_price=50, capital=23000, **params)
        # 验证风报比合理
        rrr_ok = plan["risk_reward_tp1"] > 0.5 or plan["risk_reward_tp2"] > 1.0
        sl_ok = 2.0 <= plan["stop_loss_pct"] <= 15.0  # 百分数口径(7.0=7%)
        pos_ok = plan["position_pct"] > 0
        all_ok = rrr_ok and sl_ok and pos_ok
        test(f"  场景[{label}]交易计划完整", all_ok,
             f"SL={plan['stop_loss_pct']:.1f}% TP2={plan['tp2_pct']:.1f}% RRR={plan['risk_reward_tp2']:.1f} 仓位{plan['position_pct']:.0f}%")
    
    # 止损止盈退出逻辑
    exit_test = evaluate_exit({"entry_price": 50, "sl": 46, "tp1": 54, "tp2": 58}, 45, "震荡")
    test("止损触发逻辑正确", exit_test[0] and exit_test[2] == "stop_loss", f"退出原因: {exit_test[1]}")
    
    exit_test2 = evaluate_exit({"entry_price": 50, "sl": 46, "tp1": 54, "tp2": 58}, 59, "震荡")
    test("止盈TP2触发逻辑正确", exit_test2[0] and exit_test2[2] == "take_profit", f"退出原因: {exit_test2[1]}")
    
    exit_test3 = evaluate_exit({"entry_price": 50, "sl": 46, "tp1": 54, "tp2": 58}, 52, "震荡")
    test("未触发时不退出", not exit_test3[0], f"should_exit={exit_test3[0]}")
    
    exit_test4 = evaluate_exit({"entry_price": 50, "sl": 46, "tp1": 54, "tp2": 58}, 52, "恐慌")
    test("市场恐慌时强制退出", exit_test4[0] and exit_test4[2] == "market_exit", f"退出原因: {exit_test4[1]}")
    
    # ═══════════════════════════════════════════
    #  Phase 5: Cron定时任务
    # ═══════════════════════════════════════════
    print("\n⏰ Phase 5: Cron定时任务")
    print("-" * 50)

# 检查cron list
import subprocess
if __name__ == "__main__":
    cron_out = subprocess.run(["hermes", "cron", "list"], capture_output=True, text=True, 
                              cwd=PROJECT).stdout
    has_daily = "daily-pick" in cron_out
    has_weekly = "weekly-report" in cron_out
    test("每日选股cron已注册", has_daily)
    test("周度报告cron已注册", has_weekly)
    
    # 检查脚本文件存在
    scripts_dir = os.path.expanduser("~/.hermes/scripts")
    daily_exists = os.path.exists(os.path.join(scripts_dir, "daily_pick.py"))
    weekly_exists = os.path.exists(os.path.join(scripts_dir, "weekly_report.py"))
    test("daily_pick.py脚本存在", daily_exists)
    test("weekly_report.py脚本存在", weekly_exists)
    
    # 检查Gateway
    gateway_out = subprocess.run(["hermes", "cron", "status"], capture_output=True, text=True,
                                  cwd=PROJECT).stdout
    gateway_running = "running" in gateway_out or "Gateway is running" in gateway_out
    test("Gateway运行中(定时触发)", gateway_running)
    
    # ═══════════════════════════════════════════
    #  总分
    # ═══════════════════════════════════════════
    total_tests = results["passed"] + results["failed"]
    score_pct = TOTAL_SCORE / total_tests * 100 if total_tests > 0 else 0
    
    print("\n" + "=" * 68)
    print("  📊 验证结果汇总")
    print("=" * 68)
    print(f"  总测试数: {total_tests}")
    print(f"  ✅ 通过: {results['passed']}")
    if results["warnings"]:
        print(f"  ⚠️  警告: {results['warnings']}")
    if results["failed"]:
        print(f"  ❌ 失败: {results['failed']}")
    print(f"  🏆 通过率: {score_pct:.0f}%")
    print()
    
    if results["failed"] > 0:
        print("  ❌ 失败项:")
        for t in results["tests"]:
            if not t["passed"]:
                print(f"    - {t['name']}: {t['detail']}")
    
    if results["warnings"] > 0:
        print("  ⚠️  警告项:")
        for t in results["tests"]:
            if "⚠️" in str(t.get("detail", "")):
                print(f"    - {t['name']}: {t['detail']}")
    
    # 保存报告
    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "passed": results["passed"],
        "failed": results["failed"],
        "warnings": results["warnings"],
        "total": total_tests,
        "score_pct": round(score_pct, 1),
        "tests": results["tests"],
    }
    
    report_file = os.path.join(PROJECT, "data", "system_health.json")
    os.makedirs(os.path.dirname(report_file), exist_ok=True)
    atomic_json.atomic_dump(report, report_file, ensure_ascii=False, indent=2, encoding="utf-8")
    print(f"\n  💾 报告已保存: {report_file}")
    print("\n" + "=" * 68)
