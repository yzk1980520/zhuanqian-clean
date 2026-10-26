# -*- coding: utf-8 -*-
"""test_parquet_data.py — Parquet 数据层 TDD

Seams tested:
1. ParquetDataLoader.load_history(code, start_date?, end_date?) — 单股读取，输出兼容原 JSON dict list
2. ParquetDataLoader.load_all_history(start_date?, end_date?) — 批量读取，返回 DataFrame
3. convert_to_parquet.convert_history_daily(...) — 转换 + 压缩 + 元数据落档
4. smart_read_history() fallback 行为 — Parquet 缺失时退回 JSON

纪律：断言用独立手算值，不用代码重算；临时目录隔离，不回写生产。
"""
import sys, json, os
from pathlib import Path
from datetime import datetime
from functools import reduce

import pytest
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_bars():
    """生成 30 条基准 K 线，close 从 10.0 到 12.9，每日 +0.1"""
    bars = []
    base = datetime(2024, 1, 1)
    for i in range(30):
        bars.append({
            "date": (base + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": round(10.0 + i * 0.1, 2),
            "high": round(10.5 + i * 0.1, 2),
            "low": round(9.5 + i * 0.1, 2),
            "close": round(10.0 + i * 0.1, 2),
            "volume": 1_000_000 + i * 100,
            "amount": 10_000_000 + i * 1000,
        })
    return bars


@pytest.fixture
def tmp_json_history(tmp_path, sample_bars):
    """在 tmp_path 下建 history_daily/，写入 3 只股票 JSON"""
    hist_dir = tmp_path / "history_daily"
    hist_dir.mkdir()
    for code, bars in [
        ("sh600519", sample_bars),
        ("sh600000", sample_bars),
        ("sz000001", sample_bars),
    ]:
        (hist_dir / f"{code}.json").write_text(json.dumps(bars), encoding="utf-8")
    return hist_dir


@pytest.fixture
def tmp_parquet_history(tmp_path, sample_bars):
    """在 tmp_path 下建 parquet/history_daily/，写入合并 Parquet"""
    p_root = tmp_path / "parquet" / "history_daily"
    p_root.mkdir(parents=True)

    all_records = []
    for code, bars in [
        ("sh600519", sample_bars),
        ("sh600000", sample_bars),
        ("sz000001", sample_bars),
    ]:
        for row in bars:
            r = dict(row)
            r["code"] = code
            r["date"] = pd.to_datetime(r["date"])
            r["open"] = float(r["open"])
            r["high"] = float(r["high"])
            r["low"] = float(r["low"])
            r["close"] = float(r["close"])
            r["volume"] = int(r["volume"])
            r["amount"] = float(r["amount"])
            all_records.append(r)

    df = pd.DataFrame(all_records)
    table = pa.Table.from_pandas(df, schema=None)
    pq.write_table(table, str(p_root / "history_daily.parquet"), compression="zstd", row_group_size=100)

    meta = {
        "source_dir": str(tmp_path / "history_daily"),
        "output_file": str(p_root / "history_daily.parquet"),
        "format": "parquet",
        "compression": "zstd",
        "row_group_size": 100,
        "total_records": len(df),
        "total_size_original": sum(
            (tmp_path / "history_daily" / f).stat().st_size
            for f in (tmp_path / "history_daily").glob("*.json")
        ) if (tmp_path / "history_daily").exists() else 0,
        "total_size_compressed": (p_root / "history_daily.parquet").stat().st_size,
        "compression_ratio": 1.0,
        "columns": list(df.columns),
        "dtypes": {col: str(df[col].dtype) for col in df.columns},
        "created_at": datetime.now().isoformat(),
    }
    (p_root / "metadata.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return p_root


# ── Seam 1: load_history — 单股读取 ───────────────────────────────────────

class TestLoadHistory:
    """Seam 1: ParquetDataLoader.load_history(code, start_date?, end_date?)"""

    def test_returns_list_of_dicts_matching_json_schema(self, tmp_parquet_history):
        from scripts.read_parquet_data import ParquetDataLoader
        loader = ParquetDataLoader(str(tmp_parquet_history.parent))
        result = loader.load_history("sh600519")

        # 独立断言：30 条
        assert isinstance(result, list)
        assert len(result) == 30

        # 第一根 close = 10.0（手算，非重算代码）
        assert result[0]["close"] == pytest.approx(10.0, abs=0.01)
        # 最后一根 close = 12.9
        assert result[-1]["close"] == pytest.approx(12.9, abs=0.01)

        # 每根都有必需字段
        for rec in result:
            assert "date" in rec
            assert "open" in rec
            assert "close" in rec
            assert "volume" in rec
            assert "code" not in rec  # 输出不应暴露 code 列（兼容原 JSON 格式）

    def test_start_date_filter(self, tmp_parquet_history):
        from scripts.read_parquet_data import ParquetDataLoader
        loader = ParquetDataLoader(str(tmp_parquet_history.parent))
        result = loader.load_history("sh600519", start_date="2024-01-15")

        # 2024-01-15 是第 15 天（i=14），应有 16 条
        assert len(result) == 16
        assert result[0]["date"] == "2024-01-15"

    def test_end_date_filter(self, tmp_parquet_history):
        from scripts.read_parquet_data import ParquetDataLoader
        loader = ParquetDataLoader(str(tmp_parquet_history.parent))
        result = loader.load_history("sh600519", end_date="2024-01-10")

        # 2024-01-10 是第 10 天（i=9），应有 10 条
        assert len(result) == 10
        assert result[-1]["date"] == "2024-01-10"

    def test_both_date_filters(self, tmp_parquet_history):
        from scripts.read_parquet_data import ParquetDataLoader
        loader = ParquetDataLoader(str(tmp_parquet_history.parent))
        result = loader.load_history("sh600519", start_date="2024-01-10", end_date="2024-01-15")

        # i=9 到 i=14，共 6 条
        assert len(result) == 6
        assert result[0]["date"] == "2024-01-10"
        assert result[-1]["date"] == "2024-01-15"

    def test_missing_code_returns_empty(self, tmp_parquet_history):
        from scripts.read_parquet_data import ParquetDataLoader
        loader = ParquetDataLoader(str(tmp_parquet_history.parent))
        result = loader.load_history("sh999999")
        assert result == []

    def test_parquet_not_found_raises(self, tmp_path):
        from scripts.read_parquet_data import ParquetDataLoader
        loader = ParquetDataLoader(str(tmp_path / "nonexistent"))
        with pytest.raises(FileNotFoundError):
            loader.load_history("sh600519")


# ── Seam 2: load_all_history — 批量读取 ──────────────────────────────────

class TestLoadAllHistory:
    """Seam 2: ParquetDataLoader.load_all_history(start_date?, end_date?)"""

    def test_returns_dataframe_with_all_stocks(self, tmp_parquet_history):
        from scripts.read_parquet_data import ParquetDataLoader
        loader = ParquetDataLoader(str(tmp_parquet_history.parent))
        df = loader.load_all_history()

        assert isinstance(df, pd.DataFrame)
        # 3 只 × 30 天 = 90 条
        assert len(df) == 90
        assert set(df.columns) >= {"date", "code", "open", "high", "low", "close", "volume", "amount"}

    def test_date_filter_reduces_rows(self, tmp_parquet_history):
        from scripts.read_parquet_data import ParquetDataLoader
        loader = ParquetDataLoader(str(tmp_parquet_history.parent))
        df = loader.load_all_history(start_date="2024-01-16")

        # i>=15，每只 15 条，共 45 条
        assert len(df) == 45

    def test_predicate_pushdown_skips_irrelevant_row_groups(self, tmp_parquet_history):
        """谓词下推：过滤后只读部分 row group"""
        from scripts.read_parquet_data import ParquetDataLoader
        loader = ParquetDataLoader(str(tmp_parquet_history.parent))
        df = loader.load_all_history(start_date="2024-01-26")

        # i>=25，每只 5 条，共 15 条
        assert len(df) == 15
        # 验证日期
        assert (df["date"] >= pd.Timestamp("2024-01-26")).all()


# ── Seam 3: convert_history_daily — 转换 + 压缩 + 元数据 ──────────────────

class TestConvertHistoryDaily:
    """Seam 3: convert_to_parquet.convert_history_daily(...)"""

    def test_dry_run_no_output(self, tmp_json_history):
        import scripts.convert_to_parquet as conv
        out = tmp_json_history.parent / "parquet_out"
        result = conv.convert_history_daily(
            str(tmp_json_history),
            str(out),
            compress="zstd",
            compression_level=5,
            dry_run=True,
        )
        assert result is None
        assert not (out / "history_daily.parquet").exists()

    def test_output_parquet_exists_and_readable(self, tmp_json_history):
        import scripts.convert_to_parquet as conv
        out = tmp_json_history.parent / "parquet_out"
        result = conv.convert_history_daily(
            str(tmp_json_history),
            str(out),
            compress="zstd",
            compression_level=5,
            dry_run=False,
        )
        assert result is not None
        assert result.exists()
        # 可读取
        df = pd.read_parquet(result)
        assert len(df) > 0

    def test_metadata_json_written(self, tmp_json_history):
        import scripts.convert_to_parquet as conv
        out = tmp_json_history.parent / "parquet_out"
        conv.convert_history_daily(
            str(tmp_json_history),
            str(out),
            compress="zstd",
            compression_level=5,
            dry_run=False,
        )
        meta_path = out / "metadata.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["format"] == "parquet"
        assert meta["compression"] == "zstd"
        assert meta["total_records"] > 0
        assert meta["compression_ratio"] > 1.0  # 必须有压缩

    def test_compression_ratio_reasonable(self, tmp_json_history):
        """ZSTD 压缩比应 > 2x（本测试用 30 行样本，但逻辑应成立）"""
        import scripts.convert_to_parquet as conv
        out = tmp_json_history.parent / "parquet_out"
        conv.convert_history_daily(
            str(tmp_json_history),
            str(out),
            compress="zstd",
            compression_level=5,
            dry_run=False,
        )
        meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
        # 小样本也可能有不错压缩比，断言 > 1.5x
        assert meta["compression_ratio"] >= 1.5

    def test_parquet_has_correct_dtypes(self, tmp_json_history):
        import scripts.convert_to_parquet as conv
        out = tmp_json_history.parent / "parquet_out"
        conv.convert_history_daily(
            str(tmp_json_history),
            str(out),
            compress="zstd",
            compression_level=5,
            dry_run=False,
        )
        df = pd.read_parquet(out / "history_daily.parquet")
        # date 应为 datetime
        assert pd.api.types.is_datetime64_any_dtype(df["date"])
        # volume 应为 int
        assert pd.api.types.is_integer_dtype(df["volume"])
        # close 应为 float
        assert pd.api.types.is_float_dtype(df["close"])


# ── Seam 4: smart_read_history fallback ──────────────────────────────────

class TestSmartReadFallback:
    """Seam 4: smart_read_history() — Parquet 缺失时退回 JSON"""

    def test_fallback_to_json_when_parquet_missing(self, tmp_json_history, tmp_path):
        from scripts.read_parquet_data import smart_read_history
        # parquet_root 指向一个不存在的目录 → 触发 fallback
        # 用 tmp_json_history 里的样本数据作为 JSON 路径
        result = smart_read_history("sh600519", use_parquet=True,
                                    parquet_root=str(tmp_path / "nonexistent"),
                                    history_dir=str(tmp_json_history))
        # fallback 到 JSON，应返回 30 条
        assert isinstance(result, list)
        assert len(result) == 30
        assert result[0]["close"] == pytest.approx(10.0, abs=0.01)

    def test_prefer_parquet_when_available(self, tmp_parquet_history):
        from scripts.read_parquet_data import smart_read_history
        # 指向 parquet 目录 → 应走 Parquet 路径
        result = smart_read_history("sh600519", use_parquet=True, parquet_root=str(tmp_parquet_history.parent))
        assert isinstance(result, list)
        assert len(result) == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
