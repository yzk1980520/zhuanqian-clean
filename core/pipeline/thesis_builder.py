import core.pipeline.atomic_json as atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
thesis_builder.py — AI论点合成器 v1.0
=====================================
基于量化因子数据生成结构化投资论点（看多/看空对称 + 可证伪条件）

用途:
  1. 实盘: 选股后打印论点摘要供快速判断
  2. 回测: 生成historical thesis用于事后检验
  3. 诊断: 持仓复盘时追溯选股逻辑

集成:
  from thesis_builder import build_thesis, print_thesis_summary
  thesis = build_thesis(stock_data)
  print_thesis_summary(thesis)

输入格式:
  stock_data = {
    'code': str, 'name': str,
    'score_zonghe': float, 'gap_score': int, 'nb_score': int,
    'fin_health': int, 'fraud_fatal': bool,
    'market_score': int, 'market_label': str,
    'strategy': str, 'entry_price': float,
    'stop_loss': float, 'tp1': float, 'tp2': float,
    'chg5': float, 'rsi14': float, 'vol_ratio': float,
    'ma5': float, 'ma10': float, 'ma20': float,
    'gross_margin': float, 'roe': float, 'debt_ratio': float,
  }

输出格式 (JSON可机读):
  {
    'code': str, 'name': str, 'generated_at': str,
    'core_thesis': str,
    'bull_cases': list[str],  # >=3条
    'bear_cases': list[str],  # >=3条 (权重比>=1:1)
    'falsifiability': list[str],  # 失效条件
    'confidence': str,  # 高/中/低
    'confidence_basis': str,
  }
