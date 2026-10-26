import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""sequence_risk.py — P2-C 轮动序列风控（独立模块）

总管规格 (T-20260815-003, 重新定义版):
原"组合层风控"与单票全仓冲突 → 改为"轮动序列风控(只读告警不修改推荐逻辑)"

3条规则 (按优先级顺序应用):
  R1 行业避让:  行业热度排名 TopN 的热门行业 → 个股推荐分 × 0.8 降权
                (避免追高热门板块, 买入即套)
  R2 行业黑天鹅:当日(或最近1根日线)该行业内 ≥2 只个股跳空 -15% →
                排除该行业所有推荐 (当日不推该行业)
  R3 题材上限:  同题材(行业=题材粗分类)每日最多保留 3 只候选,
                按调整后分数高者优先 (避免推荐列表全是同一题材)

接入点:
  1. integrated_picker.py 主流程末尾 → apply_sequence_risk(candidates, ...)
  2. backtest.py 回测选股流程末尾 → 同上

独立调用:
  python sequence_risk.py  →  自检demo (运行纯函数)

安全边界 (按任务单 ack 承诺):
  · 不改 recommendation 数据结构/字段名 (新增 _seq_adjusted 可选字段)
  · 不改返回路径, 仅在最后做后处理
  · 不碰 risk_rules / risk_monitor / risk_alerter / position_alerts / scoring_engine
    权重、止盈止损参数
  · 不改 calculate_position (单票仓位仍 100%)
  · 不新建缓存文件, 复用 tdx_core.load_industry_map / get_industry_heat / data/industry_heat.json
  · 交易数据零写入 (只写 data/sequence_risk_yyyymmdd.json 新日志文件)
