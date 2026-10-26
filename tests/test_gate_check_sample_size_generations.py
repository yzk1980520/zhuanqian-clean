# -*- coding: utf-8 -*-
"""
tests/test_gate_check_sample_size_generations.py — D-10 gate_check sample_size 判据代际错位回归锁
(2026-10-25, t_4d5e81c5; 三方会签后随 gate_check.py 修复一起落)

背景:
  口径切换 (calculate_v3 → pure_python_v10_exact_132d) 后, 权威源 132d 池文件里
  total_samples=31 (池因子数, 源头 factor_ic_132d_refresh.py L945), 而因子级
  sample_size=132 (截面日数)。gate_check 旧判据 `ss != total_samples` 跨代际比较
  两个不同语义字段 → 唯一 valid 因子 TURN5 被误 flag sample_size_mismatch(132!=31)
  → 门禁 1/8 降为 0/8。

方案A 判据 (scripts/gate_check.py):
  sample_size 合法集 = _SS_GEN_ANCHORS 引擎代际锚点表 (132d={132}, v3={199})
                     ∪ 文件自证字段 dates_with_ic
                     ∪ 文件内众数因子级 sample_size
  无代际依据 (无锚点命中/无 dates_with_ic/无因子级 sample_size) → 回退旧判据
  ss==total_samples (fail-close)。total_samples 语义按代际报告, 不参与因子级交叉。

本组行为级断言 (防退化 + 防假绿复辟):
  T1 132d 代现形 (total_samples=31 / TURN5 ss=132) → TURN5 不入 flagged, strict_valid=['TURN5']
  T2 10/21 注入签名灵敏度: valid 因子 ss 伪造为 total_samples 值 (31) → 仍被
     sample_size_mismatch flag (旧判据下 ss==total_samples 会放行, 必须拦住)
  T3 v3 代 (total_samples=199=截面日数, 因子级 ss=199) → 通过 (代际锚点 {199})
  T4 未知代际无锚点/无 dates_with_ic → 回落到文件内众数一致性 (与众数一致过 / 偏离众数 flag;
     全文件无因子级 ss 时合法集为空, 缺字段 fail-close)
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from gate_check import _cross_check, _legal_sample_sizes  # noqa: E402


def _valid_pairs(ic_data):
    """模拟 main()/_parse_authority: 传入 status=valid 因子的 (name, ic) 对。"""
    return [(it["name"], it.get("ic")) for it in ic_data["factors"]
            if isinstance(it, dict) and it.get("status") == "valid"]


def _make_132d(turn5_ic=-0.0661, turn5_ss=132, total_samples=31):
    """132d 代现形: 31 因子池 (30 dead + TURN5 valid), 因子级 ss=截面日数 132。"""
    factors = [{"name": f"F{i}", "ic": 0.01, "status": "dead", "sample_size": 132}
               for i in range(30)]
    factors.append({"name": "TURN5", "ic": turn5_ic, "status": "valid", "sample_size": turn5_ss})
    return {
        "last_date": "2026-10-23",
        "total_samples": total_samples,
        "source": "pure_python_v10_exact_132d@3a6e4236",
        "dates_with_ic": 132,
        "factors": factors,
    }


def test_132d_turn5_no_longer_flagged():
    """T1 (验收#1): 132d 代 total_samples=31 vs TURN5 ss=132 → 不再 sample_size_mismatch。"""
    ic_data = _make_132d()
    strict_valid, flagged, meta = _cross_check(ic_data, _valid_pairs(ic_data))
    flag_names = [f["name"] for f in flagged]
    assert "TURN5" not in flag_names, f"TURN5 被误 flag: {flagged}"
    assert strict_valid == ["TURN5"], f"strict_valid 应为 ['TURN5'], 实际 {strict_valid}"
    assert meta["strict_valid_count"] == 1
    assert not any("sample_size_mismatch" in fl for f in flagged for fl in f["flags"])
    # 判据可追溯元数据落 meta
    assert meta["total_samples_semantics"]
    assert 132 in (meta["legal_sample_sizes"] or []), f"合法集缺 132: {meta['legal_sample_sizes']}"
    assert "total_samples_consistency_warn" not in meta, (
        f"total_samples=31 应等于 len(factors)=31, 不该告警: {meta.get('total_samples_consistency_warn')}")


def test_132d_total_samples_consistency_warn():
    """文件级一致性: 132d 代 total_samples != len(factors) → 仅告警, 不阻断判定。"""
    ic_data = _make_132d(total_samples=99)
    strict_valid, flagged, meta = _cross_check(ic_data, _valid_pairs(ic_data))
    assert "total_samples_consistency_warn" in meta, "132d 代 total_samples=99!=31 应落一致性告警"
    # 告警不改判定: TURN5 仍 strict valid
    assert strict_valid == ["TURN5"]


def test_injected_sample_size_still_flagged():
    """T2 (10/21 注入签名): 伪造 ss=31 (恰好=total_samples) 的 valid 因子 → 必须被 flag。

    旧判据 ss==total_samples 会放行此伪造; 方案A 合法集={132}, 31∉合法集 → 拦住。
    """
    ic_data = _make_132d(turn5_ss=31)
    strict_valid, flagged, _ = _cross_check(ic_data, _valid_pairs(ic_data))
    assert strict_valid == [], "伪造 ss=31 的 valid 因子不得计入 strict_valid"
    assert any(f["name"] == "TURN5" and any("sample_size_mismatch" in fl for fl in f["flags"])
               for f in flagged), f"注入签名未被捕获: {flagged}"


def test_v3_generation_passes():
    """T3: v3 代 total_samples=199=截面日数, 因子级 ss=199 → 代际锚点 {199} 通过。"""
    ic_data = {
        "last_date": "2026-10-20",
        "total_samples": 199,
        "source": "calculate_v3@abc123",
        "factors": [
            {"name": "TURN5", "ic": -0.0868, "status": "valid", "sample_size": 199},
            {"name": "F1", "ic": 0.01, "status": "dead", "sample_size": 199},
        ],
    }
    strict_valid, flagged, meta = _cross_check(ic_data, _valid_pairs(ic_data))
    assert "TURN5" not in [f["name"] for f in flagged], f"v3 代 ss=199 被误 flag: {flagged}"
    assert strict_valid == ["TURN5"]
    assert 199 in (meta["legal_sample_sizes"] or [])


def test_unknown_engine_no_anchor_uses_in_file_consistency():
    """T4: 未知代际 (无锚点命中/无 dates_with_ic) → 判据回落到文件内众数一致性:
    - T4a 全文件无因子级 ss → 合法集为空, valid 因子缺字段 → sample_size_missing (fail-close)
    - T4b valid 因子 ss 与文件内众数一致 → 过 (众数即文件内真值, 无需锚点表)
    - T4c valid 因子 ss 偏离众数 → sample_size_mismatch (10/21 单因子篡改签名, 无锚点也拦)

    注: 合法集为空的角落 (无任何因子级正整型 ss) 下, 代码保留旧判据
    ss==total_samples 兜底 (fail-close, 一行防御性路径, 正常文件不可达)。
    """
    def _unknown(turn5_ss, dead_ss=None):
        dead = [{"name": f"F{i}", "ic": 0.01, "status": "dead",
                 **({"sample_size": dead_ss} if dead_ss is not None else {})}
                for i in range(30)]
        return {
            "last_date": "2026-10-25",
            "total_samples": 31,
            "source": "unknown_engine_v99@z",
            "factors": dead + [
                {"name": "TURN5", "ic": -0.0661, "status": "valid", "sample_size": turn5_ss},
            ],
        }

    # T4a: 全文件无因子级 ss → 合法集为空, 缺字段即 fail-close
    ic_a = _unknown(None)
    ic_a["factors"][-1].pop("sample_size")
    assert _legal_sample_sizes(ic_a) == set(), "无代际依据时合法集必须为空"
    sv, fl, _ = _cross_check(ic_a, _valid_pairs(ic_a))
    assert sv == [] and any(f["name"] == "TURN5" and "sample_size_missing" in f["flags"]
                            for f in fl), f"缺字段未 fail-close: {fl}"

    # T4b: valid ss=40 与文件内众数 40 一致 → 过 (众数一致性, 无锚点也可判定)
    ic_b = _unknown(40, dead_ss=40)
    assert _legal_sample_sizes(ic_b) == {40}
    sv, fl, _ = _cross_check(ic_b, _valid_pairs(ic_b))
    assert sv == ["TURN5"], f"ss 与文件内众数一致应过: {fl}"

    # T4c: valid ss=7 偏离众数 40 → sample_size_mismatch (单因子篡改签名)
    ic_c = _unknown(7, dead_ss=40)
    sv, fl, _ = _cross_check(ic_c, _valid_pairs(ic_c))
    assert sv == [], "偏离文件内众数的 ss 不得计入 strict_valid"
    assert any(f["name"] == "TURN5" and any(x.startswith("sample_size_mismatch") for x in f["flags"])
               for f in fl), f"无锚点时单因子篡改未被捕获: {fl}"


def test_missing_sample_size_still_flagged():
    """缺字段签名 (10/21 注入另一形态) 保留: valid 因子无 sample_size → sample_size_missing。"""
    ic_data = _make_132d()
    ic_data["factors"][-1].pop("sample_size")
    sv, fl, _ = _cross_check(ic_data, _valid_pairs(ic_data))
    assert sv == []
    assert any(f["name"] == "TURN5" and "sample_size_missing" in f["flags"] for f in fl)
