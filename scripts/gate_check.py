# DEPRECATED → use scripts/check_all.py backtest-gate
"""
门禁状态检查脚本 - 每日20:00执行

【S3 权威源口径 - 2026-10-17 老大拍板】
  IC 权威源   : data/factor_ic/factor_ic_latest.json  (132d 精确口径)
  门禁阈值    : >= 8 个有效因子                        (不变)

【口径翻转 - 2026-10-23 晚 (老五落地, commit 8908f805 基础上)】
  有效因子判定: 严口径复合规则 (GATE_STRICT_RULE=True)
    = status=='valid' AND sample_size格式校验 AND |IC|>=0.03 AND 死池历史一致
  依据: 10/21 注入前科 (status 被人为改+伪造icir, 裸|IC|计数被-0.2782大数穿透);
        总管裁定站位=严 + 全团队技术共识 + 老大"@all 继续后续"指令
  保守方向: 只收紧不放开 (gap 2→3, 门禁仍FAIL, 策略冻结不受影响)
  回退: GATE_STRICT_RULE=False 一行翻转回 status 宽口径

[D-10 代际错位修复 - 2026-10-25 方案A (待三方会签, 总管落 commit)]
  口径切换 (calculate_v3→pure_python_v10_exact_132d) 后, total_samples 语义变为
  池因子数 (=len(factors), 源头 factor_ic_132d_refresh.py L945), 而因子级
  sample_size 仍是截面日数 (132d 池=132, v3 代=199)。旧判据 ss!=total_samples
  跨代际比较两个不同语义字段 → TURN5 被误 flag sample_size_mismatch(132!=31)
  → 门禁 1/8 降为 0/8。
  新判据: sample_size 与「本文件引擎代际的任一合法样本格式」匹配:
  合法集 = _SS_GEN_ANCHORS 代际锚点表 ∪ 文件自证字段 dates_with_ic ∪ 文件内众数 sample_size
  total_samples 不再参与因子级交叉 (语义按代际报告); 132d 代 total_samples!=len(factors)
  仅落一致性告警, 不阻断。无代际依据 (无锚点/无 dates_with_ic/无因子级 sample_size)
  时保留旧判据 ss==total_samples (fail-close)。

  旧源 data/factor_ic.json 已降级为"非权威历史快照":
  - 它只由 .scratch/ 下的临时脚本产出, 无 source/computed_at 元数据
  - 它自带 valid_factors/dead_factors 分段, 与 132d 口径结论相反(12 vs 1)
  - 门禁不再读它; 一旦权威源缺失, 本脚本必须 fail loud, 绝不回退到旧源假绿

因子层开关 (2026-10-19 L4 修复):
  config.json factor_layer_enabled (默认 false) 决定因子层是否参与选股打分。
  本报告把开关状态显式落盘 (factor_layer_enabled/factor_layer_source/
  factor_layer_note) —— "因子层关闭"是一等状态, 不靠"文件缺失"隐式表达;
  门禁判定口径本身不变 (valid 计数 >= threshold), 关闭因子层不会让门禁变绿。

权威源 schema (顶层 dict, factors 为 LIST):
  {
    "last_date": "2026-10-14",
    "freshness_days": 2,
    "total_samples": 28,
    "source": "pure_python_v10_exact_132d@unknown",
    "computed_at": "2026-10-16 08:06:09",
    "factors": [{"name": "...", "ic": 0.0428, "status": "valid"|"dead"}, ...]
  }
"""
import json
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))  # import config_loader (因子层硬开关读口)

import config_loader

# S3 权威源 (老大拍板口径)
IC_AUTHORITY = PROJECT_ROOT / "data" / "factor_ic" / "factor_ic_latest.json"
# 旧源: 只用于"对比提示", 不参与判定
IC_LEGACY = PROJECT_ROOT / "data" / "factor_ic.json"

