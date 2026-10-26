#!/usr/bin/env python3
"""
read_parquet_data.py — 从 Parquet 文件读取数据的工具函数

提供与原有 JSON 读取接口兼容的 Parquet 读取方式。
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Union

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


class ParquetDataLoader:
    """Parquet 数据加载器，提供与 JSON 读取兼容的接口"""

    def __init__(self, parquet_root: str = 'data/parquet'):
        self.parquet_root = Path(parquet_root)
        self._cache = {}

    def load_history(self, code: str, start_date: Optional[str] = None,
                     end_date: Optional[str] = None) -> List[Dict]:
        """
        加载单只股票的历史数据（兼容原有 JSON 接口）

        Args:
            code: 股票代码 (如 'sh600519')
            start_date: 开始日期 (如 '2024-01-01')
            end_date: 结束日期 (如 '2024-12-31')

        Returns:
            历史数据列表，格式与原 JSON 一致
        """
        parquet_path = self.parquet_root / 'history_daily' / 'history_daily.parquet'

        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

        # 先读全量，再在 Pandas 层过滤（兼容旧版 pyarrow）
        df = pd.read_parquet(str(parquet_path))

        # 日期过滤
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            if start_date:
                df = df[df['date'] >= pd.Timestamp(start_date)]
            if end_date:
                df = df[df['date'] <= pd.Timestamp(end_date)]

        # 过滤指定股票代码
        if code:
            df = df[df['code'] == code]

        # 转换为原 JSON 格式
        records = []
        for _, row in df.iterrows():
            records.append({
                'date': row['date'].strftime('%Y-%m-%d') if pd.notna(row['date']) else None,
                'open': float(row['open']) if pd.notna(row['open']) else None,
                'high': float(row['high']) if pd.notna(row['high']) else None,
                'low': float(row['low']) if pd.notna(row['low']) else None,
                'close': float(row['close']) if pd.notna(row['close']) else None,
                'volume': int(row['volume']) if pd.notna(row['volume']) else None,
                'amount': float(row['amount']) if pd.notna(row['amount']) else None,
            })

        return records

    def load_all_history(self, start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> pd.DataFrame:
        """
        加载所有股票的历史数据（返回 DataFrame）

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame with columns: date, code, open, high, low, close, volume, amount
        """
        parquet_path = self.parquet_root / 'history_daily' / 'history_daily.parquet'

        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

        df = pd.read_parquet(str(parquet_path))
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            if start_date:
                df = df[df['date'] >= pd.Timestamp(start_date)]
            if end_date:
                df = df[df['date'] <= pd.Timestamp(end_date)]
        return df

    def load_factors(self, code: Optional[str] = None) -> pd.DataFrame:
        """
        加载因子数据

        Args:
            code: 股票代码 (可选，不指定则加载所有)

        Returns:
            DataFrame with factor data
        """
        parquet_path = self.parquet_root / 'factors' / 'factors.parquet'

        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

        df = pq.read_table(str(parquet_path)).to_pandas()

        if code:
            df = df[df['code'] == code]

        return df

    def load_csv_data(self, csv_name: str) -> pd.DataFrame:
        """
        加载 CSV 转换后的 Parquet 数据

        Args:
            csv_name: CSV 文件名 (不含扩展名)

        Returns:
            DataFrame
        """
        parquet_path = self.parquet_root / 'csv' / f"{csv_name}.parquet"

        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

        return pd.read_parquet(str(parquet_path))

    def get_metadata(self) -> Dict:
        """获取 Parquet 文件的元数据"""
        metadata_path = self.parquet_root / 'history_daily' / 'metadata.json'

        if metadata_path.exists():
            with open(metadata_path) as f:
                return json.load(f)

        return {}


def read_history_json_legacy(code: str, history_dir: str = 'data/history_daily') -> List[Dict]:
    """
    原有 JSON 读取方式（保留作为 fallback）

    Args:
        code: 股票代码
        history_dir: 历史数据目录

    Returns:
        历史数据列表
    """
    json_path = os.path.join(history_dir, f'{code}.json')

    if not os.path.exists(json_path):
        return []

    with open(json_path) as f:
        return json.load(f)


def smart_read_history(code: str, use_parquet: bool = True, parquet_root: str = 'data/parquet',
                       history_dir: str = 'data/history_daily', **kwargs) -> Union[List[Dict], pd.DataFrame]:
    """
    智能读取历史数据，优先使用 Parquet，fallback 到 JSON

    Args:
        code: 股票代码
        use_parquet: 是否尝试使用 Parquet
        parquet_root: Parquet 根目录
        history_dir: JSON 历史数据目录（fallback 用）
        **kwargs: 传递给 Parquet 读取的参数

    Returns:
        历史数据（列表或 DataFrame）
    """
    if use_parquet:
        try:
            loader = ParquetDataLoader(parquet_root)
            return loader.load_history(code, **kwargs)
        except Exception as e:
            print(f"⚠️  Parquet read failed: {e}, fallback to JSON")

    # Fallback to JSON
    return read_history_json_legacy(code, history_dir=history_dir)


# 便捷函数
def load_history_parquet(parquet_path: str, code: Optional[str] = None,
                         start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> pd.DataFrame:
    """直接加载 Parquet 历史数据"""
    loader = ParquetDataLoader(parquet_path)
    return loader.load_all_history(start_date, end_date) if code is None else pd.DataFrame(loader.load_history(code))


def load_factors_parquet(parquet_path: str, code: Optional[str] = None) -> pd.DataFrame:
    """直接加载 Parquet 因子数据"""
    loader = ParquetDataLoader(parquet_path)
    return loader.load_factors(code)
