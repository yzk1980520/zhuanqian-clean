import core.pipeline.atomic_json as atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""health_check.py — 系统健康监控 v1.0 (2026-08-07)
=================================================
每日 8:45 cron 前置检查, 防脏数据选股:
  1. TDX 数据完整性: get_latest_tdx_date == 最近交易日 (红: 阻断)
  2. akshare 可用性: stock_fund_flow_individual 探测 (黄: 告警, 有缓存降级)
  3. FTShare 可用性: ft_adapter.ft_stock_quotes 分页探测 (黄)
  4. 缓存状态: financial_cache 新鲜度 + capital_flow_daily.pkl cached_at (黄)
  5. 磁盘空间: logs/ 目录 >1GB 告警 (红: 阻断)
  6. skill 完整性: 核心 skill SKILL.md 存在 + frontmatter created_by (红: 阻断)

分级:
  红(阻断) = TDX 数据缺失 / 磁盘满 / skill 缺失 → gate=block
  黄(告警) = akshare/FTShare 失败 / 缓存过期 → gate=open (系统有降级链)

输出:
  logs/health_check_YYYYMMDD.json + data/health_gate.json

用法:
  python health_check.py          # 全量检查
  python health_check.py --gate   # gate 模式: exit 0=通过 1=阻断 (供 cron 前置)