GATE_THRESHOLD = 8
VALID_STATUS = "valid"
# 严口径交叉验证项 (老五 2026-10-23): 判定计数必须绑定这三项,
# 裸 |IC| 阈值在 10/21 注入案中被伪造大数穿透过 (真值靠 sample_size+历史一致性抓到)。
IC_MIN = 0.03  # 机械强度阈值, 与 20d 滚动监控 ic_min 同口径
# 判定口径 (2026-10-23 晚 老五落地, 总管裁定站位=严 + 团队技术共识 + 老大"@all 继续后续"指令):
# 门禁计数 = 严口径复合规则 (status=valid AND 三交叉项全过)。保守方向: 只收紧不放开,
# 门禁仍 FAIL (gap 2→3), 不影响策略冻结; 若后续改判宽口径, 将 GATE_STRICT_RULE 置 False 即回退。
GATE_STRICT_RULE = True

# [D-10 方案A] 引擎代际 → 因子级 sample_size 合法值锚点表 (截面日数, 三方会签后增删)
# 132d 池: total_samples=因子数(31), 因子级 sample_size=截面日数(132)
# v3 代:   total_samples=截面日数(199), 因子级 sample_size=截面日数(199)
_SS_GEN_ANCHORS = {
    "pure_python_v10_exact_132d": {132},  # 132d 池: 截面日数
    "calculate_v3": {199},                # v3 松散日期口径: 截面日数
}


def _engine_generation(source):
    """source → 引擎代际前缀 ('@' 之前部分)。"""
    return str(source or "").split("@", 1)[0]


def _legal_sample_sizes(ic_data):
    """D-10 方案A: 本文件因子级 sample_size 合法值集 (引擎代际感知)。

    三来源并集:
    ① _SS_GEN_ANCHORS 代际锚点 (source 前缀命中)
    ② dates_with_ic 文件自证字段 (本文件含 IC 的截面日数, 引擎无关真值)
    ③ 文件内众数因子级 sample_size (文件内一致性; 单因子被篡改会偏离众数 → 仍被 10/21 签名捕获)
    """
    legal = set()
    gen = _engine_generation(ic_data.get("source"))
    for key, vals in _SS_GEN_ANCHORS.items():
        if gen.startswith(key):
            legal |= vals
    dwi = ic_data.get("dates_with_ic")
    if isinstance(dwi, int) and not isinstance(dwi, bool) and dwi > 0:
        legal.add(dwi)
    factors = ic_data.get("factors", [])
    fcs = []
    for it in factors:
        if not isinstance(it, dict):
            continue
        s = it.get("sample_size")
        if isinstance(s, int) and not isinstance(s, bool) and s > 0:
            fcs.append(s)
    if fcs:
        legal.add(max(set(fcs), key=fcs.count))
    return legal


def _total_samples_semantics(ic_data):
    """total_samples 语义按引擎代际区分 (只报告, 不参与因子级交叉)。"""
    gen = _engine_generation(ic_data.get("source"))
    if gen.startswith("pure_python_v10_exact_132d"):
        return "池因子数 (=len(factors), 源头 factor_ic_132d_refresh.py)"
    if gen.startswith("calculate_v3"):
        return "截面日数 (松散日期口径)"
    return "代际未知; total_samples 不参与 sample_size 交叉"


