# -*- coding: utf-8 -*-
"""确定性锚点可复现回归 (老三 2026-09-27, 台账C件3 + 老五③升级, 交@laowu验收)。

老五③升级: P2v3 锚点块哈希自相矛盾(字段判 PASS 但留痕 r1≠r2), 根因=v3 runner 里
"字段级相等"与"哈希"用了不同排除集。验收口径升级为**可复现**: 锚点函数跑出的哈希
必须与落盘值一致才算过——即同一函数 + 同一参数 => 同一哈希, 可被回归直接调用复核。

被测模块 = 根目录 determinism_anchor.py (canonical_hash / anchor_pair):
  - 字段级相等 与 规范化哈希 共用同一 excluded_fields(显式参数, 写死进留痕)
  - 哈希序列化参数(algo/encoding/sort_keys/ensure_ascii/separators/前缀)全记录
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.determinism_anchor import anchor_pair, canonical_hash, DEFAULT_EXCLUDED


class TestCanonicalHashReproducible:
    def test_same_dict_same_params_same_hash(self):
        """同 dict + 同参数 => 同哈希 (跨次调用可复现, 老五"可复现"判据)。"""
        d = {"b": 2, "a": 1, "nested": {"x": 10, "y": [1, 2, 3]}}
        h1 = canonical_hash(d)
        h2 = canonical_hash(d)
        assert h1 == h2, "同参数同dict哈希必须可复现"
        assert len(h1) == 16, "默认前缀16位"

    def test_key_order_independent(self):
        """字段顺序无关 (sort_keys=True) — dict 插入顺序不同但内容同 => 同哈希。"""
        h1 = canonical_hash({"a": 1, "b": 2})
        h2 = canonical_hash({"b": 2, "a": 1})
        assert h1 == h2, "哈希与字段顺序无关"

    def test_different_excluded_diverges(self):
        """排除集不同 => 哈希不同 (这正是 v3 自相矛盾的根源, 锁定'必须显式传同一组')。"""
        d = {"config": "cfg_x", "ret": 100}
        h_with = canonical_hash(d, excluded_fields=("config",))
        h_without = canonical_hash(d, excluded_fields=())
        assert h_with != h_without, "排除集不一致哈希必不同 → 留痕必须记录排除集"

    def test_hash_params_recorded(self):
        """anchor_pair 留痕必须记录全序列化参数(哈希仅留痕, 字段级相等才是判据)。"""
        a = {"config": "x", "_fuse_tag": "r1", "ret": 100}
        b = {"config": "y", "_fuse_tag": "r2", "ret": 100}
        r = anchor_pair(a, b)  # 默认排除 config/_fuse_tag/generated
        p = r["sha_params"]
        for k in ("algo", "encoding", "sort_keys", "ensure_ascii", "separators",
                  "hash_prefix", "excluded_fields"):
            assert k in p, f"哈希参数留痕缺 {k}"
        assert p["excluded_fields"] == list(DEFAULT_EXCLUDED)


class TestAnchorPairEquivalence:
    def test_equal_reports_consistent_hash(self):
        """字段级相等时, 同参数哈希也必一致 (sha_consistent 与 equal 同向, 消除自相矛盾)。"""
        a = {"config": "x", "ret": 346.2, "trades": 48}
        b = {"config": "y", "ret": 346.2, "trades": 48}
        r = anchor_pair(a, b, excluded_fields=("config",))
        assert r["equal"] is True, "去 config 后字段应相等"
        assert r["sha_consistent"] is True, "字段相等时同参数哈希必须一致"

    def test_differs_reports_mismatch(self):
        """内容真不同 → equal=False 且 sha_consistent=False (双向一致, 无自相矛盾)。"""
        a = {"config": "x", "ret": 346.2}
        b = {"config": "y", "ret": -26.0}
        r = anchor_pair(a, b, excluded_fields=("config",))
        assert r["equal"] is False
        assert r["sha_consistent"] is False

    def test_same_keyset_detects_drift(self):
        """键集漂移(一份多一份少) → same_keyset=False, 触发键漂移检测。"""
        a = {"config": "x", "ret": 1}
        b = {"config": "y", "ret": 1, "extra": 2}
        r = anchor_pair(a, b, excluded_fields=("config",))
        assert r["same_keyset"] is False, "键集不一致必须被检出"


class TestNonNativeGuard:
    def test_native_fields_no_non_native(self):
        """全原生字段 → non_native_fields=None (无 default=str 触发, 留痕干净)。"""
        a = {"config": "x", "ret": 346.2, "trades": 48, "win_rate": 33.3}
        b = {"config": "y", "ret": 346.2, "trades": 48, "win_rate": 33.3}
        r = anchor_pair(a, b, excluded_fields=("config",))
        assert r["sha_params"]["non_native_fields"] is None, "全原生不得有 non_native 留痕"

    def test_nonnative_type_recorded_and_warned(self, capsys):
        """非原生字段(date对象) → 走 default=str, non_native_fields 记名 + 打 WARN(不静默)。"""
        from datetime import date
        a = {"config": "x", "ret": 346.2, "end_date": date(2026, 9, 18)}
        b = {"config": "y", "ret": 346.2, "end_date": date(2026, 9, 18)}
        r = anchor_pair(a, b, excluded_fields=("config",))
        # 字段级相等仍 True (date==date), 哈希仍一致
        assert r["equal"] is True
        assert r["sha_consistent"] is True
        # 关键: 非原生类型被记名进留痕 (老五③加固)
        assert "date" in (r["sha_params"]["non_native_fields"] or []), "date 触发 default=str 必须记名"
        # WARN 必须打到 stderr (不静默吞)
        captured = capsys.readouterr()
        assert "default=str 兜底触发" in captured.err, "非原生兜底必须告警, 不得静默污染留痕"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