"""

import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys
import logging
from collections import defaultdict
from datetime import date

SCRIPT_DIR = PROJECT_ROOT
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from core.pipeline.atomic_json import atomic_dump

logger = logging.getLogger("sequence_risk")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(name)s] %(levelname)s %(message)s"))
    logger.addHandler(_h)


# ────────────────────────────────────────────────────────────────
# 可配置参数 (全部集中在这里, 方便总管改阈值, 不要分散到接入点)
# ────────────────────────────────────────────────────────────────

# R1 行业避让: 行业热度排名 Top N 比例的行业算作"过热"
R1_HEAT_TOP_RATIO = 0.25  # 热度前 25% = 过热
R1_DISCOUNT = 0.8         # 过热行业推荐分 × 此系数 (任务单定: 0.8)

# R2 行业黑天鹅: 行业内跳空-15%的个股数 ≥ 此阈值 → 排除该行业
R2_GAP_PCT = -15.0        # 跳空阈值 (向下百分比)
R2_MIN_TRIGGERS = 2       # 触发所需个股数 (任务单定: 2)

# R3 题材上限: 同题材每日最多保留的候选数
R3_TOPIC_LIMIT = 3        # 同题材上限 (任务单定: 3)

# 黑天鹅内存缓存 (避免同一交易日重复计算): {date_str: {industry_code_or_name: True}}
_BLACKLISTED_INDUSTRIES_CACHE = {}
_BLACKLISTED_INDUSTRIES_DATE = None


# ────────────────────────────────────────────────────────────────
# 纯函数 R1: 行业避让降权
# ────────────────────────────────────────────────────────────────

def apply_industry_avoidance(candidates, industry_heat_rank,
                             heat_top_ratio=R1_HEAT_TOP_RATIO,
                             discount=R1_DISCOUNT):
    """R1 行业避让: 过热行业推荐分×discount

    Args:
        candidates: list[dict] 候选列表, 每项至少含
                    code(str), name(str), final_score(float/int) 或 score(float/int),
                    可选 industry(str)
        industry_heat_rank: dict[str, float] 行业名 → 排名百分位(0~1, 1=最热)
                            由 tdx_core.get_industry_heat() 返回
        heat_top_ratio:  float 0~1, 超过此排名百分位算"过热"
        discount:        float 0~1, 降权系数

    Returns:
        list[dict]  新的 candidates 列表(副本)
                    对过热行业条目: score *= discount, 打标 _seq_avoided=True,
                    记录 _seq_orig_score
        dict        执行日志 {"avoided": [{code, industry, orig, new}], ...}
    """
    if not candidates or not industry_heat_rank:
        # 没数据 → 不修改, 日志说明
        return [c.copy() if isinstance(c, dict) else c for c in candidates], {"avoided": [], "reason": "no_candidates_or_no_heat"}

    heat_threshold = 1.0 - heat_top_ratio  # e.g. 0.75, 超过=前25%最热
    avoided = []
    new_cands = []
    # 2026-08-20 修复: tdx_core.get_industry_heat 的 key 是东财板块名(如"白酒Ⅱ"),
    # 粗分类映射在 __alias__ (如 "白酒"→{rank,percentile,...}); 不解引用 → R1 恒不触发
    _alias = industry_heat_rank.get("__alias__") if isinstance(industry_heat_rank, dict) else None
    for c in candidates:
        if not isinstance(c, dict):
            new_cands.append(c)
            continue
        cp = dict(c)
        ind = cp.get("industry") or ""
        if ind:
            rank = industry_heat_rank.get(ind)
            if rank is None and isinstance(_alias, dict):
                rank = _alias.get(ind)
            rank = rank.get("percentile") if isinstance(rank, dict) else rank
            if isinstance(rank, (int, float)) and rank > heat_threshold:
                # 过热行业 → 降权
                for sk in ("final_score", "score", "recommend_score"):
                    if sk in cp and isinstance(cp[sk], (int, float)):
                        orig_val = cp[sk]
                        cp[sk] = round(cp[sk] * discount, 4)
                        cp["_seq_avoided"] = True
                        cp["_seq_orig_score"] = orig_val
                        cp["_seq_heat_rank"] = round(rank, 4)
                        avoided.append({
                            "code": cp.get("code", ""),
                            "industry": ind,
                            "orig_score": orig_val,
                            "new_score": cp[sk],
                            "discount": discount,
                        })
                        break
        new_cands.append(cp)
    return new_cands, {"avoided": avoided, "heat_threshold": round(heat_threshold, 4)}


# ────────────────────────────────────────────────────────────────
# 纯函数 R2: 行业黑天鹅 → 当日排除该行业
# ────────────────────────────────────────────────────────────────

def detect_black_swan_industries(stock_gap_pcts,
                                  gap_threshold=R2_GAP_PCT,
                                  min_triggers=R2_MIN_TRIGGERS):
    """R2 检测行业黑天鹅

    Args:
        stock_gap_pcts: list[dict] 每只个股的最近1根跳空数据, 每项
                         {code, industry(str, 可选, 可空), gap_pct(float, 向下为负)}
        gap_threshold:  float 跳空阈值(如 -15.0, 向下超过=触发)
        min_triggers:   int 行业内触发个股数 ≥ 此值 → 拉黑

    Returns:
        set[str] 被拉黑的行业名集合 (当日不推荐)
        dict     调试日志 {industry: {triggers:[code...], count:N}, total_triggered:N}
    """
    if not stock_gap_pcts:
        return set(), {"total_triggered": 0, "industries": {}}

    industry_triggers = defaultdict(list)
    for s in stock_gap_pcts:
        if not isinstance(s, dict):
            continue
        gp = s.get("gap_pct")
        ind = s.get("industry") or ""
        code = s.get("code") or ""
        if not ind:
            # 无行业的无法判断行业黑天鹅, 跳过 (不影响有行业的候选)
            continue
        if isinstance(gp, (int, float)) and gp <= gap_threshold:
            industry_triggers[ind].append(code)

    blacklist = set()
    detail = {}
    for ind, codes in industry_triggers.items():
        n = len(codes)
        if n >= min_triggers:
            blacklist.add(ind)
        detail[ind] = {"triggers": codes, "count": n}
    return blacklist, {"total_triggered": len(blacklist), "industries": detail}


def filter_blacklist(candidates, blacklisted_industries):
    """过滤掉黑天鹅行业的候选 (R2 应用阶段)

    Returns:
        list[dict] 过滤后副本
        dict       日志 {"removed": [{code, name, industry}], "kept": N}
    """
    if not candidates or not blacklisted_industries:
        return [c.copy() if isinstance(c, dict) else c for c in candidates], {"removed": [], "kept": len(candidates)}
    kept, removed = [], []
    for c in candidates:
        if not isinstance(c, dict):
            kept.append(c)
            continue
        cp = dict(c)
        ind = cp.get("industry") or ""
        if ind and ind in blacklisted_industries:
            removed.append({
                "code": cp.get("code", ""),
                "name": cp.get("name", ""),
                "industry": ind,
            })
        else:
            kept.append(cp)
    return kept, {"removed": removed, "kept": len(kept)}


# ────────────────────────────────────────────────────────────────
# 纯函数 R3: 题材上限 (每题材最多 top N 只, 按分数高者优先)
# ────────────────────────────────────────────────────────────────

def apply_topic_cap(candidates, topic_limit=R3_TOPIC_LIMIT):
    """R3 同题材上限: 同行业(=题材粗分类)每日最多保留 topic_limit 只

    按调整后分数(降序)保留前N只。如果某条既无industry也无industry字段,
    归到 "__unknown__" 组单独限额。

    Returns:
        list[dict] 截断后的新列表
        dict       日志 {"topic_counts": {topic: [kept, removed, total]},
                         "removed": [{code, name, industry, score}]}
    """
    if not candidates:
        return [], {"topic_counts": {}, "removed": []}

    # 1. 先为每个候选拿到"分数键" (兼容各种字段名)
    def _score_of(c):
        for sk in ("final_score", "score", "recommend_score"):
            v = c.get(sk)
            if isinstance(v, (int, float)):
                return v
        return 0

    # 2. 按题材分组
    groups = defaultdict(list)
    for idx, c in enumerate(candidates):
        if not isinstance(c, dict):
            # 非标对象不分组, 原样保留 (不限额)
            groups.setdefault("__raw__", []).append((idx, c))
            continue
        topic = c.get("industry") or "__unknown__"
        groups[topic].append((idx, dict(c), _score_of(c)))

    # 3. 每组按分数(desc)截 top N
    topic_counts = {}
    removed_log = []
    kept_items = []  # [(orig_idx, item_dict)]
    for topic, items in groups.items():
        if topic == "__raw__":
            # 非标对象全保留
            kept_items.extend(items)
            topic_counts[topic] = [len(items), 0, len(items)]
            continue
        items_sorted = sorted(items, key=lambda t: t[2], reverse=True)
        kept_list = items_sorted[:topic_limit]
        rem_list = items_sorted[topic_limit:]
        for _, itm, sc in rem_list:
            removed_log.append({
                "code": itm.get("code", ""),
                "name": itm.get("name", ""),
                "industry": topic,
                "score": sc,
            })
        kept_items.extend(kept_list)
        topic_counts[topic] = [len(kept_list), len(rem_list), len(items_sorted)]

    # 4. 恢复原顺序 (按 candidates 原索引排序)
    kept_items.sort(key=lambda t: t[0])
    final_result = []
    for t in kept_items:
        # items tuple 格式: (orig_idx, dict) 或 (orig_idx, dict, score)
        # 都取 t[1] 作为 dict
        if isinstance(t, tuple) and len(t) >= 2 and isinstance(t[1], dict):
            final_result.append(t[1])
        else:
            final_result.append(t)

    return final_result, {
        "topic_counts": topic_counts,
        "removed": removed_log,
        "limit": topic_limit,
    }


# ────────────────────────────────────────────────────────────────
# 复合入口: 依次应用 R1→R2→R3
# ────────────────────────────────────────────────────────────────

def apply_sequence_risk(candidates,
                         industry_heat_rank=None,
                         stock_gap_pcts=None,
                         run_date=None,
                         r1_heat_top_ratio=R1_HEAT_TOP_RATIO,
                         r1_discount=R1_DISCOUNT,
                         r2_gap_pct=R2_GAP_PCT,
                         r2_min=R2_MIN_TRIGGERS,
                         r3_limit=R3_TOPIC_LIMIT,
                         write_log=True):
    """复合入口: 依次应用 R1→R2→R3 (容错: 缺任何一条输入就跳过那步, 不抛错)

    Args:
        candidates:        list[dict] 选股候选 (来自 integrated_picker 或 backtest)
        industry_heat_rank: dict[str,float] tdx_core.get_industry_heat() 的返回值 (可选)
        stock_gap_pcts:    list[dict] 候选对应个股最近1根跳空 {code,industry,gap_pct} (可选)
        run_date:          str "YYYY-MM-DD" 或 date (日志用, 默认今天)
        r1_* / r2_* / r3_*: 覆盖默认阈值 (测试用)
        write_log:         bool 是否落盘 data/sequence_risk_yyyymmdd.json

    Returns:
        list[dict]  处理后的候选列表 (结构与输入一致, 仅调整排序+删减+降权)
        dict        完整审计日志 (3条规则分别的动作+数量, 供回传/人工审查)
    """
    if not candidates:
        return [], {"info": "empty_candidates"}

    if run_date is None:
        run_date = str(date.today())
    elif isinstance(run_date, date):
        run_date = str(run_date)

    audit = {"date": run_date, "input_count": len(candidates)}

    # --- R1 行业避让降权 ---
    try:
        after_r1, log_r1 = apply_industry_avoidance(
            candidates, industry_heat_rank or {},
            heat_top_ratio=r1_heat_top_ratio, discount=r1_discount,
        )
    except Exception as e:
        logger.warning("R1 行业避让失败, 跳过: %s", e, exc_info=True)
        after_r1 = [dict(c) if isinstance(c, dict) else c for c in candidates]
        log_r1 = {"error": str(e), "skip": True}
    audit["R1"] = log_r1

    # --- R2 行业黑天鹅过滤 ---
    try:
        # 黑天鹅名单来自 stock_gap_pcts (如果给了的话)
        blacklist, log_r2_detail = detect_black_swan_industries(
            stock_gap_pcts or [],
            gap_threshold=r2_gap_pct, min_triggers=r2_min,
        )
        after_r2, log_r2_filter = filter_blacklist(after_r1, blacklist)
        log_r2 = {**log_r2_detail, **log_r2_filter, "blacklist": sorted(list(blacklist))}
    except Exception as e:
        logger.warning("R2 黑天鹅过滤失败, 跳过: %s", e, exc_info=True)
        after_r2 = after_r1
        log_r2 = {"error": str(e), "skip": True}
    audit["R2"] = log_r2

    # --- R3 题材上限截断 ---
    try:
        after_r3, log_r3 = apply_topic_cap(after_r2, topic_limit=r3_limit)
    except Exception as e:
        logger.warning("R3 题材上限失败, 跳过: %s", e, exc_info=True)
        after_r3 = after_r2
        log_r3 = {"error": str(e), "skip": True}
    audit["R3"] = log_r3

    audit["output_count"] = len(after_r3)

    # --- 落盘日志 (sequence_risk_YYYYMMDD.json) ---
    if write_log:
        try:
            data_dir = os.path.join(SCRIPT_DIR, "data")
            os.makedirs(data_dir, exist_ok=True)
            date_str_compact = run_date.replace("-", "")
            log_path = os.path.join(data_dir, f"sequence_risk_{date_str_compact}.json")
            atomic_dump(audit, log_path, ensure_ascii=False, indent=2)
            audit["log_file"] = log_path
        except Exception as e:
            logger.warning("sequence_risk 日志落盘失败: %s", e, exc_info=True)

    return after_r3, audit


# ────────────────────────────────────────────────────────────────
# 单元测试友好的纯数据Demo (__main__保护, import 即跑=绝不发生)
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 纯自举: 不依赖 tdx/market_state, 用假数据演示 3 条规则
    demo_cands = [
        # --- 银行 (行业), 非过热, 无黑天鹅 ---
        {"code": "sz000001", "name": "平安银行", "industry": "银行", "final_score": 88.0},
        {"code": "sz002142", "name": "宁波银行", "industry": "银行", "final_score": 86.0},
        {"code": "sh600036", "name": "招商银行", "industry": "银行", "final_score": 85.0},
        {"code": "sh601398", "name": "工商银行", "industry": "银行", "final_score": 80.0},
        # --- 科技 (过热: 0.95 → R1 降权×0.8) ---
        {"code": "sh600519", "name": "茅台科技", "industry": "科技", "final_score": 90.0},  # → 72
        {"code": "sz002415", "name": "海康威视", "industry": "科技", "final_score": 89.0},  # → 71.2
        {"code": "sz300750", "name": "宁德时代", "industry": "科技", "final_score": 87.0},  # → 69.6
        {"code": "sz000977", "name": "浪潮信息", "industry": "科技", "final_score": 86.0},  # → 68.8 (R3上限=3 被截断)
        # --- 医药 (黑天鹅: 2只 -16%/-18% → R2 排除行业) ---
        {"code": "sz300760", "name": "迈瑞医疗", "industry": "医药", "final_score": 92.0},
        {"code": "sz000538", "name": "云南白药", "industry": "医药", "final_score": 91.0},
    ]
    demo_heat = {
        "银行": 0.3,      # 非过热
        "科技": 0.95,     # 过热前25%
        "医药": 0.4,
    }
    demo_gaps = [
        {"code": "sz300760", "industry": "医药", "gap_pct": -16.2},
        {"code": "sz000538", "industry": "医药", "gap_pct": -18.5},
    ]

    final, audit = apply_sequence_risk(
        demo_cands,
        industry_heat_rank=demo_heat,
        stock_gap_pcts=demo_gaps,
        run_date="2026-08-15",
        write_log=False,
    )

    print("="*60)
    print("sequence_risk.py — 自举Demo (非生产)")
    print("="*60)
    print(f"输入候选: {audit['input_count']} 只 → 输出: {audit['output_count']} 只")
    print(f"\nR1 降权: {len(audit.get('R1',{}).get('avoided',[]))} 只(科技×0.8)")
    for r in audit["R1"]["avoided"]:
        print(f"  · {r['code']} {r['industry']}: {r['orig_score']}→{r['new_score']}")
    print(f"\nR2 排除行业: {audit.get('R2',{}).get('blacklist',[])}")
    for r in audit["R2"].get("removed", []):
        print(f"  · ✂️ 移除: {r['code']} {r['name']}({r['industry']})")
    print(f"\nR3 题材上限(3): 保留/移除")
    for t, (k, rm, tot) in audit.get("R3", {}).get("topic_counts", {}).items():
        print(f"  · {t}: 保留{k}/{tot} 移除{rm}")
    for r in audit["R3"].get("removed", []):
        print(f"  · ✂️ 限额外: {r['code']} {r.get('name','')}({r['industry']}) score={r['score']}")

    print("\n✅ 输出候选列表 (最终顺序):")
    for i, c in enumerate(final, 1):
        mark = ""
        if c.get("_seq_avoided"):
            mark = " ↓已避 R1"
        print(f"  {i:>2}. {c.get('code','?')} {c.get('name','?'):12s} {c.get('industry','?'):6s} score={c.get('final_score',c.get('score',0))}{mark}")
