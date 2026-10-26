# -*- coding: utf-8 -*-
"""core.scoring — FACTOR/SCORING 族包（基地化 S3，2026-10-22，卡 t_d1d79d96）。

收录根级 17 因子评分模块（自仓库根迁入 core/scoring/，原根级 import 位点
已全部改写为 core.scoring.* 前缀; 根级旧位置留 re-export 兼容 shim）：
- scoring_engine          统一 final 评分引擎 (P0-1)
- factor_registry         因子登记/IC历史 唯一真源
- factor_cache            扫描/历史数据缓存
- factor_gate_v2          因子门禁 v2.1 (CLI: python core/scoring/factor_gate_v2.py)
- factor_ic_monitor       因子 IC 监控 (FactorICMonitor)
- factor_analysis_phase2  因子分析 Phase2
- pca_factor_synthesis    PCA 因子合成
- tdx_score               扁平兼容入口文件 (注: 根级 tdx_score/ 目录包同名遮蔽本文件,
                          一切 `import tdx_score` 解析到根级包, 本文件仅存留位)
- tdx_score_original      TDX 评分引擎 (Phase C-1 拆分自 tdx_core)
- tdx_strategies          TDX 策略配置 (STRATEGIES/load_strategy)
- tdx_factor_v2           V2 新因子计算
- tdx_indicators          TDX 技术指标计算
- tdx_breakout_detector   真突破特征检测指标
- breakout_filter         真突破检测集成
- earnings_gap            净利润断层策略
- gap_channel             断层通道策略池
- financial_filter        财务健康/舞弊评分

注意: 本 __init__ 不主动 import 子模块（子模块依赖 numpy/pandas/akshare，
保持轻量导入），按需以 core.scoring. 前缀导入子模块。
根级同名 .py shim 为兼容层（re-export + __main__ 委托），S7 收官后统一处置。
"""