def _cross_check(ic_data, effective_factors):
    """严口径交叉验证 (只报告, 不改判定): 对 status=valid 因子逐条做
    ① sample_size 代际合法集校验 (D-10 方案A: ss ∈ 代际锚点∪dates_with_ic∪文件内众数;
       缺字段/非正整数/偏离合法集 = 10/21 注入签名)
    ② |IC| >= IC_MIN 强度
    ③ 历史一致性 (存在 rolled_back/rollback_note 死池回滚记录 = 一致性交叉项)
    返回 (strict_valid_names, flagged, meta)。
    """
    total_samples = ic_data.get("total_samples")
    legal_ss = _legal_sample_sizes(ic_data)
    all_factors = ic_data.get("factors", []) if isinstance(ic_data, dict) else []
    # 死池历史: 任何带回滚注记的因子名 (10/17 真值 dead 池)
    dead_pool_history = set()
    if isinstance(all_factors, list):
        for it in all_factors:
            if isinstance(it, dict) and (it.get("rolled_back") or it.get("rollback_note")):
                dead_pool_history.add(it.get("name"))
    elif isinstance(all_factors, dict):
        for name, payload in all_factors.items():
            if isinstance(payload, dict) and (payload.get("rolled_back") or payload.get("rollback_note")):
                dead_pool_history.add(name)

    flagged, strict_valid = [], []
    for name, ic in effective_factors:
        flags = []
        item = next((it for it in all_factors
                     if isinstance(it, dict) and it.get("name") == name), None) \
            if isinstance(all_factors, list) else None
        if item is None and isinstance(all_factors, dict):
            item = all_factors.get(name)
        ss = item.get("sample_size") if isinstance(item, dict) else None
        if ss is None:
            flags.append("sample_size_missing")
        elif not isinstance(ss, int) or isinstance(ss, bool) or ss <= 0:
            flags.append(f"sample_size_malformed({ss!r})")
        elif legal_ss:
            # D-10 方案A: 与引擎代际合法样本格式匹配 (代际锚点∪dates_with_ic∪文件内众数)
            if ss not in legal_ss:
                flags.append(f"sample_size_mismatch({ss}∉{sorted(legal_ss)} 代际合法样本格式)")
        elif total_samples:
            # 无代际依据 (无锚点/无dates_with_ic/无因子级sample_size): 保留旧判据 fail-close
            if ss != total_samples:
                flags.append(f"sample_size_mismatch({ss}!={total_samples})")
        if ic is None or abs(ic) < IC_MIN:
            flags.append(f"ic_weak(|{ic if ic is not None else 'None'}|<{IC_MIN})")
        if name in dead_pool_history:
            flags.append("dead_pool_history")
        if not flags:
            strict_valid.append(name)
        else:
            flagged.append({"name": name, "ic": ic, "flags": flags})
    meta = {
        "ic_min": IC_MIN,
        "total_samples": total_samples,
        # D-10 方案A: total_samples 语义按引擎代际区分, 不再参与因子级交叉
        "total_samples_semantics": _total_samples_semantics(ic_data),
        "legal_sample_sizes": sorted(legal_ss) if legal_ss else None,
        "strict_valid_count": len(strict_valid),
        "strict_valid": strict_valid,
        "strict_gap": max(0, GATE_THRESHOLD - len(strict_valid)),
        "flagged": flagged,
        "rule": ("strict = status=='valid' AND sample_size∈代际合法样本格式"
                 "(_SS_GEN_ANCHORS锚点∪dates_with_ic∪文件内众数; 10/21注入签名=偏离合法集) "
                 "AND |IC|>=ic_min AND 死池历史一致; 裸|IC|计数禁用(10/21注入前科)"),
    }
    # 文件级一致性报告 (只报告不阻断): 132d 代 total_samples 应为池因子数
    if (isinstance(all_factors, list)
            and _engine_generation(ic_data.get("source")).startswith("pure_python_v10_exact_132d")
            and isinstance(total_samples, int) and total_samples != len(all_factors)):
        meta["total_samples_consistency_warn"] = (
            f"132d 代 total_samples={total_samples} != len(factors)={len(all_factors)}; "
            "按代际契约 total_samples 应为池因子数, 请核查上游 factor_ic_132d_refresh.py")
    return strict_valid, flagged, meta


def _parse_authority(ic_data):
    """解析权威源, 返回 (有效因子list, 非有效因子list)。

    权威源 factors 是 LIST of {name, ic, status};
    同时兼容 dict of {name: {ic/status}}, 防止上游改结构时整段被静默跳过。
    """
    factors = ic_data.get("factors", []) if isinstance(ic_data, dict) else ic_data

    effective, others = [], []
    if isinstance(factors, list):
        items = factors
    elif isinstance(factors, dict):
        # 兼容 dict-of-dict 形态: 把 key 作为 name 补进去
        items = []
        for name, payload in factors.items():
            if isinstance(payload, dict):
                item = dict(payload)
                item.setdefault("name", name)
                items.append(item)
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        ic = item.get("ic")
        status = item.get("status")
        if status == VALID_STATUS:
            effective.append((name, ic))
        else:
            others.append((name, ic))
    return effective, others


