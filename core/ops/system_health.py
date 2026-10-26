import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
system_health.py — 系统自检 + 自动修复 v1.0
==============================================
由 cron 定期执行，检测系统健康度并自动修复常见问题。

检查项:
  1. TDX 数据新鲜度 (当天)
  2. 财务缓存新鲜度 (24h内)
  3. 市场状态缓存 (1h内)
  4. 核心文件完整性
  5. Gateway 运行状态

自动修复:
  - 过期缓存自动删除 (强制下次重建)
  - 文件缺失自动记录

用法:
  python system_health.py              # 执行自检
  python system_health.py --fix        # 执行自检+自动修复
  python system_health.py --status     # 输出系统状态 JSON
"""
import os, sys, json, time, datetime, subprocess
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT = r"D:\open code\zhuanqian"
HERMES_HOME = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
DATA_DIR = os.path.join(PROJECT, "data")
now = datetime.datetime.now()
status = {"healthy": True, "checks": [], "timestamp": now.isoformat()}


def check(name, ok, detail="", fix_action=None):
    """记录检查结果"""
    status["checks"].append({
        "name": name, "ok": ok, "detail": detail,
        "fix": fix_action or "无操作",
    })
    if not ok:
        status["healthy"] = False
        print(f"  ❌ {name}: {detail}")
        return False
    print(f"  ✅ {name}")
    return True


# ═══════════════════════════════════════════
#  检查项
# ═══════════════════════════════════════════

def check_tdx_freshness():
    """检查 TDX 数据新鲜度"""
    tdx = r"D:\TDX\vipdoc"
    if not os.path.exists(tdx):
        return check("TDX数据", False, "目录不存在")
    
    latest_ts = 0
    for mkt in ["sh", "sz"]:
        d = os.path.join(tdx, mkt, "lday")
        if not os.path.isdir(d): continue
        for f in os.listdir(d):
            if f.endswith(".day"):
                latest_ts = max(latest_ts, os.path.getmtime(os.path.join(d, f)))
    
    if latest_ts == 0:
        return check("TDX数据", False, "无日线文件")
    
    tdx_date = datetime.datetime.fromtimestamp(latest_ts)
    days = (now - tdx_date).days
    ok = days <= 3  # 周末允许3天
    return check("TDX数据新鲜度", ok, f"最新: {tdx_date.strftime('%m-%d')} ({days}天前)")


def check_financial_cache():
    """检查财务缓存"""
    path = os.path.join(DATA_DIR, "financial_cache.json")
    if not os.path.exists(path):
        return check("财务缓存", False, "文件不存在")
    
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("_timestamp", 0)
        age_h = (time.time() - ts) / 3600
        stocks = len(data.get("stocks", {}))
        ok = age_h < 30 and stocks > 50
        return check("财务缓存", ok, f"{stocks}只, {age_h:.0f}h前")
    except Exception as e:
        return check("财务缓存", False, str(e))


def check_market_cache():
    """检查市场状态缓存"""
    path = os.path.join(DATA_DIR, "market_state_cache.json")
    if not os.path.exists(path):
        return check("市场缓存", False, "文件不存在")
    try:
        age_h = (time.time() - os.path.getmtime(path)) / 3600
        return check("市场缓存", age_h < 2, f"{age_h:.0f}h前")
    except Exception as e:
        return check("市场缓存", False, str(e))


def check_aux_caches():
    """检查辅助缓存(北向/板块热度/新闻情绪) — 事件驱动刷新，允许更宽松阈值"""
    specs = {
        "industry_heat.json": ("板块热度", 24 * 2),      # 日级，容忍2天
        "news_sentiment_cache.json": ("新闻情绪", 24 * 3), # 容忍3天
    }
    now = time.time()
    stale = []
    for fname, (label, max_age_h) in specs.items():
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            stale.append(f"{label}:缺失")
            continue
        age_h = (now - os.path.getmtime(path)) / 3600
        if age_h > max_age_h:
            stale.append(f"{label}:{age_h:.0f}h")
    ok = not stale
    return check("辅助缓存", ok, "；".join(stale) if stale else "北向/板块/情绪 均在保鲜期")


def check_gateway():
    """检查 Gateway 运行状态 — 直接检查进程 + gateway_state.json"""
    try:
        # 方式1: gateway_state.json 的 pid 是否存活
        state_path = os.path.join(HERMES_HOME, "..", "gateway-runtime", "gateway_state.json")
        state_path = os.path.normpath(state_path)
        pid_alive = False
        state_detail = "无状态文件"
        if os.path.exists(state_path):
            try:
                with open(state_path, encoding="utf-8") as f:
                    st = json.load(f)
                pid = st.get("pid")
                state_detail = f"state pid={pid} status={st.get('gateway_state')}"
                if pid:
                    # Windows 下检查进程存活
                    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                      capture_output=True, text=True, timeout=5)
                    pid_alive = str(pid) in r.stdout
            except Exception as e:
                state_detail = f"state读取失败: {e}"

        # 方式2: 直接查进程 (CLI pythonw + 桌面端 runtime exe)
        proc_alive = False
        real_pids = []
        try:
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pythonw.exe"],
                              capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "pythonw.exe" and parts[1].isdigit():
                    real_pids.append(parts[1])
            proc_alive = len(real_pids) > 0
        except Exception:
            pass

        # 桌面端 runtime gateway (hermes-agent-cn-runtime-win32-x64.exe gateway run)
        desktop_gw_pids = []
        try:
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq hermes-agent-cn-runtime-win32-x64.exe"],
                              capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                parts = line.split()
                # tasklist 截断为31字符: hermes-agent-cn-runtime-w
                if len(parts) >= 2 and parts[0].startswith("hermes-agent-cn-runtime") and parts[1].isdigit():
                    desktop_gw_pids.append(parts[1])
            proc_alive = proc_alive or len(desktop_gw_pids) > 0
        except Exception:
            pass

        ok = pid_alive or proc_alive
        detail = f"{state_detail} | 进程: {'CLI:'+','.join(real_pids) if real_pids else ''}{' 桌面端:'+','.join(desktop_gw_pids) if desktop_gw_pids else ''}{' 无' if not real_pids and not desktop_gw_pids else ''}"
        if not ok:
            detail += " → Gateway未运行，cron将不会自动触发!"
        return check("Gateway状态", ok, detail)
    except Exception as e:
        return check("Gateway状态", False, str(e))


def check_cron_scripts():
    """检查 cron 脚本存在性 — 实际执行目录是 hermes-home/scripts"""
    cron_dir = os.path.join(HERMES_HOME, "scripts")
    req = ["daily_pick.py", "weekly_report.py", "system_health.py"]
    missing = [f for f in req if not os.path.exists(os.path.join(cron_dir, f))]
    ok = not missing
    return check("Cron脚本", ok, f"缺失: {missing}" if missing else f"全部就位 ({cron_dir})")


def check_trade_log():
    """检查交易记录完整性"""
    path = os.path.join(PROJECT, "data", "trade_log.json")  # P2(t_febdf372): 归一 data/ 真源
    if not os.path.exists(path):
        return check("交易日志", False, "文件不存在")
    try:
        with open(path, encoding="utf-8") as f:
            log = json.load(f)
        recs = log.get("recommendations", [])
        return check("交易日志", len(recs) > 0, f"{len(recs)}条记录")
    except Exception as e:
        return check("交易日志", False, str(e))


# ═══════════════════════════════════════════
#  自动修复
# ═══════════════════════════════════════════

def auto_fix():
    """执行自动修复"""
    if status["healthy"]:
        print("\n  ✅ 系统健康，无需修复")
        return
    
    print("\n🔧 自动修复:")
    for c in status["checks"]:
        if c["ok"]: continue
        name = c["name"]
        
        # 财务缓存过期 → 删除强制重建
        if name == "财务缓存" and "h前" in c["detail"]:
            path = os.path.join(DATA_DIR, "financial_cache.json")
            if os.path.exists(path):
                os.remove(path)
                print(f"  ✅ 已删除过期财务缓存，下次运行自动重建")
        
        # 市场缓存过期 → 删除
        if name == "市场缓存" and "h前" in c["detail"]:
            path = os.path.join(DATA_DIR, "market_state_cache.json")
            if os.path.exists(path):
                os.remove(path)
                print(f"  ✅ 已删除过期市场缓存")
        
        # 辅助缓存过期 → 触发刷新脚本(板块热度/新闻情绪)
        if name == "辅助缓存" and ("h" in c["detail"] or "缺失" in c["detail"]):
            # 板块热度过期 → 立即重建 (v8.2修复: 删除等下次太慢, daily_pick 08:50先于health_check 09:00)
            if "板块热度" in c["detail"]:
                try:
                    sys.path.insert(0, PROJECT)
                    from core.pipeline.tdx_core import get_industry_heat
                    get_industry_heat(force_refresh=True)
                    print("  ✅ 已立即刷新板块热度缓存")
                except Exception as e:
                    print(f"  ⚠️ 板块热度刷新失败: {e}")
            # 新闻情绪: 删除强制重建(由daily_pick运行时重新生成)
            npath = os.path.join(DATA_DIR, "news_sentiment_cache.json")
            if "新闻情绪" in c["detail"] and os.path.exists(npath):
                os.remove(npath)
                print("  ✅ 已删除过期新闻情绪缓存，下次运行重建")

        # 交易日志缺失 → 初始化
        if name == "交易日志":
            path = os.path.join(PROJECT, "data", "trade_log.json")  # P2(t_febdf372): 归一 data/ 真源
            if not os.path.exists(path):
                # 2026-08-13 (任务2①): 原裸 open('w') → atomic_dump 原子写 (task5-audit-report 5.1 遗留)
                from core.pipeline.atomic_json import atomic_dump
                atomic_dump({"recommendations": []}, path)
                print(f"  ✅ 已创建空交易日志")


def check_business_full():
    """--full 模式: 轻量业务正确性校验(不重跑全量, 只读最近输出)"""
    print("\n  ── 业务链路校验 (--full) ──")
    import json as _json

    # 1. 持仓数据合理性
    try:
        with open(os.path.join(PROJECT, "data", "holdings.json"), encoding="utf-8") as f:  # 2026-09-09 Bug2
            holdings = _json.load(f)
        hl = holdings.get("holdings", [])
        bad = [h for h in hl if h.get("shares", 0) <= 0 or h.get("cost", h.get("cost_price", 0)) <= 0]
        check("持仓数据", not bad, f"{len(hl)}只持仓" + (f" 异常:{len(bad)}" if bad else ""))
    except Exception as e:
        check("持仓数据", False, str(e))

    # 2. 最近选股结果
    try:
        log_path = os.path.join(PROJECT, "data", "trade_log.json")  # P2(t_febdf372): 归一 data/ 真源
        if os.path.exists(log_path):
            log = _json.load(open(log_path, encoding="utf-8"))
            recs = log.get("recommendations", [])
            recent = [r for r in recs if isinstance(r, dict) and r.get("date", "") >= (now - datetime.timedelta(days=3)).strftime("%Y-%m-%d")]
            check("近期选股", len(recent) > 0, f"{len(recs)}条推荐, 近3天{len(recent)}条")
        else:
            check("近期选股", False, "trade_log 不存在")
    except Exception as e:
        check("近期选股", False, str(e))

    # 3. 回测结果完整性
    try:
        bt = os.path.join(PROJECT, "backtest_result.json")
        if os.path.exists(bt):
            data = _json.load(open(bt, encoding="utf-8"))
            trades = data.get("总交易次数", 0)
            win = data.get("胜率", 0)
            check("回测结果", trades > 0, f"{trades}笔 胜率{win:.1f}%")
        else:
            check("回测结果", False, "backtest_result.json 不存在")
    except Exception as e:
        check("回测结果", False, str(e))

    # 4. 风控报告
    try:
        risk = os.path.join(DATA_DIR, "risk_report_latest.json")
        if os.path.exists(risk):
            rdata = _json.load(open(risk, encoding="utf-8"))
            score = rdata.get("score", 0) if isinstance(rdata, dict) else 0
            check("风控报告", os.path.getmtime(risk) > time.time() - 86400 * 2, f"评分{score}, 生成于{datetime.datetime.fromtimestamp(os.path.getmtime(risk)).strftime('%m-%d %H:%M')}")
        else:
            check("风控报告", False, "不存在")
    except Exception as e:
        check("风控报告", False, str(e))


def check_tune_consistency():
    """检查调优闭环一致性 (P1, 2026-08-04):
    ①weight_tune_result.json 是否存在且新鲜
    ②status=suggested 的调优建议是否与 STRATEGIES 当前权重漂移
      漂移 = 有建议但未应用 → 提示待确认(不自动应用, 防过拟合)
    ③config.json 是否被污染(weights 字段残留 = 旧调优机制复活)
    """
    # 1. tune_result 存在性
    tune_file = os.path.join(PROJECT, "weight_tune_result.json")
    if not os.path.exists(tune_file):
        check("调优一致性", True, "无调优建议(正常, 未运行过调优)")
        return
    try:
        tune = json.load(open(tune_file, encoding="utf-8"))
    except Exception as e:
        check("调优一致性", False, f"tune_result 解析失败: {e}")
        return

    # 2. 漂移检测: suggested 状态 vs STRATEGIES
    try:
        sys.path.insert(0, PROJECT)
        from core.pipeline.tdx_core import STRATEGIES
        strategies = tune.get("strategies", {}) if isinstance(tune, dict) else {}
        status = tune.get("status", "") if isinstance(tune, dict) else ""
        drifted = []
        for sname, suggest_w in strategies.items():
            cur = STRATEGIES.get(sname, {})
            if not isinstance(suggest_w, dict) or not cur:
                continue
            # 只比较 suggest 意图覆盖的 key (避免把 suggest 未提的 STRATEGIES key 全算成差异)
            diffs = {k: (suggest_w.get(k), cur.get(k)) for k in suggest_w
                     if suggest_w.get(k) != cur.get(k)}
            if diffs:
                drifted.append(f"{sname}({len(diffs)}项)")
        if status == "suggested" and drifted:
            # 漂移是提示不是故障: check 保持 ok=True, 但告警必须直接可见
            check("调优一致性", True, f"有{len(drifted)}个策略调优建议未应用")
            print(f"  ⚠️ 调优建议待确认: {', '.join(drifted)} (weight_tune_result.json status=suggested)")
            print(f"     📋 如需应用: agent 审查后同步到 tdx_core.STRATEGIES")
        else:
            check("调优一致性", True, f"调优状态: {status or '无'}" + (f" 已应用" if not drifted else ""))
    except Exception as e:
        check("调优一致性", False, f"漂移检测失败: {e}")

    # 3. config.json 污染检测
    try:
        cfg = json.load(open(os.path.join(PROJECT, "config.json"), encoding="utf-8"))
        if "weights" in cfg:
            check("config无weights残留", False, "⚠️ config.json 仍有 weights 字段(旧调优机制可能复活)")
        else:
            check("config无weights残留", True, "正常")
    except Exception as e:
        check("config无weights残留", False, str(e))


# ═══════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════

def main():
    print("=" * 50)
    print("  🔍 系统自检 v1.0")
    print(f"  {now.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)
    
    check_tdx_freshness()
    check_financial_cache()
    check_market_cache()
    check_aux_caches()
    check_gateway()
    check_cron_scripts()
    check_trade_log()
    check_tune_consistency()

    if "--full" in sys.argv:
        check_business_full()
    
    if "--fix" in sys.argv:
        auto_fix()
    
    print(f"\n{'='*50}")
    if status["healthy"]:
        print("  ✅ 系统健康")
    else:
        print(f"  ⚠️ 发现 {sum(1 for c in status['checks'] if not c['ok'])} 个问题")
    print(f"{'='*50}")
    
    if "--status" in sys.argv:
        print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
