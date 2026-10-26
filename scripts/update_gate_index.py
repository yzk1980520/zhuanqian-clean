# DEPRECATED → use scripts/check_all.py backtest-gate
# -*- coding: utf-8 -*-
r"""环境门指数数据补全工具 (2026-09-26, 老大指令"要补")

问题: daily_signal.json 的 gate 里 sh_close/ma250/g5_pct 长期为 null,
作战台顶部只能显示"—"。

方案: 从本地通达信日线 D:\TDX\vipdoc\sh\lday\sh000001.day 解析上证指数,
计算 收盘/MA250/5日涨幅, 用 atomic_json.update_json 回填 daily_signal.json 的 gate
数据字段(只补数据, 不动 status/position_ratio —— 门控决策权不在此)。

用法:
  python scripts/update_gate_index.py            # 回填 daily_signal.json
  python -c "from update_gate_index import read_sh_index; print(read_sh_index())"

数据时效说明: .day 文件由通达信客户端连线时更新,
收盘数据最新为 TDX 最近一次下载的交易日(文件 mtime 可查)。
"""
import json
import os
import struct
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [scripts\\update_gate_index.py] CR-01: except Exception:", file=sys.stderr)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TDX_SH_DAY = r"D:\TDX\vipdoc\sh\lday\sh000001.day"
SIGNAL_FILE = os.path.join(ROOT, "data", "daily_signal.json")
MA_N = 250


def read_sh_index(path=TDX_SH_DAY):
    """解析上证指数本地日线, 返回指标 dict; 文件不可用返回 None。

    返回: {date, close, ma250, g5_pct, gate_open, n}
    日期为 yyyymmdd int → iso 字符串。
    """
    try:
        recs = []
        with open(path, "rb") as f:
            while True:
                d = f.read(32)
                if len(d) < 32:
                    break
                # P0修复2026-10-18: 第6字段成交额是 float32(此处未使用, 但保留正确结构防误用)
                di, o, h, l, c, amt, vol, _ = struct.unpack("<IIIIIfII", d)
                s = str(di)
                if len(s) != 8:
                    continue
                recs.append({
                    "date": "{}-{}-{}".format(s[:4], s[4:6], s[6:8]),
                    "close": c / 100.0,
                })
        if len(recs) < MA_N:
            return None
        closes = [r["close"] for r in recs]
        ma250 = sum(closes[-MA_N:]) / MA_N
        latest = closes[-1]
        g5 = (latest / closes[-6] - 1) * 100 if len(closes) >= 6 else None
        return {
            "date": recs[-1]["date"],
            "close": round(latest, 2),
            "ma250": round(ma250, 2),
            "g5_pct": round(g5, 2) if g5 is not None else None,
            "gate_open": bool(latest > ma250),
            "n": len(recs),
        }
    except Exception:
        print(f"🔴 [scripts\\update_gate_index.py] CR-01(return): except Exception:", file=sys.stderr)
        return None
def backfill_daily_signal(verbose=True):
    """把指数指标回填进 daily_signal.json 的 gate 数据字段(原子写)。"""
    idx = read_sh_index()
    if not idx:
        if verbose:
            print("❌ 无法读取TDX指数数据")
        return False

    from core.pipeline.atomic_json import update_json

    def _mutate(obj):
        gate = obj.get("gate")
        if not isinstance(gate, dict):
            gate = {}
            obj["gate"] = gate
        gate["sh_close"] = idx["close"]
        gate["ma250"] = idx["ma250"]
        gate["g5_pct"] = idx["g5_pct"]
        gate["gate_open"] = idx["gate_open"]
        gate["gate_date"] = idx["date"]
        gate["source"] = "tdx_local"
        gate["reason"] = "上证收盘/MA250 由本地TDX日线回填 ({})".format(
            datetime.now().strftime("%Y-%m-%d %H:%M"))
        # P2#9: 同步更新顶层 date 字段，确保 freshness 监控有效
        obj["date"] = idx["date"]
        return obj

    update_json(SIGNAL_FILE, _mutate)
    if verbose:
        print(f"✅ 回填完成: {idx['date']}, 收盘{idx['close']}, MA250={idx['ma250']}, 门{'开' if idx['gate_open'] else '关'}")
    return True


if __name__ == "__main__":
    ok = backfill_daily_signal()
    sys.exit(0 if ok else 1)
