# -*- coding: utf-8 -*-
"""统一配置加载器 — 单一数据源原则 (2026-10-05 P1修复)

作用:
  所有模块统一通过本模块读取配置，避免硬编码和配置分散。
  
  历史:
    2026-08-23 原始版本: 基础load_contract()函数
    2026-10-05 P1修复: 扩展为完整配置加载器，统一风险参数入口

使用方式:
  from config_loader import get_stop_loss, get_trailing_config, load_config
  
  # 获取止损比例
  sl_pct = get_stop_loss("趋势")  # 返回 0.10
  
  # 获取完整配置
  cfg = load_config()
"""
import json
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from typing import Dict, Any, Optional

# 缓存配置（避免重复读取文件）
_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_PROJECT_PATH: Optional[str] = None
# 因子权重单一真源缓存 (T2a 落地 2026-10-20 t_7819f7e3): 仓库根 factor_weights.json
_FACTOR_WEIGHTS_CACHE: Optional[Dict[str, float]] = None
_FACTOR_WEIGHTS_DOC: Optional[Dict[str, Any]] = None

# 保持向后兼容
# P0修复(20261023): 基地化S4迁入core/pipeline/后, dirname(__file__)指向core/pipeline/而非仓库根,
# 导致 _CONTRACT_PATH/load_config() 找 core/pipeline/config.json 崩溃 (gate_check.py 实锤)。
# 改为从模块目录向上找仓库根标记(config.json), 迁移/回滚均稳定。
def _find_project_root() -> str:
    for parent in Path(__file__).resolve().parents:
        if (parent / 'config.json').exists():
            return str(parent)
    return str(Path(__file__).resolve().parent)

PROJECT = _find_project_root()
_CONTRACT_PATH = os.path.join(PROJECT, "config.json")


def set_project_path(path: str):
    """设置项目路径（默认使用当前目录）"""
    global _PROJECT_PATH
    _PROJECT_PATH = path


def _get_project_path() -> str:
    """获取项目根目录"""
    if _PROJECT_PATH:
        return _PROJECT_PATH
    # P0修复(20261023): 原实现 Path(__file__).parent 在S4迁移后指向core/pipeline/,
    # 与模块级 PROJECT 同病, 统一走仓库根锚点。
    return PROJECT


def load_config() -> Dict[str, Any]:
    """
    加载config.json（带缓存）
    
    Returns:
        dict: 完整配置字典
    """
    global _CONFIG_CACHE
    
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    
    project_path = _get_project_path()
    config_path = Path(project_path) / 'config.json'
    
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        _CONFIG_CACHE = json.load(f)
    
    return _CONFIG_CACHE


def get_stop_loss(strategy: str = "趋势") -> float:
    """
    获取止损比例（统一入口）
    
    Args:
        strategy: 策略类型（全仓/突破/断层/北向精选/趋势/抄底/综合）
        
    Returns:
        float: 止损比例（如 0.10 表示10%）
    """
    try:
        from risk_rules import STRATEGY_STOP_LOSS_PCT
        return STRATEGY_STOP_LOSS_PCT.get(strategy, 0.10)
    except ImportError:
        cfg = load_config()
        return cfg.get('stop_loss_pct', 0.10)


def get_time_stop_days() -> int:
    """获取时间止损天数"""
    try:
        from risk_rules import TIME_STOP_TRADING_DAYS
        return TIME_STOP_TRADING_DAYS
    except ImportError:
        cfg = load_config()
        return cfg.get('time_stop', {}).get('max_hold_days', 120)


def get_chase_ban_pct() -> float:
    """获取追高关闭阈值"""
    try:
        from risk_rules import CHASE_BAN_PCT
        return CHASE_BAN_PCT
    except ImportError:
        cfg = load_config()
        return cfg.get('trade_params', {}).get('chase_ban_pct', 4.0)


def get_trailing_config() -> Dict[str, Any]:
    """获取移动止盈配置"""
    cfg = load_config()
    return cfg.get('trailing', {})


def get_market_gate_config() -> Dict[str, Any]:
    """获取环境门配置"""
    cfg = load_config()
    return cfg.get('market_gate', {})


