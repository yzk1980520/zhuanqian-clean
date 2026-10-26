#!/usr/bin/env python3
# 组件3 历史事件统计对照组 (老三, 用户裁定 10/26 前全落件): 按 @老五 冻结 L1 事件定义独立重算 600312
# 冻结规格 (laowu 件, 逐条照做):
#   事件日: close[i]/close[i-5] >= +3%  (日线 close, 收盘买入点)
#   后5日: close[i+4]/close[i]
#   窗口:  全史 + >=2024-10-01 近2年 双口径
#   重叠事件独立计数 (n 不剔重)
# 对照锚: 在档值 n=1738 亏钱53% / 近2年 n=133 亏钱56%
# 只读 TDX .day, 不写盘. 与 forward_prob_card 卡片值逐值比对, 一致=对照组 PASS
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.pipeline.tdx_data import get_tdx_data  # noqa: E402

TARGET = "sh600312"
ANCHOR_FULL_N, ANCHOR_FULL_LOSE = 1738, 53
ANCHOR_2Y_N, ANCHOR_2Y_LOSE = 133, 56


def events(recs, since=None):
    """按冻结定义产事件: 返回 (n, lose_pct, avg_pct, 小样本级). since=事件日期过滤(全库扫描, 前窗不丢)"""
    n, lose, fwd = 0, 0, []
    for i in range(5, len(recs)):
        if since is not None and _d(recs[i]) < since:
            continue
        if recs[i - 5]["close"] <= 0:
            continue
        if recs[i]["close"] / recs[i - 5]["close"] - 1.0 >= 0.03:  # +3% 事件
            if i + 4 >= len(recs):
                continue  # 后 5 日窗口不完整则不计
            n += 1
            f = recs[i + 4]["close"] / recs[i]["close"] - 1.0
            fwd.append(f)
            if f < 0:
                lose += 1
    avg = sum(fwd) / len(fwd) * 100 if fwd else float("nan")
    lvl = "OK" if n >= 30 else ("WEAK_SMALL" if n >= 10 else "MEAN_ONLY")
    return n, (lose / n * 100 if n else float("nan")), avg, lvl


recs = get_tdx_data(TARGET, days=10 ** 6)  # 全史
print(f"bars={len(recs)} last={recs[-1]['date']}")

# since: TDX date 字段可能是 date 对象或 str
import datetime as _dt

since = _dt.date(2024, 10, 1)


def _d(r):
    v = r["date"]
    return _dt.date.fromisoformat(str(v)[:10]) if isinstance(v, str) else v


n_f, lp_f, avg_f, lvl_f = events(recs, since=None)
n_2, lp_2, avg_2, lvl_2 = events(recs, since=since)
print(f"全史口径: n={n_f} 亏钱占比={lp_f:.1f}% 均值={avg_f:+.2f}% 级={lvl_f}  (锚 n={ANCHOR_FULL_N} 亏{ANCHOR_FULL_LOSE}%)")
print(f"近2年口径: n={n_2} 亏钱占比={lp_2:.1f}% 均值={avg_2:+.2f}% 级={lvl_2}  (锚 n={ANCHOR_2Y_N} 亏{ANCHOR_2Y_LOSE}%)")

ok_f = n_f == ANCHOR_FULL_N and round(lp_f) == ANCHOR_FULL_LOSE
ok_2 = n_2 == ANCHOR_2Y_N and round(lp_2) == ANCHOR_2Y_LOSE
print(f"对照组判定: 全史 {'PASS' if ok_f else 'MISMATCH'} / 近2年 {'PASS' if ok_2 else 'MISMATCH'}")
sys.exit(0 if (ok_f and ok_2) else 1)
