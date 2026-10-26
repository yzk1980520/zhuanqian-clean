#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R1-2: RULING 快照对齐验收测试
覆盖场景：
  S1: hash 一致 → judge 按 body 值裁决（等价性：行为零变化）
  S2: hash 漂移（旧→新，如 35%/60%）→ 报"口径过期"而非静默拒
  S3: 无 hash 字段 → 容错降级为旧逻辑
"""

import sys
import os

# 项目根目录加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from utils.ruling_hash import (
    compute_ruling_hash,
    extract_ruling_hash_from_body,
    validate_ruling_alignment,
    judge_accept_with_ruling_check,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

# S4/S5 归档后真址 (2026-10-24 T051 C2 对齐): 2026-10-22 文档瘦身将活跃层裁决文档
# 归档至 docs/archive/20261022-cleanup/ (归档件哈希 d4b280f2ce22 与 EXPECTED_HASH 一致, 已验证)。
# 归档指针源 (archive/) 只读, 改判口径须走 docs/ 新件 + TSS 流程。
RULING_DOC = "docs/archive/20261022-cleanup/DD门禁口径裁定-20261015-新基线重裁.md"
EXPECTED_HASH = "d4b280f2ce22"  # sha1(content.rstrip())[:12]，v2 尾部归一化


@pytest.fixture(scope="session")
def current_hash():
    """计算当前 RULING 文档 hash（用于 S1 对照）"""
    return compute_ruling_hash(RULING_DOC)


@pytest.fixture
def body_with_matching_hash(current_hash):
    """S1: body 内嵌 hash 与当前一致"""
    return f"""
## RULING 快照对齐

| 字段 | 值 |
|------|-----|
| 适用 RULING | RULING-DD-20261015 |
| 快照 hash | {current_hash} |
| 裁定期望值 | DD ≤ 60% |

DD = 56.66%
""".strip()


@pytest.fixture
def body_with_drifted_hash():
    """S2: body 内嵌 hash 为旧值（35% 口径时代）"""
    return """
## RULING 快照对齐

| 字段 | 值 |
|------|-----|
| 适用 RULING | RULING-DD-20261015 |
| 快照 hash | aaa111bbb222 |
| 裁定期望值 | DD ≤ 35% |

DD = 35%
""".strip()


@pytest.fixture
def body_without_hash_field():
    """S3: body 无 RULING 快照表格"""
    return "DD = 35%\n任务内容：修复门禁。"


# ── 辅助：hash 提取 ───────────────────────────────────────────────────────────

class TestExtractHash:
    def test_extract_from_table(self):
        body = "| 快照 hash | b3c17cb2a1ee |"
        assert extract_ruling_hash_from_body(body) == "b3c17cb2a1ee"

    def test_extract_from_table_with_spaces(self):
        body = "|  快照  hash  |  abc123def456  |"
        assert extract_ruling_hash_from_body(body) == "abc123def456"

    def test_no_hash_field(self):
        body = "DD = 35%\n修复门禁。"
        assert extract_ruling_hash_from_body(body) is None

    def test_malformed_hash_too_short(self):
        body = "| 快照 hash | abc123 |"  # 6位不够
        assert extract_ruling_hash_from_body(body) is None

    def test_malformed_hash_too_long(self):
        body = "| 快照 hash | b3c17cb2a1eee |"  # 13位
        assert extract_ruling_hash_from_body(body) is None


# ── S1: hash 一致 → judge 按 body 值裁决（等价性：行为零变化） ─────────────────

class TestS1_HashConsistent:
    def test_accept_when_dd_below_threshold(self, body_with_matching_hash, current_hash):
        """S1a: DD=56.66% ≤ 60% → ACCEPT"""
        result = judge_accept_with_ruling_check(
            body_with_matching_hash,
            {"RULING-DD": RULING_DOC},
            threshold=0.60,
        )
        assert result["verdict"] == "ACCEPT"
        assert "56.66%" in result["reason"]
        assert result["ruling_check"]["aligned"] is True
        assert result["ruling_check"]["current_hash"] == current_hash

    def test_reject_when_dd_above_threshold(self, current_hash):
        """S1b: DD=70% > 60% → REJECT（不变行为）"""
        body = f"""
## RULING 快照对齐
| 快照 hash | {current_hash} |
| 裁定期望值 | DD ≤ 60% |
DD = 70%
""".strip()
        result = judge_accept_with_ruling_check(body, {"RULING-DD": RULING_DOC}, threshold=0.60)
        assert result["verdict"] == "REJECT"
        assert result["ruling_check"]["aligned"] is True

    def test_hash_matches_computed(self, current_hash):
        """S1c: 嵌入 hash 与 compute_ruling_hash 返回一致"""
        assert current_hash == EXPECTED_HASH


# ── S2: hash 漂移 → judge 报"口径过期"（非静默按旧值拒） ─────────────────────

class TestS2_HashDrift:
    def test_drift_reports_expired(self, body_with_drifted_hash):
        """S2主场景：旧 hash(aaa111bbb222) ≠ 当前 hash → BLOCKED + 口径过期"""
        result = judge_accept_with_ruling_check(
            body_with_drifted_hash,
            {"RULING-DD": RULING_DOC},
            threshold=0.60,
        )
        assert result["verdict"] == "BLOCKED"
        assert "口径过期" in result["reason"]
        assert "aaa111bbb222" in result["reason"]
        assert EXPECTED_HASH in result["reason"]
        ruling = result["ruling_check"]
        assert ruling["aligned"] is False
        assert ruling["embedded_hash"] == "aaa111bbb222"
        assert ruling["current_hash"] == EXPECTED_HASH

    def test_drift_not_silent_reject(self, body_with_drifted_hash):
        """S2反例：确认 NOT 返回 REJECT（否则是旧静默行为）"""
        result = judge_accept_with_ruling_check(
            body_with_drifted_hash,
            {"RULING-DD": RULING_DOC},
            threshold=0.60,
        )
        assert result["verdict"] != "REJECT"  # 关键：不是静默拒

    def test_drift_35_to_60_scenario(self, current_hash):
        """S2具体漂移：35%任务单(hash=旧) vs 60% RULING(hash=新)"""
        old_body = """
