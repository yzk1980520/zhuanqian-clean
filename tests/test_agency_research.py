# -*- coding: utf-8 -*-
"""test_agency_research.py — agency 专家库接入研究层 (B方案, RED→GREEN)

seam (3个):
  1. load_expert_prompt(library, expert_id) — 解析 agency-agents-zh 专家 md
     (frontmatter name + 正文 system prompt), 用 tmp 假库隔离, 不依赖真实 clone
  2. build_market_brief(code, tmp K线) — 公开行情摘要文本, 独立手算断言 (非 tautology)
  3. run_expert_review(code, mock LLM) — 产物落 expert-layer/ + manifest 只加
     expert_layer 键 (phases 原样), trade_log/holdings 零改动
纪律: 专家输出=研究输入, 不进决策链, 不碰交易数据。
"""
import sys, json
from pathlib import Path
from datetime import date, timedelta

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "team"))


# ── 1. 专家 prompt 解析 ─────────────────────────────────────────────
def _make_expert_lib(tmp_path):
    lib = tmp_path / "agency"
    (lib / "finance").mkdir(parents=True)
    (lib / "finance" / "finance-investment-researcher.md").write_text(
        "---\nname: 投资研究员\ndescription: 专业投资研究员\nemoji: 🔍\ncolor: green\n---\n\n"
        "# 投资研究员\n你是投资研究员...关键规则...可证伪触发条件...\n",
        encoding="utf-8")
    return lib


def test_load_expert_prompt_parses_name_and_body(tmp_path):
    from agency_research import load_expert_prompt
    lib = _make_expert_lib(tmp_path)
    name, prompt = load_expert_prompt(str(lib), "finance-investment-researcher")
    assert name == "投资研究员"
    # 独立锚点: 正文含 marker, 且不含 frontmatter 自身
    assert "关键规则" in prompt
    assert "name: 投资研究员" not in prompt


def test_load_expert_prompt_missing_raises(tmp_path):
    from agency_research import load_expert_prompt
    lib = _make_expert_lib(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_expert_prompt(str(lib), "finance-nonexistent")


# ── 2. 公开行情摘要 (独立手算, 非重算) ─────────────────────────────
def _bars_from(start, n=30, base_close=10.0):
    out = []
    s = date(2026, 9, 1)
    for i in range(n):
        out.append({"date": (s + timedelta(days=i)).isoformat(),
                    "open": base_close, "close": base_close + i * 0.1,
                    "high": base_close + i * 0.1 + 0.5, "low": base_close + i * 0.1 - 0.5,
                    "volume": 1_000_000 + i * 100, "amount": 10_000_000})
    return out


def test_build_market_brief_independent_values(tmp_path):
    from agency_research import build_market_brief
    hist = tmp_path / "history_daily"
    hist.mkdir()
    bars = _bars_from(date(2026, 9, 1), n=30, base_close=10.0)
    (hist / "sh600519.json").write_text(json.dumps(bars), encoding="utf-8")

    brief = build_market_brief("sh600519", history_dir=str(hist))
    # 手算: 末根 close = 10.0 + 29*0.1 = 12.9; 第1根(90天窗口=30根)close=10.0
    # 30日涨幅 = (12.9-10.0)/10.0*100 = 29.0% (独立期望值, 非重算代码)
    assert "sh600519" in brief
    assert "12.9" in brief                      # 末根 close (独立值)
    assert "29" in brief and "29.0" in brief or "29.00" in brief  # 30日涨幅≈29.0%
    # 红线: 摘要不得含持仓/交易记录字段名
    for banned in ("holdings", "trade_log", "因子权重", "factor_weights"):
        assert banned not in brief


# ── 3. 专家评审跑通: 产物 + manifest 只增不删 + 交易数据零改动 ──────
def test_run_expert_review_mock(tmp_path, monkeypatch):
    import agency_research
    from agency_research import run_expert_review

    # 临时根: 隔离 deliverables / trade_log / holdings
    root = tmp_path
    (root / "data").mkdir(parents=True)
    (root / "trade_log.json").write_text(json.dumps({"trade": [1]}), encoding="utf-8")
    (root / "data" / "holdings.json").write_text(
        json.dumps({"holdings": []}), encoding="utf-8")
    before_hold = (root / "data" / "holdings.json").read_text(encoding="utf-8")
    before_tl = (root / "trade_log.json").read_text(encoding="utf-8")

    monkeypatch.setattr(agency_research, "PROJECT_ROOT", root)

    fake_lib = _make_expert_lib(tmp_path)
    (tmp_path / "history_daily").mkdir()
    (tmp_path / "history_daily" / "sh600519.json").write_text(
        json.dumps(_bars_from(date(2026, 9, 1), n=30)), encoding="utf-8")

    calls = []

    def fake_llm(system_prompt, user_brief, model=None):
        calls.append((system_prompt, user_brief))
        return "MOCK_RESEARCH_OUTPUT_MARKER"

    files = run_expert_review(
        "sh600519",
        expert_ids=["finance-investment-researcher"],
        library_path=str(fake_lib),
        history_dir=str(tmp_path / "history_daily"),
        llm=fake_llm,
    )

    # ① 产物文件含 mock 输出 (独立 marker)
    assert len(files) == 1
    out = Path(files[0])
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "MOCK_RESEARCH_OUTPUT_MARKER" in content
    assert "研究输入" in content                      # 免责声明在位

    # ② LLM 收到的 system prompt = 专家正文 (含锚点), user brief 含股票代码
    assert "关键规则" in calls[0][0]
    assert "sh600519" in calls[0][1]

    # ③ manifest 只加 expert_layer, phases 模板原样
    mf = root / "deliverables" / "trading-agent" / "sh600519" / "manifest.json"
    assert mf.exists(), "manifest 应生成于 deliverables/trading-agent/sh600519/"
    m = json.loads(mf.read_text(encoding="utf-8"))
    assert m["expert_layer"]["experts"] == ["finance-investment-researcher"]
    assert m["phases"]["phase1"]["market"]["done"] is False   # 模板 phases 未被污染

    # ④ 交易数据零改动 (红线)
    assert (root / "data" / "holdings.json").read_text(encoding="utf-8") == before_hold
    assert (root / "trade_log.json").read_text(encoding="utf-8") == before_tl


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