"""
import json
from datetime import datetime

# ═══════════════════════════════════════════
#  置信度判定规则 (基于因子阈值)
# ═══════════════════════════════════════════
CONFIDENCE_RULES = {
    'high': {
        'min_score': 85,
        'min_gap': 3,
        'no_fraud': True,
        'reason': '高分+强断层+无舞弊风险',
    },
    'medium': {
        'min_score': 70,
        'min_gap': 1,
        'no_fraud': True,
        'reason': '中等评分+有断层信号',
    },
    'low': {
        'min_score': 0,
        'min_gap': 0,
        'no_fraud': False,
        'reason': '低分或存在风险信号',
    },
}


def _safe_float(val, default=0.0):
    """安全转换为float，处理字符串/None"""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=0):
    """安全转换为int，处理字符串/None"""
    if val is None:
        return default
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def assess_confidence(data):
    """根据因子阈值判定置信度"""
    score = _safe_float(data.get('score_zonghe', 0))
    gap = _safe_int(data.get('gap_score', 0))
    fraud = data.get('fraud_fatal', False)
    
    if score >= CONFIDENCE_RULES['high']['min_score'] and \
       gap >= CONFIDENCE_RULES['high']['min_gap'] and \
       not fraud:
        return '高', CONFIDENCE_RULES['high']['reason']
    elif score >= CONFIDENCE_RULES['medium']['min_score'] and \
         gap >= CONFIDENCE_RULES['medium']['min_gap'] and \
         not fraud:
        return '中', CONFIDENCE_RULES['medium']['reason']
    else:
        return '低', CONFIDENCE_RULES['low']['reason']


def generate_bull_cases(data):
    """生成看多论据 (≥3条)"""
    bulls = []
    
    # 断层信号
    gap = _safe_int(data.get('gap_score', 0))
    if gap >= 3:
        bulls.append(f"净利润断层强势(评分{gap}/5)，业绩超预期跳空未回补")
    elif gap >= 1:
        bulls.append(f"存在断层信号(评分{gap}分)，业绩利好支撑")
    
    # 动量
    chg5 = _safe_float(data.get('chg5', 0))
    if chg5 > 5:
        bulls.append(f"短期动量强劲(5日涨幅{chg5:+.1f}%)，趋势向上确认")
    elif chg5 > 2:
        bulls.append(f"短期动量良好(5日涨幅{chg5:+.1f}%)")
    
    # 技术形态
    rsi = _safe_float(data.get('rsi14', 50))
    if 50 < rsi < 70:
        bulls.append(f"RSI{rsi:.0f}处于健康区间，无超买风险")
    
    ma5 = _safe_float(data.get('ma5', 0))
    ma20 = _safe_float(data.get('ma20', 0))
    if ma5 > ma20 > 0:
        bulls.append("均线多头排列(MA5>MA20)，趋势向上")
    
    # 财务健康
    fin = _safe_int(data.get('fin_health', 0))
    if fin >= 30:
        bulls.append(f"财务健康度高({fin}/40)，盈利质量可靠")
    elif fin >= 20:
        bulls.append(f"财务状况良好({fin}/40)")
    
    # 行业热度
    heat = data.get('heat_desc', '')
    if heat:
        bulls.append(f"板块轮动配合: {heat}")
    
    # 确保至少3条
    if len(bulls) < 3:
        bulls.append(f"综合评分{_safe_float(data.get('score_zonghe', 0)):.0f}分，多因子共振")
    
    return bulls[:5]  # 最多5条


def generate_bear_cases(data):
    """生成看空论据 (≥3条，与看多权重比≥1:1)"""
    bears = []
    
    # RSI超买
    rsi = _safe_float(data.get('rsi14', 50))
    if rsi > 70:
        bears.append(f"RSI{rsi:.0f}接近超买区，短期回调风险增加")
    elif rsi > 60:
        bears.append(f"RSI{rsi:.0f}偏高，注意技术性调整")
    
    # 涨幅过大
    chg5 = _safe_float(data.get('chg5', 0))
    if chg5 > 10:
        bears.append(f"短期涨幅过大(5日{chg5:+.1f}%)，获利盘抛压风险")
    elif chg5 > 7:
        bears.append(f"短期涨幅偏大(5日{chg5:+.1f}%)，追高风险")
    
    # 财务风险
    fin = _safe_int(data.get('fin_health', 0))
    if fin < 15:
        bears.append(f"财务健康度偏低({fin}/40)，盈利质量存疑")
    
    fraud = data.get('fraud_fatal', False)
    if fraud:
        bears.append("⚠️ 存在舞弊风险信号，一票否决")
    
    # 市场状态
    market = data.get('market_label', '震荡')
    if market in ('弱', '恐慌'):
        bears.append(f"市场状态{market}，系统性风险较高")
    
    # 成交量异常
    vol = _safe_float(data.get('vol_ratio', 1.0))
    if vol > 3.0:
        bears.append(f"成交量异常放大(量比{vol:.1f}倍)，可能是出货信号")
    elif vol < 0.5:
        bears.append(f"成交量萎缩(量比{vol:.1f}倍)，资金关注不足")
    
    # 均线背离
    ma5 = _safe_float(data.get('ma5', 0))
    ma20 = _safe_float(data.get('ma20', 0))
    if ma5 > 0 and ma20 > 0 and ma5 < ma20:
        bears.append("均线空头排列(MA5<MA20)，趋势向下")
    
    # 确保至少3条 (对称性要求: 看空>=看多权重比1:1)
    if len(bears) < 3:
        bears.append("量化选股存在幸存者偏差，历史表现不代表未来")
        bears.append("单票全仓策略风险集中，黑天鹅事件影响大")
        if len(bears) < 3:
            bears.append(f"市场环境{market}，系统性风险需监控")
    
    return bears[:5]  # 最多5条


def generate_falsifiability(data):
    """生成可证伪条件"""
    conditions = []

    # 技术面失效
    rsi = _safe_float(data.get('rsi14', 50))
    if rsi > 60:
        conditions.append(f"若RSI突破80且连续2日未回落 → 超买确认，论点失效")

    # 跌幅失效
    entry = _safe_float(data.get('entry_price', 0))
    sl = _safe_float(data.get('stop_loss', 0))
    if entry > 0 and sl > 0:
        drop_pct = (sl / entry - 1) * 100
        conditions.append(f"若股价跌破止损位{sl:.2f}({drop_pct:.1f}%) → 硬性止损触发")

    # 时间失效
    conditions.append("若持仓超过60个交易日仍未达止盈 → 时间止损触发")

    # 市场状态恶化
    market = data.get('market_label', '震荡')
    if market not in ('恐慌',):
        conditions.append("若市场状态恶化至'恐慌' → 系统性风险，重新评估")

    # 财务恶化
    conditions.append("若下期财报显示净利润下滑>20% → 基本面证伪")

    return conditions[:4]


def build_core_thesis(data):
    """生成核心论点摘要"""
    parts = []
    
    # 市场定位
    market_label = data.get('market_label', '震荡')
    market_score = _safe_int(data.get('market_score', 0))
    parts.append(f"当前{market_label}市({market_score}分)")
    
    # 核心信号
    gap = _safe_int(data.get('gap_score', 0))
    if gap >= 3:
        parts.append(f"业绩断层驱动(断层{gap}分)")
    elif gap >= 1:
        parts.append(f"有断层信号(断层{gap}分)")
    else:
        parts.append("技术动量驱动")
    
    # 财务状态
    fin = _safe_int(data.get('fin_health', 0))
    if fin >= 30:
        parts.append("财务健康")
    elif fin >= 15:
        parts.append("财务基本合格")
    else:
        parts.append("财务存在隐患")
    
    # 风险状态
    fraud = data.get('fraud_fatal', False)
    if fraud:
        parts.append("⚠️存在舞弊风险")
    
    strategy = data.get('strategy', '综合')
    return " | ".join(parts) + f"，适合{strategy}策略"


def build_thesis(data):
    """
    构建结构化投资论点
    
    Args:
        data: dict — 量化因子数据（见模块文档）
    
    Returns:
        dict: 结构化论点JSON
    """
    confidence, basis = assess_confidence(data)
    
    thesis = {
        'code': data.get('code', ''),
        'name': data.get('name', ''),
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'core_thesis': build_core_thesis(data),
        'bull_cases': generate_bull_cases(data),
        'bear_cases': generate_bear_cases(data),
        'falsifiability': generate_falsifiability(data),
        'confidence': confidence,
        'confidence_basis': basis,
        # 原始因子快照（便于追溯）
        'factors_snapshot': {
            'score_zonghe': data.get('score_zonghe'),
            'gap_score': data.get('gap_score'),
            'fin_health': data.get('fin_health'),
            'market_score': data.get('market_score'),
            'rsi14': data.get('rsi14'),
            'chg5': data.get('chg5'),
        }
    }
    
    return thesis


def print_thesis_summary(thesis):
    """打印结构化论点摘要（终端输出）"""
    print("\n" + "=" * 60)
    print(f"  📋 投资论点摘要 — {thesis['name']} ({thesis['code']})")
    print("=" * 60)
    print(f"  核心论点: {thesis['core_thesis']}")
    print(f"  置信度: {thesis['confidence']} ({thesis['confidence_basis']})")
    print(f"\n  看多论据 ({len(thesis['bull_cases'])}条):")
    for i, case in enumerate(thesis['bull_cases'][:3], 1):
        print(f"    ✅ {i}. {case}")
    print(f"\n  看空论据 ({len(thesis['bear_cases'])}条):")
    for i, case in enumerate(thesis['bear_cases'][:3], 1):
        print(f"    ⚠️  {i}. {case}")
    print(f"\n  失效条件:")
    for cond in thesis['falsifiability'][:2]:
        print(f"    🔴 {cond}")
    print("=" * 60)


def save_thesis_json(thesis, output_path=None):
    """保存论点JSON到文件"""
    if output_path is None:
        output_path = 'data/latest_thesis.json'
    
    import os
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    
    atomic_json.atomic_dump(thesis, output_path, ensure_ascii=False, indent=2, encoding="utf-8")
    
    return output_path
