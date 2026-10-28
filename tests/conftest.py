"""Pytest fixtures for laya tests + CI 环境依赖排除 (2026-10-28)"""
import os
import pytest

collect_ignore = [
    "test_5_transitions.py",
    "test_a12_assertion_effectiveness.py",
    "test_agency_combo.py",
    "test_agency_research.py",
    "test_atomic_json.py",
    "test_backtest_execution.py",
    "test_backtest_fast_inds.py",
    "test_board_data_sync.py",
    "test_board_server.py",
    "test_board_watchdog.py",
    "test_bootstrap_contract.py",
    "test_bot_config.py",
    "test_circuit_breaker.py",
    "test_closedloop_health.py",
    "test_compute_indicators_date.py",
    "test_cooldown_alias_load.py",
    "test_cooldown_integration.py",
    "test_d8_d9_tradability_filters.py",
    "test_dashboard_data_api.py",
    "test_data_flow_audit_alert_contract.py",
    "test_data_supply_scripts.py",
    "test_delisted_coverage.py",
    "test_determinism_anchor.py",
    "test_dl_completeness.py",
    "test_dl_import_degradation.py",
    "test_dl_integration.py",
    "test_dl_modules.py",
    "test_dl_predictor.py",
    "test_dl_retrain_pipeline.py",
    "test_doc_freshness.py",
    "test_error_recovery.py",
    "test_evolution_loop_p1v2.py",
    "test_evolution_loop_p2v2.py",
    "test_evolution_loop_p3v2.py",
    "test_evolution_loop_p5.py",
    "test_factor_decay_monitor.py",
    "test_factor_gate_blocking.py",
    "test_factor_ic.py",
    "test_factor_layer_sign.py",
    "test_factor_registry_audit.py",
    "test_factor_registry_isolated_ic.py",
    "test_factor_weights_drift.py",
    "test_factor_weights_loud_fail.py",
    "test_fallback_health.py",
    "test_feishu_alert.py",
    "test_feishu_send_chat.py",
    "test_fuse_trigger.py",
    "test_gap_filter.py",
    "test_gate.py",
    "test_gate_check_sample_size_generations.py",
    "test_gate_fn_integration.py",
    "test_git_sync_task_refresh.py",
    "test_hermes_config.py",
    "test_holdings_sync.py",
    "test_hs300_backtest.py",
    "test_integrated_picker.py",
    "test_key_scripts.py",
    "test_key_scripts_final.py",
    "test_key_scripts_fixed.py",
    "test_ladder_single_source.py",
    "test_layers.py",
    "test_layers_contract.py",
    "test_lhb_revival.py",
    "test_live_board_filter.py",
    "test_live_board_filter_integration.py",
    "test_load_universe_newest_first.py",
    "test_memory_verified_at.py",
    "test_model_config.py",
    "test_no_bare_core_imports.py",
    "test_no_phantom_script_refs.py",
    "test_no_remote_egress.py",
    "test_ops2_write_side.py",
    "test_p19_stop_loss_sensitivity.py",
    "test_p2a_retry_on_removal.py",
    "test_pattern_filter.py",
    "test_picker_entry_integration.py",
    "test_pipeline_equivalence.py",
    "test_precommit_hook.py",
    "test_r4c_pack_atomic.py",
    "test_review_gate.py",
    "test_risk_engine.py",
    "test_risk_monitor_s3.py",
    "test_role_permissions.py",
    "test_ruling_snapshot_alignment.py",
    "test_runner_lock.py",
    "test_s3_strategy_consistency.py",
    "test_scan_error_registry.py",
    "test_scan_performance.py",
    "test_scan_range_zero.py",
    "test_scoring_fixes.py",
    "test_self_audit_checkers.py",
    "test_stop_loss_single_source.py",
    "test_suppress_priority_layering.py",
    "test_system.py",
    "test_system_unified.py",
    "test_t2_weight_channel_convergence.py",
    "test_tdx_score.py",
    "test_trade_consistency.py",
    "test_trading_hours.py",
    "test_trading_hours_fail_close.py",
    "test_v36_param_usage.py",
    "test_ic_monitor_guard.py",
    "test_weekly_report_fake_positive.py",
]

@pytest.fixture(scope="session")
def model_path():
    """获取本地模型路径"""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models", "laya-typed-decisions"
    )


@pytest.fixture
def agent(model_path):
    """加载测试用的 Agent"""
    import sys
    os.environ['USE_TF'] = '0'
    
    if not os.path.exists(model_path):
        pytest.skip("Local model not found")
    
    from laya.agent import Agent
    return Agent(model_path)