"""
import json
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys
from datetime import datetime, date

PROJECT = PROJECT_ROOT
LOG_DIR = os.path.join(PROJECT, "logs")
CACHE_DIR = os.path.join(PROJECT, "cache")
DATA_DIR = os.path.join(PROJECT, "data")
GATE_FILE = os.path.join(DATA_DIR, "health_gate.json")
SKILL_DIR = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\skills"

MAX_LOG_GB = 1.0          # logs/ 目录上限
TDX_MAX_AGE_DAYS = 5      # TDX 数据最大滞后(自然日, 容忍周末)
CORE_SKILLS = [
    # 2026-08-29 移除假配置：原引用 finance/a-share-position-risk-control 和
    # finance/a-share-post-market-review 但从未实现过（skills-lock.json / Hermes home
    # / 项目目录 均无对应 SKILL.md），导致 health_check 每天报红假警报。
    # 未来若真建这俩 skill，把它们加回来。
]
PROBE_CODE = "sh600000"   # TDX 探测用股票

def _find_skill_md(name):
    """在 skills 目录下递归找 SKILL.md (支持简单名称和 category/名称 格式)"""
    for root, _dirs, files in os.walk(SKILL_DIR):
        rel = os.path.relpath(root, SKILL_DIR).replace("\\", "/")
        if "SKILL.md" not in files:
            continue
        # 支持 "finance/a-share-post-market-review" 格式（相对路径精确匹配）
        if "/" in name and rel == name:
            return os.path.join(root, "SKILL.md")
        # 兼容简单名称（basename 匹配，原有行为）
        if "/" not in name and os.path.basename(root) == name:
            return os.path.join(root, "SKILL.md")
    return None

def check_tdx():
    """检查1: TDX 数据完整性 (红)"""
    try:
        sys.path.insert(0, PROJECT)
        from core.pipeline.tdx_core import get_latest_tdx_date
        d = get_latest_tdx_date(PROBE_CODE)
        if not d:
            return "red", "TDX 无数据: %s" % PROBE_CODE
        age = (date.today() - d).days
        if age > TDX_MAX_AGE_DAYS:
            return "red", "TDX 数据滞后 %d 天 (最后 %s)" % (age, d)
        return "green", "TDX 数据正常 (最后 %s, %d 天前)" % (d, age)
    except Exception as e:
        return "red", "TDX 检查异常: %s" % e

def check_akshare():
    """检查2: akshare 可用性 (黄)"""
    try:
        # 修复: cron 以 SYSTEM 账户运行，PATH 不含 Python311 → 显式设置 sys.path
        py_dir = r"C:\Users\WIN10\AppData\Local\Programs\Python\Python311"
        py_dir_scripts = r"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\Scripts"
        if py_dir not in sys.path:
            sys.path.insert(0, py_dir)
        if py_dir_scripts not in sys.path:
            sys.path.insert(0, py_dir_scripts)
        import akshare as ak
        import contextlib
        import io
        # 2026-08-07: 抑制 akshare 内部 tqdm 进度条 (stderr 噪音)
        with contextlib.redirect_stderr(io.StringIO()):
            df = ak.stock_fund_flow_individual(symbol="即时")
        if df is not None and len(df) > 0:
            return "green", "akshare 正常 (%d 只)" % len(df)
        return "yellow", "akshare 返回空"
    except Exception as e:
        return "yellow", "akshare 不可用: %s" % e

def check_ftshare():
    """检查3: FTShare 可用性 (黄)"""
    try:
        sys.path.insert(0, PROJECT)
        from ft_adapter import ft_stock_quotes
        df = ft_stock_quotes(page_size=5)
        if df is not None and len(df) > 0:
            return "green", "FTShare 正常 (%d 行)" % len(df)
        return "yellow", "FTShare 返回空"
    except Exception as e:
        return "yellow", "FTShare 不可用: %s" % e

def check_cache():
    """检查4: 缓存状态 (黄)"""
    issues = []
    # financial_cache
    fp = os.path.join(DATA_DIR, "financial_cache.json")
    if not os.path.exists(fp):
        issues.append("financial_cache 缺失")
    else:
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
            ts = d.get("_timestamp", 0)
            age_days = (datetime.now().timestamp() - ts) / 86400 if ts else 999
            if age_days > 30:
                issues.append("financial_cache 过期 %.0f 天" % age_days)
        except Exception:
            issues.append("financial_cache 解析失败")
    # capital_flow_daily.pkl — 非交易日（周末/节假日）跳过检查
    cfp = os.path.join(CACHE_DIR, "capital_flow_daily.pkl")
    weekday = datetime.now().weekday()  # 0=Mon, 6=Sun
    if not os.path.exists(cfp):
        if weekday >= 5:
            issues.append("capital_flow_daily.pkl 缺失（周末，待下个交易日刷新）")
        else:
            issues.append("capital_flow_daily.pkl 缺失")
    elif not os.path.exists(cfp + ".hmac"):
        issues.append("capital_flow_daily.pkl.hmac 缺失（实体存在但签名丢失）")
    else:
        if weekday >= 5:
            pass  # 周末：文件+签名均在，属正常
        try:
            import pickle
            with open(cfp, "rb") as f:
                cached = pickle.load(f)
            today = datetime.now().strftime("%Y-%m-%d")
            # 非交易日：接受最近一个交易日的格式（含 cached_at 即可）
            ent = cached.get(today) if isinstance(cached, dict) else None
            if ent is None and isinstance(cached, dict) and cached:
                # 取缓存里最新的一条
                latest_key = max(cached.keys())
                ent = cached.get(latest_key)
            if not (isinstance(ent, dict) and "cached_at" in ent):
                issues.append("capital_flow 缓存非今日格式")
        except Exception:
            issues.append("capital_flow 缓存解析失败")
    if issues:
        return "yellow", "; ".join(issues)
    return "green", "缓存正常 (financial_cache + capital_flow 今日)"

def check_disk():
    """检查5: 磁盘空间 (红)"""
    total = 0
    for root, _dirs, files in os.walk(LOG_DIR):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    gb = total / 1024 ** 3
    if gb > MAX_LOG_GB:
        return "red", "logs/ 目录 %.2f GB > %d GB" % (gb, MAX_LOG_GB)
    return "green", "logs/ 目录 %.2f MB" % (gb * 1024)

def check_skills():
    """检查6: skill 完整性 (红)"""
    missing = []
    for name in CORE_SKILLS:
        sp = _find_skill_md(name)
        if not sp:
            missing.append("%s(SKILL.md 缺失)" % name)
            continue
        try:
            c = open(sp, encoding="utf-8").read()
            if "created_by:" not in c:
                missing.append("%s(frontmatter 缺 created_by)" % name)
        except Exception:
            missing.append("%s(读取失败)" % name)
    if missing:
        return "red", "; ".join(missing)
    return "green", "核心 skill 完整 (%d 个)" % len(CORE_SKILLS)

def check_trade_loop():
    """检查7: 实盘闭环 (黄) — 已买入但推荐未回填的条数 (P0-2, 2026-08-08)"""
    try:
        tp = os.path.join(PROJECT, "data", "trade_log.json")  # P0修复(2026-09-25): 真源统一到 data/
        with open(tp, encoding="utf-8") as f:
            t = json.load(f)
        recs = t.get("recommendations", [])
        buys = t.get("buys", [])
        if not recs:
            return "green", "无推荐记录"
        buy_codes = {str(b.get("code", ""))[-6:] for b in buys if b.get("code")}
        # 按 code 取最新一条推荐判定 (2026-08-10: 旧推荐 followed=null 但当日后续已有回填 → 误报)
        latest_by_code = {}
        for r in recs:
            if r.get('type', 'recommendation') != 'recommendation':  # 排除 variant_reference (2026-08-09 jcode)
                continue
            code = str(r.get("code", ""))[-6:]
            d = str(r.get("date", ""))
            if code not in latest_by_code or d > latest_by_code[code].get("date", ""):
                latest_by_code[code] = r
        # 2026-08-29: 历史遗留豁免——2026-08-04 之前系统未启用推荐追踪，这些买入属于"系统未上线"缺口
        # 白名单在 trade_log.json 的 meta.known_gaps 里维护，避免硬编码
        known_gaps = set()
        meta = t.get("meta", {})
        if isinstance(meta, dict):
            for g in meta.get("known_gaps", []):
                known_gaps.add(str(g.get("code", ""))[-6:])
        unfilled = [r for r in latest_by_code.values()
                    if r.get("followed") is not True
                    and r.get("buy_date")  # 2026-08-17: 仅"推荐本身已买入未回填"算缺口; buy_date=null 的推荐(未买入/欺诈过滤)不算, 防误报
                    and str(r.get("code", ""))[-6:] in buy_codes]
        # 2026-08-21: 反向检测 — buys 有买入但 recommendations 完全无该 code 的推荐记录 (隐形缺口, 如 600033 补录前)
        rec_codes = {str(r.get("code", ""))[-6:] for r in recs
                     if r.get('type', 'recommendation') == 'recommendation'}
        buy_no_rec = [b for b in buys
                      if b.get("code")
                      and str(b.get("code", ""))[-6:] not in rec_codes
                      and str(b.get("code", ""))[-6:] not in known_gaps]  # 历史豁免
        followed_n = sum(1 for r in recs if r.get("followed") is True)
        if buy_no_rec:
            names = "、".join("%s(%s)" % (b.get("code"), b.get("name") or "?") for b in buy_no_rec[:5])
            return "yellow", "实盘闭环缺口: %d 条买入无推荐记录 (推荐=%d, followed=%d): %s" % (
                len(buy_no_rec), len(recs), followed_n, names)
        if unfilled:
            names = "、".join("%s(%s)" % (r.get("code"), r.get("name") or "?") for r in unfilled[:5])
            return "yellow", "实盘闭环缺口: %d 条已买入未回填 (推荐=%d, followed=%d): %s" % (
                len(unfilled), len(recs), followed_n, names)
        return "green", "实盘闭环正常 (推荐=%d, followed=%d)" % (len(recs), followed_n)
    except Exception as e:
        return "yellow", "trade_log 检查异常: %s" % e

def run_health_check():
    """执行全部检查, 写 health_check_YYYYMMDD.json + gate 文件

    调用场景:
    - 每日 8:45 cron 前置检查 (必须通过 gate=open 才能启动选股)
    - 手动运行排查数据问题

    检查项:
        红(阻断): TDX数据缺失 / 磁盘满 / skill缺失 → gate=block
        黄(告警): akshare/FTShare失败 / 缓存过期 → gate=open (有降级链)

    输出:
        logs/health_check_YYYYMMDD.json — 详细检查结果
        data/health_gate.json — gate 状态 (供 cron 前置判断)
    """
    checks = {
        "tdx": check_tdx(),
        "akshare": check_akshare(),
        "ftshare": check_ftshare(),
        "cache": check_cache(),
        "disk": check_disk(),
        "skills": check_skills(),
        "trade_loop": check_trade_loop(),
    }
    red = [k for k, (lv, _m) in checks.items() if lv == "red"]
    yellow = [k for k, (lv, _m) in checks.items() if lv == "yellow"]
    gate = "block" if red else "open"

    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "gate": gate,
        "red": red,
        "yellow": yellow,
        "checks": {k: {"level": lv, "message": m} for k, (lv, m) in checks.items()},
        "summary": "全绿" if not red and not yellow else
                   ("红: %s | 黄: %s" % ("/".join(red), "/".join(yellow)) if red else "黄: %s" % "/".join(yellow)),
    }
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    atomic_json.atomic_dump(result, os.path.join(LOG_DIR, "health_check_%s.json" % datetime.now().strftime("%Y-%m-%d")), ensure_ascii=False, indent=2, encoding="utf-8")
    atomic_json.atomic_dump({"date": result["date"], "gate": gate, "red": red}, GATE_FILE, ensure_ascii=False, indent=2, encoding="utf-8")

    # 控制台
    for k, (lv, m) in checks.items():
        sym = {"green": "✅", "yellow": "⚠️", "red": "🔴"}[lv]
        print("  %s %s: %s" % (sym, k, m))
    print("  状态: %s (gate=%s)" % (result["summary"], gate))
    return result

if __name__ == "__main__":
    result = run_health_check()
    if "--gate" in sys.argv:
        sys.exit(1 if result["gate"] == "block" else 0)
