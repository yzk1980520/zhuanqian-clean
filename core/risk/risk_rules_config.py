# -*- coding: utf-8 -*-
"""RiskConfig - 风控配置数据类

深度模块设计：
- Config与Engine分离，便于测试时注入MockConfig
- 提供validate()方法保证配置合法
- 符合依赖注入原则
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RiskConfig:
    """风控参数配置（深度模块接口的一部分）"""
    
    # 止损参数
    stop_loss_base: float = 0.10  # 基础止损10%（S3三方会签确认）
    
    # 止盈参数
    tp_ladder: List[float] = field(default_factory=lambda: [0.06, 0.08, 0.10, 0.12])  # 移动止盈阶梯
    
    # 追高关闭
    chase_ban_pct: float = 4.0  # 信号日涨幅>4%不买（P0-A: 回测+14pp）
    
    # 时间止损
    time_stop_days: int = 120  # 持有超120日强制平仓（2026-09-06 老大拍板）
    time_stop_warning_days: int = 5  # 剩余5日预警（2026-09-03 老大拍板）
    
    # 市场状态调整系数（由MarketStateAdapter提供，此处仅默认值）
    market_adjustment: dict = field(default_factory=lambda: {
        "恐慌": 0.55,
        "弱": 0.85,
        "震荡": 0.62,
        "偏暖": 1.0,
        "强": 1.1,
        "极强": 0.9,
    })
    
    def validate(self) -> bool:
        """验证配置合法性（Seam: 配置边界）"""
        errors = []
        
        # 止损幅度验证
        if not (0 < self.stop_loss_base <= 0.5):
            errors.append(f"止损幅度应在0-50%，当前: {self.stop_loss_base:.2%}")
        
        # 追高关闭验证
        if not (0 < self.chase_ban_pct <= 10):
            errors.append(f"追高关闭应在0-10%，当前: {self.chase_ban_pct:.1f}%")
        
        # 时间止损验证
        if self.time_stop_days <= 0:
            errors.append(f"时间止损应大于0，当前: {self.time_stop_days}日")
        
        if self.time_stop_warning_days >= self.time_stop_days:
            errors.append(f"预警天数应早于止损天数，当前: 预警{self.time_stop_warning_days}日 vs 止损{self.time_stop_days}日")
        
        # 止盈阶梯验证
        if len(self.tp_ladder) != 4:
            errors.append(f"止盈阶梯应有4档，当前: {len(self.tp_ladder)}档")
        
        if errors:
            raise ValueError("RiskConfig验证失败:\n" + "\n".join(f"  - {e}" for e in errors))
        
        return True
    
    @classmethod
    def default(cls) -> 'RiskConfig':
        """默认配置（与现有常量对齐，向后兼容）"""
        return cls()
    
    @classmethod
    def from_legacy_constants(cls) -> 'RiskConfig':
        """从旧常量创建配置（用于迁移期）"""
        # 这里可以添加从旧全局常量读取的逻辑
        return cls()
    
    def __post_init__(self):
        """初始化后自动验证"""
        self.validate()
    
    def copy(self, **kwargs) -> 'RiskConfig':
        """创建配置副本（支持部分覆盖）"""
        from dataclasses import replace
        return replace(self, **kwargs)
    
    def get_stop_loss_multiplier(self, regime: str) -> float:
        """根据市场状态获取止损调整系数"""
        return self.market_adjustment.get(regime, 1.0)
    
    def get_time_stop_warning_date(self, entry_date) -> 'datetime.date':
        """计算时间止损预警日期"""
        from datetime import timedelta
        return entry_date + timedelta(days=self.time_stop_days - self.time_stop_warning_days)
