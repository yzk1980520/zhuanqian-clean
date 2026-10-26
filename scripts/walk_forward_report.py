#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""walk_forward_report.py — walk-forward 衰减读数/告警入口 (现为阻断门禁的前门)。

历史
----
2026-10-17(W1) 建本脚本: 只做"读数 + 大声报", 退出码恒为 0 —— 因为"衰减是否升级为
阻塞门禁"是老大的政策决定, 当时未擅自改。
2026-10-17(W8) 老大拍板: 把衰减纳入**真正的阻断门禁**。判定逻辑下沉到
scripts/walk_forward_gate.py, 本脚本保留原调用面(Windows 计划任务
Zhuanqian_WalkForward.bat 调用的就是本脚本, 且 bat 末尾 `exit /b %RP_RC%`
会把它这里的退出码原样交给任务计划程序), 因此本脚本必须如实透传门禁退出码,
不得再吞成 0 —— 吞掉等于门禁白装。

退出码语义 (透传自 walk_forward_gate)
  0 = 门禁通过
  2 = 无可用结果文件/数据不可读 —— fail loud, 不伪装成通过
  3 = 被门禁阻断 (与 daily_pick.py 一致: 3=被门禁暂停)
"""
import os
import sys
from pathlib import Path

if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from walk_forward_gate import main as gate_main  # noqa: E402


if __name__ == "__main__":
    sys.exit(gate_main())