def main():
    """主函数"""
    print("=" * 70)
    print("门禁状态检查 (权威源: factor_ic_latest.json / 132d)")
    print("=" * 70)
    print()

    # 1. 权威源必须存在 — 缺失即 fail loud, 不回退旧源
    if not IC_AUTHORITY.exists():
        print(f"权威源不存在: {IC_AUTHORITY}")
        print("  已按老大拍板口径停止判定, 不回退 data/factor_ic.json (旧口径会假绿)")
        return 1

    with open(IC_AUTHORITY, 'r', encoding='utf-8') as f:
        ic_data = json.load(f)

    # 2. 统计有效因子 — status == 'valid'
    effective_factors, other_factors = _parse_authority(ic_data)
    # 2b. 严口径交叉验证 (老五 2026-10-23: 只报告, 不改变判定口径, 待老大拍板后翻转)
    strict_valid, flagged, cross_meta = _cross_check(ic_data, effective_factors)

    print("【IC权威源】")
    print(f"  文件      : {IC_AUTHORITY.relative_to(PROJECT_ROOT)}")
    print(f"  引擎      : {ic_data.get('source', 'unknown')}")
    print(f"  计算时间  : {ic_data.get('computed_at', 'unknown')}")
    print(f"  最后数据日: {ic_data.get('last_date', 'unknown')}")
    print(f"  陈旧天数  : {ic_data.get('freshness_days', 'unknown')}")
    print(f"  样本量    : {ic_data.get('total_samples', 'unknown')} (语义: {cross_meta['total_samples_semantics']})")
    print()
    print("【IC数据统计】(判定口径: status == 'valid')")
    print(f"  有效因子: {len(effective_factors)} 个")
    print(f"  其他因子: {len(other_factors)} 个 (含 dead / frozen / 未判定)")
    print()

    # 严口径交叉验证 — 判定依据 (GATE_STRICT_RULE) + 报告项
    print(f"【严口径交叉验证】({'判定规则' if GATE_STRICT_RULE else '报告项'}; 宽口径 status 计数={len(effective_factors)})")
    print(f"  严口径有效: {cross_meta['strict_valid_count']} 个 (status=valid 且 样本完整+|IC|>={IC_MIN}+死池一致)")
    print(f"  严口径缺口: {cross_meta['strict_gap']} 个")
    if flagged:
        for fitem in flagged:
            print(f"  [FLAG] {fitem['name']}: {', '.join(fitem['flags'])}")
    else:
        print("  [OK] 无交叉项标记")
    print(f"  说明: 10/21 注入前科 — 裸|IC|计数不可单独作判定, 必须绑定 sample_size 格式+历史一致性")
    print()

    # 因子层硬开关 (2026-10-19 L4): 每次运行打印当前值+来源; 关闭时把"关闭"
    # 写成显式状态落盘, 不再依赖"文件不存在"这种隐式失败表达关闭。
    factor_layer_on, factor_layer_src = config_loader.get_factor_layer_enabled()
    print("【因子层开关】")
    print(f"  factor_layer_enabled={factor_layer_on} (来源: {factor_layer_src})")
    if not factor_layer_on:
        print("  语义: false = 因子层不参与选股打分, 选股只走结构/执行性判据 (tech_score)")
    print()

    # 3. 门禁判定 (严口径复合规则: 2026-10-23 生效; GATE_STRICT_RULE=False 回退 status 口径)
    if GATE_STRICT_RULE:
        counted_factors, counted_n = strict_valid, cross_meta['strict_valid_count']
    else:
        counted_factors, counted_n = [n for n, _ in effective_factors], len(effective_factors)
    gate_passed = counted_n >= GATE_THRESHOLD

    print("【门禁判定】(严口径: status=valid AND sample_size完整 AND |IC|>=0.03 AND 死池一致)")
    print(f"  要求: >={GATE_THRESHOLD}个有效因子")
    print(f"  当前: {counted_n}个 (宽口径 status 计数参考: {len(effective_factors)}个)")
    print(f"  结果: {'通过' if gate_passed else '未通过'}")
    print()

    # 4. 显示有效因子详情 (严口径计数名单 + 被交叉项标记的)
    if effective_factors:
        print("【有效因子详情】(宽口径 status=valid)")
        for factor, ic in effective_factors[:10]:
            mark = "严口径计入" if (GATE_STRICT_RULE and factor in strict_valid) else ("严口径FLAG" if GATE_STRICT_RULE else "")
            print(f"  [OK] {factor}: IC={ic:+.4f} {mark}".rstrip())
        print()

    # 5. 旧源对比提示 (只读, 不参与判定)
    legacy_note = "未读取"
    if IC_LEGACY.exists():
        try:
            with open(IC_LEGACY, 'r', encoding='utf-8') as f:
                legacy = json.load(f)
            legacy_note = (f"存在但非权威(computed_at="
                           f"{legacy.get('computed_at', '无元数据')}, "
                           f"自带valid_factors={len(legacy.get('valid_factors', []))}个) "
                           f"— 口径与132d不一致, 不参与判定")
        except Exception as e:
            legacy_note = f"存在但解析失败({e})"
    print("【旧源 data/factor_ic.json】")
    print(f"  {legacy_note}")
    print()

    # 6. 更新门禁报告
    gate_report = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'gate_passed': gate_passed,
        'counted_factors': counted_n,
        'effective_factors': len(effective_factors),
        'threshold': GATE_THRESHOLD,
        'gap': max(0, GATE_THRESHOLD - counted_n),
        'effective_list': [{'name': f[0], 'ic': f[1]} for f in effective_factors],
        'frozen_list': [{'name': f[0], 'ic': f[1]} for f in other_factors],
        # S3 新增: 判定可追溯元数据
        'ic_authority': str(IC_AUTHORITY.relative_to(PROJECT_ROOT)),
        'ic_source_engine': ic_data.get('source', 'unknown'),
        'ic_computed_at': ic_data.get('computed_at', 'unknown'),
        'ic_last_date': ic_data.get('last_date', 'unknown'),
        'ic_freshness_days': ic_data.get('freshness_days'),
        'valid_rule': ("strict: status=='valid' AND sample_size格式 AND |IC|>=0.03 AND 死池一致"
                       if GATE_STRICT_RULE else "status == 'valid' (宽口径)"),
        # 严口径交叉验证 (老五 2026-10-23): 已生效为判定规则; 宽口径保留为参考计数
        'cross_check': {
            **{k: cross_meta[k] for k in ('ic_min', 'total_samples', 'total_samples_semantics',
                                          'legal_sample_sizes', 'strict_valid_count',
                                          'strict_valid', 'strict_gap', 'flagged', 'rule')},
            **({'total_samples_consistency_warn': cross_meta['total_samples_consistency_warn']}
               if 'total_samples_consistency_warn' in cross_meta else {}),
            'status': 'in_effect' if GATE_STRICT_RULE else 'reference_only',
            'note': ('判定口径=严口径复合规则 (2026-10-23 生效: 总管站位+团队共识+老大继续指令; 保守收紧, 门禁仍FAIL不影响冻结)；'
                      '回退宽口径: GATE_STRICT_RULE=False 一行翻转'
                      if GATE_STRICT_RULE else
                      '宽口径 status 计数生效, 严口径为参考报告项'),
        },
        'legacy_source_note': legacy_note,
        # L4 (2026-10-19): 因子层开关显式落盘 —— 读门禁报告的人能直接看到
        # "因子层是显式关闭的", 而不是从"文件缺失/valid 数不够"去猜。
        'factor_layer_enabled': factor_layer_on,
        'factor_layer_source': factor_layer_src,
        'factor_layer_note': (
            '因子层显式关闭: 不参与选股打分, 选股只走结构/执行性判据; '
            '本门禁判定口径不变 (valid 计数), 不因关闭而置绿'
            if not factor_layer_on else ''),
    }

    gate_file = PROJECT_ROOT / "data" / "factor_ic" / "factor_gate.json"
    gate_file.parent.mkdir(parents=True, exist_ok=True)

    with open(gate_file, 'w', encoding='utf-8') as f:
        json.dump(gate_report, f, ensure_ascii=False, indent=2)

    print(f"[OK] 门禁报告已更新: {gate_file.relative_to(PROJECT_ROOT)}")
    print()

    # 7. 返回结果
    if gate_passed:
        print("=" * 70)
        print("门禁通过")
        print("=" * 70)
        return 0
    else:
        print("=" * 70)
        print(f"门禁未通过，需补充 {gate_report['gap']} 个 valid 有效因子 (132d口径)")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