def get_factor_weights() -> Dict[str, float]:
    """获取因子权重 — 单一真源: 仓库根 factor_weights.json 的 weights 段 (T2a 单源落地, t_7819f7e3 2026-10-20)。

    历史:
      2026-10-20 之前: 读 config.json 的 factor_weights 段。当时生产评分实际只有
      LOWER_SHADOW 0.15 一个因子在跑, 其余键 0.0 —— 老五 R0 打回实锤
      (t_69d56592: 三文件与备份 ZERO_DIFF, 10-18 假报修复时真源确为 config.json)。
      现在: 读 factor_weights.json (版本化单一真源; v2.6 = 4 活跃因子, 净和 5.5)。
    契约:
      - 文件缺失 / JSON 损坏 / weights 段缺失或空 / 非数值 (含数值字符串与 bool,
        不做 float() 强转放行) → loud fail (RuntimeError),
        禁止静默回退 config.json (SOUL#9 / 任务单红线)。
      - 同进程内缓存结果, 经 clear_config_cache() 统一清除。
    注意:
      config.json 的 factor_weights 段仍被 tdx_strategies.load_strategy() 通道读取
      (独立通道, 不在本函数职责内); 生产评分链路 (auto_live_pipeline) 以本函数为唯一权重真源。
    """
    global _FACTOR_WEIGHTS_CACHE, _FACTOR_WEIGHTS_DOC
    if _FACTOR_WEIGHTS_CACHE is not None:
        return _FACTOR_WEIGHTS_CACHE

    path = Path(PROJECT) / 'factor_weights.json'
    if not path.exists():
        raise RuntimeError(
            f'Loud fail (因子权重单一真源缺失): {path} 不存在。禁止静默回退 config.json。'
            f'回滚点: factor_weights.json.bak_T2rework_20261017')
    try:
        doc = json.loads(path.read_text(encoding='utf-8-sig'))
    except (json.JSONDecodeError, OSError, ValueError) as e:
        raise RuntimeError(f'Loud fail (因子权重单一真源损坏): {path} 不可读: {e}') from e
    if not isinstance(doc, dict):
        raise RuntimeError(f'Loud fail (因子权重单一真源结构非法): {path} 顶层不是 JSON 对象')
    weights = doc.get('weights')
    if not isinstance(weights, dict) or not weights:
        raise RuntimeError(f'Loud fail (因子权重单一真源结构非法): {path} 的 weights 段缺失/空/非dict')
    for k, v in weights.items():
        # docstring 承诺"非数值 -> loud fail"; 旧实现用 float(v) 强转校验, 会静默放过
        # 数值字符串 ("0.5" -> 0.5) 与 bool (float(True)==1.0) —— 与契约相反, 故严格判定。
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise RuntimeError(
                f'Loud fail (因子权重单一真源结构非法): {path} 存在非数值权重: '
                f'键 {k!r} 为 {type(v).__name__} ({v!r}), 期望 int/float (不做 float() 强转)')
    _FACTOR_WEIGHTS_CACHE = {k: float(v) for k, v in weights.items()}
    _FACTOR_WEIGHTS_DOC = doc
    return _FACTOR_WEIGHTS_CACHE


def get_backtest_factor_weights() -> Dict[str, float]:
    """回测侧因子 z-score 权重通道 — T2 通道收敛 (2026-10-26, 老三, 任务单 T2)。

    病根: 回测链 (backtest/__init__.py) 的因子 z-score 权重读静态 STRATEGIES 表
    (tdx_strategies.py) / config.json factor_weights 段 (旧通道), 与实盘链
    (auto_live_pipeline.get_factor_weights → factor_weights.json v2.6 单一真源) 分叉,
    两链对同一截面算出不同因子加权 z 分 (等价检查实测最大差 167.14, 2026-10-26)。

    本函数 = 回测侧 z-score 权重通道的唯一读口:
      - 与实盘同源: 经 get_factor_weights() 读仓库根 factor_weights.json (单一真源),
        不引入任何新数值 (通道对齐, 权重值零改动 — 任务单红线)。
      - 继承 get_factor_weights() 的 loud-fail 校验 (缺失/损坏/非数值 → RuntimeError,
        禁止静默回退 config.json 旧通道, SOUL#9)。
      - 缓存语义与 get_factor_weights() 一致 (同进程缓存, clear_config_cache() 统一清除),
        返回浅拷贝防调用方意外改写单一真源缓存。
    证据链: scripts/check_weight_equivalence.py (36 股日对, 收敛后逐对差 <0.01 → exit 0)。
    """
    return dict(get_factor_weights())


def get_factor_weights_meta() -> Dict[str, Any]:
    """因子权重真源元数据 (version/updated_at) — 供生产打印, 杜绝谎报 (10-18 谎报事故修复)。

    先触发 get_factor_weights() 的 loud-fail 校验 (复用缓存), 再返回真源文档顶层字段。
    """
    get_factor_weights()
    return dict(_FACTOR_WEIGHTS_DOC or {})


