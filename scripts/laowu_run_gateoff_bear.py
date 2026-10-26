# -*- coding: utf-8 -*-
"""老五·熊市区间(2021-2024, MA250门关) 剔除环境门回测
LOOKBACK_DAYS=1600 → p10窗口≈2021-07(覆盖2022熊); STEP=20 控制扫描数; 门关=市场门关闭(全状态选股)
产物 → backtest_analysis/gateoff_bear/ (不碰 final_verify)
"""
import sys, os, time
os.chdir(r"D:/open code/zhuanqian")
os.environ.pop("PYTHONPATH", None)
sys.path.insert(0, ".")
import backtest as BT

BT.MARKET_GATE_SKIP_ENABLED = False   # 剔除环境门: 任何市场状态都选股
BT.LOOKBACK_DAYS = 1600              # 扩窗: 让p10落在2021, 覆盖2022熊市
BT.STEP = 20                          # 步长20: 扫描数≈40, 控制耗时
BT.P1_STRONG_BAN = False
print("[runner] gate-off + bear-window: LOOKBACK=%d STEP=%d" % (BT.LOOKBACK_DAYS, BT.STEP))
t0 = time.time()
BT.run_backtest(strategy="综合", output_dir=os.path.join("backtest_analysis", "gateoff_bear"))
print("[runner] DONE in %.0fs" % (time.time() - t0))
