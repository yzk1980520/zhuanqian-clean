import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
integrated_picker.py — 三层过滤选股系统 v3.0 (精简版)
=============================================
流程: 综合评分 → 断层评分 → 财务健康

P0改进 (2026-08-25):
  - ENABLE_GAP_STRATEGY: 断层策略开关 (默认False, 因超额-2.61%)
  - ENABLE_IC_MONITOR: IC监控开关 (默认True)
"""

# P0改进配置
ENABLE_GAP_STRATEGY = False  # 132d门禁NOT-PASS, 老五t_7e2fa56a裁定A摘除, 原10-10单样本依据废止 (P1#5: 回滚=改回True, 单commit可逆)
ENABLE_IC_MONITOR = True     # IC监控开关
ENABLE_STARTUP_DETECTOR = False  # 132d门禁NOT-PASS, 老五t_7e2fa56a裁定A摘除, 原10-10单样本依据(IC=0.5252)废止 (P1#5: 回滚=改回True, 单commit可逆)
ENABLE_DL_PREDICTOR = True  # DL预测开关 (PyTorch版门禁通过: IC=0.377, ICIR=4.97, 样本9079只)

# 三层过滤架构: L1 综合评分 + L2 断层 + L3 财务健康(舞弊)
# 移除: 北向资金(2024停披露)/板块热度(恒0)
# 策略自动切换: 强市趋势/震荡断层/弱市抄底

import sys, os, json, logging, time
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

PROJECT = PROJECT_ROOT
sys.path.insert(0, PROJECT)

from core.pipeline.tdx_core import (
    get_tdx_data, compute_indicators, compute_weekly_indicators,
    should_include, is_st_stock, score_stock, load_name_cache,
    STRATEGIES, get_industry, VIPDOC, ALLOWED_PREFIXES_SH, ALLOWED_PREFIXES_SZ,
    load_industry_map, has_recent_gap,
)

# KIMI审查-20 P1修复: 新增真突破检测集成
try:
    from core.scoring.breakout_filter import apply_breakout_filter, ENABLE_BREAKOUT_FILTER
    _HAS_BREAKOUT_FILTER = True
except ImportError:
    _HAS_BREAKOUT_FILTER = False
    print("  ⚠️ breakout_filter模块未找到，跳过真突破检测")

# DL预测模块集成 (2026-09-24)
try:
    from factors.dl_stock_predictor import dl_score_stock
    _HAS_DL = True
except ImportError:
    _HAS_DL = False
    print("  ⚠️ dl_stock_predictor模块未找到，跳过DL预测")

# 新策略模块
from core.scoring.earnings_gap import batch_score_gaps

# 基本面财务过滤引擎 v1.0
from core.scoring.financial_filter import batch_score_financial

# 华泰数据增强（P0-2 老五审查接入，2026-08-23）
try:
    from huatai_data import huatai_enrich_stocks, get_remaining_calls
    _HAS_HUATAI = True
except ImportError:
    _HAS_HUATAI = False

# 市场状态量化引擎
from market_state_engine import assess_market_full
# 简化版市场状态机（方案C）
try:
    from simple_regime import get_simple_regime, get_strategy_weights
except ImportError:
    get_simple_regime = lambda: {"regime": "震荡", "confidence": 0.5, "gate_status": "close"}
    get_strategy_weights = lambda regime: {"momentum": 1.0, "quality": 1.0, "value": 1.0}

# DL预测模块（门禁未通过时降级为statistical fallback）
try:
    from factors.dl_stock_predictor_torch import DLPredictionEngine, DL_WEIGHT, ENABLE_DL_PREDICTOR
    _HAS_DL = True
    _dl_engine = DLPredictionEngine() if ENABLE_DL_PREDICTOR else None
except ImportError:
    _HAS_DL = False
    _dl_engine = None
    print("  ⚠️ dl_stock_predictor模块未找到，跳过DL预测")
# atomic_json for safe file writes
import core.pipeline.atomic_json as atomic_json  # 2026-10-24 [t_laosan_r5_bare_import]: 原裸 import 只绑定 core, 下方 atomic_json.* 会 NameError, 补 as 别名

# 止损止盈规则引擎
from risk_rules import generate_trade_plan, print_trade_plan, evaluate_exit

# 主升浪/反弹启动检测 (唯识学种子理论)
# 2026-08-26 P0 修复: 模块未落地时用 no-op 兜底, 避免 8:30 闭环 import 失败
try:
    from core.pipeline.startup_detector import calculate_startup_score
except ImportError:
    # ponytail: no-op fallback; 启动评分层回测无 alpha (8/25 回测已证), 缺失不影响主打分
    def calculate_startup_score(recs, market_label=None):
        return 0, 0, 0

# ═══════════════════════════════════════════
#  财务过滤候选池 (P0-4, 2026-08-05): Top50 → Top100
#  可环境变量 FINANCIAL_TOP_N 覆盖; 只扩大财务过滤覆盖面(缓存预热),
#  主链路排名仍基于 Layer 1 的 Top50, 不改变下游行为
# ═══════════════════════════════════════════
_FIN_TOP_N_RAW = os.environ.get("FINANCIAL_TOP_N", "100")
try:
    FINANCIAL_TOP_N = int(_FIN_TOP_N_RAW)
except ValueError:
    FINANCIAL_TOP_N = 100
assert 50 <= FINANCIAL_TOP_N <= 500, f"FINANCIAL_TOP_N 越界: {_FIN_TOP_N_RAW}"

# ═══════════════════════════════════════════
#  v36 回测优化参数 (2026-09-21)
#  回测结果: 500日+22.13%收益, 35笔交易, 48.6%胜率
# ═══════════════════════════════════════════
COOLDOWN_DAYS = int(os.environ.get("S1_COOLDOWN", "5"))        # 冷却期5天
# 注意: MIN_SCORE, MOMENTUM_LIMIT, HARD_STOP_PCT等已在risk_rules.py定义
# integrated_picker使用risk_rules的权威源，不重复定义


# ═══════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════


def check_position_for_pick():
    """
    P0修复(2026-09-05): 统一持仓检查逻辑（单票轮动）
    返回: (allow_pick: bool, positions_count: int, message: str)
    """
    try:
        # 2026-09-09 Bug2修复: 持仓真源=data/holdings.json(与automation_scheduler/positioner/risk_manager一致),根目录为build_realdata旧产物
        _holdings_path = os.path.join(PROJECT, "data", "holdings.json")
        if os.path.exists(_holdings_path):
            with open(_holdings_path, 'r', encoding='utf-8') as _hf:
                _holdings = json.load(_hf)
            _positions = _holdings.get("holdings", [])
            if len(_positions) == 0:
                return True, 0, "空仓"
            else:
                return False, len(_positions), f"有持仓({len(_positions)}只)"
        else:
            return True, 0, "无持仓文件"
    except Exception as _he:
        print(f"  ⚠️ 持仓检查异常: {_he}", file=sys.stderr)
        return False, -1, f"检查失败: {_he}"


def check_cooldown_for_pick():
    """v36优化: 冷却期检查（持仓后需等待N天才能换票）
    返回: (allow_pick: bool, days_since_entry: int, message: str)
    """
    try:
        from datetime import date, datetime
        # 动态读取PROJECT以支持测试monkeypatch
        # P0#1 (2026-10-09): 别名加载(spec_from_file_location, 不注册sys.modules)下
        #   __name__ 不在 sys.modules → 原 sys.modules[__name__] KeyError 被吞成"检查失败"
        #   → 冷却纪律"冷却5天"静默失效 (SOUL#9 同源埋雷)。改: 命中才用, 否则回退模块顶层 PROJECT。
        _importing_module = sys.modules.get(__name__)
        if _importing_module is not None and hasattr(_importing_module, "PROJECT"):
            _project_path = _importing_module.PROJECT
        else:
            _project_path = PROJECT
        _holdings_path = os.path.join(_project_path, "data", "holdings.json")
        if not os.path.exists(_holdings_path):
            return True, 0, "无持仓文件"

        with open(_holdings_path, 'r', encoding='utf-8') as _hf:
            _holdings = json.load(_hf)
        _positions = _holdings.get("holdings", [])

        if len(_positions) == 0:
            return True, 0, "空仓"

        # 检查第一笔持仓的冷却期
        entry_date_str = _positions[0].get("entry_date")
        if not entry_date_str:
            return True, -1, "持仓无入场日期"

        try:
            entry_date = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
        except ValueError:
            return True, -1, "持仓日期格式错误"

        today = date.today()
        days_since = (today - entry_date).days
        threshold = COOLDOWN_DAYS

        if days_since < threshold:
            return False, days_since, f"冷却期中(已{days_since}天, 需{threshold}天)"
        else:
            return True, days_since, f"冷却期满({days_since}天)"
    except Exception as _he:
        print(f"  ⚠️ 冷却期检查异常: {_he}", file=sys.stderr)
        return True, -1, f"检查失败: {_he}"


def validate_v36_params():
    """v36启动验证: 确保关键参数配置一致"""
    try:
        from risk_rules import TIME_STOP_TRADING_DAYS, CHASE_BAN_PCT
        issues = []

        # 验证冷却期
        if COOLDOWN_DAYS != 5:
            issues.append(f"COOLDOWN_DAYS={COOLDOWN_DAYS} (建议5天)")

        # 验证时间止损与risk_rules一致
        if TIME_STOP_TRADING_DAYS != 120:
            issues.append(f"TIME_STOP_TRADING_DAYS={TIME_STOP_TRADING_DAYS} (建议120)")

        # 验证追高关闭（2026-09-25 统一口径: 4%, 对齐08-16拍板与CONTEXT.md契约）
        if CHASE_BAN_PCT != 4.0:
            issues.append(f"CHASE_BAN_PCT={CHASE_BAN_PCT} (建议4.0)")

        if issues:
            print(f"  ⚠️ v36参数不一致: {', '.join(issues)}")
            return False
        return True
    except Exception as e:
        print(f"  ⚠️ v36参数验证失败: {e}")
        return True  # 验证失败不阻塞启动

def load_industry_heat():
    """加载今日行业热度数据"""
    try:
        heat_file = os.path.join(PROJECT, "data", "industry_heat.json")
        if os.path.exists(heat_file):
            data = json.load(open(heat_file, encoding="utf-8"))
            return data.get("data", {})
    except Exception:
        pass
    return {}


def get_industry_heat_bonus(industry, heat_data):
    """根据行业热度给加分"""
    if not heat_data or not industry:
        return 0, ""

    valid_sectors = {k: v for k, v in heat_data.items()
                     if isinstance(v, dict) and "rank" in v}

    alias_map = {
        "金融": ["银行", "证券", "保险", "多元金融"],
        "银行": ["金融"],
        "证券": ["金融"],
        "保险": ["金融"],
    }

    for sector_name, info in valid_sectors.items():
        clean_name = sector_name.replace("Ⅱ", "").replace("Ⅰ", "")
        if industry in clean_name or clean_name in industry:
            rank = info.get("rank", 999)
            pct = info.get("change_pct", 0)
            if rank <= 5:
                return 8, "🔥 TOP%d %s(+%.1f%%)" % (rank, sector_name[:6], pct)
            elif rank <= 10:
                return 6, "🔥 TOP%d %s(+%.1f%%)" % (rank, sector_name[:6], pct)
            elif rank <= 20:
                return 4, "📈 TOP%d %s(+%.1f%%)" % (rank, sector_name[:6], pct)
            elif rank <= 30:
                return 2, "📊 TOP%d %s(+%.1f%%)" % (rank, sector_name[:6], pct)
        if industry in alias_map:
            for alias in alias_map[industry]:
                if alias in clean_name or clean_name in alias:
                    rank = info.get("rank", 999)
                    pct = info.get("change_pct", 0)
                    if rank <= 5:
                        return 8, "🔥 %s→%s TOP%d(+%.1f%%)" % (industry[:4], sector_name[:4], rank, pct)
                    elif rank <= 10:
                        return 6, "🔥 %s→%s TOP%d(+%.1f%%)" % (industry[:4], sector_name[:4], rank, pct)
                    elif rank <= 20:
                        return 4, "📈 %s→%s(+%.1f%%)" % (industry[:4], sector_name[:4], pct)
                    elif rank <= 30:
                        return 2, "📊 %s→%s(+%.1f%%)" % (industry[:4], sector_name[:4], pct)
    return 0, ""


def get_market_analysis():
    """使用量化引擎获取市场分析，替代旧的 detect_market_mood"""
    m = assess_market_full(use_cache=False, cache_ttl=300)  # P1-2修复: 选股时强制重算, 避免市场缓存陈旧
    market_score = m["market_score"]
    market_label = m["market_label"]
    strategy_weights = m["strategy_weights"]
    primary_strategy = m["primary_strategy"]
    position_ratio = m["position_ratio"]
    position_advice = m["position_advice"]
    sub_scores = m["sub_scores"]
    
    return market_score, market_label, strategy_weights, primary_strategy, position_ratio, position_advice, sub_scores


# ═══════════════════════════════════════════
#  候选池前端过滤 (T-20260816-002 Option E): 流动性/价格/ST/停牌
# ═══════════════════════════════════════════
# 反转可交易性弱(成本超30bps即失效, 收益集中小盘不流动票) → 选股前端过滤
# 近20日均成交额≥3000万 (曾有"严格档5000万 LIQUIDITY_STRICT=1"说法, 但该环境变量全库零处 os.environ 读取、当前未实现, 设置它没有任何效果; 真实门槛=3000万)
# 收盘价≥5元 | 排除 ST/退市整理/当日停牌
LIQUIDITY_MIN_AMT = 30_000_000  # 方案D (2026-09-18): 放宽到3000万，避免流动性过滤过严导致无票可出
LIQUIDITY_MIN_PRICE = 5.0
LIQUIDITY_LOOKBACK = 20
MIN_LIQUIDITY_LOOKBACK = 60  # 次新股过滤: 至少60个交易日数据
MIN_SCORE = 20  # P0整改: 22→20 (2026-09-30)
_LIQ_REASON_CN = {
    "liquidity": "近20日均成额<阈值",
    "price": "收盘价<5元",
    "st": "ST",
    "delisting": "退市整理期/待退市(名称含退)",
    "halt": "当日停牌",
    "data": "数据不足",
    "non_main_board": "非沪深主板(仅保留60/00开头)",
    "new_stock": "次新股(上市不足60日)",
    "high_atr": "高波动(14日ATR>8%)",
}


def _is_main_board(code):
    """校验是否为沪深主板（60开头/00开头）"""
    if not code:
        return False
    code_str = str(code).strip()
    # 去掉 sh/sz 前缀
    if code_str[:2] in ("sh", "sz"):
        code_str = code_str[2:]
    # 仅保留60开头（沪主板）和00开头（深主板）
    return code_str.startswith('60') or code_str.startswith('00')


def apply_tradability_filter(code, name, recs):
    """Option E 候选前端过滤; 返回 (pass_flag: bool, reason_key: str|None)
    ST 判定复用 tdx_core.is_st_stock; amount 单位=元
    新增主板过滤+次新股过滤+ATR波动率过滤
    D9-3 (2026-10-19 老大拍板): 「待退市」显式化 — 退市整理期(名称含"退")从 ST 里
    拆出单列 delisting 原因。排除集合不变, 只是原因可区分、可复盘。"""
    if not recs or len(recs) < LIQUIDITY_LOOKBACK:
        return False, "data"
    # D9-3: 退市整理期/待退市显式化。财务红线(净利为负+营收<3亿)本系统无财务数据
    # (TDX 仅 OHLCV + amount + 名称)做不了, 只用代理: 名称含"退" + 下方价格地板 +
    # 流动性枯竭; 不接财务数据源(硬约束3)。
    if name and "退" in name:
        return False, "delisting"
    if is_st_stock(name):  # ST/*ST 前缀("退"已在上方单列, 不混入)
        return False, "st"
    # 主板硬过滤: 仅保留沪深主板(60/00开头)
    if not _is_main_board(code):
        return False, "non_main_board"
    # 次新股过滤: 上市不足60个交易日
    if len(recs) < MIN_LIQUIDITY_LOOKBACK * 2:  # 至少 120 根K线（60交易日×2，门槛见常量 MIN_LIQUIDITY_LOOKBACK）
        return False, "new_stock"
    last = recs[-1]
    # 当日停牌: 最新bar无成交(volume=0)或最新bar早于市场最新交易日 → 数据滞后必过滤
    if not last.get("volume") or last.get("volume", 0) <= 0:
        return False, "halt"
    if not last.get("close") or last["close"] <= 0:
        return False, "halt"
    if last["close"] < LIQUIDITY_MIN_PRICE:
        return False, "price"
    amts = [r.get("amount") or 0 for r in recs[-LIQUIDITY_LOOKBACK:]]
    avg_amt = sum(amts) / len(amts)
    if avg_amt < LIQUIDITY_MIN_AMT:
        return False, "liquidity"
    # ATR波动率过滤: 剔除14日ATR>8%的高波动标的
    try:
        atr_v = last.get("atr14") or recs[-1].get("atr14")
        cur_price = last.get("close") or recs[-1].get("close", 1)
        if atr_v and cur_price > 0 and (atr_v / cur_price) > 0.08:  # ATR百分比>8%
            return False, "high_atr"
    except Exception:
        pass
    return True, None


# ═══════════════════════════════════════════
#  核心选股逻辑
# ═══════════════════════════════════════════

def _load_available_cash():
    """读取 holdings.json 真实现金 (2026-08-06 P1: 落库层现金感知)
    失败回退 23000(旧硬编码) 保证兼容"""
    try:
        # 2026-09-09 Bug2: 持仓真源=data/holdings.json
        p = os.path.join(PROJECT, "data", "holdings.json")
        if os.path.exists(p):
            h = json.load(open(p, encoding="utf-8"))
            cash = float(h.get("available_cash", 0) or 0)
            if cash > 0:
                return cash
    except Exception:
        pass
    return 23000


def run_integrated_picker(top_n=1, debug=False, force_strategy=None, dry_run=False):
    """三层过滤主逻辑 — 每日唯一推荐入口

    单票轮动模式（老大2026-09-05拍板）：
    - 默认输出TOP1，强制单票轮动
    - 空仓时允许选股（观察池），持仓时硬拦截
    - 换票触发条件：硬止损8%/移动止盈5%+7%/时间止损120交易日（risk_rules.py定义）
    """

    # 参数:
    #   top_n: 输出 Top N 只推荐 (默认1, 实盘只看 Top1)
    #   debug: 启用调试输出
    #   force_strategy: 强制使用指定策略 (用于AB测试)
    #   dry_run: True 只评分不写 trade_log (验证/调试用, 防止污染实盘记录)
    #
    # 注意:
    #   - dry_run=True 时必须显式传, 避免验证脚本误写入 trade_log
    #   - 环境门关时 (上证<MA250) 仍运行但仓位建议<=50% (2026年9月4日 放宽)
    print("  🎯 三层过滤选股系统 v3.0")
    print("  综合评分 × 断层评分 × 财务健康")
    print("  %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 68)

    # P0 (2026-08-07): 过滤日志 — 记录各层被过滤/降权的股票, 供盘后复盘"错过分析"
    reject_log = []

    # ── Step 0: 市场状态量化评分 ──
    print("\n📊 Layer 0: 市场状态量化评分...")
    market_score, market_label, strategy_weights, primary_strategy, \
        pos_ratio, pos_advice, sub_scores = get_market_analysis()
    
    print("  🏆 综合评分: %d/100 — %s" % (market_score, market_label))
    print("  📈 维度分解:")
    for dim, info in sub_scores.items():
        sigs = " | ".join(info["signals"]) if info["signals"] else "中性"
        print("    %-8s: %3d分  (%s)" % (dim, info["score"], sigs))
    
    if force_strategy and force_strategy in STRATEGIES:
        strategy_weights = {force_strategy: 1.0}
        primary_strategy = force_strategy
        print("  📋 手动指定策略: %s" % force_strategy)
    else:
        top3 = sorted(strategy_weights.items(), key=lambda x: -x[1])[:3]
        print("  🎯 推荐策略TOP3: %s" % 
              ", ".join("%s(%.0f%%)" % (n, w*100) for n, w in top3))
    print("  💼 仓位建议: %s (%.0f%%)  ← 2026-09-04 放宽到50%%" % (pos_advice, pos_ratio * 100))
    
    # ── 预加载 Layer 7.5 龙虎榜数据 ──
    _lhb_map = {}
    try:
        import akshare as _lhb_ak
        _lhb_today = datetime.now().strftime("%Y%m%d")
        _lhb_path = os.path.join(PROJECT, "data", "akshare", f"get_lhb_detail_{_lhb_today}.json")
        if os.path.exists(_lhb_path):
            with open(_lhb_path, "r", encoding="utf-8") as _lf:
                _lhb_data = json.load(_lf)
            _rows = _lhb_data.get("data", []) if isinstance(_lhb_data, dict) else (_lhb_data if isinstance(_lhb_data, list) else [])
            for _row in _rows:
                _code = str(_row.get("代码", "")).zfill(6)
                try:
                    _ratio = float(_row.get("净买额占总成交比", 0)) / 100.0
                except (ValueError, TypeError):
                    _ratio = 0.0
                _lhb_map[_code] = _ratio
        # 当日无数据或空数据时用最近缓存
        if not _lhb_map:
            _akshare_dir = os.path.join(PROJECT, "data", "akshare")
            if os.path.exists(_akshare_dir):
                for _fn in sorted(os.listdir(_akshare_dir), reverse=True):
                    if _fn.startswith("get_lhb_detail_") and _fn.endswith(".json"):
                        try:
                            with open(os.path.join(_akshare_dir, _fn), "r", encoding="utf-8") as _lf2:
                                _lhb_cached = json.load(_lf2)
                            _rows2 = _lhb_cached.get("data", []) if isinstance(_lhb_cached, dict) else []
                            if len(_rows2) > 0:
                                for _row2 in _rows2:
                                    _code2 = str(_row2.get("代码", "")).zfill(6)
                                    try:
                                        _ratio2 = float(_row2.get("净买额占总成交比", 0)) / 100.0
                                    except (ValueError, TypeError):
                                        _ratio2 = 0.0
                                    _lhb_map[_code2] = _ratio2
                                if _lhb_map:
                                    break
                        except Exception:
                            continue
        print(f"  🐉 龙虎榜加载 {len(_lhb_map)} 只")
    except Exception as _e:
        print(f"  🐉 龙虎榜数据加载失败: {_e}")

    _allow_pick = True  # 2026-09-18 老大拍板：环境门仅作辅助，空仓时必须出票

    # ── v36启动验证 ──
    validate_v36_params()

    # ── v36优化: 冷却期检查（持仓后需等待COOLDOWN_DAYS天才能换票）──
    _cooldown_ok, _days_since, _cooldown_msg = check_cooldown_for_pick()
    if not _cooldown_ok:
        print(f"  ⏸️ 冷却期检查: {_cooldown_msg} → 硬拦截: 不输出选股结果")
        _allow_pick = False
    else:
        print(f"  ⏸️ 冷却期检查: {_cooldown_msg}")
    
    # ── Step 1: 全量扫描 ──
    print("\n📊 Layer 0b: 板块热度加载...")
    heat_data = load_industry_heat()
    if heat_data:
        valid = {k: v for k, v in heat_data.items()
                 if isinstance(v, dict) and "rank" in v}
        top5 = sorted(valid.items(), key=lambda x: x[1]["rank"])[:5]
        print("  🔥 今日热点板块TOP5:")
        for name, info in top5:
            print("    #%d %s (+%.1f%%)" % (info["rank"], name[:8], info["change_pct"]))
    else:
        print("  ⚠️ 板块热度数据不可用")

    # ── Layer 7.5 龙虎榜评分 (环境门取消后无条件执行，在final_ranking定义后) ──
    # 2026-09-04 智囊团终审：LHB IC=0.0991全场最强，恢复主评分
    # 恢复+5/-10权重，大买加分大卖否决
    _lhb_bought, _lhb_sold = 0, 0

    # ── Step 1: 全量扫描 ──
    print("\n📡 Layer 1: 全量扫描+综合评分...")
    cache = load_name_cache()
    ind_cache = load_industry_map()

    all_codes = []
    for market, mname, prefixes in [
        ("sh", "上海", ALLOWED_PREFIXES_SH),
        ("sz", "深圳", ALLOWED_PREFIXES_SZ),
    ]:
        day_dir = os.path.join(VIPDOC, market, "lday")
        if os.path.isdir(day_dir):
            for f in os.listdir(day_dir):
                if f.endswith(".day"):
                    # 关键修复：保留 sh/sz 前缀，TDX文件名与get_tdx_data的查找路径一致
                    raw_code = f.replace(".day", "")
                    if not raw_code[:2] in ("sh", "sz"):
                        continue
                    # 检查代码是否属于当前市场
                    code_prefix = raw_code[2:5] if raw_code[2:] else ""
                    if not code_prefix in prefixes:
                        continue
                    code_clean = raw_code[2:]  # 纯6位数字
                    if not is_st_stock(cache.get(code_clean, "")):
                        all_codes.append(raw_code)  # 保留前缀

    print("  扫描 %d 只..." % len(all_codes))
    
    # 加载策略权重 (v8.0: config.json 覆盖层已删除, 实盘/回测统一用 STRATEGIES)
    # 修复 M3: force_strategy 时真正切换综合评分权重（此前仅改展示标签，
    # score_stock 仍固定用"综合"权重，用户以为切了策略实际没变）
    if force_strategy and force_strategy in STRATEGIES:
        strategy_zonghe = dict(STRATEGIES[force_strategy])
        strategy_quancang = STRATEGIES["全仓"]   # 风控口径保持全仓
    else:
        # 2026-09-22 P0修复: 回退至"综合"策略（Alpha101核心因子已冻结，v36回测验证"综合"+22.13%）
        strategy_zonghe = dict(STRATEGIES["综合"])
        strategy_quancang = STRATEGIES["全仓"]

    # 收集所有股票的数据
    candidates = []
    recs_dict = {}       # 缓存日线数据，供 gap/nb 模块复用
    weekly_dict = {}     # 缓存周线指标
    breakout_dict = {}    # 缓存真突破检测结果
    scanned = 0
    inds_list = []       # v8.0: 收集所有 inds 用于截面百分位
    liq_filter = {"count": 0, "reasons": {}}   # T-20260816-002 Option E: 过滤统计
    
    for code in all_codes:
        recs = get_tdx_data(code, 150)
        if not recs or len(recs) < 30:
            continue
        # T-20260816-002 Option E: 流动性/价格/ST/停牌 前端过滤 (不静默, 记过滤日志)
        liq_ok, liq_reason = apply_tradability_filter(code, cache.get(code, ""), recs)
        if not liq_ok:
            liq_filter["count"] += 1
            liq_filter["reasons"][liq_reason] = liq_filter["reasons"].get(liq_reason, 0) + 1
            reject_log.append({
                "code": code, "name": cache.get(code, ""), "layer": "Layer1流动性",
                "reason": "流动性/成本过滤: %s" % _LIQ_REASON_CN.get(liq_reason, liq_reason),
                "score_before": 0,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            })
            continue
        # H2修复: 实盘除权防护 — 最近30日有向下>15%跳空(除权特征)的排除
        try:
            from core.pipeline.tdx_core import has_recent_gap
            hg, hg_date, hg_pct = has_recent_gap(recs, days=30, threshold=15.0)
            # 方向判断: 找跳空当天的开/收确认是向下(除权)还是向上(可能断层)
            if hg and hg_date:
                down = False
                for i in range(1, len(recs)):
                    if str(recs[i].get("date", "")) == hg_date:
                        if recs[i-1].get("close", 0) and recs[i].get("open", 0):
                            if recs[i]["open"] < recs[i-1]["close"] * 0.90:
                                down = True
                        break
                if down:
                    reject_log.append({
                        "code": code, "name": "", "layer": "Layer1",
                        "reason": "除权向下跳空(数据失真排除)",
                        "score_before": 0,
                        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    })
                    continue  # 向下跳空=除权失真, 排除
        except Exception:
            pass
        
        # KIMI审查-20 P1修复: 真突破检测过滤（可选）
        if _HAS_BREAKOUT_FILTER and ENABLE_BREAKOUT_FILTER:
            current_price = recs[-1]['close'] if recs else 0
            breakout_result = apply_breakout_filter(recs, current_price)
            if breakout_result['pass']:
                # P1-2026-09-07: 真突破票加分（上限5分），存储结果供第二遍使用
                breakout_bonus = min(5, breakout_result['score'] // 20)
                breakout_dict[code] = {"score": breakout_result['score'], "bonus": breakout_bonus}
            # 非真突破票不扣分，保留观察
        inds = compute_indicators(recs)
        if not inds:
            continue
        weekly = compute_weekly_indicators(recs)

        # 缓存数据供后续使用
        recs_dict[code] = recs
        weekly_dict[code] = weekly
        inds_list.append({"code": code, "inds": inds})
        scanned += 1

    print("  可评分股票数: %d只" % scanned)
    if liq_filter["count"]:
        _ld_fmt = ", ".join("%s%d只" % (_LIQ_REASON_CN.get(k, k), v)
                            for k, v in sorted(liq_filter["reasons"].items(), key=lambda x: -x[1]))
        print("  🚫 流动性/价格过滤: 排除%d只 (%s, 阈值%s均额≥%.0f万/价≥%.1f元)" % (
            liq_filter["count"], _ld_fmt, "严格5000万" if LIQUIDITY_MIN_AMT == 50_000_000 else "默认3000万",
            LIQUIDITY_MIN_AMT / 1e4, LIQUIDITY_MIN_PRICE))

    # v8.1: 计算截面z-score (chg5/vol_ratio/rsi14/pos_vs_ma20) - 替代百分位提升区分度
    # P0修复(2026-09-23): 先评分写入raw_score，再计算z-score
    zscores = None
    
    # 第一遍: 综合评分 (先评分写入raw_score)
    import re as _re
    _temporal_re = _re.compile(r"时序([+-]\d+\.\d+)")
    _ts_count = 0      # |时序delta|>=0.5 的股票数
    _ts_total = 0      # 被评分股票数 (sc_zh>0)
    for item in inds_list:
        code = item["code"]
        inds = item["inds"]
        weekly = weekly_dict.get(code)
        recs = recs_dict.get(code, [])

        # 综合评分 (T-20260816-006-B: 三态市场倍率表已回测验证PASS, 实盘启用)
        # v8.1: 使用z-score替代cross_rank提升区分度
        sc_zh, sigs_zh, _ = score_stock(inds, weekly, strategy=strategy_zonghe, zscore=None, records=recs,
                                        market_state=market_label)
        # V2新因子调整 (2026-09-26): 门控, 与回测链路同源(tdx_factor_v2), 关闭时零行为变化
        _v2_adj = 0.0
        try:
            from core.scoring.tdx_factor_v2 import v2_adjust as _v2a, compute_v2_factors as _v2c
            if recs and len(recs) >= 60:
                _v2f = _v2c([float(r.get('close') or 0) for r in recs],
                            [float(r.get('open') or 0) for r in recs],
                            [float(r.get('high') or 0) for r in recs],
                            [float(r.get('low') or 0) for r in recs],
                            [float(r.get('volume') or 0) for r in recs],
                            [float(r.get('amount') or 0) for r in recs])
                _v2_adj = _v2a(_v2f)
                if _v2_adj:
                    sc_zh += _v2_adj
                    sigs_zh.append(f"V2因子{_v2_adj:+.1f}")
        except Exception as _v2e:
            # 2026-09-26 接入排查: 首次异常落盘, 不静默 (修复后可移除)
            if not globals().get('_v2_err_logged'):
                globals()['_v2_err_logged'] = True
                try:
                    with open(os.path.join(PROJECT, ".scratch", "v2_debug.txt"), "w", encoding="utf-8") as _f:
                        import traceback as _tb
                        _f.write(f"code={code} recs_len={len(recs) if recs else 0}\n")
                        _tb.print_exc(file=_f)
                except Exception:
                    pass  # 因子层异常不影响原评分
        # P0修复(2026-09-23): 评分后立即写入raw_score供截面标准化使用
        if inds is not None and isinstance(inds, dict):
            inds['raw_score'] = float(sc_zh)
        # P1-2026-09-07: 应用真突破加分
        if code in breakout_dict:
            sc_zh += breakout_dict[code]["bonus"]
            sigs_zh.append(f"🚀 真突破({breakout_dict[code]['score']}分)+{breakout_dict[code]['bonus']}")
        if sc_zh <= 0:
            continue
        # v8.1 指标2: 覆盖率分母 = 候选池(base分≥40, 有资格被时序增强的股票)
        # 低分股(<40)不进候选, 给它们增强无意义 — 2026-08-06 针对性修
        if sc_zh >= 40:
            _ts_total += 1
            for _s in sigs_zh:
                _m = _temporal_re.search(_s)
                if _m and abs(float(_m.group(1))) >= 0.5:
                    _ts_count += 1
                    break

        # 全仓评分（风控过滤）(T-20260816-006-B: 倍率表实盘启用)
        # 2026-09-24修复: zscore=None避免NameError（截面z-score在评分后计算）
        sc_qc, sigs_qc, _ = score_stock(inds, weekly, strategy=strategy_quancang, zscore=None, records=recs,
                                         market_state=market_label)
        # V2新因子调整 (2026-09-26): 与综合评分同源同值, 保证两口径排序一致
        if _v2_adj:
            sc_qc += _v2_adj
            sigs_qc.append(f"V2因子{_v2_adj:+.1f}")

        # 2026-09-24: DL预测集成
        dl_score = 0.0
        if _HAS_DL and ENABLE_DL_PREDICTOR:
            try:
                dl_result = dl_score_stock(code, recs)
                dl_score = dl_result.get('dl_score', 0.0)
            except Exception as _e:
                dl_score = 0.0  # DL故障不阻塞主流程

        # 综合评分 + DL加权
        if _HAS_DL and ENABLE_DL_PREDICTOR:
            final_score = sc_zh * (1 - DL_WEIGHT) + dl_score * DL_WEIGHT
        else:
            final_score = sc_zh

        # 行业
        industry = get_industry(code, cache.get(code, ""), ind_cache)
        if industry is None:
            industry = "其他"

        # 板块热度加分
        heat_bonus, heat_desc = get_industry_heat_bonus(industry, heat_data)

        # DL预测加分 (门开时才启用)
        dl_bonus = 0
        dl_desc = ""
        if _HAS_DL and ENABLE_DL_PREDICTOR and _dl_engine:
            try:
                dl_ret, dl_conf = _dl_engine.predict_single_stock(recs)
                if dl_ret is not None:
                    # 将DL预测收益率转换为分数 (-10, +10)
                    # 收益率±8%对应分数±10分（与止损阈值对齐）
                    dl_bonus = max(-10, min(10, dl_ret * 125))  # 0.08*125=10
                    dl_desc = f"🤖 DL预测{dl_ret:+.2%}(conf={dl_conf:.0%})"
                    sigs_zh.append(dl_desc)
            except Exception as _dl_e:
                logging.debug(f"DL预测失败 {code}: {_dl_e}")

        candidates.append((sc_zh, sc_qc, code, cache.get(code, ""), industry,
                           sigs_zh, sigs_qc, heat_bonus, heat_desc,
                           dl_bonus, dl_desc, final_score))

    print("  Top 50进入断层+北向+风控+板块过滤...")

    # P0修复(2026-09-23): 评分后计算截面z-score
    try:
        from core.pipeline.tdx_core import compute_cross_section_zscores, build_zscore
        zscores = compute_cross_section_zscores(inds_list)
        print(f"  📊 截面z-score计算完成 ({len(zscores)}只)")
    except Exception as ce:
        print(f"  ⚠️ 截面zscore计算失败: {ce}")
        zscores = None

    # v8.1 验证指标2: 时序增强覆盖率写入诊断 (2026-08-06)
    _ts_coverage = (_ts_count / _ts_total * 100) if _ts_total else 0.0
    print(f"  📊 时序增强覆盖率: {_ts_count}/{_ts_total} = {_ts_coverage:.1f}% "
          f"({'✅≥60%' if _ts_coverage >= 60 else '⚠️<60%'})")
    try:
        _diag_file = os.path.join(PROJECT, "backtest_analysis", "score_diagnostics.json")
        _diag = {"date": datetime.now().strftime("%Y-%m-%d"),
                 "temporal_coverage": round(_ts_coverage, 1),
                 "temporal_count": _ts_count,
                 "temporal_total": _ts_total,
                 "temporal_coverage_ok": _ts_coverage >= 60}
        if os.path.exists(_diag_file):
            _d0 = json.load(open(_diag_file, encoding="utf-8"))
            if isinstance(_d0, dict):
                _d0.update(_diag)
                _diag = _d0
        os.makedirs(os.path.dirname(_diag_file), exist_ok=True)
        atomic_json.atomic_dump(_diag, _diag_file, ensure_ascii=False, indent=2, encoding="utf-8")
    except Exception as _e:
        print(f"  ⚠️ 诊断写入失败: {_e}")

    # 排序取Top 50
    candidates.sort(key=lambda x: -x[0])

    # P0-1 评分归一化 (2026-09-05 修复): 线性缩放替代百分位排名
    # 根因: percentile_rank 在弱因子环境下将"噪声重新排名", TOP5方差=0
    # 方案A: linear_scale 保留绝对区分度, 最低分→5, 最高分→100
    # 方案B: 同分票用 secondary key 排序 (vol>chg20>gap_score)
    from core.scoring.scoring_engine import linear_scale as _lin_scale
    _all_scores = [c[0] for c in candidates]
    for _i in range(len(candidates)):
        candidates[_i] = (
            _lin_scale(candidates[_i][0], _all_scores),  # 线性缩放
            candidates[_i][1], candidates[_i][2],          # score_qc, code
            *candidates[_i][3:]                           # 其余字段不变
        )
    candidates.sort(key=lambda x: -x[0])
    top50 = candidates[:50]

    # ── P0-1 方案B: 同分票 secondary key 排序 (2026-09-05) ──
    # 当 linear_scale 后仍有同分票时, 用 vol>chg20>gap_score 打破平局
    # vol: 成交量(越高越好); chg20: 20日涨幅(越高越好); gap_score: 断层加分
    if len(top50) > 1:
        _sorted_top50 = []
        _i = 0
        while _i < len(top50):
            _cur = top50[_i]
            _group = [_cur]
            _j = _i + 1
            while _j < len(top50) and top50[_j][0] == _cur[0]:
                _group.append(top50[_j])
                _j += 1
            if len(_group) == 1:
                _sorted_top50.append(_group[0])
            else:
                # 同分票按 secondary key 排序
                def _secondary_key(item):
                    _code = item[2]
                    _recs = recs_dict.get(_code, [])
                    _vol = _recs[-1].get('volume', 0) if _recs and len(_recs) >= 1 else 0
                    _chg20 = 0
                    if _recs and len(_recs) >= 21:
                        _c0 = _recs[-21].get('close', 0)
                        _c1 = _recs[-1].get('close', 0)
                        _chg20 = (_c1 / _c0 - 1) * 100 if _c0 > 0 else 0
                    _gap = item[7] if len(item) > 7 else 0  # heat_bonus field or gap_score
                    return (_vol, _chg20, _gap)
                _group.sort(key=_secondary_key, reverse=True)
                _sorted_top50.extend(_group)
            _i = _j
        top50 = _sorted_top50

    # ── Layer 5b: 动量加分 (P1-2修复 2026-10-21: 硬过滤→加分项) ──
    # 原设计: 5日>3% / 10日>5% / 20日>8% 之一通过 → 保留, 否则排除
    # 问题: 弱市/震荡市大部分票动量不达标 → 候选池被清空 → 无票输出
    # 修复: 改为加分模式 — 满足动量条件的票 +5 分, 不剔除其他候选
    # 与 Layer 5c 主升浪加速 (+5分) 逻辑一致
    momentum_bonus_count = 0
    new_top50 = []
    for item in top50:
        code = item[2]
        recs = recs_dict.get(code, [])
        if len(recs) < 20:
            new_top50.append(item)
            continue
        close_5d_ago = recs[-6]['close'] if len(recs) >= 6 else recs[0]['close']
        close_10d_ago = recs[-11]['close'] if len(recs) >= 11 else recs[0]['close']
        close_20d_ago = recs[-21]['close'] if len(recs) >= 21 else recs[0]['close']
        current_close = recs[-1]['close']
        mom_5d = (current_close / close_5d_ago - 1) * 100 if close_5d_ago > 0 else 0
        mom_10d = (current_close / close_10d_ago - 1) * 100 if close_10d_ago > 0 else 0
        mom_20d = (current_close / close_20d_ago - 1) * 100 if close_20d_ago > 0 else 0
        if mom_5d > 3 or mom_10d > 5 or mom_20d > 8:
            item_list = list(item)
            item_list[0] = round(item_list[0] + 5, 1)
            item = tuple(item_list)
            momentum_bonus_count += 1
        new_top50.append(item)
    top50 = new_top50
    print(f"  📈 动量加分: {momentum_bonus_count}只 (+5分, P1-2: 原硬过滤改为加分)")
    
    # ── Layer 5c: 主升浪加速检测 (唯识学种子理论) ──
    # P1#5(2026-10-10 老三): 启用并改为加分模式 (原硬过滤导致候选池过度收缩)
    # 逻辑: 加速股+5分, 不剔除其他候选
    accel_bonus_count = 0
    if ENABLE_STARTUP_DETECTOR:
        new_top50 = []
        for item in top50:
            code = item[2]
            recs = recs_dict.get(code, [])
            if len(recs) < 20:
                new_top50.append(item)
                continue

            accel_score, is_starting, signals = calculate_startup_score(recs, market_label)
            if is_starting:
                # 主升浪启动信号: +5分
                item_list = list(item)
                item_list[0] = round(item_list[0] + 5, 1)
                item = tuple(item_list)
                accel_bonus_count += 1
                print(f"    🚀 {code}: 主升浪加速 (+5分, score={accel_score})")
            new_top50.append(item)
        top50 = new_top50[:50]
        print(f"  🚀 主升浪加速: {accel_bonus_count}只 (+5分)")
    else:
        print("  ⏸️ 主升浪检测已禁用")

    # v8.1 指标1/3: 今日候选池分数写入诊断 (score_diagnostics 优先读, 避免历史污染)
    try:
        _diag_file = os.path.join(PROJECT, "backtest_analysis", "score_diagnostics.json")
        _today_scores = [round(c[0], 1) for c in candidates if c[0] >= 40]
        _diag2 = {"date": datetime.now().strftime("%Y-%m-%d"),
                  "today_scores": _today_scores[:50],
                  "today_n": len(_today_scores)}
        _d1 = {}
        if os.path.exists(_diag_file):
            _d1 = json.load(open(_diag_file, encoding="utf-8")) or {}
        if not isinstance(_d1, dict):
            _d1 = {}
        _d1.update(_diag2)
        os.makedirs(os.path.dirname(_diag_file), exist_ok=True)
        atomic_json.atomic_dump(_d1, _diag_file, ensure_ascii=False, indent=2, encoding="utf-8")
    except Exception as _e:
        print(f"  ⚠️ 今日分数写入失败: {_e}")

    # ── Step 2: 净利润断层评分 ──
    print("\n📡 Layer 2: 净利润断层评分...")
    # 从top50中取代码
    top_codes = [item[2] for item in top50]
    # 使用断层策略权重（或从config读取）
    gap_strategy = STRATEGIES.get("断层", strategy_zonghe)
    
    # 修复 H4: 断层评分需要日线指标(price/ma5/ma10/ma20/market_state)，
    # 此前误传 weekly_dict 导致 current_price=0、全部断层分系统性失真
    daily_inds_dict = {}
    for _it in inds_list:
        _inds = dict(_it["inds"])
        _inds["market_state"] = market_label  # score_gaps 需要市场状态修正
        daily_inds_dict[_it["code"]] = _inds
    
    gap_scores = batch_score_gaps(
        top_codes, recs_dict, daily_inds_dict, gap_strategy
    )

    gap_hit = sum(1 for c in top_codes if gap_scores.get(c, (0, "", []))[0] > 0)
    print("  断层信号命中: %d/50只" % gap_hit)

    # ── L2b 强断层 (2026-08-16 验证合入): 断层信号 + 净利润增速>50% → +8分 ──
    # 依据: scripts_tmp/hermes-verify-earnings-gap.py, 全市场132扫描日 n=90 胜率52.2%
    #       avg5净+3.71% 超额+4.73pp (验收线: 胜率>50% 且 超额>+3pp 达标)
    # ⚠️ 回测为乐观上界(财务缓存=当前快照); 实盘用当前财务无前视, 安全
    try:
        _fin_cache = json.load(open(os.path.join(PROJECT, "data", "financial_cache.json"), encoding="utf-8"))
        _fin_stocks = _fin_cache.get("stocks", {})
        _l2b_count = 0
        for _c in top_codes:
            if gap_scores.get(_c, (0, "", []))[0] > 0:
                _cc = _c[2:] if _c[:2].isalpha() else _c
                _ind = _fin_stocks.get(_cc, {}).get("indicators", {})
                if (_ind.get("net_profit_yoy") or 0) > 0.50:
                    _old = gap_scores.get(_c)
                    if _old:
                        _new_sigs = list(_old[2]) + ["💪强断层(净利增速>50%)"]
                        gap_scores[_c] = (_old[0] + 8, _old[1], _new_sigs)
                        _l2b_count += 1
        if _l2b_count:
            print(f"  💪 L2b强断层命中: {_l2b_count}只 (断层+净利增速>50%, +8分)")
    except Exception as _l2b_e:
        print(f"  ⚠️ L2b强断层跳过: {_l2b_e}")

    # ── v8.1 断层独立通道 (事件驱动alpha不与连续评分混合) ──
    # P0改进: 可通过 ENABLE_GAP_STRATEGY 开关控制
    gap_pool = {}
    if ENABLE_GAP_STRATEGY:
        try:
            from core.scoring.gap_channel import get_gap_channel
            gap_chan = get_gap_channel()
            chan_candidates = []
            for _c in top50:
                _code = _c[2]
                if _code in recs_dict:
                    chan_candidates.append({"code": _code, "recs": recs_dict[_code],
                                            "inds": daily_inds_dict.get(_code)})
            gap_pool = gap_chan.update_pool(chan_candidates)
            if gap_pool:
                print(f"  🎯 断层独立通道: {len(gap_pool)}只事件驱动标的 (优先推荐)")
                for _g in gap_pool.values():
                    print(f"    {_g['code']} 缺口{_g['gap_pct']:.1f}% 强度{_g['score']}")
        except Exception as _e:
            print(f"  ⚠️ 断层独立通道跳过: {_e}")
            gap_pool = {}
    else:
        print("  ⏸️ 断层策略已关闭 (ENABLE_GAP_STRATEGY=False)")

    # ── Step 3: 北向资金评分 ──
    # 已停用: 2024年5月后港交所停披露北向实时个股数据
    nb_scores = {}
    nb_hit = 0
    print("  ⏸️ 北向评分已停用")

    # ── Step 3b: 基本面财务评分 + 舞弊检测 (Layer 2b) ──
    print("\n📡 Layer 2b: 基本面财务评分+舞弊检测...")

    # 动态阈值: 根据市场状态调整财务过滤强度
    # 强市放宽(避免错失机会), 弱市收紧(排除劣质股)
    fin_threshold = -5  # 默认: 净加分 >= -5 才通过
    if market_score >= 75:
        fin_threshold = -8   # 强市/极强: 高度宽松
        fin_mode = "🧊 宽松"
    elif market_score >= 55:
        fin_threshold = -5   # 偏暖: 默认
        fin_mode = "📊 默认"
    elif market_score >= 35:
        fin_threshold = -5   # 震荡: 默认
        fin_mode = "📊 默认"
    elif market_score >= 15:
        fin_threshold = -2   # 弱: 收紧
        fin_mode = "🔍 收紧"
    else:
        fin_threshold = 0    # 恐慌: 极严
        fin_mode = "🚨 极严"

    print(f"  📐 财务过滤阈值: {fin_threshold} ({fin_mode}) 市场:{market_label}({market_score}分)")

    # P0-4: 财务过滤候选池 Top50 → Top100 (可配置 FINANCIAL_TOP_N)
    # 2026-09-20: 财务数据覆盖率为0（akshare不可用），关闭财务过滤
    fin_scores = {}
    fin_hit = 0
    fraud_fatal = 0

    # ── P0-2 华泰数据增强（老五审查接入，2026-08-23）──
    # 用华泰资金流/基本面补充财务层，六层→完整六层
    _huatai_enriched = 0
    if _HAS_HUATAI:
        try:
            _remaining = get_remaining_calls()
            if _remaining > 10:
                # 构建 scored_list 格式传入华泰
                _ht_input = [(s, c, m, n, {"industry": ind, "price": 0}, [])
                             for s, c, m, n, ind in top50[:10]]
                _ht_result = huatai_enrich_stocks(_ht_input, top_n=10, strategy_name="综合")
                _huatai_enriched = sum(1 for item in _ht_result if item[4].get("huatai_available"))
                _after = get_remaining_calls()
                print(f"  🏢 华泰数据: 丰富Top10 ({_huatai_enriched}只有数据) | 今日剩余{_after}次")
            else:
                print(f"  ⚠️ 华泰数据跳过: 今日剩余仅{_remaining}次")
        except Exception as _ht_e:
            print(f"  ⚠️ 华泰数据异常 (不影响选股): {_ht_e}")
    else:
        print(f"  📡 华泰数据未安装 (huatai_data.py)")

    # ── Layer 3c: bearish形态回避池 (P2, Kimi审查-4) ──
    # 圆弧顶/头肩顶/双顶 通过门禁后，不进入推荐记录，而是作为回避池信号（一票否决）
    # P2优化 2026-09-30: 降低惩罚阈值从-50→-20，减少误杀
    BEARISH_PATTERNS = ['圆弧顶', '头肩顶', '双顶']
    BEARISH_PENALTY = 20  # P2优化: 从50降至20

    # 头肩顶检测 (镜像头肩底: 找三个高点，头部最高，颈线=左肩低点)
    def detect_head_shoulders_top(records, lookback=60):
        """头肩顶形态 (Head and Shoulders Top)"""
        if len(records) < 50:
            return {"found": False, "score": 0, "desc": ""}
        highs = [r["high"] for r in records[-lookback:]]
        lows = [r["low"] for r in records[-lookback:]]
        n = len(highs)
        # 找三个高点（左肩、头部、右肩）
        left_max = max(highs[:n // 3])
        right_max = max(highs[2 * n // 3:])
        mid_max = max(highs[n // 3:2 * n // 3])
        # 头部应最高
        if mid_max <= left_max or mid_max <= right_max:
            return {"found": False, "score": 0, "desc": ""}
        # 左右肩高度相近
        if abs(left_max - right_max) / left_max > 0.05:
            return {"found": False, "score": 0, "desc": ""}
        # 颈线 = 两肩间最高低点
        neckline = max(lows[n // 3:2 * n // 3])
        cur_price = records[-1]["close"]
        below_neck = cur_price < neckline
        score = -18 if below_neck else -12
        desc = f"🎩 头肩顶{'确认' if below_neck else '雏形'}(颈线{neckline:.2f})"
        return {"found": True, "score": score, "desc": desc}

    bearish_pool = {}
    try:
        from pattern_recognition import (
            detect_rounding_top, detect_double_top,
        )
        _bearish_funcs = {
            "圆弧顶": detect_rounding_top,
            "双顶": detect_double_top,
            "头肩顶": detect_head_shoulders_top,
        }
        _bearish_count = 0
        for item in top50:
            code = item[2]
            recs = recs_dict.get(code, [])
            if not recs or len(recs) < 50:
                continue
            for pat_name, pat_func in _bearish_funcs.items():
                if pat_name not in BEARISH_PATTERNS:
                    continue
                if pat_func is None:
                    continue
                try:
                    _pat_result = pat_func(recs, lookback=80)
                    if _pat_result.get("found") and _pat_result.get("score", 0) < 0:
                        # 高置信度bearish形态：score为负且绝对值>=10
                        if abs(_pat_result["score"]) >= 10:
                            if code not in bearish_pool:
                                bearish_pool[code] = []
                            bearish_pool[code].append({
                                "pattern": pat_name,
                                "score": _pat_result["score"],
                                "desc": _pat_result.get("desc", ""),
                            })
                            _bearish_count += 1
                except Exception:
                    pass
        print(f"  📐 bearish回避池: {_bearish_count}只检测到高置信度空头形态 {BEARISH_PATTERNS}")
        if bearish_pool:
            for _bp_code, _bps in list(bearish_pool.items())[:3]:
                for _bp in _bps:
                    print(f"    {_bp_code} {_bp['pattern']}: {_bp['desc']}")
    except ImportError:
        print("  ⚠️ bearish形态回避池跳过: pattern_recognition模块未导入")
        bearish_pool = {}
    except Exception as _bp_e:
        print(f"  ⚠️ bearish形态检测异常: {_bp_e}")
        bearish_pool = {}

    # ── Step 4+5: 综合排序+风控+板块 ──
    analyzed = []
    
    # 归一化系数
    gap_weight = 1.0   # 断层每个打分点=1分
    nb_weight = 1.0    # 北向每个打分点=1分
    
    for item in top50:
        # item may have 9 or 11 fields (dl_bonus/dl_desc added in v3.x)
        sc_zh, sc_qc, code, name, industry, sigs_zh, sigs_qc, heat_bonus, heat_desc, *_rest = item
        dl_bonus, dl_desc = (_rest[0], _rest[1]) if len(_rest) >= 2 else (0, "")
        base_final = _rest[2] if len(_rest) >= 3 else sc_zh  # P0-1修复: 当前股票的DL混合分，不再用陈旧变量
        risk = sc_zh - sc_qc
        confidence = min(sc_zh, sc_qc)
        pass_risk = (sc_qc >= sc_zh * 0.7)

        # 断层加分
        gap_score, gap_desc, gap_sigs = gap_scores.get(code, (0, "", []))
        
        # 北向加分
        nb_score, nb_desc, nb_sigs = nb_scores.get(code, (0, "", []))

        # 基本面财务评分 + 舞弊检测
        clean_code = code[2:] if code[:2].isalpha() else code
        fin_result = fin_scores.get(clean_code, {})
        # P1-13: 缺数据联动 — 不否决(fin_fatal=False), 依赖 financial_health=-20 自然降权
        # (fin_bonus clamp 后=-10, 为财务维度最大降权; 空dict同样视为缺数据防御)
        if not fin_result or fin_result.get("data_status") == "missing":
            logging.warning(f"P1-13: {clean_code} 财务数据缺失, 已降权(fin_health=-20)")
        fin_health = fin_result.get("financial_health", 0)     # 0~40 (缺数据=-20)
        fin_penalty = fin_result.get("fraud_penalty", 0)        # -30~0
        fin_fatal = fin_result.get("fraud_fatal", False)
        fin_health_sigs = fin_result.get("health_signals", [])
        fin_fraud_sigs = fin_result.get("fraud_signals", [])
        # 综合财务加分：健康分直接转换，舞弊扣分叠加
        # health→0~20 范围: 健康20分+扣分-10 = 净-10~+20
        fin_bonus = max(-10, min(20, int(fin_health / 2) + fin_penalty))

        # 增强信号列表（包含新策略信号）
        extra_sigs = []
        if gap_score > 0:
            extra_sigs.append("📈缺口")
        if nb_score > 5:
            extra_sigs.append("🏦北向")
        elif nb_score < -5:
            extra_sigs.append("⚠️北向减")
        if fin_scores:
            if fin_bonus >= 5:
                extra_sigs.append("🏭优质")
            elif fin_bonus <= fin_threshold:
                extra_sigs.append("🔴优质")
            if fin_fatal:
                extra_sigs.append("🚫排雷")

        # v8.1 舞弊一票否决: 排雷股直接重罚跌出推荐 (不仅是标记)
        # 震荡市/弱市(veto豁免): 流动性差+欺诈股难出货→允许买入,但需标注
        veto_penalty = 0
        if fin_fatal and market_score >= 55:
            veto_penalty = 20  # 牛市中排除欺诈股
        elif fin_fatal:
            veto_penalty = 10  # 震荡市减半惩罚,标注风险

        # v8.1 断层独立通道: 断层池标的优先 — P1-6去重(2026-08-08): 5→2
        # 断层同源去重: gap_adj×0.8已给断层加分, chan_bonus再×0.5=同源重复计权(Kimi模式I)
        # 降为2分边际加成, 避免断层单源贡献过大
        chan_bonus = 0
        if gap_pool and code in gap_pool:
            chan_bonus = 2
            extra_sigs.append("🎯断层通道")

        # v8.2 断层追高豁免: 断层股(跳空高开天然偏离MA20)豁免追高惩罚
        # Kimi框架审查发现: 断层奖励(+15) vs 追高惩罚(-15~-20) 内生冲突 → 内耗筛掉真断层
        chase_exempt = 0
        if gap_score > 0 or (gap_pool and code in gap_pool):
            chase_exempt = min(gap_score * 0.5, 6)  # 最多豁免6分
        # T3核查(2026-09-29): chase_exempt与CHASE_BAN_PCT=4%不冲突
        # chase_exempt仅影响评分加分, 追高拦截在选股入口硬门禁执行(integrated_picker.py:1753)
        # 豁免逻辑有效: 断层股天然偏离MA20, 不应受追高惩罚压制

        # P0-2 (2026-10-21 三方讨论拍板): 实盘改走 compute_final_score() 统一公式
        # 回测(backtest.py:742)与实盘现在共用同一公式结构:
        #   final = base + gap*0.8 + fin*fin_w + chan*0.5 + chase*0.5 - risk*0.05
        # 实盘独有输入通过 base_override(DL混合分) 和 pattern_bonus(bearish) 参数传入
        # veto_penalty 保留动态(牛市20/震荡10) — 回测固定20, 差异已文档标注
        _bearish_penalty = 0
        if code in bearish_pool:
            _bearish_penalty = BEARISH_PENALTY  # P2优化: 使用配置常量
            _pat_descs = [f"{bp['pattern']}:{bp['desc'][:20]}" for bp in bearish_pool[code]]
            extra_sigs.append(f"🚫bearish形态回避")
            print(f"  🚫 {code} {name}: bearish形态回避池命中 (-{abs(_bearish_penalty)}分)")

        from core.scoring.scoring_engine import compute_final_score as _cfs
        _final, _rank = _cfs(
            confidence, risk, pass_risk,
            gap_score=gap_score, fin_bonus=fin_bonus, fin_fatal=False,
            chan_bonus=chan_bonus, primary_strategy=primary_strategy,
            base_override=base_final,
            pattern_bonus=-_bearish_penalty,
        )
        # P0-2: 动态 veto_penalty (实盘牛市20/震荡10, 回测固定20)
        final = round(max(0.0, _final - veto_penalty), 1)
        _rank = round(_rank, 1)

        # P0 (2026-08-07): 过滤日志 — 财务劣质/舞弊排雷
        if fin_fatal:
            reject_log.append({
                "code": code, "name": name, "layer": "Layer2b舞弊",
                "reason": f"舞弊信号(一票否决 {veto_penalty}分)",
                "score_before": round(final + veto_penalty, 1),
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            })
        if fin_scores and fin_bonus <= fin_threshold:
            reject_log.append({
                "code": code, "name": name, "layer": "Layer2b财务",
                "reason": "财务评分 %d < 阈值 %d (劣质)" % (fin_bonus, fin_threshold),
                "score_before": round(final, 1),
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            })

        analyzed.append((final, sc_zh, sc_qc, risk, confidence, pass_risk,
                         heat_bonus, heat_desc, code, name, industry,
                         sigs_zh, sigs_qc, gap_score, gap_desc, gap_sigs,
                         nb_score, nb_desc, nb_sigs, extra_sigs))

    # P0 (2026-08-07): 过滤日志 — 风控未通过(追高/超买)
    for _a in analyzed:
        if not _a[5]:
            reject_log.append({
                "code": _a[8], "name": _a[9], "layer": "风控",
                "reason": "综合%d→全仓%d 风险%+d (追高/超买)" % (_a[1], _a[2], _a[3]),
                "score_before": round(_a[0], 1),
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            })

    # 排序
    # 修复 M4: 此前 passed+failed 硬分档，只要通过风控就无条件排在所有未通过前，
    # 绝对强度高的强股(追高被剔除)反而落到后面。改为统一按 final 排序，
    # 未通过风控的票给软惩罚(×0.85)而非硬分档。
    RISK_FAIL_PENALTY = 0.85
    analyzed.sort(key=lambda x: -x[0] * (1.0 if x[5] else RISK_FAIL_PENALTY))
    final_ranking = analyzed

    # ── Layer 7.5 龙虎榜评分 (环境门已取消硬拦截，直接执行) ──
    # 2026-09-04 智囊团终审：LHB IC=0.0991全场最强，恢复主评分
    # 恢复+5/-10权重，大买加分大卖否决
    # 2026-09-27 老大拍板：环境门已取消，不再检查 _gate_closed
    _lhb_bought, _lhb_sold = 0, 0
    if _lhb_map:
        for idx, _item in enumerate(final_ranking):
            _c = _item[8]
            if _c in _lhb_map:
                _r = _lhb_map[_c]
                if _r > 0.05:
                    _lhb_bought += 1
                    # 修复B003: tuple不可变，转list修改后再转回
                    _item_list = list(_item)
                    _item_list[0] = _item_list[0] + 5  # 大买+5分
                    final_ranking[idx] = tuple(_item_list)
                elif _r < -0.05:
                    _lhb_sold += 1
                    # 修复B003: tuple不可变，转list修改后再转回
                    _item_list = list(_item)
                    _item_list[0] = _item_list[0] - 10  # 大卖-10分
                    final_ranking[idx] = tuple(_item_list)

        print(f"  🐉 龙虎榜信号: 大买{_lhb_bought}只 大卖{_lhb_sold}只 ({len(_lhb_map)}只覆盖) (+5/-10)")

        # 记录龙虎榜监控数据
        try:
            _monitor_path = os.path.join(PROJECT, "data", "lhb_monitor.json")
            _monitor_data = {
                "timestamp": datetime.now().isoformat(),
                "bought": _lhb_bought,
                "sold": _lhb_sold,
                "covered": len(_lhb_map),
                "status": "observed"
            }
            with open(_monitor_path, 'w', encoding='utf-8') as _mf:
                json.dump(_monitor_data, _mf, ensure_ascii=False, indent=2)
        except Exception as _me:
            print(f"  ⚠️ 龙虎榜监控记录失败: {_me}")

    # ── Layer 6: 主力资金流加权 (akshare全市场 + FTShare fallback + 当日缓存) ──
    # 2026-08-07 修复: FTShare 逐只 symbol 查询是线性扫描(排名中间30s+超时, 且候选
    # 通常不在主力净流入TOP200内)。改为 akshare 一次性全市场(8s, 5200只全覆盖含负值)
    # 为主, FTShare TOP50(0.3s) 为 fallback。加分公式不变(每百万+1封顶+10/每两百万-1封顶-5)。
    # 缓存: cache/capital_flow_daily.pkl 当日有效+60分钟时间戳, 命中跳过 akshare (0.01s vs 8s)
    # 叠加加分逻辑: 主力流入加分/流出减分, 冲突抑制(P2): 资金大幅流出时形态加分减半
    # P0修复(2026-09-25): 原此行被压扁成注释, 吞掉了 flow_map/try 两条语句, 致 Layer6/7/8
    # 整段被吸收进上方 except 处理器, 正常运行时三条 Layer 从未执行 (AST 结构判定实锤)
    cap_flows = {}
    flow_map = {}
    _flow_src = ""
    try:
        import pickle as _pickle
        _cache_path = os.path.join(PROJECT, "cache", "capital_flow_daily.pkl")  # P1修复(20261023): S4迁移锚点漂移, 改用仓库根PROJECT
        _today_key = datetime.now().strftime("%Y-%m-%d")
        _cached = {}
        if os.path.exists(_cache_path):
            try:
                with open(_cache_path, "rb") as _f:
                    _cached = _pickle.load(_f)
            except Exception:
                _cached = {}
        cap_flows = {}
        flow_map = {}
        _flow_src = ""
        # P1 (2026-08-07): 缓存时间戳 — 60分钟失效, 防盘中过期数据
        # 新格式: {date: {"cached_at": iso, "flow": {code: net}}}; 旧格式(无时间戳)直接重拉
        _cached_ent = _cached.get(_today_key)
        _use_cache = False
        _cache_age_min = 0
        if isinstance(_cached_ent, dict) and "flow" in _cached_ent:
            _cached_at = _cached_ent.get("cached_at", "")
            if _cached_at:
                try:
                    _cache_age_min = (datetime.now() - datetime.fromisoformat(_cached_at)).total_seconds() / 60
                    _use_cache = _cache_age_min < 60
                except Exception:
                    _use_cache = False
        if _use_cache:
            flow_map = _cached_ent["flow"]
            _flow_src = f"akshare全市场(缓存 {len(flow_map)}只, {int(_cache_age_min)}分钟前)"
        else:
            try:
                import akshare as ak
                _df_flow = None
                for _attempt in range(2):  # 重试1次 (瞬时限流常见)
                    try:
                        _df_flow = ak.stock_fund_flow_individual(symbol="即时")
                        break
                    except Exception:
                        continue
                if _df_flow is None or len(_df_flow) == 0:
                    raise RuntimeError("akshare 资金流获取失败")
                for _, _row in _df_flow.iterrows():
                    _code = str(_row["股票代码"]).zfill(6)
                    _s = str(_row["净额"]).strip()
                    try:
                        if _s.endswith("亿"):
                            _net = float(_s[:-1]) * 1e8
                        elif _s.endswith("万"):
                            _net = float(_s[:-1]) * 1e4
                        else:
                            _net = float(_s)
                    except ValueError:
                        _net = 0.0
                    flow_map[_code] = _net
                _flow_src = "akshare全市场"
                # 写当日缓存 (P1: 新格式含 cached_at 时间戳)
                _cached[_today_key] = {"cached_at": datetime.now().isoformat(), "flow": flow_map}
                try:
                    os.makedirs(os.path.dirname(_cache_path), exist_ok=True)
                    with open(_cache_path, "wb") as _f:
                        _pickle.dump(_cached, _f)
                    # 2026-08-31 修复 (fix-hmac-20260831.md):
                    #   同步刷新 .hmac 签名，否则 data_quality_daily.py 会因 HMAC 不匹配
                    #   拒绝加载，导致 completeness 从 95 掉到 75 (根因)。
                    try:
                        import hmac as _hmac_mod, hashlib as _hashlib_mod
                        _hmac_key = os.environ.get("DATA_CACHE_HMAC_KEY", "")
                        # integrated_picker.py 原本未加载 .env，这里就近补一次
                        if not _hmac_key:
                            try:
                                from dotenv import load_dotenv as _ld
                                _env_path = os.path.join(PROJECT, ".env")  # P1修复(20261023): S4迁移锚点漂移, 改用仓库根PROJECT
                                if os.path.exists(_env_path):
                                    _ld(_env_path)
                                _hmac_key = os.environ.get("DATA_CACHE_HMAC_KEY", "")
                            except Exception:
                                pass
                        if _hmac_key:
                            with open(_cache_path, "rb") as _f2:
                                _pkl_bytes = _f2.read()
                            _sig = _hmac_mod.new(
                                _hmac_key.encode("utf-8"), _pkl_bytes, _hashlib_mod.sha256
                            ).hexdigest()
                            with open(_cache_path + ".hmac", "w", encoding="utf-8") as _f3:
                                _f3.write(_sig)
                        else:
                            print("  ⚠️ capital_flow HMAC 签名跳过: DATA_CACHE_HMAC_KEY 未配置")
                    except Exception as _hmac_e:
                        # HMAC 写失败不阻断选股（降级为 data_quality_daily 的 hmac_warn）
                        print(f"  ⚠️ capital_flow HMAC 签名刷新失败(不影响选股): {_hmac_e}")
                except Exception:
                    pass
            except Exception as _e1:
                from ft_adapter import ft_capital_flows
                r = ft_capital_flows(page=1, page_size=50)
                for it in r.get("items", []):
                    sym = (it.get("symbol") or "").split(".")[0]
                    try:
                        flow_map[sym] = float(it.get("net_inflow_main") or 0)
                    except (TypeError, ValueError):
                        pass
                _flow_src = f"FTShare TOP50 (akshare失败:{str(_e1)[:40]})"
        for item in final_ranking[:10]:  # 只查TOP10, 控制性能
            code = item[8]
            clean = code[2:] if code[:2].isalpha() else code
            inflow = flow_map.get(clean, 0)
            if inflow > 0:
                bonus = min(10.0, inflow / 1000000.0)  # 主力流入: 每百万+1分, 封顶+10
            else:
                bonus = max(-5.0, inflow / 2000000.0)  # 主力流出: 每两百万-1分, 封顶-5
            if inflow != 0 or clean in flow_map:
                cap_flows[code] = (bonus, inflow, 0, len(flow_map))
        if cap_flows:
            try:
                new_ranking = []
                for item in final_ranking:
                    code = item[8]
                    if code in cap_flows:
                        bonus, inflow, rank, total = cap_flows[code]
                        item = list(item)
                        item[0] = round(min(100.0, item[0] + bonus), 1)  # final分加资金流加权, clamp≤100
                        new_ranking.append(tuple(item))
                    else:
                        new_ranking.append(item)
                final_ranking = new_ranking
                final_ranking.sort(key=lambda x: -x[0])
                print(f"  💰 主力资金流加权完成: {len(cap_flows)}只 ({_flow_src})")
            except Exception as e:
                print(f"  💰 资金流加权跳过: {e}")
        else:
            print(f"  💰 主力资金流加权: 候选不在覆盖范围 ({_flow_src}, 共{len(flow_map)}只)")
    except Exception as _flow_e:  # P0修复(2026-09-25): 补回 Layer6 try 的 4空格 except 收尾
        print(f"  💰 主力资金流加权异常跳过: {_flow_e}")

    # ── Layer 7: 技术形态识别加分 (a-share-pattern-recognition skill v1.0) ──
    # 评分映射: W底确认+15/杯柄突破+12/牛旗+10/三角收敛+8/V型反转+8
    # 加分按形态类型分档 (与映射语义对齐, 不依赖detect原始score尺度):
    #   高分形态(W底/杯柄) → +5; 中分形态(牛旗) → +3; 低分形态(三角/V反) → +2
    #   多形态共存取最高分不叠加 (identify_all_patterns 已返回最高分形态)
    try:
        from pattern_recognition import identify_all_patterns
        from core.pipeline.tdx_core import get_tdx_data as _get_tdx_data
        _PATTERN_BONUS = {"W底": 5, "杯柄": 5, "牛旗": 3, "三角收敛": 2, "V型反转": 2}
        pat_scored = 0
        new_ranking = []
        for item in final_ranking[:15]:  # 只查TOP15, 控制性能 (每只120根TDX本地数据~0.01s)
            code = item[8]
            try:
                recs = _get_tdx_data(code, 120)
                if recs:
                    pr = identify_all_patterns(recs)
                    if pr["found"]:
                        bonus = _PATTERN_BONUS.get(pr["pattern"], 2)
                        # P2 冲突抑制 (2026-08-07): 资金大幅流出时形态加分减半
                        # 主力净流出>5亿: 形态加分封顶+1; >2亿: 减半 (防主力出货+技术骗线)
                        _clean7 = code[2:] if code[:2].isalpha() else code
                        _inflow7 = flow_map.get(_clean7, 0)
                        _suppress = ""
                        if _inflow7 < -5e8:
                            bonus = min(bonus, 1)
                            _suppress = "⚠️流出>5亿"
                        elif _inflow7 < -2e8:
                            bonus = max(1, bonus // 2)
                            _suppress = "⚠️流出>2亿减半"
                        pat_scored += 1
                        item = list(item)
                        item[0] = round(min(100.0, item[0] + bonus), 1)  # final分加形态加分, clamp≤100
                        _sig = f"📐{pr['pattern']}+{bonus}分"
                        if _suppress:
                            _sig += f"({_suppress})"
                        item[19] = list(item[19]) + [_sig]
                        new_ranking.append(tuple(item))
                        continue
            except Exception:
                pass
            new_ranking.append(item)
        if pat_scored:
            final_ranking = new_ranking
            final_ranking.sort(key=lambda x: -x[0])
            print(f"  📐 技术形态识别加分完成: {pat_scored}只 (W底/杯柄/牛旗/三角/V反)")
    except Exception as e:
        print(f"  📐 形态识别跳过: {e}")

    # ═══════════════════════════════════════════════════════════
    #  P2-C 轮动序列风控 (T-20260815-003 总管规格, 后处理不拆主流程)
    #  R1 行业避让降权 ×0.8 → R2 行业黑天鹅排除 → R3 题材上限 3 只
    #  容错: 缺行业热度/缺口数据 → 自动降级跳对应规则, 不抛错
    # ═══════════════════════════════════════════════════════════
    try:
        from core.ops.sequence_risk import apply_sequence_risk

        # 1. 把 tuple (final, sc_zonghe, ..., code, name, industry, ...) 转 dict
        def _to_dict(item):
            return {
                "final_score": item[0],
                "_sc_zonghe": item[1],
                "_sc_quancang": item[2],
                "_risk": item[3],
                "_confidence": item[4],
                "_pass_risk": item[5],
                "_heat_bonus": item[6],
                "_heat_desc": item[7],
                "code": item[8],
                "name": item[9],
                "industry": item[10],
                "_sigs_zh": item[11],
                "_sigs_qc": item[12],
                "_gap_score": item[13],
                "_gap_desc": item[14],
                "_gap_sigs": item[15],
                "_nb_score": item[16],
                "_nb_desc": item[17],
                "_nb_sigs": item[18],
                "_extra_sigs": item[19],
                # 保留原 tuple 用于还原
                "_orig_tuple": item,
            }

        # 2. 取行业热度
        try:
            _heat_rank = load_industry_heat()
        except Exception:
            _heat_rank = {}

        # 3. 构造 stock_gap_pcts — T-20260815-003 §R2 实盘数据接入:
        #    优先级: gap_pool (gap_channel 事件驱动, 已剔除权) > tdx_core.get_last_bar_gap_pct (原始日线兜底)
        #    R2 detect侧会跳过 None/非数值, 只对 ≤-15% 的向下跳空行业计数拉黑.
        #    历史上这里 gap_pct=None 硬编码 = R2 恒死代码 (总管审计 2026-08-17 已修复)
        try:
            from core.pipeline.tdx_core import get_last_bar_gap_pct
        except Exception:
            get_last_bar_gap_pct = lambda _: None  # 降级跳过R2
        _gap_data = []
        for item in final_ranking:
            _code = item[8]
            _ind = item[10]
            # 第一层: gap_channel 独立通道已经算好的真 gap_pct (过滤了除权假缺口,优先用)
            _gp = None
            if isinstance(gap_pool, dict) and _code in gap_pool:
                try:
                    _v = gap_pool[_code].get("gap_pct")
                    if isinstance(_v, (int, float)):
                        _gp = round(float(_v), 1)
                except Exception:
                    _gp = None
            # 第二层: 用 recs_dict 原始日线兜底 (未除权, 但 ≥2 只同行业同方向除权 ≈ 0)
            if _gp is None and isinstance(recs_dict, dict) and _code in recs_dict:
                _gp = get_last_bar_gap_pct(recs_dict[_code])
            _gap_data.append({
                "code": _code,
                "industry": _ind,
                "gap_pct": _gp,
            })

        # 4. 调用 apply_sequence_risk (全部缺输入就跳 R1/R2, 但仍跑 R3 题材上限)
        cands_dict = [_to_dict(it) for it in final_ranking]
        new_dict_list, _audit = apply_sequence_risk(
            cands_dict,
            industry_heat_rank=_heat_rank,
            stock_gap_pcts=_gap_data,
            write_log=True,
        )

        # 5. 还原为 tuple: 顺序 = dict 列表顺序; score 改了取 final_score 覆盖原位置0
        _orig_tuples = []
        for d in new_dict_list:
            ot = d["_orig_tuple"]
            # 如被 R1 降权 → 新的 final_score 覆盖 tuple 第 0 位
            new_score = d.get("final_score", ot[0])
            if new_score != ot[0] and isinstance(new_score, (int, float)):
                new_tup = list(ot)
                new_tup[0] = type(ot[0])(new_score) if not isinstance(ot[0], float) else round(float(new_score), 4)
                # 保留 list 字段原样
                ot = tuple(new_tup)
            _orig_tuples.append(ot)

        if _orig_tuples:
            n_orig = len(final_ranking)
            final_ranking = _orig_tuples
            # 还原后按 new_score (tuple[0]) 再排一次序 (保持按分数降序惯例)
            final_ranking.sort(key=lambda x: -x[0])
            n_new = len(final_ranking)
            n_r1 = len(_audit.get("R1", {}).get("avoided", []))
            n_r2 = len(_audit.get("R2", {}).get("removed", []))
            n_r3_count = sum(v[1] for v in _audit.get("R3", {}).get("topic_counts", {}).values()) if isinstance(_audit.get("R3"), dict) else 0
            log_file = _audit.get("log_file", "")
            summary = []
            if n_r1:
                summary.append(f"R1避让降权{n_r1}只")
            if n_r2:
                summary.append(f"R2黑天鹅排除{n_r2}只")
            if n_r3_count:
                summary.append(f"R3限额外移除{n_r3_count}只")
            if not summary:
                summary.append("无动作(全行业OK)")
            print(f"  🔒 P2-C 序列风控: {' | '.join(summary)} | 输入{n_orig}只→输出{n_new}只 | 日志: {log_file or '未写'}")
    except Exception as _seq_e:
        print(f"  🔒 P2-C 序列风控跳过(不阻断主流程): {_seq_e}")

    # ── v8.1 断层池名额规则 (事件驱动优先, 常规评分补充) ──
    # 断层池≥2只: 断层取2 + 常规取3; 断层池1只: 断层取1 + 常规取4
    display_order = final_ranking
    if gap_pool:
        gap_codes = [c for c in gap_pool if any(x[8] == c for x in final_ranking)]
        if len(gap_codes) >= 2:
            gap_items = [x for x in final_ranking if x[8] in gap_pool][:2]
            non_gap = [x for x in final_ranking if x[8] not in gap_pool][:3]
            display_order = gap_items + non_gap
            print(f"  🎯 断层池优先: 断层{len(gap_items)}只 + 常规{len(non_gap)}只")
        elif len(gap_codes) == 1:
            gap_items = [x for x in final_ranking if x[8] in gap_pool][:1]
            non_gap = [x for x in final_ranking if x[8] not in gap_pool][:4]
            display_order = gap_items + non_gap
            print(f"  🎯 断层池优先: 断层{len(gap_items)}只 + 常规{len(non_gap)}只")

    # ── P1-7 区分度告警 (2026-08-09 单票轮动对齐: abort→warning, 卖出必出票不阻断) ──
    # 原P1-7(8/8) TOP5方差<3.0 abort — 与"卖出后肯定要出票交易"冲突, 改警告不阻断
    import statistics as _stat_p17
    import sys as _sys_p17
    _top5_scores = [x[0] for x in final_ranking[:5]]
    _disc = _stat_p17.pstdev(_top5_scores) if len(_top5_scores) >= 3 else 0
    if _disc < 3.0:
        print("  ⚠️ 区分度提示: TOP5方差%.2f < 3.0 (评分同质, 仅供参考)" % _disc)

    # ── 输出结果 ──
    print("\n" + "=" * 90)
    print("  🏆 五重过滤推荐排名 (Top %d)" % min(top_n, len(display_order)))
    print("  [综合×断层×北向×风控×板块] | 市场:%s | 策略:%s" % (
        market_label, primary_strategy))
    print("=" * 90)
    print("  %-4s %-10s %-7s %-8s %4s/%4s %4s %4s %5s %4s %-12s" % (
        "#", "代码", "名称", "行业", "综合", "全仓", "断层", "北向",
        "财务", "通过", "信号"))
    print("  " + "-" * 100)

    shown = 0
    for idx, item in enumerate(display_order, 1):
        (final, sc_zh, sc_qc, risk, confidence, pass_risk,
         heat_bonus, heat_desc, code, name, industry,
         sigs_zh, sigs_qc, gap_score, gap_desc, gap_sigs,
         nb_score, nb_desc, nb_sigs, extra_sigs) = item

        if shown >= top_n:
            break
        shown += 1  # 修复: 此前 shown 从不递增, --top N 失效(打印全部)

        risk_flag = ""
        if risk > 15:
            risk_flag = "🔴"
        elif risk > 5:
            risk_flag = "🟡"
        elif risk <= 0:
            risk_flag = "🟢"

        pass_flag = "✅" if pass_risk else "⚠️"
        heat_flag = heat_desc[:6] if heat_desc else ""
        # 财务评分标签
        clean_code = code[2:] if code[:2].isalpha() else code
        fin_r = fin_scores.get(clean_code, {})
        fin_b = max(-10, min(20, int(fin_r.get("financial_health", 0) / 2) + fin_r.get("fraud_penalty", 0)))
        fin_label = "%+d" % fin_b if fin_b != 0 else " 0"
        # P1-13: 缺数据显示联动 — 标记"缺数据"而非笼统"劣质"(用户可见, 区分真劣质)
        if (not fin_r or fin_r.get("data_status") == "missing") and "🔴缺数据" not in extra_sigs:
            extra_sigs.append("🔴缺数据")
        extra_tag = " ".join(extra_sigs[:4]) if extra_sigs else "-"

        print("  %-4s %-10s %-7s %-8s %4d/%4d %4d %4d %5s %4s %-12s" % (
            "#%d" % idx, code, name[:6], industry,
            sc_zh, sc_qc, gap_score, nb_score,
            fin_label, pass_flag, extra_tag))

        # PATCH-1: 得分链透明化 (每行显示final + 完整加分链)
        if debug:
            _temporal = 0.0
            for _s in sigs_zh:
                if "时序" in _s and "(" in _s and ")" in _s:
                    try:
                        _temporal = float(_s.split("时序")[1].split(")")[0])
                    except Exception:
                        pass
            _ft_bonus = cap_flows.get(code, (0, 0, 0, 0))[0] if cap_flows else 0
            _fin_pen = fin_r.get("fraud_penalty", 0) or 0
            _fatal_now = fin_r.get("fraud_fatal", False)   # 修复: 显示循环重新读取(原用循环1残留fin_fatal)
            _veto = 20 if _fatal_now else 0
            print("    └─ final:%6.1f | 基础:%d 北向:%+d 资金:%+.1f 断层:%+d 时序:%+.1f 舞弊:%+d 否决:%+d 板块:%+d" % (
                final, sc_zh, nb_score, _ft_bonus, gap_score, _temporal, _fin_pen, -_veto, heat_bonus))

        if debug:
            # 关键信号展示
            gap_display = " | ".join(gap_sigs[:2]) if gap_sigs else ""
            nb_display = " | ".join(nb_sigs[:2]) if nb_sigs else ""
            key_sigs = [s for s in sigs_zh if "✅" in s or "🔴" in s or "⚠️" in s][:3]
            
            print("  %-17s%5s" % ("", "技术:"), ", ".join(key_sigs) if key_sigs else "-")
            if gap_display:
                print("  %-17s%5s" % ("", "断层:"), gap_display)
            if nb_display:
                print("  %-17s%5s" % ("", "北向:"), nb_display)
            # 财务信号
            fin_health_sigs = fin_r.get("health_signals", [])
            fin_fraud_sigs = fin_r.get("fraud_signals", [])
            if fin_health_sigs:
                print("  %-17s%5s" % ("", "财务健康:"), " | ".join(fin_health_sigs[:3]))
            if fin_fraud_sigs:
                print("  %-17s%5s" % ("", "舞弊信号:"), " | ".join(fin_fraud_sigs[:3]))
            print("")

    # 风控剔除
    # 修复 M4 回归: M4 删除了 passed/failed 硬分档变量，此处引用会 NameError
    _failed_list = [a for a in analyzed if not a[5]]
    if _failed_list and not debug:
        print("\n  ⚠️ 以下股票因风控(追高/超买)被剔除（但有断层/北向信号仍可关注）:")
        for item in _failed_list[:5]:
            sc_zh, sc_qc, risk = item[1], item[2], item[3]
            gap_s = item[13]
            nb_s = item[16]
            extra = " | ".join(item[19])
            print("    %s %s: 综合%d→全仓%d(风险%+d) %s" % (
                item[8], item[9][:6], sc_zh, sc_qc, risk,
                " [%s]" % extra if extra else ""))

    # ── P2 (2026-08-12): 落盘当日评分排名TOP30 (模拟轮回TOP10开仓 + 分层跟踪数据源) ──
    try:
        _rank_date = datetime.now().strftime("%Y-%m-%d")
        _rank_path = os.path.join(PROJECT, "logs", "rank_%s.json" % _rank_date)
        _rank_items = []
        for _i, _it in enumerate(final_ranking[:30]):
            _rank_items.append({"rank": _i + 1, "code": _it[8], "name": _it[9],
                                "final_score": round(_it[0], 1), "score_zonghe": round(_it[1], 1)})
        if _rank_items:
            from core.pipeline.atomic_json import atomic_dump
            atomic_dump({"date": _rank_date, "count": len(_rank_items), "items": _rank_items}, _rank_path)
            print("  📊 评分排名已落盘: %s (%d只)" % (_rank_path, len(_rank_items)))
    except Exception as _rank_e:
        print("  ⚠️ 评分排名落盘失败: %s" % _rank_e, file=sys.stderr)

    # ── 自动记录推荐(跨进程锁读-改-写; R3: 原裸读-改-写+atomic_dump 与 cron/手动并发会丢记录) ──
    # 2026-08-13: dry_run=True 跳过落库 (验证/调试不污染 trade_log)
    # v36优化: MIN_SCORE=22, COOLDOWN=5天
    print(f"  ⚙️ v36配置: 评分≥{MIN_SCORE}, 冷却{COOLDOWN_DAYS}天")
    if final_ranking and final_ranking[0][5] and not dry_run:
        best = final_ranking[0]

        # P0-2026-08-23 实盘门控接线: 弱市<40分禁落库推荐 (回测已验证10日超额转正, 实盘接线补齐)
        # 老五实锤: 此前 config.json 写死 market_gate 但_picker 落库前从不读, 门控"死接线"
        try:
            _cfg = json.load(open(os.path.join(PROJECT, "config.json"), encoding="utf-8"))
            _mg = _cfg.get("market_gate", {})
            _weak_thr = _mg.get("weak_threshold", 40)
            _skip_weak = _mg.get("skip_when_weak", True)
            if _skip_weak and isinstance(market_score, (int, float)) and market_score < _weak_thr:
                print(f"  🛑 弱市门控: 市场分{market_score}<{_weak_thr}, 跳过推荐落库 "
                      f"(策略{primary_strategy}/{market_label})")
                return final_ranking, {
                    "primary": primary_strategy, "weights": strategy_weights,
                    "position": pos_advice, "position_ratio": pos_ratio,
                    "market_score": market_score, "market_label": market_label,
                    "gate_block": "weak_market",
                }, daily_inds_dict
        except Exception as _ge:
            print(f"  ⚠️ 弱市门控检查失败(回退放行): {_ge}", file=sys.stderr)

        today = datetime.now().strftime("%Y-%m-%d")  # P0-2修复: 提前定义, 供下方影子账户落库闭包捕获(原 L1279 滞后定义→NameError 被 except 吞掉)

        # P1-2 修复: 追高硬门禁 (与回测/orchestrator 闭环一致, 老五审查打回项)。
        # 信号日涨幅>阈值 且非断层豁免 → 不落库(顺延); 断层(gap_score>0)按系统既有豁免保留。
        # 2026-09-25 (体检P1-1): 4.0 硬编码 → 引用 risk_rules.CHASE_BAN_PCT 权威源(已统一为4%)
        try:
            from risk_rules import signal_day_chg as _sdc, CHASE_BAN_PCT as _chase_pct
            _best_recs = recs_dict.get(best[8]) or []
            _sd = _sdc(_best_recs, today) if _best_recs else None
            _gap_ok = (best[13] if len(best) > 13 else 0) > 0
            if _sd and _sd[1] is not None and _sd[1] > _chase_pct and not _gap_ok:
                print(f"  🛑 追高硬门禁: {best[8]} 信号日涨幅{_sd[1]:+.1f}% > {_chase_pct}% (非断层), 跳过推荐落库")
                return final_ranking, {
                    "primary": primary_strategy, "weights": strategy_weights,
                    "position": pos_advice, "position_ratio": pos_ratio,
                    "market_score": market_score, "market_label": market_label,
                    "gate_block": "chase_high",
                }, daily_inds_dict
            # 接飞刀禁买 (2026-09-25 优化, 与回测 knife_ban_pct 对齐):
            # 信号日暴跌(跌幅<-5%)且非断层 → 不落库。诊断: 新金路-5.3%大跌日被推荐后又跌10%
            _knife_pct = 5.0
            if _sd and _sd[1] is not None and _sd[1] < -_knife_pct and not _gap_ok:
                print(f"  🛑 接飞刀禁买: {best[8]} 信号日跌幅{_sd[1]:+.1f}% < -{_knife_pct}% (非断层), 跳过推荐落库")
                return final_ranking, {
                    "primary": primary_strategy, "weights": strategy_weights,
                    "position": pos_advice, "position_ratio": pos_ratio,
                    "market_score": market_score, "market_label": market_label,
                    "gate_block": "knife_ban",
                }, daily_inds_dict
        except Exception as _ce:
            print(f"  ⚠️ 追高门禁检查失败(回退放行): {_ce}", file=sys.stderr)

        # P1: 评分门槛检查（v36: 已降至22分，回测验证+22.13%收益）
        if best[1] < MIN_SCORE:
            print(f"  ⚠️ TOP1综合分{best[1]:.1f} < {MIN_SCORE}门槛, 跳过推荐落库")
            # P0-2026-08-23 影子账户(老五方案C1): 低分跳过日落SHADOW条目
            # 供 e_variant_backfill 自动回填 signal_return_pct(固定5日口径), 积累配对样本
            try:
                from core.pipeline.atomic_json import update_json as _s_update_json
                _s_code, _s_name = best[8], (best[9] if len(best) > 9 else "")

                def _s_mutate(log):
                    if not isinstance(log, dict):
                        log = {"recommendations": []}
                    log.setdefault("recommendations", [])
                    for _r in log["recommendations"]:
                        if _r.get("date") == today and _r.get("type") == "variant_reference" and _r.get("variant") == "SHADOW":
                            return log  # 同日同 variant 去重
                    log["recommendations"].append({
                        "type": "variant_reference", "variant": "SHADOW",
                        "date": today, "code": _s_code, "name": _s_name,
                        "score": round(best[1], 1),
                        "market_label": market_label,
                        "source": os.environ.get("PICK_SOURCE", "manual"),
                        "note": "影子账户: TOP1<门槛跳过日仍落库, 供回测口径校准",
                    })
                    return log

                _s_update_json(os.path.join(PROJECT, "data", "trade_log.json"), _s_mutate,
                               default={"recommendations": []})
                print(f"  📋 影子条目已落库: {_s_code} {_s_name} (分{best[1]:.1f})")
            except Exception as _se:
                print(f"  ⚠️ 影子落库: {_se}", file=sys.stderr)
            return final_ranking, {
                "primary": primary_strategy, "weights": strategy_weights,
                "position": pos_advice, "position_ratio": pos_ratio,
                "market_score": market_score, "market_label": market_label,
            }, daily_inds_dict
        log_path = os.path.join(PROJECT, "data", "trade_log.json")
        # 修复 H1: 用 best 自己的财务数据重算（此前复用展示循环残留变量
        # fin_b/fin_fatal，可能记的是别的股票）
        _best_cc = best[8][2:] if best[8][:2].isalpha() else best[8]
        _best_fin = fin_scores.get(_best_cc, {})
        _best_fin_b = max(-10, min(20, int(_best_fin.get("financial_health", 0) / 2)
                                    + _best_fin.get("fraud_penalty", 0)))
        _best_fin_fatal = _best_fin.get("fraud_fatal", False)
        # 修复 M1: 用 best 最新收盘价生成交易计划（此前 entry_price=0，
        # 止损/止盈/仓位全部从 0 推导，落库失真）
        _ref_recs = recs_dict.get(best[8]) or []
        _ref_price = _ref_recs[-1]["close"] if _ref_recs else 0
        # 修复 M9: _ref_price<=0 时跳过 plan 落库（否则产生全 0 伪兜底数据）
        if _ref_price <= 0:
            print("  ⚠️ 无有效参考价(%s)，跳过推荐落库" % best[8], file=sys.stderr)
            return final_ranking, {
                "primary": primary_strategy, "weights": strategy_weights,
                "position": pos_advice, "position_ratio": pos_ratio,
                "market_score": market_score, "market_label": market_label,
            }, daily_inds_dict
        # P0-2026-08-23 双脑审查建议: 资金匹配度过滤 — 推荐最小买入金额>可用现金时排除
        _cash = _load_available_cash()
        _min_buy = _ref_price * 100  # A股一手=100股
        if _min_buy > _cash:
            print(f"  💰 资金匹配门: 一手需{_min_buy:.0f}元 > 可用现金{_cash:.0f}元, 跳过推荐落库")
            return final_ranking, {
                "primary": primary_strategy, "weights": strategy_weights,
                "position": pos_advice, "position_ratio": pos_ratio,
                "market_score": market_score, "market_label": market_label,
            }, daily_inds_dict
        # P0修复(2026-09-05): 动态趋势检测，替换硬编码trend="up"
        # 根因: TREND_TP_LADDER硬编码导致下降/震荡趋势止盈过宽(差距7pp)
        _stock_trend = "up"  # 默认值
        try:
            from risk_rules import detect_stock_trend
            _best_cc = best[8][2:] if best[8][:2].isalpha() else best[8]
            _best_inds = daily_inds_dict.get(_best_cc, {})
            _ma5_val = _best_inds.get('ma5', 0)
            _ma20_val = _best_inds.get('ma20', 0)
            _ma60_val = _best_inds.get('ma60', _ma20_val * 1.1)
            closes_list = [r["close"] for r in _ref_recs] if _ref_recs else []
            if len(closes_list) >= 20:
                _stock_trend = detect_stock_trend(closes_list,
                                                  ma5=_ma5_val, ma20=_ma20_val, ma60=_ma60_val)
            print(f"  📈 检测趋势: {_stock_trend} (使用{len(closes_list)}日数据)")
        except Exception as _trend_e:
            print(f"  ⚠️ 趋势检测失败，使用默认'up': {_trend_e}")
        
        plan = generate_trade_plan(
            entry_price=_ref_price,  # 修复 M1: 真实参考价（已确保 >0）
            strategy=primary_strategy,
            market_score=market_score,
            market_label=market_label,
            gap_score=best[13],
            nb_score=best[16],
            confidence="medium",
            capital=_load_available_cash(),
            reasons="",
            trend=_stock_trend,  # 动态趋势检测(2026-09-05 P0修复)
        )
        # Q2 (老五审查): 买卖理由 — 落库后随 trade_log 展示, 供总管/老大审阅
        plan["reasons"] = ("选股理由: 综合分%.1f/决赛分%.1f, 断层分%.1f, 北向分%.1f, 市场=%s; "
                           "风控: 移动止损-8%%随价上移(超+10%%启动), TP1+%.1f%%/TP2+%.1f%%; 风险回报1:%.2f"
                           ) % (best[1], best[0], best[13], best[16], market_label,
                                plan["tp1_pct"], plan["tp2_pct"], plan["risk_reward_tp2"])

        # raw_score: no_ms 口径 (对齐回测/淘汰机制, docs/raw_score_definition.md)
        # score_zonghe 是 with_ms 展示口径 — 弱市切抄底权重会压分(31-37), 不可用于 raw≥85 计数
        # 仅对 best 1 只重算 (~5ms), 只加字段不改推荐逻辑; 异常回退 score_zonghe
        # (2026-08-09 jcode 审查: 原改动落在 hermes-home 遗留副本, 实际运行版缺失 → 移植)
        _best_raw = best[1]
        try:
            # P0-2026-09-25 修复 (WorkBuddy 体检 P0-4):
            # ① ref_recs → _ref_recs (原拼写错误致 NameError)
            # ② build_cross_rank/cross_ranks 从未定义 → 移除, cross_rank 传 None
            #    (重算口径 = 无市场状态 + 无截面排名, 与 raw_score 定义一致)
            if _ref_recs and len(_ref_recs) >= 60:
                _raw_inds = compute_indicators(_ref_recs)
                _raw_weekly = compute_weekly_indicators(_ref_recs)
                _raw_sc, _, _ = score_stock(_raw_inds, _raw_weekly, strategy=strategy_zonghe, records=_ref_recs,
                                            cross_rank=None, market_state=None)
                if _raw_sc and _raw_sc > 0:
                    _best_raw = _raw_sc
        except Exception as _raw_e:
            print("  ⚠️ raw_score 重算失败, 回退 score_zonghe: %s" % _raw_e, file=sys.stderr)

        def _make_entry():
            return {
                "type": "recommendation",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "date": today,
                "code": best[8],
                "name": best[9],
                "score_zonghe": best[1],
                "raw_score": _best_raw,   # no_ms 口径 (raw≥85 淘汰机制依据, 2026-08-09)
                "final_score": round(best[0], 1),   # PATCH-3: v8.1新增final分 (含所有加分链)
                "score_quancang": best[2],
                "earnings_gap": best[13],
                "financial_health": _best_fin_b,
                "fraud_fatal": _best_fin_fatal,
                "risk": best[3],
                "strategy": primary_strategy,
                "market_score": market_score,
                "market_label": market_label,
                "entry_price": _ref_price,
                "stop_loss": plan["stop_loss"],
                "stop_loss_pct": plan["stop_loss_pct"],
                "tp1": plan["tp1"],
                "tp1_pct": plan["tp1_pct"],
                "tp2": plan["tp2"],
                "tp2_pct": plan["tp2_pct"],
                "position_size": plan["position_size"],
                "position_value": plan["position_value"],
                "risk_reward": plan["risk_reward_tp2"],
                "trailing": plan["trailing"],
                "price_template": plan["price_template"],
                "reasons": plan["reasons"],
                "followed": None,
                "buy_date": None,
                "buy_price": None,
                "buy_shares": None,
                "actual_return_pct": None,
                "entry_score": best[0],  # 入场时评分，用于信号衰减检测
            }

        recorded = False
        try:
            from core.pipeline.atomic_json import update_json

            def mutate(log):
                if not isinstance(log, dict):
                    log = {"recommendations": [], "buys": [], "sells": [], "meta": {}}
                log.setdefault("recommendations", [])
                entry = _make_entry()
                # 2026-08-07 修复调试污染: 加 source 标记 + 当天覆盖(保护已执行记录)
                # source: cron(cron自动) / manual(手动/调试); 默认 manual
                entry["source"] = os.environ.get("PICK_SOURCE", "manual")
                today_recs = [r for r in log["recommendations"] if r.get("date") == entry["date"]]
                executed = [r for r in today_recs if r.get("followed") or r.get("buy_date")]
                if executed:
                    return log  # 当天已有执行记录(买入), 保留不动, 避免覆盖丢操作状态
                log["recommendations"] = [r for r in log["recommendations"]
                                          if not (r.get("date") == entry["date"]
                                                  and r.get("type", "recommendation") == "recommendation")]
                log["recommendations"].append(entry)
                nonlocal recorded
                recorded = True
                return log

            update_json(log_path, mutate, default={"recommendations": [], "buys": [], "sells": [], "meta": {}})
        except Exception:
            # 兜底: 旧读-改-写 + 原子写(不因锁工具异常中断)
            try:
                log = json.load(open(log_path, encoding="utf-8"))
            except Exception:
                log = {"recommendations": [], "buys": [], "sells": [], "meta": {}}
            if not isinstance(log, dict):
                log = {"recommendations": [], "buys": [], "sells": [], "meta": {}}
            log.setdefault("recommendations", [])
            _fb_entry = _make_entry()
            _fb_entry["source"] = os.environ.get("PICK_SOURCE", "manual")
            _fb_today = [r for r in log["recommendations"] if r.get("date") == _fb_entry["date"]]
            _fb_executed = [r for r in _fb_today if r.get("followed") or r.get("buy_date")]
            if not _fb_executed:
                log["recommendations"] = [r for r in log["recommendations"] if r.get("date") != _fb_entry["date"]]
                log["recommendations"].append(_fb_entry)
                try:
                    from core.pipeline.atomic_json import atomic_dump
                    atomic_dump(log, log_path)
                except Exception as _tle:
                    # P0-1修复: trade_log.json 是交易数据, 绝不再退到裸open("w")并发覆盖
                    # 放弃本次写入 → 下一轮cron再重试即可, 并发覆盖的破坏性>漏写一次
                    import logging as _lg
                    _lg.getLogger("integrated_picker").warning(
                        "【P0-1修复】trade_log.json 兜底写也失败(放弃, 避免并发覆盖): %s", _tle, exc_info=True)
                    recorded = False
                else:
                    recorded = recorded or True
        # ── E 变体参考 (2026-08-21 双系统合并: 从 orchestrator.run_daily 迁入) ──
        # E 是重排选择器: min(chg20 + 1.25*max_ret5), 非打分器 — 展示 E 变体 TOP1 作观察期参考
        # 口径: 候选池 Top15, 与回测 top30 不同, 仅作参考; 持仓/空仓都落库 (同日同 variant 去重)
        try:
            from core.pipeline.tdx_core import get_tdx_data as _e_get_tdx
            _e_best = None
            for _cand in final_ranking[:15]:
                _cc = _cand[8]
                try:
                    _erecs = _e_get_tdx(_cc, 60)
                except Exception:
                    _erecs = None
                if not _erecs or len(_erecs) < 30:
                    continue
                _einds = compute_indicators(_erecs)
                if not _einds:
                    continue
                _e_score = (_einds.get("chg20", 0) or 0) + 1.25 * (_einds.get("max_ret5", 0) or 0)
                if _e_best is None or _e_score < _e_best[0]:
                    _e_best = (_e_score, _cc, _cand[9] if len(_cand) > 9 else "")
            if _e_best:
                _e_score, _e_code, _e_name = _e_best
                _e_same = ("✅一致" if _e_code == best[8] else "🔄不同")
                print(f"  🔬 E变体参考(反转+MAX回避): {_e_code} {_e_name} (E分{_e_score:+.1f}) | 与现状: {_e_same}")
                try:
                    from core.pipeline.atomic_json import update_json as _e_update_json

                    def _e_mutate(log):
                        if not isinstance(log, dict):
                            log = {"recommendations": []}
                        log.setdefault("recommendations", [])
                        for _r in log["recommendations"]:
                            if _r.get("date") == today and _r.get("type") == "variant_reference" and _r.get("variant") == "E":
                                return log  # 同日同 variant 去重
                        log["recommendations"].append({
                            "type": "variant_reference", "variant": "E",
                            "date": today, "code": _e_code, "name": _e_name,
                            "e_score": round(_e_score, 1),
                            "market_label": market_label,
                            "source": os.environ.get("PICK_SOURCE", "manual"),
                            "note": "E变体参考(反转+MAX回避), 不替换现状推荐",
                        })
                        return log

                    _e_update_json(os.path.join(PROJECT, "data", "trade_log.json"), _e_mutate,
                                   default={"recommendations": []})
                except Exception as _le:
                    print(f"  ⚠️ E变体落库: {_le}", file=sys.stderr)
        except Exception as _ee:
            print(f"  ⚠️ E变体参考: {_ee}", file=sys.stderr)

        if recorded:
            print("\n  📝 已记录推荐(含交易计划)到 trade_log.json")
        else:
            print("\n  📝 今日推荐已存在，跳过重复记录")

        # ── P0-2: 形态分析注入 (仅对TOP5推荐，dry_run保护) ──
        if not dry_run:
            try:
                from core.pipeline.atomic_json import update_json as _p_update_json
                _log_path = os.path.join(PROJECT, "data", "trade_log.json")

                def _pattern_mutate(log):
                    if not isinstance(log, dict):
                        return log
                    recs = log.get("recommendations", [])
                    if not recs:
                        return log
                    # P0-3 修复：按final_score降序取top5（而非时间最后5条）
                    sorted_recs = sorted(recs, key=lambda x: x.get("final_score", 0), reverse=True)
                    top5 = sorted_recs[:5] if len(sorted_recs) >= 5 else sorted_recs
                    enriched = 0
                    for rec in top5:
                        code = rec.get("code", "")
                        if not code or "pattern_analysis" in rec:
                            continue
                        # 导入形态分析函数
                        try:
                            from scripts.night_integrate import get_pattern_analysis
                            analysis = get_pattern_analysis(code)
                            if analysis:
                                rec["pattern_analysis"] = analysis
                                enriched += 1
                        except Exception as _pa_e:
                            print(f"  ⚠️ 形态分析失败 {code}: {_pa_e}")
                    if enriched > 0:
                        print(f"  🔍 形态分析已注入: {enriched}只股票")
                    return log

                _p_update_json(_log_path, _pattern_mutate, default={"recommendations": [], "buys": [], "sells": [], "meta": {}})
            except Exception as _pat_e:
                print(f"  ⚠️ 形态分析注入失败(不影响选股): {_pat_e}")
    elif final_ranking and not dry_run:
        print("\n  ⚠️ 最优标的未通过全仓风控，不记录推荐")
    elif final_ranking and dry_run:
        print("\n  ℹ️ dry-run 模式: 跳过推荐落库 (非风控原因)")

    # ── P0 (2026-08-07): 写过滤日志 (供盘后复盘"错过分析") ──
    if reject_log:
        try:
            _log_dir = os.path.join(PROJECT, "logs")
            os.makedirs(_log_dir, exist_ok=True)
            _rej_path = os.path.join(_log_dir, "reject_%s.json" % datetime.now().strftime("%Y-%m-%d"))
            _rej_data = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "market_score": market_score,
                "market_label": market_label,
                "fin_threshold": fin_threshold,
                "count": len(reject_log),
                "items": reject_log,
            }
            from core.pipeline.atomic_json import atomic_dump
            atomic_dump(_rej_data, _rej_path)
            print("  🚫 过滤日志已写: %s (%d条)" % (_rej_path, len(reject_log)))
        except Exception as _rej_e:
            print("  ⚠️ 过滤日志写入失败: %s" % _rej_e)

    # ── 市场概要 ──
    print("\n" + "=" * 68)
    print("  📊 市场量化评分: %d/100 — %s" % (market_score, market_label))
    for dim, info in sub_scores.items():
        sigs = " | ".join(info["signals"]) if info["signals"] else "中性"
        print("    %-8s ➤ %3d分  %s" % (dim, info["score"], sigs))
    top3 = sorted(strategy_weights.items(), key=lambda x: -x[1])[:3]
    print("  🎯 动态策略: %s ➤ 仓位%s(%.0f%%)" % (
        ", ".join("%s(%.0f%%)" % (n, w*100) for n, w in top3),
        pos_advice, pos_ratio * 100))
    
    print("\n" + "=" * 68)
    print("  💡 三层过滤: 综合评分 × 断层评分 × 财务健康")
    print("               × 全仓风控 × 板块轮动")
    print("  市场量化: 5维度×动态权重 → 自动适配策略与仓位")
    print("  基本面: 五维财务评分(ROE/毛利率/负债率/现金流/成长) + 舞弊检测")
    print("=" * 68)

    # ── 转换策略权重为可返回的配置 ──
    strategy_config = {
        "primary": primary_strategy,
        "weights": strategy_weights,
        "position": pos_advice,
        "position_ratio": pos_ratio,
        "market_score": market_score,
        "market_label": market_label,
    }
    
    return final_ranking, strategy_config, daily_inds_dict


def dual_pool_gate(results, top_n=5):
    """P1-3 双池硬门(2026-09-09): 技术Top ∩ 妙想基本面池 = 质量警示层

    定位: 牛马方向三。技术评分Top5 与 妙想ROE精选池(基本面硬门) 取交集:
      - 有交集 → 高质量信号(技术+基本面共振), 正常提示
      - 空交集 → 弱信号日(技术面强但基本面池无一命中), 建议观望/降仓,
        但保留出票能力(不违反"门禁不卡出票"原则, 三闸降频率是P2-2)

    妙想池: data/mx_daily_screen.json (ROE>=5% 且 负债率<=60% 精选, code纯6位)
    技术池: results 前 top_n, code 带 sh/sz 前缀(取[2:]对齐妙想6位码)

    返回: dict {hit, top_codes, mx_codes, signal, advice, reason}
    """
    import os, json
    out = {
        "hit": False, "top_codes": [], "mx_codes": [],
        "signal": "unknown", "advice": "", "reason": "",
    }
    if not results:
        out.update(signal="empty", advice="无技术Top池", reason="results为空")
        return out

    # 技术Top5 (带前缀 → 纯6位)
    out["top_codes"] = [r[8][2:] if len(r) > 8 and r[8][:2].isalpha() else r[8]
                        for r in results[:top_n]]
    # 妙想池 (纯6位 code, 去重保序)
    mx_path = os.path.join(PROJECT, "data", "mx_daily_screen.json")
    mx_codes = []
    mx_ok = False
    if os.path.exists(mx_path):
        try:
            with open(mx_path, encoding="utf-8") as f:
                mx = json.load(f)
            for s in mx.get("stocks", []):
                c = str(s.get("code", "")).strip()
                if c:
                    mx_codes.append(c)
            mx_ok = True
        except Exception as e:
            out["reason"] = f"妙想池读取失败:{e}"
    out["mx_codes"] = list(dict.fromkeys(mx_codes))

    if not mx_ok:
        out.update(signal="mx_missing", advice="妙想基本面池缺失,双池门降级为仅技术Top",
                   reason="mx_daily_screen.json 不可用")
        return out

    inter = [c for c in out["top_codes"] if c in set(mx_codes)]
    if inter:
        out.update(hit=True, signal="resonance",
                   advice=f"技术Top∩妙想池={inter} (共振, 正常提示)",
                   reason=f"{len(inter)}/{top_n} 命中基本面精选池")
    else:
        out.update(hit=False, signal="weak_day",
                   advice=f"技术Top{top_n}无一命中妙想基本面池 → 弱信号日, 建议观望/降仓(保留出票, 非拦截)",
                   reason=f"空交集: 技术面强但无基本面共振, 震荡市质量存疑")
    return out


def three_gate_advice(results, top_n=5):
    """P2-2 三闸仓位判决(2026-09-09, 牛马方向四, 老大已拍板执行): 环境闸+信号闸+板块闸 → 仓位分级建议.

    定位: 将三闸合成一个仓位"建议"(不拦截出票, 遵守核心原则「环境门仅仓位提示, 不卡出票」):
      - 环境闸: market_state_cache.market_label (恐慌/弱/震荡=收紧仓位; 偏暖/强=正常)
        ⚠️ 2026-09-17 老大拍板取消环境门: 本闸仅作风险提醒，不降仓位
      - 信号闸: P1-3 双池门 (resonance=技术∩基本面共振 / weak_day=空交集弱信号)
      - 板块闸: P1-4 quadrant (补涨新走强=优选低位 / 共识顶部=回避; 历史<3天→降级待定, 不阻塞)
    判决(核心原则: 只建议仓位分级, 不否决出票):
      panic         → 恐慌市建议空仓/观望 (本金安全第一, 硬地板)
      strong        → 信号共振且环境不收紧 → 全仓1只开仓
      weak_watch    → 信号弱+环境收紧 → 建议观察/极小仓
      reduced       → 部分闸未过 → 建议降仓(当前仅作参考，实际执行全仓1只)
    返回: dict {verdict, pos_advice, env_gate, sig_gate, sector_gate, reasons}
    """
    import os, json
    out = {"verdict": "unknown", "pos_advice": "", "env_gate": "unknown",
           "sig_gate": "unknown", "sector_gate": "pending", "reasons": []}

    # 信号闸: 复用 P1-3 双池门
    try:
        _d = dual_pool_gate(results, top_n=top_n)
        out["sig_gate"] = _d.get("signal", "unknown")
        if out["sig_gate"] == "resonance":
            out["reasons"].append("信号闸 PASS: 技术Top∩妙想基本面池 共振")
        elif out["sig_gate"] == "weak_day":
            out["reasons"].append("信号闸 未过: 技术Top无一命中基本面池(弱信号日)")
        else:
            out["reasons"].append(f"信号闸 降级({out['sig_gate']})")
    except Exception as _se:
        out["sig_gate"] = "error"
        out["reasons"].append(f"信号闸 读取异常(不影响出票): {_se}")

    # 环境闸: market_state_cache (2026-09-17取消，仅作提示不卡出票)
    _env_pos = 1.0
    try:
        _ms = json.load(open(os.path.join(PROJECT, "data", "market_state_cache.json"),
                             encoding="utf-8")).get("result", {})
        out["env_gate"] = _ms.get("market_label", "unknown")
        # 环境门已取消，不再按仓位收紧
        _env_pos = 1.0  # 始终建议全仓
        if out["env_gate"] in ("恐慌", "弱", "震荡"):
            out["reasons"].append(f"环境闸 提示: {out['env_gate']}市(仅作风险提醒, 不降仓位)")
        else:
            out["reasons"].append(f"环境闸 正常: {out['env_gate']}市")
    except Exception as _ee:
        out["reasons"].append(f"环境闸 状态不可读(按正常处理): {_ee}")
    out["env_pos"] = _env_pos

    # 板块闸: P1-4 quadrant (历史<3天降级待定, 不阻塞)
    _quad = {}
    for _p in (os.path.join(PROJECT, "mainline", "data", "industry_heat_daily.json"),
               os.path.join(PROJECT, "data", "industry_heat_daily.json")):
        if os.path.exists(_p):
            try:
                _quad = json.load(open(_p, encoding="utf-8")).get("quadrant", {})
            except Exception:
                _quad = {}
            break
    _n_hist = _quad.get("n_history", 0)
    if _n_hist < 3:
        out["sector_gate"] = "pending"
        out["reasons"].append(f"板块闸 待定: P1-4历史仅{_n_hist}天(<3), 维持现状, 积累满后激活")
    else:
        _hot = _quad.get("quadrants", {}).get("补涨新走强", [])
        _top = _quad.get("quadrants", {}).get("共识顶部", [])
        out["sector_gate"] = "active"
        if _hot:
            out["reasons"].append(f"板块闸: {len(_hot)}个板块'补涨新走强', 低位补涨优先")
        if _top:
            out["reasons"].append(f"板块闸: {len(_top)}个板块'共识顶部', 高位回避")

    # 统一判决 (核心原则: 建议仓位分级, 不否决出票)
    _hard_weak = out["env_gate"] in ("恐慌", "弱", "震荡")
    _sig_ok = out["sig_gate"] == "resonance"
    if out["env_gate"] == "恐慌":
        out["verdict"] = "panic_wait"
        out["pos_advice"] = "恐慌市: 建议空仓/观望 (本金安全第一, 硬地板)"
    elif _sig_ok and not _hard_weak:
        out["verdict"] = "strong"
        out["pos_advice"] = f"信号强: 技术∩基本面共振且环境不收紧 → 正常仓位 {int(_env_pos*100)}% 开仓"
    elif (not _sig_ok) and _hard_weak:
        out["verdict"] = "weak_watch"
        out["pos_advice"] = f"弱信号+环境{out['env_gate']}收紧: 建议空仓/极小仓, 观望等信号修复"
    else:
        out["verdict"] = "reduced"
        out["pos_advice"] = f"部分闸未过: 建议降仓 {int(_env_pos*0.5*100)}% (环境闸仓位×50%), 不否决出票"
    return out


def main():
    top_n = 15
    debug = False
    force_strategy = None
    dry_run = False

    # 修复 M2: 同时支持 --top=15 / --top 15 与 --strategy=断层 / --strategy 断层
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--top" or arg.startswith("--top="):
            try:
                top_n = int(arg.split("=")[-1]) if "=" in arg else int(args[i + 1])
                if top_n <= 0:
                    raise ValueError
                i += 2 if "=" not in arg else 1
                continue
            except (ValueError, IndexError):
                print("  ⚠️ 无效 --top 参数，使用默认 15", file=sys.stderr)
                i += 2 if "=" not in arg else 1
                continue
        if arg == "--debug":
            debug = True
            i += 1
            continue
        if arg == "--dry-run":
            # 2026-08-13: CLI显式dry-run — 验证/测试不写 trade_log
            dry_run = True
            i += 1
            continue
        if arg == "--force-trade":
            # P0-2026-08-23: 门禁FAIL时的显式豁免开关(人工拍板才用, 留痕于输出)
            print("  ⚠️ --force-trade: 显式豁免回测门禁(人工确认)")
            _gate_force = True
            i += 1
            continue
        if arg == "--strategy" or arg.startswith("--strategy="):
            val = arg.split("=")[-1] if "=" in arg else (args[i + 1] if i + 1 < len(args) else "")
            if val in STRATEGIES:
                force_strategy = val
            else:
                print("  ⚠️ 未知策略 '%s'，可用: %s，使用自动" % (
                    val, "/".join(STRATEGIES.keys())), file=sys.stderr)
            i += 2 if "=" not in arg else 1
            continue
        i += 1

    # 门禁FAIL强制观察模式 — CLI豁免(--force-trade)可覆盖
    if not locals().get("_gate_force", False) and not dry_run:
        _gate_path = os.path.join(PROJECT, "data", "gate_status.json")
        _st = None
        for _ in range(3):
            try:
                with open(_gate_path, encoding="utf-8") as _gf:
                    _gd = json.load(_gf)
                    _st = _gd.get("status")
                    break
            except json.JSONDecodeError:
                time.sleep(0.2)
            except FileNotFoundError:
                break
        if _st == "FAIL":
            print("  🚦 回测门禁: FAIL -> 强制观察模式(dry_run, 不落库; 豁免请加--force-trade)")
            dry_run = True
        elif _st == "WARN":
            print("  ⚠️ 回测门禁: WARN (n<30, 结果仅供参考)")

    # P0-2026-09-30: 老五审批检查（AGENTS.md §4.7）
    # P0修复 2026-09-30 (准则9·总管裁定comment89): fail-open→fail-closed。
    # 文件缺失/JSON损坏/字段缺失 一律拦截退出(打印原因+exit 1)，仅显式 --force-trade 可绕过。
    if not dry_run and not locals().get("_gate_force", False):
        _review_path = os.path.join(PROJECT, "data", "review_status.json")
        import review_gate  # B3: 走唯一仲裁读法 (final_verdict 否决 + B1 findings 否决 + fail-safe), 不裸读 laowu_approved
        _gate = review_gate.evaluate(_review_path)
        if _gate["frozen"]:
            print(f"  🚫 老五审批冻结 (review_gate source={_gate['source']}): {_gate['reason']}")
            print("  📋 见 data/review_status.json。绕过请加 --force-trade")
            sys.exit(1)

    results, config, daily_inds_dict = run_integrated_picker(
        top_n=top_n, debug=debug, force_strategy=force_strategy, dry_run=dry_run
    )

    if results:
        best = results[0]
        if best[5]:
            print("\n  🥇 最优推荐: %s %s" % (best[8], best[9]))

            # ── P1-3 双池门: 技术Top∩妙想基本面池 = 质量警示层(不拦截出票) ──
            try:
                _dual = dual_pool_gate(results, top_n=5)
                print("  🔬 双池门: %s" % _dual["signal"].upper())
                print("     %s" % _dual["advice"])
                if _dual.get("reason"):
                    print("     (%s)" % _dual["reason"])
            except Exception as _dual_e:
                print("  🔬 双池门: 校验异常(不影响出票): %s" % _dual_e, file=sys.stderr)

            # ── P2-2 三闸仓位判决: 环境闸+信号闸+板块闸 → 仓位分级建议(不否决出票) ──
            try:
                _tri = three_gate_advice(results, top_n=5)
                print("  🚧 三闸判决: %s" % _tri["verdict"].upper())
                print("     %s" % _tri["pos_advice"])
                for _r in _tri.get("reasons", []):
                    print("       · %s" % _r)
            except Exception as _tri_e:
                print("  🚧 三闸判决: 校验异常(不影响出票): %s" % _tri_e, file=sys.stderr)

            print("     综合评分: %d | 断层评分: %d | 北向评分: %d" % (
                best[1], best[13], best[16]))
            print("     全仓风控: %d | 风险系数: %+d" % (best[2], best[3]))
            print("     板块热度: %s | 策略: %s(%.0f%%) | 仓位: %s(%.0f%%)\n" % (
                best[7] or "中性",
                config.get("primary", "?"),
                config.get("weights", {}).get(config.get("primary", ""), 0) * 100,
                config.get("position", "?"),
                config.get("position_ratio", 0) * 100,
            ))
            
            # 生成交易计划（取best最新收盘价作为参考）
            from core.pipeline.tdx_core import get_tdx_data, compute_indicators
            ref_recs = get_tdx_data(best[8], 5)
            ref_price = ref_recs[-1]["close"] if ref_recs and len(ref_recs) > 0 else 0
            
            if ref_price > 0:
                # 获取最佳股票指标（提前到此处，避免作用域问题）
                _best_cc = best[8][2:] if best[8][:2].isalpha() else best[8]
                _best_inds = daily_inds_dict.get(_best_cc, {})
                
                # 检测股票趋势 (2026-09-04: 用于动态止盈阶梯切换)
                from risk_rules import detect_stock_trend
                _ma5_val = _best_inds.get('ma5', 0)
                _ma20_val = _best_inds.get('ma20', 0)
                _ma60_val = _best_inds.get('ma60', _ma20_val * 1.1)  # 默认估算
                # 提取收盘价列表
                closes_list = [r["close"] for r in ref_recs] if ref_recs else []
                _stock_trend = detect_stock_trend(closes_list,
                                                   ma5=_ma5_val, ma20=_ma20_val, ma60=_ma60_val)

                plan = generate_trade_plan(
                    entry_price=ref_price,
                    strategy=config.get("primary", "断层"),
                    market_score=config.get("market_score", 50),
                    market_label=config.get("market_label", "震荡"),
                    gap_score=best[13],
                    nb_score=best[16],
                    confidence="medium",
                    capital=23000,
                    trend=_stock_trend,
                )
                print_trade_plan(plan)

            # ── AI论点合成 (Phase 1: 轻量提示词) ──
            try:
                from thesis_builder import build_thesis, print_thesis_summary, save_thesis_json
                # 复用 daily_inds_dict 获取指标 (已在506行构建)
                _chg5 = _best_inds.get('chg5', 0)
                _rsi = _best_inds.get('rsi14', 50)
                _vol = _best_inds.get('vol_ratio', 1.0)
                _ma5 = _best_inds.get('ma5', 0)
                _ma20 = _best_inds.get('ma20', 0)

                thesis_data = {
                    'code': best[8],
                    'name': best[9],
                    'score_zonghe': best[1],
                    'gap_score': best[13],
                    'nb_score': best[16],
                    'market_score': config.get('market_score', 50),
                    'market_label': config.get('market_label', '震荡'),
                    'strategy': config.get('primary', '断层'),
                    'entry_price': ref_price,
                    'stop_loss': plan['stop_loss'],
                    'tp1': plan['tp1'],
                    'tp2': plan['tp2'],
                    'chg5': _chg5,
                    'rsi14': _rsi,
                    'vol_ratio': _vol,
                    'ma5': _ma5,
                    'ma20': _ma20,
                    'heat_desc': best[7] if len(best) > 7 and best[7] else '',
                }
                thesis = build_thesis(thesis_data)
                print_thesis_summary(thesis)
                # 保存JSON（不污染trade_log）
                try:
                    save_thesis_json(thesis)
                except Exception as _te:
                    print(f"  ⚠️ 论点JSON保存失败: {_te}")
            except Exception as _thesis_e:
                print(f"  ⚠️ 论点合成失败(不影响选股): {_thesis_e}")


if __name__ == "__main__":
    main()


# ═══════════════════════════════════════════
#  动量筛选 (优化版: 增强趋势持续性评分)
# ═══════════════════════════════════════════
def apply_momentum_filter(code, name, recs, inds, market_close):
    """动量筛选: 5日/10日/20日涨幅 + 相对强度
    返回 (pass_flag, reason_key, momentum_score)
    """
    if not recs or len(recs) < 20:
        return False, "data", 0
    
    last = recs[-1]
    close = last.get("close", 0)
    if close <= 0:
        return False, "price", 0
    
    # 计算涨幅
    gain_5d = (close / recs[-6]["close"] - 1) * 100 if len(recs) >= 6 else 0
    gain_10d = (close / recs[-11]["close"] - 1) * 100 if len(recs) >= 11 else 0
    gain_20d = (close / recs[-21]["close"] - 1) * 100 if len(recs) >= 21 else 0
    
    # 相对强度
    market_gain_5d = (market_close / recs[-6].get("market_close", market_close) - 1) * 100 if len(recs) >= 6 else 0
    rs = (gain_5d / market_gain_5d) if market_gain_5d > 0 else 1.0
    
    # 评分逻辑
    score = 0
    if gain_5d >= 3:
        score += 25
    elif gain_5d >= 1:
        score += 15
    elif gain_5d >= 0:
        score += 5
    
    if gain_10d >= 5:
        score += 25
    elif gain_10d >= 2:
        score += 15
    elif gain_10d >= 0:
        score += 5
    
    if gain_20d >= 8:
        score += 25
    elif gain_20d >= 4:
        score += 15
    elif gain_20d >= 0:
        score += 5
    
    if rs >= 1.2:
        score += 25
    elif rs >= 1.0:
        score += 15
    elif rs >= 0.8:
        score += 5
    
    # 阈值判定
    if gain_5d < 3 or gain_10d < 5 or gain_20d < 8 or rs < 1.2:
        return False, "momentum", score
    
    return True, None, score