def get_factor_layer_enabled():
    """因子层硬开关 -> (enabled: bool, source: str)。

    2026-10-19 L4 修复: 因子层能否启用由显式配置决定, 不由"判不出来的 valid 数"
    隐式决定 (132d 窗口 28 因子三值判定实测 valid=0, IC 统计判定在当前效应量
    水平下原理上不可达 —— QA: deliverables/QA-28因子k实测与三值判定-20261018.md)。

    语义: enabled=False 时因子层不参与选股打分, 选股只走结构/执行性判据
    (tech_score); 置 true 前必须先有符号处理 (负 IC 因子不得按正权重加分)。

    来源优先级由调用方叠加 CLI (auto_live_pipeline --factor-layer/--no-factor-layer);
    本函数只回答"配置文件 vs 默认值": config.json 缺省即 False (fail-safe)。
    """
    cfg = load_config()
    if "factor_layer_enabled" in cfg:
        return bool(cfg["factor_layer_enabled"]), "config.json"
    return False, "默认值(config.json 缺省 false)"


def get_validation_requirements() -> Dict[str, Any]:
    """获取回测验证要求"""
    cfg = load_config()
    return cfg.get('validation', {})


def clear_config_cache():
    """清除配置缓存（含因子权重单一真源缓存, T2a 落地 2026-10-20 t_7819f7e3）"""
    global _CONFIG_CACHE, _FACTOR_WEIGHTS_CACHE, _FACTOR_WEIGHTS_DOC
    _CONFIG_CACHE = None
    _FACTOR_WEIGHTS_CACHE = None
    _FACTOR_WEIGHTS_DOC = None


def get_all_risk_params() -> Dict[str, Any]:
    """
    获取所有风控参数（用于监控和验证）
    
    Returns:
        dict: 完整风控参数集合
    """
    try:
        from risk_rules import (
            STRATEGY_STOP_LOSS_PCT,
            TIME_STOP_TRADING_DAYS,
            TIME_STOP_WARNING_DAYS,
            CHASE_BAN_PCT,
            MARKET_STOP_ADJUST,
            SIGNAL_BONUS_ADJUST,
        )
        return {
            'stop_loss': STRATEGY_STOP_LOSS_PCT,
            'time_stop_days': TIME_STOP_TRADING_DAYS,
            'time_stop_warning_days': TIME_STOP_WARNING_DAYS,
            'chase_ban_pct': CHASE_BAN_PCT,
            'market_adjust': MARKET_STOP_ADJUST,
            'signal_bonus': SIGNAL_BONUS_ADJUST,
        }
    except ImportError:
        cfg = load_config()
        return {
            'stop_loss': {'default': cfg.get('stop_loss_pct', 0.10)},
            'time_stop_days': cfg.get('time_stop', {}).get('max_hold_days', 120),
            'chase_ban_pct': cfg.get('trade_params', {}).get('chase_ban_pct', 4.0),
        }


# 向后兼容接口（保持与旧代码兼容）
def load_contract():
    """向后兼容: 等同于load_config()"""
    return load_config()


def get_alert_threshold() -> Dict[str, Any]:
    """获取监控告警阈值（原ALERT_THRESHOLD）"""
    return {
        'stop_loss_pct': get_stop_loss("趋势"),
        'trailing_activate_pct': 0.15,
        'time_stop_warning_days': get_time_stop_days() - 10,
    }


if __name__ == '__main__':
    # 测试入口
    print("=" * 60)
    print("config_loader.py 自检")
    print("=" * 60)
    
    # 测试1: 加载配置
    cfg = load_config()
    print(f"\n✅ config.json 加载成功")
    print(f"   版本: {cfg.get('version', 'unknown')}")
    print(f"   策略: {cfg.get('strategy', 'unknown')}")
    print(f"   止损: {cfg.get('stop_loss_pct', 'unknown')}")
    
    # 测试2: 获取止损参数
    strategies = ['全仓', '突破', '断层', '北向精选', '趋势', '抄底', '综合']
    print("\n✅ 各策略止损比例:")
    for s in strategies:
        val = get_stop_loss(s)
        print(f"   {s:8s}: {val:.2%}")
    
    # 测试3: 获取风控参数
    params = get_all_risk_params()
    print("\n✅ 风控参数汇总:")
    print(f"   时间止损: {params['time_stop_days']} 交易日")
    print(f"   追高关闭: {params['chase_ban_pct']}%")
    
    # 测试4: 验证配置一致性
    assert cfg.get('stop_loss_pct') == 0.10, f"config.json止损应为0.10，实际{cfg.get('stop_loss_pct')}"
    assert get_stop_loss('趋势') == 0.10, "趋势策略止损应为0.10"
    
    print("\n" + "=" * 60)
    print("✅ 所有自检通过")
    print("=" * 60)

