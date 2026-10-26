#!/usr/bin/env python3
"""
data_format_converter.py — 将 JSON/CSV 数据转换为 Parquet 列式格式

功能：
  1. history_daily/*.json → history_daily.parquet (按日期分区)
  2. factors/*.json → factors.parquet (按日期分区)
  3. CSV 文件 → Parquet (保留 schema)
  4. 可选：保留原始 JSON 作为备份

用法：
  python scripts/convert_to_parquet.py [--dry-run] [--replace] [--compress zstd|snappy|none]
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def parse_args():
    parser = argparse.ArgumentParser(description='Convert data to Parquet format')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--replace', action='store_true', help='Replace JSON files with Parquet')
    parser.add_argument('--compress', choices=['zstd', 'snappy', 'none'], default='zstd',
                        help='Compression algorithm (default: zstd)')
    parser.add_argument('--compression-level', type=int, default=5, help='Compression level (1-9)')
    parser.add_argument('--output-dir', type=str, default='data/parquet',
                        help='Output directory for parquet files')
    return parser.parse_args()


def convert_history_daily(input_dir: str, output_dir: str, compress: str, compression_level: int, dry_run: bool):
    """Convert history_daily/*.json to partitioned Parquet"""
    print("\n" + "=" * 60)
    print("📁 Converting history_daily/")
    print("=" * 60)

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Count files and size
    json_files = list(input_path.glob('*.json'))
    total_size = sum(f.stat().st_size for f in json_files)
    print(f"\n📊 Input: {len(json_files)} files, {total_size/1024/1024:.1f}MB")

    if dry_run:
        print("🔍 DRY RUN: Would convert to Parquet")
        return

    # Read all JSON files
    print("\n📥 Reading JSON files...")
    start = time.time()
    all_records = []

    for i, json_file in enumerate(json_files):
        code = json_file.stem
        try:
            with open(json_file) as f:
                data = json.load(f)
            for row in data:
                row['code'] = code
            all_records.extend(data)

            if (i + 1) % 1000 == 0:
                print(f"   Progress: {i+1}/{len(json_files)} files, {len(all_records):,} records")
        except Exception as e:
            print(f"   ⚠️  Error reading {json_file}: {e}")

    read_time = time.time() - start
    print(f"   ✅ Read {len(all_records):,} records in {read_time:.1f}s")

    # Create DataFrame
    df = pd.DataFrame(all_records)
    print(f"\n📊 DataFrame: {df.shape}")

    # Convert types
    df['date'] = pd.to_datetime(df['date'])
    df['open'] = df['open'].astype('float32')
    df['high'] = df['high'].astype('float32')
    df['low'] = df['low'].astype('float32')
    df['close'] = df['close'].astype('float32')
    df['volume'] = df['volume'].astype('int64')
    df['amount'] = df['amount'].astype('float64')

    # Set index
    df = df.set_index(['date', 'code'])

    # Write partitioned Parquet
    print(f"\n💾 Writing Parquet ({compress} compression)...")
    start = time.time()

    output_file = output_path / 'history_daily.parquet'
    table = pa.Table.from_pandas(df.reset_index(), schema=None)
    pq.write_table(
        table,
        str(output_file),
        compression=compress,
        compression_level=compression_level,
        row_group_size=100000
    )

    write_time = time.time() - start
    output_size = output_file.stat().st_size

    print(f"   ✅ Written: {output_size/1024/1024:.1f}MB in {write_time:.1f}s")
    print(f"   📈 Compression ratio: {total_size/output_size:.1f}x")
    print(f"   💾 Space saved: {(total_size - output_size)/1024/1024:.1f}MB")

    # Save schema metadata
    metadata = {
        'source_dir': input_dir,
        'output_file': str(output_file),
        'format': 'parquet',
        'compression': compress,
        'row_group_size': 100000,
        'total_records': len(df),
        'total_size_original': total_size,
        'total_size_compressed': output_size,
        'compression_ratio': total_size / output_size,
        'columns': list(df.reset_index().columns),
        'dtypes': {col: str(df.reset_index()[col].dtype) for col in df.reset_index().columns},
        'created_at': datetime.now().isoformat()
    }

    with open(output_path / 'metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2, default=str)

    print(f"   📄 Metadata saved to {output_path / 'metadata.json'}")

    return output_file


def convert_factors(input_dir: str, output_dir: str, compress: str, compression_level: int, dry_run: bool):
    """Convert factors/*.json to partitioned Parquet"""
    print("\n" + "=" * 60)
    print("📁 Converting factors/")
    print("=" * 60)

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_files = list(input_path.glob('*.json'))
    total_size = sum(f.stat().st_size for f in json_files)
    print(f"\n📊 Input: {len(json_files)} files, {total_size/1024:.1f}KB")

    if dry_run:
        print("🔍 DRY RUN: Would convert to Parquet")
        return

    # Read and merge all factor files
    print("\n📥 Reading factor files...")
    all_records = []

    for i, json_file in enumerate(json_files):
        code = json_file.stem
        try:
            with open(json_file) as f:
                data = json.load(f)

            # Handle different factor file structures
            if isinstance(data, list):
                for row in data:
                    row['code'] = code
                    row['factor_date'] = row.get('date', datetime.now().date())
                all_records.extend(data)
            elif isinstance(data, dict):
                record = {'code': code}
                record.update(data)
                record['factor_date'] = record.get('date', datetime.now().date())
                all_records.append(record)
        except Exception as e:
            print(f"   ⚠️  Error reading {json_file}: {e}")

    if not all_records:
        print("   No records found")
        return None

    df = pd.DataFrame(all_records)
    print(f"\n📊 DataFrame: {df.shape}")

    # Write Parquet
    print(f"\n💾 Writing Parquet ({compress} compression)...")
    start = time.time()

    output_file = output_path / 'factors.parquet'
    table = pa.Table.from_pandas(df, schema=None)
    pq.write_table(
        table,
        str(output_file),
        compression=compress,
        compression_level=compression_level,
        row_group_size=50000
    )

    write_time = time.time() - start
    output_size = output_file.stat().st_size

    print(f"   ✅ Written: {output_size/1024:.1f}KB in {write_time:.1f}s")
    print(f"   📈 Compression ratio: {total_size/output_size:.1f}x")

    return output_file


def convert_csv(input_dir: str, output_dir: str, compress: str, dry_run: bool):
    """Convert CSV files to Parquet"""
    print("\n" + "=" * 60)
    print("📁 Converting CSV files")
    print("=" * 60)

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    csv_files = list(input_path.glob('*.csv'))
    print(f"\n📊 Found {len(csv_files)} CSV files")

    converted = []
    for csv_file in csv_files:
        print(f"\n📄 Processing: {csv_file.name}")

        if dry_run:
            print("   🔍 DRY RUN: Would convert to Parquet")
            continue

        try:
            # Read CSV
            df = pd.read_csv(csv_file)
            print(f"   Shape: {df.shape}, Columns: {list(df.columns)}")

            # Write Parquet
            output_file = output_path / f"{csv_file.stem}.parquet"
            table = pa.Table.from_pandas(df, schema=None)
            pq.write_table(table, str(output_file), compression=compress)

            original_size = csv_file.stat().st_size
            new_size = output_file.stat().st_size
            print(f"   ✅ {original_size/1024:.1f}KB → {new_size/1024:.1f}KB ({original_size/new_size:.1f}x)")

            converted.append(output_file)
        except Exception as e:
            print(f"   ⚠️  Error: {e}")

    return converted


def load_parquet_history(parquet_path: str) -> pd.DataFrame:
    """Load history_daily data from Parquet"""
    return pd.read_parquet(parquet_path)


def load_parquet_factors(parquet_path: str) -> pd.DataFrame:
    """Load factors data from Parquet"""
    return pd.read_parquet(parquet_path)


def main():
    args = parse_args()

    root = Path(__file__).parent.parent
    input_dirs = {
        'history_daily': root / 'data' / 'history_daily',
        'factors': root / 'data' / 'factors',
        'csv': root / 'data'
    }
    output_dir = root / args.output_dir

    print("=" * 60)
    print("🔄 Data Format Converter: JSON/CSV → Parquet")
    print("=" * 60)
    print(f"\n📍 Root: {root}")
    print(f"📍 Output: {output_dir}")
    print(f"📍 Compression: {args.compress}")
    print(f"📍 Dry run: {args.dry_run}")

    results = {}

    # Convert history_daily
    if input_dirs['history_daily'].exists():
        results['history_daily'] = convert_history_daily(
            str(input_dirs['history_daily']),
            str(output_dir / 'history_daily'),
            args.compress,
            args.compression_level,
            args.dry_run
        )

    # Convert factors
    if input_dirs['factors'].exists():
        results['factors'] = convert_factors(
            str(input_dirs['factors']),
            str(output_dir / 'factors'),
            args.compress,
            args.compression_level,
            args.dry_run
        )

    # Convert CSV files
    if input_dirs['csv'].exists():
        results['csv'] = convert_csv(
            str(input_dirs['csv']),
            str(output_dir / 'csv'),
            args.compress,
            args.dry_run
        )

    print("\n" + "=" * 60)
    print("✅ Conversion complete!")
    print("=" * 60)

    if results:
        print(f"\n📊 Results:")
        for name, result in results.items():
            if result:
                print(f"   {name}: {result}")

    return results


if __name__ == '__main__':
    main()
