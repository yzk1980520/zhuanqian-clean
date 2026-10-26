#!/bin/bash
# Run backtest with memory limits and logging
cd /d/open\ code/zhuanqian
PYTHONPATH= python backtest_rotation.py > data/phase2_backtest.log 2>&1
echo "Backtest completed at $(date)" >> data/phase2_backtest.log
echo "Exit code: $?" >> data/phase2_backtest.log
