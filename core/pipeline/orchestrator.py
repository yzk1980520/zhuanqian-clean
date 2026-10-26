#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
orchestrator.py — 选股系统统一编排器 v1.0
==========================================
整合六层过滤 + 数据保鲜 + 交叉验证 + 风控 + 自进化

模式:
  python orchestrator.py daily      # 每日选股日报（cron使用）
  python orchestrator.py weekly     # 每周策略周报（cron使用）
  python orchestrator.py pick       # 仅输出Top推荐
  python orchestrator.py health     # 系统健康检查
  python orchestrator.py evolve     # 触发自进化

数据源降级链:
  TDX日线(主) → mx_ds_mcp(MCP查询) → AKShare → Sina/Tencent实时
"""

import sys, os, json, time
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, date

PROJECT = PROJECT_ROOT
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)


# ═══════════════════════════════════════════
#  数据保鲜层
# ═══════════════════════════════════════════

def check_tdx_freshness():
    """检查TDX数据日期 — 通过上证指数日期推断"""
    try:
        from core.pipeline.tdx_core import get_latest_tdx_date, get_tdx_data
        # 用上证指数判断数据新鲜度
        latest = get_latest_tdx_date("sh000001")
        if not latest:
            # 备选：检查TDX目录下最新日线文件
            from core.pipeline.tdx_core import VIPDOC
            lday_dir = os.path.join(VIPDOC, "sh", "lday")
            if os.path.exists(lday_dir):
                day_files = [f for f in os.listdir(lday_dir) if f.endswith(".day")]
                if day_files:
                    latest = datetime.fromtimestamp(
                        max(os.path.getmtime(os.path.join(lday_dir, f)) for f in day_files)
                    ).date()
        if not latest:
            return False, "TDX数据日期不可用"
        today = date.today()
        delta = (today - latest).days
        status = "✅ 正常" if delta <= 3 else "⚠️ 滞后"
        return delta <= 3, f"{status} 最新数据: {latest} (滞后{delta}天)"
    except Exception as e:
        return False, f"❌ TDX检查失败: {e}"


def check_cache_freshness(max_age_hours=25):
    """检查各缓存时效性"""
    cache_specs = {
        "financial_cache.json": "财务评分",
        "market_state_cache.json": "市场状态",
        "news_sentiment_cache.json": "新闻情绪",
        "industry_heat.json": "板块热度",
    }
    now = time.time()
    results = []
    for fname, label in cache_specs.items():
        fpath = os.path.join(PROJECT, "data", fname)
        if os.path.exists(fpath):
            age_hours = (now - os.path.getmtime(fpath)) / 3600
            if age_hours < max_age_hours:
                results.append(f"✅ {label}: {age_hours:.0f}h前")
            else:
                results.append(f"⚠️ {label}: {age_hours:.0f}h前(过期)")
        else:
            results.append(f"⚠️ {label}: 无缓存")
    return results


# ═══════════════════════════════════════════
#  交叉验证层 — 主源失败自动降级
# ═══════════════════════════════════════════

def cross_validate_data(stock_code):
    """多源交叉验证单只股票数据"""
    results = {}
    errors = []
    
    # 源1: TDX日线
    try:
        from core.pipeline.tdx_core import get_tdx_data
        data = get_tdx_data(stock_code, 5)
        if data and len(data) >= 2:
            results["tdx"] = {"close": data[-1]["close"], "volume": data[-1].get("volume", 0), "valid": True}
        else:
            errors.append("TDX: 数据不足")
    except Exception as e:
        errors.append(f"TDX: {e}")

    # 源2: AKShare (financial_filter已集成)
    try:
        from core.scoring.financial_filter import _HAS_AKSHARE
        if _HAS_AKSHARE:
            import akshare as ak
            df = ak.stock_zh_a_hist(symbol=stock_code[-6:], period="daily", start_date="20260101", adjust="")
            if df is not None and len(df) > 0:
                results["akshare"] = {"close": float(df.iloc[-1]["收盘"]), "valid": True}
    except Exception:
        pass

    # 源3: mx_ds_mcp (通过MCP查询)
    # 在agent层做，脚本层跳过
    
    return results, errors


# ═══════════════════════════════════════════
#  主编排逻辑
# ═══════════════════════════════════════════

def run_daily():
    """每日选股日报流水线"""
    print("=" * 68)
    print("  📊 KIMI选股 — 每日选股日报")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 68)

    # 1. 数据保鲜
    print("\n📡 [1/5] 数据保鲜检查...")
    ok, detail = check_tdx_freshness()
    print(f"  {detail}")
    for r in check_cache_freshness():
        print(f"  {r}")

    if not ok:
        print("  ⚠️ TDX数据过期，尝试备源...")
        print("  ℹ️  mx_ds_mcp 和 akshare 可作为备源")

    # 2. 市场状态
    # [市场判断主源标注 2026-08-13] 市场判断来源: state_engine (market_state_engine是唯一市场判断主源, sentiment为备用不参与日报)
    print("\n📊 [2/5] 市场状态量化...")
    _market_gate_triggered = False  # P1-2026-08-23: 预初始化, 防异常时L292 NameError被吞
    try:
        from market_state_engine import assess_market_full
        m = assess_market_full(use_cache=False)
        print(f"  🏆 综合评分: {m['market_score']}/100 — {m['market_label']} (市场判断源: state_engine v2.1)")
        print(f"  🎯 主力策略: {m['primary_strategy']}")
        print(f"  💼 仓位建议: {m['position_advice']} ({m['position_ratio']*100:.0f}%)")
        for dim, info in m['sub_scores'].items():
            sigs = " | ".join(info['signals']) if info['signals'] else "中性"
            print(f"    {dim}: {info['score']}分 ({sigs})")
        # ⚠️ 弱市增强提醒 (2026-08-04 用户决策: 弱市提醒但不禁仓, 仍选最优个股)
        # P0-2026-08-24 T-002: 回测证据否决市场门——C无门+130% vs A/B有门-22%, 撤除实盘门控
        weak_label = m.get("market_label", "")
        weak_score = m.get("market_score", 50)
        # 仅保留提示, 不再设置 _market_gate_triggered / 禁仓标记
        if weak_label in ("弱", "恐慌") or weak_score < 40:
            print()
            print(f"  ⚠️  市场偏弱提醒: {weak_label}({weak_score}/100), 仍按策略精选个股")
            print(f"  💡 策略: 全仓1只轮动，止损8%铁律，不因市场评分放弃机会")
        _market_gate_triggered = False  # 显式常态化, 供后续兼容(不再阻断)
    except Exception as e:
        print(f"  ⚠️ {e}")

    # ── 昨日推荐回验 (2026-08-12 好友方案1: 日报标昨日推荐今日涨跌对错) ──
    print("\n📊 [2.5/5] 昨日推荐回验...")
    try:
        import json as _json
        from datetime import timedelta as _td
        _tl_path = os.path.join(PROJECT, "data", "trade_log.json")  # P0修复(2026-09-25): 真源统一到 data/ | P1修复(20261023): S4迁移后改用仓库根PROJECT
        if os.path.exists(_tl_path):
            with open(_tl_path, encoding="utf-8") as _f:
                _tl = _json.load(_f)
            _yesterday = (datetime.now() - _td(days=1)).strftime("%Y-%m-%d")
            _recs = _tl.get("recommendations", [])
            # 昨日推荐(有回验数据的优先, 其次昨日记录)
            _y_recs = [r for r in _recs if r.get("date") == _yesterday]
            _backfilled = [r for r in _y_recs if r.get("signal_return_pct") is not None]
            if _y_recs:
                for _r in _y_recs[:3]:
                    _ret = _r.get("signal_return_pct")
                    if _ret is not None:
                        _mark = "✅ 涨" if _ret > 0 else ("❌ 跌" if _ret < 0 else "➖ 平")
                        print(f"  {_r.get('date')} {_r.get('code')} {_r.get('name')}: 回验 {_ret:+.2f}% {_mark}")
                    else:
                        print(f"  {_r.get('date')} {_r.get('code')} {_r.get('name')}: ⏳ 待回填(5交易日后)")
                if not _backfilled:
                    print("  (昨日推荐回验数据未到, 5交易日后自动回填)")
            else:
                print(f"  昨日({_yesterday})无推荐记录")
    except Exception as _e:
        print(f"  ⚠️ 回验读取: {_e}")

    # 3. 选股 + 实盘唯一推荐 (结合账户可用资金)
    print("\n🎯 [3/5] 六层过滤选股...")
    try:
        # P0修复(2026-09-26 WorkBuddy, 接入实盘V2): 绕过包遮蔽, 直接加载生产权威入口
        # 根因: integrated_picker/ 包(冻结简化版, 仅Layer1, P0-5警告禁用于实盘) 遮蔽了
        #       同目录 integrated_picker.py 是生产完整版(根模块, 返回3元组)。注意
        #       `import core.pipeline.integrated_picker` 恒命中同名包(仅Layer1简化), 拿不到根模块, 结果口径
        #       与生产不一致; 故此处用文件路径直载根目录 integrated_picker.py 取生产完整版(解包见L266: 3元组)。
        import importlib.util as _ilu
        _prod_path = os.path.join(PROJECT, "integrated_picker.py")
        _prod_spec = _ilu.spec_from_file_location("integrated_picker_prod", _prod_path)
        _prod_mod = _ilu.module_from_spec(_prod_spec)
        _prod_spec.loader.exec_module(_prod_mod)
        run_integrated_picker = _prod_mod.run_integrated_picker
        # H1-P0修复(2026-08-26): 读门禁状态, FAIL→dry_run=True 防污染 trade_log
        _dry_run = False
        try:
            _gs_path = os.path.join(PROJECT, "data", "gate_status.json")
            if os.path.exists(_gs_path):
                _gs = json.load(open(_gs_path, encoding="utf-8"))
                if _gs.get("status", "").upper() != "PASS":
                    _dry_run = True
                    print(f"  🚫 门禁状态={_gs.get('status','?')}, 自动进入 dry_run 观察模式(不落库)")
                else:
                    # 代码新鲜度: tdx_core.py 变更后旧 PASS 作废(防未重跑回测即视作通过)
                    try:
                        import hashlib as _hl
                        _src = "".join(open(os.path.join(PROJECT, "tdx_core.py"), encoding="utf-8").readlines())
                        _cur_hash = _hl.md5(_src.encode()).hexdigest()[:12]
                        _gs_hash = (_gs.get("checks") or {}).get("code_hash")
                        if _gs_hash and _cur_hash != _gs_hash:
                            _dry_run = True
                            print(f"  🚫 代码已变更(tdx_core {_cur_hash}≠门禁{_gs_hash}), 旧PASS作废→dry_run")
                    except Exception as _ce:
                        print(f"  ⚠️ code_hash 比对异常({_ce}), 沿用门禁状态")
            else:
                _dry_run = True
                print("  🚫 门禁状态文件缺失(gate_status.json 不存在), fail-safe→dry_run")
        except Exception as _ge:
            _dry_run = True
            print(f"  🚫 门禁读取异常({_ge}), fail-safe→dry_run")
        # H3-数据门禁接入(2026-08-27): skill_router.pre_pick 指向缺失的 skill→no-op,
        # 故数据门禁(health_gate.json)此前从未被选股路径消费。此处就地补读: 缺失/非今日则补跑
        # health_check(懒加载), gate=block→dry_run。异常 fail-safe→dry_run。
        try:
            import datetime as _dt
            _today = _dt.datetime.now().strftime("%Y-%m-%d")
            _hg_path = os.path.join(PROJECT, "data", "health_gate.json")
            _hg = None
            if os.path.exists(_hg_path):
                _hg = json.load(open(_hg_path, encoding="utf-8"))
                if _hg.get("date") != _today:
                    _hg = None
            if _hg is None:
                try:
                    from core.ops.health_check import run_health_check
                    _hg = run_health_check()
                except Exception as _he:
                    print(f"  🚫 数据门禁补跑异常({_he}), fail-safe→dry_run")
                    _dry_run = True
            if _hg is not None and str(_hg.get("gate", "open")).lower() == "block":
                _dry_run = True
                print(f"  🚫 数据门禁 gate=block({_hg.get('red')}), 自动进入 dry_run 观察模式(不落库)")
        except Exception as _hge:
            _dry_run = True
            print(f"  🚫 数据门禁读取异常({_hge}), fail-safe→dry_run")
        ranking, config, _inds = run_integrated_picker(top_n=15, dry_run=_dry_run)
        # ── 读取账户可用现金 (决定推荐可行性) ──
        available_cash = 0
        hl = []  # P0-B(2026-08-09): 初始化, 异常分支兜底
        code = None  # P1-2修复: 预声明, 替代L239脆弱的"code in locals()"防NameError; 仅在空仓推荐块(下方L291附近)被真正赋值
        try:
            from core.ops.portfolio_review import load_holdings
            hl, ta, cash = load_holdings()
            available_cash = cash or 0
            if hl:
                print(f"  💰 账户现金: {available_cash:.0f}元 (持仓{len(hl)}只)")
        except Exception as ce:
            print(f"  ⚠️ 持仓读取: {ce}")
        # ── 空仓门禁 (2026-08-09, 单票轮动: 持仓时不推荐新票, 卖出后再选) ──
        if hl:
            print(f"  📋 单票轮动纪律: 持仓{len(hl)}只, 不推荐新票 (卖出后再选下一只)")
        # ── E 变体参考 (2026-08-09 P0-1: 反转+MAX回避, 只展示不替换推荐) ──
        # 修复(2026-08-11): 从 if ranking and not hl: 内移出 — 参考票不占资金,
        # 持仓时也应评估并落库, 否则试点永不启动 (trade_log 0 条 variant_reference)
        # E 是重排选择器: min(chg20 + 1.25*max_ret5), 非打分器 — 展示 E 变体 TOP1 作观察期参考
        if ranking:
            try:
                from core.pipeline.tdx_core import compute_indicators, get_tdx_data
                _e_best = None
                for _cand in ranking:
                    _cc = _cand[8]
                    _recs = None
                    try:
                        _recs = get_tdx_data(_cc, 60)
                    except Exception:
                        _recs = None
                    if not _recs or len(_recs) < 30:
                        continue
                    _inds = compute_indicators(_recs)
                    if not _inds:
                        continue
                    _e_score = (_inds.get("chg20", 0) or 0) + 1.25 * (_inds.get("max_ret5", 0) or 0)
                    if _e_best is None or _e_score < _e_best[0]:
                        _e_best = (_e_score, _cc, _cand[9] if len(_cand) > 9 else "")
                if _e_best:
                    _e_score, _e_code, _e_name = _e_best
                    # P1-2修复: 已在上方L202预声明code=None, 去掉脆弱的locals()检查
                    _same = ("✅一致" if _e_code == code else "🔄不同") if code else "🔬持仓参考"
                    print(f"  🔬 E变体参考(反转+MAX回避): {_e_code} {_e_name} (E分{_e_score:+.1f}) | 与现状: {_same}")
                    print("     (口径: 候选池Top15≠回测top30, 仅作参考)")
                    # P0-2: variant_reference 落库 (观察期逐笔记录, 复用 actual_return_pct 回填)
                    try:
                        from core.pipeline.atomic_json import update_json
                        _today = date.today().strftime("%Y-%m-%d")

                        def _mutate(log):
                            if not isinstance(log, dict):
                                log = {"recommendations": []}
                            log.setdefault("recommendations", [])
                            for _r in log["recommendations"]:
                                if _r.get("date") == _today and _r.get("type") == "variant_reference" and _r.get("variant") == "E":
                                    return log  # 同日同variant去重
                            log["recommendations"].append({
                                "type": "variant_reference", "variant": "E",
                                "date": _today, "code": _e_code, "name": _e_name,
                                "e_score": round(_e_score, 1),
                                "market_label": m.get("market_label", ""),  # 分状态统计用 (2026-08-09)
                                "note": "E变体参考(反转+MAX回避), 不替换现状推荐",
                            })
                            return log

                        update_json(os.path.join(PROJECT, "data", "trade_log.json"), _mutate,  # P0修复(2026-09-25): 真源统一到 data/
                                    default={"recommendations": []})
                    except Exception as _le:
                        print(f"  ⚠️ E变体落库: {_le}")
            except Exception as _ee:
                print(f"  ⚠️ E变体参考: {_ee}")

        # ── 实盘唯一推荐: 综合策略 TOP1 (贴合全仓单只风格) ──
        # P0-2026-08-24 T-002: 回测否决市场门, 撤除 _market_gate_triggered 阻断 (恒为False)
        if ranking and not hl and not _market_gate_triggered:
            # 从排名找第一个"买得起"的标的(一手成本 <= 现金)
            top = None
            for cand in ranking:
                cand_code = cand[8]
                try:
                    from core.pipeline.tdx_core import get_tdx_data
                    cand_recs = get_tdx_data(cand_code, 30)
                    cand_price = cand_recs[-1]["close"] if cand_recs else 999
                except Exception:
                    cand_price = 999
                # P0-追高关闭 (2026-08-16 老大拍板: 回测+14pp, 实盘接入): 信号日涨幅>4% 顺延下一候选
                try:
                    from backtest.backtest_rotation import signal_day_chg as _sdc
                    _sd = _sdc(cand_recs, cand_recs[-1]["date"]) if cand_recs else None
                    if _sd and _sd[1] is not None and _sd[1] > 4.0:
                        print(f"  🚫 追高关闭: {cand_code} 信号日涨幅{_sd[1]:+.1f}% > 4% 跳过(顺延)")
                        continue
                except Exception:
                    pass
                lot_cost = cand_price * 100
                if available_cash <= 0 or lot_cost <= available_cash:
                    top = cand
                    break
            if top is None:
                top = ranking[0]
                print("  ⚠️ 现金不足买不起任何候选, 仍推荐TOP1(仅供参考, 待现金回笼后执行)")
            # 20元组: 0=final 1=sc_zh 2=sc_qc 3=risk 4=confidence 5=pass_risk
            # 8=code 9=name 10=industry 13=gap_score 16=nb_score 19=extra_sigs
            code = top[8]
            name = top[9]
            score = top[1]
            print("\n  🎯 实盘唯一推荐(综合TOP1):")
            if m.get("market_label") in ("弱", "恐慌"):
                print("  ⚠️ 弱市中: 推荐仅供参考, 若买入请轻仓+严格止损")
            print(f"    {code} {name} 综合评分{score}")
            # ── 拥挤度监测 (2026-08-12 自动学习#4: 风格拥挤度风险) ──
            # 注: ranking无行业字段, 用板块(主板/创业板/科创板)近似风格集中度; 行业级需另接数据源
            try:
                _ind_cnt = {}
                for _c in ranking:
                    _ind = _c[10] if len(_c) > 10 and _c[10] else "未知"
                    _ind_cnt[_ind] = _ind_cnt.get(_ind, 0) + 1
                _top3 = sorted(_ind_cnt.items(), key=lambda x: -x[1])[:3]
                _crowd = _top3[0][1] / max(len(ranking), 1) * 100 if _top3 else 0
                _crowd_note = "⚠️ 拥挤" if _crowd >= 40 else ("—" if _crowd >= 25 else "分散")
                _sec_line = " | ".join(f"{k}({v}只)" for k, v in _top3)
                print(f"  🧭 候选池拥挤度: TOP1板块占比{_crowd:.0f}%{_crowd_note}")
                print(f"     板块分布: {_sec_line}")
                if _crowd >= 40:
                    print("     ⚠️ 拥挤提示: 候选池过度集中同一板块, 若该板块回调, 推荐同质化风险高")
            except Exception as _ce:
                print(f"  ⚠️ 拥挤度计算: {_ce}")
            # 生成交易计划
            try:
                from risk_rules import generate_trade_plan
                from core.pipeline.tdx_core import get_tdx_data
                recs = get_tdx_data(code, 30)
                entry = recs[-1]["close"] if recs else 0
                gap_score = top[13] if len(top) > 13 else 0
                nb_score = top[16] if len(top) > 16 else 0
                capital = available_cash if available_cash > 0 else 23000
                plan = generate_trade_plan(entry, "综合", m.get("market_score", 50),
                                           m.get("market_label", "震荡"),
                                           gap_score, nb_score, "medium", capital,
                                           trend="up")  # 默认上升趋势，使用M2阶梯
                if plan:
                    print(f"    入场参考: {entry:.2f} (一手{entry*100:.0f}元)")
                    # P0-T1低开提醒 (2026-08-16 老大拍板: 提醒模式, 不自动拦截):
                    # 次日开盘低开>3% = 利空兑现/跳空死区, 建议回避。8:50盘前无开盘价, 给静态回避线
                    print(f"    🛑 T1低开提醒: 若开盘 < {entry*0.97:.2f} 元(低开>3%) 建议回避 | 昨收 {entry:.2f}")
                    print(f"    可用现金: {available_cash:.0f}元 → {'✅可买' if entry*100 <= available_cash or available_cash<=0 else '⚠️现金不足'}")
                    print(f"    止损: {plan.get('stop_loss','-')} ({plan.get('stop_loss_pct','-')}%)")
                    print(f"    TP1: {plan.get('tp1','-')} ({plan.get('tp1_pct','-')}%)")
                    print(f"    TP2: {plan.get('tp2','-')} ({plan.get('tp2_pct','-')}%)")
                    print(f"    仓位: {plan.get('position_pct','-')}%")
            except Exception as pe:
                print(f"    (交易计划生成失败: {pe})")
    except Exception as e:
        print(f"  ⚠️ {e}")

    # 3.5 评分质量诊断 (v8.1 三指标验收, 2026-08-06: 自动产出, 供明晨验收)
    try:
        print("\n📊 [3.5/5] 评分质量诊断 (v8.1 三指标验收)...")
        from core.ops.score_diagnostics import run_diagnostics
        _diag_report = run_diagnostics()
        for _line in _diag_report.split("\n"):
            print(f"    {_line}")
    except Exception as de:
        print(f"  ⚠️ 评分诊断: {de}")

    # 3.6 拥挤度监测 (2026-08-12 学习采纳①: 候选池行业重叠度>阈值→风格拥挤提示)
    try:
        print("\n🧩 [3.6/5] 拥挤度监测 (风格集中风险)...")
        if ranking and len(ranking) >= 3:
            from core.pipeline.tdx_core import load_industry_map
            _ind_map = load_industry_map()
            _cnt = {}
            for _cand in ranking[:10]:
                _cc = _cand[8]
                _ind = _ind_map.get(_cc) or _ind_map.get(_cc[2:]) or "未知"
                _cnt[_ind] = _cnt.get(_ind, 0) + 1
            _top_ind, _top_n = max(_cnt.items(), key=lambda x: x[1])
            _ratio = _top_n / min(len(ranking), 10)
            print(f"    候选池前10行业分布: {dict(sorted(_cnt.items(), key=lambda x:-x[1]))}")
            if _ratio >= 0.4:
                print(f"    🚨 风格拥挤: {_top_ind} 占 {_top_n}/10 ({_ratio*100:.0f}%) → 同板块共振风险, 追高需谨慎")
            elif _ratio >= 0.3:
                print(f"    ⚠️ 偏集中: {_top_ind} 占 {_top_n}/10 ({_ratio*100:.0f}%) → 注意板块联动")
            else:
                print(f"    ✅ 分散正常: 最集中行业 {_top_ind} 占 {_ratio*100:.0f}%")
        else:
            print("    候选池不足, 跳过")
    except Exception as ce:
        print(f"  ⚠️ 拥挤度: {ce}")

    # 4. 持仓复盘 + 监控提醒
    print("\n📁 [4/5] 持仓复盘+监控提醒...")
    try:
        from core.ops.portfolio_review import load_holdings, analyze_single_stock
        from core.ops.position_alerts import check_position_alerts
        hl, ta, cash = load_holdings()
        if hl:
            for h in hl:
                result = analyze_single_stock(h.get("code",""), h.get("name",""),
                                              h.get("cost_price",0), h.get("shares",0))
                if result:
                    print(f"    浮盈: {result.get('pl_pct',0):+.2f}%  |  止损: {result.get('stop_loss','-')}")
                # 财务健康分 (基本面维度)
                try:
                    from core.scoring.financial_filter import score_stock_financial
                    code_clean = h.get("code","")
                    code_clean = code_clean[2:] if code_clean[:2].isalpha() else code_clean
                    fr = score_stock_financial(code_clean, force_refresh=False)
                    print(f"    🏭 财务健康: {fr['financial_health']}/40 | 舞弊: {fr['fraud_penalty']} | 净: {fr['total_bonus']:+d}")
                except Exception as fe:
                    print(f"    ℹ️  财务评分: {fe}")
            # 持仓监控提醒(触发则输出, 由 cron 投递微信)
            alerts = check_position_alerts()
            if alerts:
                print("\n  🔔 持仓提醒:")
                for a in alerts:
                    print(f"    {a['level']} [{a['name']}] {a['message']}")
        else:
            print("  ℹ️  无持仓数据")
    except Exception as e:
        print(f"  ℹ️  持仓读取: {e}")

    # 5. 风控
    print("\n⚠️ [5/5] 风控检查...")
    try:
        import subprocess
        # W3 2026-10-17 静默运行: 派生一律带 CREATE_NO_WINDOW, 否则 Windows 给无控制台宿主
        # 的子进程分配新可见控制台(弹黑框)。见 docs/规范-静默运行-20261017.md
        # 回灌自 archive/root-py-batch3: 6adbea0a 回滚误删, 2026-10-21 合回根侧
        CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run([sys.executable, os.path.join(PROJECT, "risk_monitor.py"), "--report"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                          creationflags=CREATE_NO_WINDOW)
        out = (r.stdout or "").strip()
        if out:
            # 提取关键行
            for line in out.split("\n"):
                if any(kw in line for kw in ["🟢", "🟡", "🔴", "风控", "风险", "止损", "仓位", "警报"]):
                    print(f"  {line.strip()}")
        print("  ✅ 风控模块已运行")
    except Exception as e:
        print(f"  ℹ️  风控: {e}")

    print("\n" + "=" * 68)
    print(f"  ✅ 日报完成 — {datetime.now().strftime('%H:%M')}")
    print("=" * 68)


def _load_profit_ratio_stats():
    """P2-1: 单笔盈亏比统计 — 读回测明细 trade_detail.csv (utf-8-sig) 直接计算,
    CSV 缺失时回退 profit_ratio.json. 返回 dict 或 None."""
    csv_path = os.path.join(PROJECT, "backtest_analysis", "trade_detail.csv")
    rows = []
    try:
        import csv as _csv
        if os.path.exists(csv_path):
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                for r in _csv.DictReader(f):
                    try:
                        chg5 = float(r["5日收益%"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    rows.append({"date": r.get("扫描日期", ""), "name": r.get("股票名称", ""), "chg5": chg5})
    except Exception:
        rows = []
    if rows:
        wins = [r["chg5"] for r in rows if r["chg5"] > 0]
        losses = [r["chg5"] for r in rows if r["chg5"] < 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        ratio = abs(avg_win / avg_loss) if avg_loss != 0 else (float("inf") if avg_win > 0 else 0.0)

        def _buckets(vals, edges):
            dist = {}
            prev = None
            for lo, hi, label in edges:
                dist[label] = sum(1 for v in vals if (prev is None or v > prev) and v <= hi)
                prev = hi
            return dist

        win_dist = _buckets(wins, [(0, 5, "0~5%"), (5, 10, "5~10%"), (10, 20, "10~20%"), (20, 1e9, ">20%")])
        loss_dist = _buckets(losses, [(-5, 0, "-5%~0"), (-10, -5, "-10%~-5"), (-20, -10, "-20%~-10"), (-1e9, -20, "<-20%")])
        return {
            "总笔数": len(rows), "盈利笔数": len(wins), "亏损笔数": len(losses),
            "avg_win": avg_win, "avg_loss": avg_loss,
            "盈亏比": ratio if ratio != float("inf") else "∞",
            "最大单笔盈利": max(wins) if wins else 0.0,
            "最大单笔亏损": min(losses) if losses else 0.0,
            "盈利笔分布": win_dist, "亏损笔分布": loss_dist,
            "最大盈利股票": max(rows, key=lambda x: x["chg5"]) if rows else None,
            "最大亏损股票": min(rows, key=lambda x: x["chg5"]) if rows else None,
        }
    # 回退: 读统计脚本产物 json
    try:
        import json as _json4
        jp = os.path.join(PROJECT, "backtest_analysis", "profit_ratio.json")
        if os.path.exists(jp):
            return _json4.load(open(jp, encoding="utf-8"))
    except Exception:
        pass
    return None


def _load_live_vs_backtest():
    """P2-2: 实盘 vs 回测差异追踪 — 优先读 data/live_vs_backtest.json
    (由 scripts_tmp/analyze_live_vs_backtest.py 生成, 含本地模型 LLM 解读);
    缺失/过期(>7天)时内联轻量重算(同口径, 解读用模板兜底, 不调LLM不写文件)."""
    jp = os.path.join(PROJECT, "data", "live_vs_backtest.json")
    try:
        if os.path.exists(jp):
            with open(jp, encoding="utf-8") as f:
                d = json.load(f)
            g = str(d.get("generated_at", ""))[:10]
            try:
                gd = datetime.strptime(g, "%Y-%m-%d").date()
                if (date.today() - gd).days <= 7:
                    return d
            except ValueError:
                pass
    except Exception:
        pass
    return _compute_live_vs_backtest_inline()


def _compute_live_vs_backtest_inline():
    """内联轻量版 实盘vs回测对比(与独立脚本 scripts_tmp/analyze_live_vs_backtest.py 同口径, 无LLM):
    持仓浮盈(TDX现价) + 已结算统计(sells[]/recommendations.actual_return_pct) + 回测基准 + 模板解读"""
    try:
        from core.pipeline.tdx_core import get_tdx_data
        with open(os.path.join(PROJECT, "data", "holdings.json"), encoding="utf-8") as f:  # 2026-09-09 Bug2
            hd = json.load(f)
        holdings = hd.get("holdings", []) or []
        cash = hd.get("available_cash", 0) or 0

        total_cost = total_value = 0.0
        open_positions = []
        for h in holdings:
            code = h.get("code", "")
            cost = float(h.get("cost", h.get("cost_price", 0)) or 0)
            shares = int(h.get("shares", 0) or 0)
            price = None
            try:
                recs = get_tdx_data(code, 60)
                if recs:
                    price = recs[-1]["close"]
            except Exception:
                price = None
            pl_out = None if price is None else round((price - cost) / cost * 100, 2) if cost else 0.0
            mv = (price * shares) if price else (cost * shares)  # 取价失败按成本近似
            total_cost += cost * shares
            total_value += mv
            open_positions.append({
                "code": code, "name": h.get("name", code), "cost_price": cost, "shares": shares,
                "current_price": price, "unrealized_pl_pct": pl_out, "market_value": round(mv, 2),
            })

        with open(os.path.join(PROJECT, "data", "trade_log.json"), encoding="utf-8") as f:  # P0修复(2026-09-25): 真源统一到 data/
            tl = json.load(f)
        settled = []
        seen = set()
        for s in tl.get("sells", []):
            if s.get("actual_return_pct") is None:
                continue
            key = (str(s.get("code", "")), str(s.get("sell_date", "")))
            if key in seen:
                continue
            seen.add(key)
            settled.append(s)
        for r in tl.get("recommendations", []):
            if not r.get("followed") or r.get("actual_return_pct") is None:
                continue
            key = (str(r.get("code", "")), str(r.get("sell_date", "")))
            if key in seen:
                continue
            seen.add(key)
            settled.append(r)
        n = len(settled)
        wins = [s["actual_return_pct"] for s in settled if s["actual_return_pct"] > 0]
        losses = [s["actual_return_pct"] for s in settled if s["actual_return_pct"] < 0]
        rets = [s["actual_return_pct"] for s in settled]
        avg_w = sum(wins) / len(wins) if wins else None
        avg_l = sum(losses) / len(losses) if losses else None
        ratio = (abs(avg_w / avg_l) if (avg_w and avg_l) else None)

        with open(os.path.join(PROJECT, "backtest_result.json"), encoding="utf-8-sig") as f:
            bt = json.load(f)
        pr = _load_profit_ratio_stats() or {}
        benchmark = {
            "range": bt.get("回测区间", ""), "trades": bt.get("总交易次数", 0),
            "win_rate": bt.get("胜率", 0), "avg_5d": bt.get("平均持仓5日收益", 0),
            "excess_5d": bt.get("超额收益5日", 0), "profit_ratio": pr.get("盈亏比"),
            "avg_win": pr.get("avg_win"), "avg_loss": pr.get("avg_loss"),
            "source": "inline (backtest_result.json + profit_ratio)",
        }
        unrealized = ((total_value - total_cost) / total_cost * 100) if total_cost else 0.0
        live = {
            "open_positions": open_positions, "open_count": len(open_positions),
            "total_cost": round(total_cost, 2), "total_value": round(total_value, 2),
            "unrealized_pl_pct": round(unrealized, 2), "cash": cash,
            "total_assets": round(total_value + cash, 2),
            "settled": settled, "settled_trades": n, "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / n * 100, 1) if n else None,
            "avg_return": round(sum(rets) / len(rets), 2) if rets else None,
            "avg_win": round(avg_w, 2) if avg_w is not None else None,
            "avg_loss": round(avg_l, 2) if avg_l is not None else None,
            "profit_ratio": round(ratio, 2) if ratio is not None else None,
        }
        wd = (round(live["win_rate"] - benchmark["win_rate"], 2)
              if live["win_rate"] is not None else None)
        ad = (round(live["avg_return"] - benchmark["avg_5d"], 2)
              if live["avg_return"] is not None else None)
        pd = None
        if isinstance(benchmark["profit_ratio"], (int, float)) and isinstance(live["profit_ratio"], (int, float)):
            pd = round(live["profit_ratio"] - benchmark["profit_ratio"], 2)
        comparison = {
            "win_rate_diff": wd, "avg_return_diff": ad, "profit_ratio_diff": pd,
            "sample_note": "实盘已结算样本量过小，与回测无可比性" if n < 10 else "样本量可初步对比",
            "note": "内联降级计算(无LLM解读); 完整版由 scripts_tmp/analyze_live_vs_backtest.py 生成",
        }
        interp = {
            "summary": f"实盘已结算仅{n}笔，样本量远小于回测{benchmark['trades']}笔，"
                       f"差异主要来自样本量不足而非策略失效；持仓浮盈未结算存在回撤风险。",
            "risks": ["实盘样本过小，统计结论不可靠", "持仓浮盈未实现，市场回调将侵蚀收益"],
            "source": "template_fallback (inline)",
        }
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "as_of": date.today().strftime("%Y-%m-%d"),
            "live": live, "backtest_benchmark": benchmark,
            "comparison": comparison, "llm_interpretation": interp,
        }
    except Exception as e:
        return {"error": f"差异追踪计算失败: {e}"}


def run_weekly():
    """每周策略周报流水线"""
    print("=" * 68)
    print("  📊 KIMI选股 — 每周策略周报")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 68)

    # 本周大盘
    print("\n📈 [1/5] 本周大盘走势...")
    try:
        from core.pipeline.tdx_core import get_tdx_data
        sh = get_tdx_data("sh000001", 10)
        if sh and len(sh) >= 5:
            prices = [r["close"] for r in sh[-5:]]
            chg = (prices[-1] - prices[0]) / prices[0] * 100
            print(f"  上证指数: {prices[-1]:.2f}  周涨幅: {chg:+.2f}%")
            print(f"  区间: {min(prices):.2f} ~ {max(prices):.2f}")
        else:
            print("  ⚠️ 上证指数数据不足")
    except Exception as e:
        print(f"  ⚠️ {e}")

    # 推荐回顾
    print("\n🎯 [2/5] 本周推荐回顾...")
    try:
        from core.ops.trade_tracker import calc_performance
        stats = calc_performance()
        if stats:
            print(f"  总交易: {stats.get('total_trades',0)}  胜率: {stats.get('win_rate',0):.1f}%")
            print(f"  平均收益: {stats.get('avg_return_pct',0):+.2f}%  盈亏比: {stats.get('profit_factor','∞')}")
            print(f"  最大盈利: {stats.get('max_return_pct',0):+.2f}%  最大亏损: {stats.get('min_return_pct',0):+.2f}%")
        else:
            print("  ℹ️  暂无已结算推荐")
    except Exception as e:
        print(f"  ⚠️ {e}")

    # 持仓复盘(含实盘绩效汇总)
    print("\n📁 [3/5] 持仓周度复盘...")
    try:
        from core.ops.portfolio_review import load_holdings, analyze_single_stock
        from core.pipeline.tdx_core import get_tdx_data
        hl, ta, cash = load_holdings()
        if hl:
            total_value = 0
            total_cost = 0
            for h in hl:
                result = analyze_single_stock(h.get("code",""), h.get("name",""),
                                              h.get("cost_price",0), h.get("shares",0))
                if result:
                    pl = result.get('pl_pct', 0)
                    mv = result.get('market_value', 0)
                    total_value += mv
                    total_cost += h.get("cost", h.get("cost_price", 0)) * h.get("shares", 0)
                    print(f"    {h.get('name')}: 浮盈 {pl:+.2f}% | 市值 {mv:.0f}")
            # 实盘汇总
            total_pl = (total_value - total_cost) / total_cost * 100 if total_cost else 0
            print(f"  实盘汇总: 持仓市值 {total_value:.0f} | 成本 {total_cost:.0f} | 浮盈 {total_pl:+.2f}%")
            print(f"  可用现金: {cash:.0f} | 总资产: {total_value + cash:.0f}")
        else:
            print("  ℹ️  无持仓数据")
    except Exception as e:
        print(f"  ℹ️  {e}")

    # 策略胜率对比(实盘 vs 回测) — P1 (2026-08-04): 自动重跑回测确保对比最新评分
    print("\n📊 [3b/5] 策略表现对比...")
    try:
        # P1: 自动重跑 strict-top1 回测 (与实盘逻辑一致), 产出最新 backtest_result.json
        import subprocess as _sp
        # W3 2026-10-17 静默运行: 派生一律带 CREATE_NO_WINDOW(见 docs/规范-静默运行-20261017.md)
        # 回灌自 archive/root-py-batch3: 6adbea0a 回滚误删, 2026-10-21 合回根侧
        CREATE_NO_WINDOW = getattr(_sp, "CREATE_NO_WINDOW", 0)
        bt_result = None
        try:
            print("  🔄 自动重跑回测 (strict-top1, 与实盘逻辑一致)...")
            r = _sp.run([sys.executable, os.path.join(PROJECT, "backtest.py"), "backtest", "--strict-top1"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                        creationflags=CREATE_NO_WINDOW)
            import json as _json2
            if os.path.exists(os.path.join(PROJECT, "backtest_result.json")):
                bt_result = _json2.load(open(os.path.join(PROJECT, "backtest_result.json"), encoding="utf-8-sig"))
                print(f"  ✅ 回测完成: {bt_result.get('总交易次数',0)}笔 胜率{bt_result.get('胜率',0):.1f}%")
            else:
                print(f"  ⚠️ 回测未产出结果: {r.stderr[-200:] if r.stderr else '无输出'}")
        except Exception as be:
            print(f"  ⚠️ 自动回测失败(用缓存结果): {be}")
            bt_file = os.path.join(PROJECT, "backtest_result.json")
            if os.path.exists(bt_file):
                import json as _json3
                bt_result = _json3.load(open(bt_file, encoding="utf-8"))

        from core.ops.trade_tracker import calc_performance
        stats = calc_performance()
        if stats:
            live_win = stats.get('win_rate', 0)
            print(f"  实盘已结算: {stats.get('total_trades',0)}笔 胜率{live_win:.1f}% 平均{stats.get('avg_return_pct',0):+.2f}%")
        # 回测基准对比(严格全仓单只)
        if bt_result:
            bt_win = bt_result.get("胜率", 0)
            bt_trades = bt_result.get("总交易次数", 0)
            bt_excess = bt_result.get("超额收益5日", 0)
            print(f"  回测基准(全仓单只): {bt_trades}笔 胜率{bt_win:.1f}% 超额5日{bt_excess:+.2f}%")
            # P1: 基线对比 (2026-08-13 更新: 真实费率回测后胜率29.8% — v8.0的65.8%是虚假高胜率口径已废弃)
            # 真实费率口径下: 胜率~30%, 超额5日~-1% 是当前策略实际水平, 触发线同步调整
            base_win, base_excess = 29.8, -1.0
            win_delta = bt_win - base_win
            exc_delta = bt_excess - base_excess
            # 2026-08-13 P0-1 修复: 触发线改为相对基线偏离度 — 旧绝对阈值(胜率<50%)在真实费率口径下永远触发(29.8%<50),
            # 导致每日日报反复写审计标记+反复spawn审查子进程死循环。现在: 胜率低于基线5pct或超额低于基线1pct才触发
            if win_delta < -5.0 or exc_delta < -1.0:
                print(f"  🚨 回测异常告警: 胜率{bt_win:.1f}% (<50%) 或 超额{bt_excess:+.2f}% (<-1%) — 建议触发 agent 审查")
                # P2 (2026-08-04): 写审查触发标记, 由 audit-review cron 检测并启动 agent 审查
                try:
                    from core.pipeline.atomic_json import atomic_dump  # R4c #2 (K54 补2 全量替换语义): 全量覆盖+原子写, 行为等同原裸 open('w'), 零读侧改动
                    trigger = {
                        "triggered_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "reason": f"回测异常: 胜率{bt_win:.1f}% 超额{bt_excess:+.2f}%",
                        "backtest": {"trades": bt_trades, "win_rate": bt_win, "excess_5d": bt_excess},
                        "status": "pending",  # pending → 被 agent 审查后置 reviewed
                    }
                    atomic_dump(trigger, os.path.join(PROJECT, "data", "audit_trigger.json"))
                    print(f"  📝 已写入审查触发标记: data/audit_trigger.json (待 agent 审查, 原子写)")
                except Exception as ae:
                    print(f"  ⚠️ 审查标记写入失败: {ae}")
            else:
                # 正常时清除旧标记(如果存在)
                try:
                    trig_path = os.path.join(PROJECT, "data", "audit_trigger.json")
                    if os.path.exists(trig_path):
                        os.remove(trig_path)
                        print("  ✅ 回测正常, 已清除旧审查标记")
                except Exception:
                    pass
            print(f"  📈 vs v8.0基线(65.8%/+1.09%): 胜率{win_delta:+.1f}pct 超额{exc_delta:+.2f}pct")
            if stats and bt_win:
                diff = live_win - bt_win
                print(f"  实盘vs回测: {'✅ 实盘优于回测' if diff > 0 else '⚠️ 实盘落后回测'} ({diff:+.1f}pct)")
    except Exception as e:
        print(f"  ⚠️ {e}")

    # P2-1: 单笔盈亏比分析 (回测明细 trade_detail.csv → avg_win/avg_loss/盈亏比/最大盈亏)
    print("\n📊 [3c/5] 盈亏比分析...")
    try:
        pr = _load_profit_ratio_stats()
        if pr:
            ratio_s = pr.get("盈亏比", 0)
            ratio_s = f"{ratio_s:.2f}" if isinstance(ratio_s, (int, float)) else str(ratio_s)
            print(f"  回测明细: {pr.get('总笔数', 0)}笔 | 盈利{pr.get('盈利笔数', 0)} / 亏损{pr.get('亏损笔数', 0)} | 胜率{pr.get('胜率', (pr.get('盈利笔数', 0) / pr.get('总笔数', 1) * 100) if pr.get('总笔数') else 0):.1f}%")
            print(f"  avg_win: {pr.get('avg_win', 0):+.2f}% | avg_loss: {pr.get('avg_loss', 0):+.2f}% | 盈亏比: {ratio_s}")
            print(f"  最大单笔盈利: {pr.get('最大单笔盈利', 0):+.2f}% | 最大单笔亏损: {pr.get('最大单笔亏损', 0):+.2f}%")
            max_w = pr.get("最大盈利股票") or {}
            max_l = pr.get("最大亏损股票") or {}
            print(f"  最佳: {max_w.get('name', '-')} ({max_w.get('date', '')}) {max_w.get('chg5', 0):+.2f}%"
                  f" | 最差: {max_l.get('name', '-')} ({max_l.get('date', '')}) {max_l.get('chg5', 0):+.2f}%")
            wd = pr.get("盈利笔分布") or {}
            if wd:
                print(f"  盈利分布: " + " | ".join(f"{k}:{v}笔" for k, v in wd.items()))
        else:
            print("  ℹ️  无回测明细 (trade_detail.csv / profit_ratio.json 缺失)")
    except Exception as e:
        print(f"  ⚠️ 盈亏比分析失败: {e}")

    # P2-2 (2026-08-05): 实盘 vs 回测差异解读 (本地模型辅助)
    print("\n📊 [3d/5] 实盘vs回测差异解读...")
    try:
        lvb = _load_live_vs_backtest()
        if not lvb or lvb.get("error"):
            print(f"  ⚠️ {(lvb or {}).get('error', '无对比数据')}")
        else:
            live = lvb.get("live") or {}
            bt = lvb.get("backtest_benchmark") or {}
            cmp_ = lvb.get("comparison") or {}
            interp = lvb.get("llm_interpretation") or {}

            def _f(v, plus=False):
                if v is None:
                    return "-"
                if isinstance(v, str):
                    return v
                return f"{v:+.2f}" if plus else f"{v:.1f}"

            def _pr(v):
                if v is None:
                    return "-"
                if isinstance(v, str):
                    return v
                return f"{v:.2f}"

            print(f"  实盘已结算 {live.get('settled_trades', 0)}笔: 胜率{_f(live.get('win_rate'))}% "
                  f"平均{_f(live.get('avg_return'), plus=True)}% 盈亏比{_pr(live.get('profit_ratio'))}")
            print(f"  实盘持仓浮盈 {live.get('unrealized_pl_pct', 0):+.2f}% (未结算) | "
                  f"总资产 {live.get('total_assets', 0):.0f} | 现金 {live.get('cash', 0):.0f}")
            for p in live.get("open_positions", []):
                pl = p.get("unrealized_pl_pct")
                pl_s = f"{pl:+.2f}%" if pl is not None else "N/A(取价失败)"
                px = p.get("current_price")
                print(f"    {p.get('name')}({p.get('code')}): 现价{px if px else 'N/A'} 浮盈{pl_s}")
            print(f"  回测基准(strict-top1): {bt.get('trades', 0)}笔 胜率{_f(bt.get('win_rate'))}% "
                  f"平均5日{_f(bt.get('avg_5d'), plus=True)}% 超额5日{_f(bt.get('excess_5d'), plus=True)}% "
                  f"盈亏比{_pr(bt.get('profit_ratio'))}")
            diffs = []
            if cmp_.get("win_rate_diff") is not None:
                diffs.append(f"胜率{cmp_['win_rate_diff']:+.1f}pct")
            if cmp_.get("avg_return_diff") is not None:
                diffs.append(f"平均收益{cmp_['avg_return_diff']:+.2f}pct")
            if diffs:
                print("  差异: " + " ".join(diffs))
            if cmp_.get("sample_note"):
                print(f"  ℹ️  {cmp_['sample_note']}")
            print(f"  🧠 解读({interp.get('source', '-')}): {interp.get('summary', '-')}")
            for r in interp.get("risks", []):
                print(f"    ⚠️ {r}")
            print(f"  (数据生成: {lvb.get('generated_at', '-')})")
    except Exception as e:
        print(f"  ⚠️ 差异解读失败: {e}")

    # 自进化
    print("\n🧬 [4/5] 自进化状态...")
    try:
        from evolution_engine import check_status
        check_status()
    except Exception as e:
        print(f"  ⚠️ {e}")

    # 下周展望
    print("\n🔮 [5/5] 下周策略展望...")
    try:
        from market_state_engine import assess_market_full
        m = assess_market_full(use_cache=True)
        top3 = sorted(m['strategy_weights'].items(), key=lambda x: -x[1])[:3]
        print(f"  当前市场: {m['market_label']} ({m['market_score']}/100)")
        print(f"  建议策略: {m['primary_strategy']}")
        print(f"  仓位建议: {m['position_advice']} ({m['position_ratio']*100:.0f}%)")
        print(f"  下周重点: {', '.join(f'{n}({w*100:.0f}%)' for n,w in top3)}")
    except Exception as e:
        print(f"  ⚠️ {e}")

    # P1-14A (2026-08-08): 记忆使用率自动采集 — 验证C决策证伪条件
    # (压缩后>90%连续2周或每月压缩≥2次 → 启动holographic插件评估)
    # 注意: 实测 hermes memory status CLI 不输出 usage%, 故直接读 MEMORY.md 字节数
    try:
        _mem_path = os.path.join(
            os.environ.get("HERMES_HOME", r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"),
            "memories", "MEMORY.md")
        if os.path.exists(_mem_path):
            with open(_mem_path, encoding="utf-8") as _f:
                _mem_chars = len(_f.read())
            _mem_limit = 2200  # Hermes memory 字符上限
            _mem_pct = _mem_chars / _mem_limit * 100
            print(f"  📊 记忆使用率: {_mem_chars}/{_mem_limit} 字符 ({_mem_pct:.0f}%)")
            if _mem_pct > 90:
                print("  ⚠️ 记忆>90%: 需压缩; 若连续2周/每月压缩≥2次 → 启动holographic插件评估")
        else:
            print(f"  ⚠️ 记忆文件不存在: {_mem_path}")
    except Exception as e:
        print(f"  ⚠️ 记忆使用率采集失败: {e}")

    print("\n" + "=" * 68)
    print("  ✅ 周报完成")
    print("=" * 68)


def run_health():
    """系统健康检查"""
    # system_health_check 无 run_all_checks 函数(只有 test/warn), 改用 system_health 主流程
    import core.ops.system_health as system_health  # 2026-10-24 [t_laosan_r5_bare_import]: 原裸 import 只绑定 core, 下方 system_health.* 会 NameError, 补 as 别名
    system_health.main()


def run_evolve():
    """触发自进化"""
    from evolution_engine import run_evolution
    run_evolution()  # 签名无参数(auto 由内部自动判断)


# ═══════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    modes = {
        "daily": run_daily,
        "weekly": run_weekly,
        "pick": run_daily,
        "health": run_health,
        "evolve": run_evolve,
    }
    fn = modes.get(mode)
    if fn:
        fn()
    else:
        print(f"用法: python orchestrator.py [daily|weekly|pick|health|evolve]")
        print(f"可用模式: {', '.join(modes.keys())}")