## RULING 快照对齐
| 快照 hash | c0ffee000000 |
| 裁定期望值 | DD ≤ 35% |
DD = 35%
""".strip()
        result = judge_accept_with_ruling_check(old_body, {"RULING-DD": RULING_DOC}, threshold=0.60)
        assert result["verdict"] == "BLOCKED"
        assert "口径过期" in result["reason"]


# ── S3: 无 hash 字段 → 容错降级 ───────────────────────────────────────────────

class TestS3_NoHashField:
    def test_fallback_to_old_logic(self, body_without_hash_field):
        """S3: 无 hash → 降级旧逻辑，不抛异常"""
        result = judge_accept_with_ruling_check(
            body_without_hash_field,
            {"RULING-DD": RULING_DOC},
            threshold=0.60,
        )
        # 35% ≤ 60% → ACCEPT（旧逻辑同样结果，证明容错正常）
        assert result["verdict"] in ("ACCEPT", "REJECT")
        assert result["ruling_check"].get("skipped") is True


# ── 工具函数直接验证 ──────────────────────────────────────────────────────────

class TestComputeRulingHash:
    def test_hash_is_12_hex_chars(self, current_hash):
        assert len(current_hash) == 12
        assert all(c in "0123456789abcdef" for c in current_hash)

    def test_hash_is_stable(self):
        """同一文件两次计算结果一致"""
        h1 = compute_ruling_hash(RULING_DOC)
        h2 = compute_ruling_hash(RULING_DOC)
        assert h1 == h2 == EXPECTED_HASH

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            compute_ruling_hash("docs/nonexistent_ruling.md")

    def test_trailing_whitespace_hash_unchanged(self):
        """v2: rstrip 尾部空白/换行后 hash 不变——加尾换行再算应得相同 hash"""
        import hashlib, tempfile, os
        # 读原文档，加一个尾换行后 rstrip 应回到原内容
        path = os.path.join(os.path.dirname(__file__), '..', RULING_DOC)
        with open(path, 'rb') as f:
            original = f.read()
        # 模拟有额外尾换行的版本
        modified = original + b'\n\n'
        h_original = hashlib.sha1(original.rstrip()).hexdigest()[:12]
        h_modified = hashlib.sha1(modified.rstrip()).hexdigest()[:12]
        assert h_original == h_modified == EXPECTED_HASH, \
            f"rstrip 归一化失败: orig={h_original}, modified={h_modified}"


class TestValidateAlignment:
    def test_aligned(self, current_hash):
        r = validate_ruling_alignment(current_hash, {"RULING-DD": RULING_DOC})
        assert r["aligned"] is True
        assert "对齐" in r["message"]

    def test_not_aligned(self):
        r = validate_ruling_alignment("deadbeef0000", {"RULING-DD": RULING_DOC})
        assert r["aligned"] is False
        assert "过期" in r["message"]
        assert r["embedded_hash"] == "deadbeef0000"
        assert r["current_hash"] == EXPECTED_HASH

    def test_missing_doc(self):
        r = validate_ruling_alignment(EXPECTED_HASH, {"RULING-DD": "docs/missing.md"})
        assert r["aligned"] is False
        assert "不存在" in r["message"]


# ── 端到端：漂移场景红 → 报"口径过期"实证 ────────────────────────────────────

class TestEndToEnd_DriftScenario:
    """
    验收场景：构造35%/60%漂移任务单 → 断言 judge 报"口径过期"
    而非静默按35%拒。
    """

    def test_35_percent_task_blocked_by_60_percent_ruling(self, current_hash):
        """35%口径任务单（旧hash）面对60%口径RULING（新hash）→ BLOCKED"""
        old_hash = "c0ffee000000"  # 假设旧RULING的hash
        body = f"""
# 任务单：旧门禁修复

## RULING 快照对齐

| 字段 | 值 |
|------|-----|
| 快照 hash | {old_hash} |
| 裁定期望值 | DD ≤ 35% |

DD = 35%
""".strip()
        result = judge_accept_with_ruling_check(body, {"RULING-DD": RULING_DOC}, threshold=0.60)
        assert result["verdict"] == "BLOCKED", \
            f"预期 BLOCKED，实际 {result['verdict']}: {result['reason']}"
        assert "口径过期" in result["reason"]

    def test_60_percent_task_accepted_by_60_percent_ruling(self, body_with_matching_hash):
        """60%口径任务单（新hash）面对60%口径RULING → ACCEPT（不变行为）"""
        result = judge_accept_with_ruling_check(body_with_matching_hash, {"RULING-DD": RULING_DOC}, threshold=0.60)
        assert result["verdict"] == "ACCEPT"
        assert result["ruling_check"]["aligned"] is True
