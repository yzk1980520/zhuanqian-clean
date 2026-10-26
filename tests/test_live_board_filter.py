# -*- coding: utf-8 -*-
"""test_live_board_filter.py — 实盘选股主板白名单剔除 (Kimi 拍板: 主板前缀白名单口径)

故障①根因: auto_live_pipeline.run_stock_selection 直接读 data/history_daily(9436只全板块),
唯一门槛是 `if len(data)<100`(数据条数), 从没调 should_include → 创业板/科创板/北证/ETF 全进评分。

公共 seam(原子真源, 放 tdx_data): is_tradable_code(code, name="")
  = 主板前缀白名单(复用 should_include) ∧ 非ST/非退市(复用 is_st_stock, 仅当传了 name)
生产(auto_live_pipeline / daily_pick)都 import 它, 不各写各的。

期望值全部来自独立字面真值(手写前缀规则 + 全池实跑), 不用被测实现造期望(防循环/tautology)。
"""
import sys
from pathlib import Path

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))


def _is_mainboard_literal(code: str) -> bool:
    """独立字面主板前缀规则(手写, 不 import should_include)——用作期望值真源。
    沪: 600/601/603/605; 深: 000/001/002/003; 裸码 5/6 开头当沪, 其余当深。"""
    has_prefix = code[:2].isalpha()
    num = code[2:] if has_prefix else code
    is_sh = (code[:2] == "sh") or (not has_prefix and num[:1] in "56")
    if is_sh:
        return num.startswith(("600", "601", "603", "605"))
    return num.startswith(("000", "001", "002", "003"))


def test_board_whitelist_unit():
    """主板留 / 创业板·科创·北证·ETF 剔 (14 只 = 7 主板 + 7 非主板, 独立归类)"""
    from tdx_data import is_tradable_code

    keep = ["sh600519", "sh603135", "sh601038", "sh600036",
            "sz000001", "sz002594", "sz000858"]
    drop = ["sz300001", "sz300750",          # 创业板
            "sh688001", "sh688981",          # 科创板
            "sh510090", "sh501038", "sh561360",  # ETF/基金(5开头)
            "bj430047", "bj832566"]          # 北证
    for c in keep:
        assert is_tradable_code(c) is True, f"{c} 应保留(主板)"
    for c in drop:
        assert is_tradable_code(c) is False, f"{c} 应剔除(非主板)"
    assert len([c for c in keep + drop if is_tradable_code(c)]) == 7


def test_st_and_delisted_excluded():
    """ST/*ST/退市 即使主板也剔 (仅当传 name; 不传 name 时纯按板块白名单放行)"""
    from tdx_data import is_tradable_code

    assert is_tradable_code("sh600519", "贵州茅台") is True    # 主板非ST 留
    assert is_tradable_code("sh600519", "ST某某") is False      # 主板 ST 剔
    assert is_tradable_code("sh600519", "*ST华仪") is False     # 主板 *ST 剔
    assert is_tradable_code("sh600002", "万科退") is False       # 退市 剔


def test_real_universe_passes_mainboard_only():
    """集成: 真实 9436 池, 保留集 = 独立字面主板白名单, 无一带创业板/科创/ETF/北证"""
    from tdx_data import is_tradable_code

    codes = [f.stem for f in sorted((BASE / "data" / "history_daily").glob("*.json"))
             if f.name != "download_errors.json"]
    assert len(codes) >= 9000, f"池太小({len(codes)}), 测试前提不成立"
    kept = [c for c in codes if is_tradable_code(c)]
    expected = [c for c in codes if _is_mainboard_literal(c)]   # 独立字面规则, 非 should_include
    assert set(kept) == set(expected), \
        f"保留 {len(kept)} 与独立字面主板 {len(expected)} 不一致"
    for c in kept:
        num = c[2:] if c[:2].isalpha() else c
        assert not num.startswith(("300", "301", "302", "303", "688", "689")), \
            f"{c} 创业板/科创前缀却进了保留集"
        assert num[:1] != "5", f"{c} 5开头(ETF)却进了保留集"
        assert c[:2] != "bj", f"{c} 北证前缀却进了保留集"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
