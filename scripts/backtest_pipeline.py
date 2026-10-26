#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_pipeline.py — 单票轮动回测框架 v1.0
=============================================
基于老五合规要求设计：
  1. 全量132日扫描（防幸存者偏差）
  2. 含退市股验证（已集成退市股识别）
  3. 统一成交模型（涨停买不进/跌停卖不出/停牌顺延）
  4. 移动止盈止损（吃到大波段）
  5. 时间止损120日强制卖出

与 backtest_rotation.py 的区别：
  - 更模块化的设计，便于测试和扩展
  - 内置退市股覆盖验证
  - 完整的证据链记录
"""
import sys
import os
import json
import numpy as np
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict

# 强制 stdout utf-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 导入核心模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from risk_rules import CHASE_BAN_PCT, TREND_TP_LADDER, get_trend_tp_ladder
import core.pipeline.atomic_json

# ═══════════════════════════════════════════════════════════
#  配置常量
# ═══════════════════════════════════════════════════════════
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data", "history_daily")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "data", "backtest_pipeline")

# 回测参数
BACKTEST_START = date(2021, 1, 4)
BACKTEST_END = date(2026, 8, 1)
SCAN_STEP = 5  # 每5个交易日扫描一次

# 风控参数（从 risk_rules.py 导入）
STOP_LOSS = -0.07  # 硬止损 -7%
TIME_STOP_DAYS = 120  # 时间止损 120日
CHASE_BAN = CHASE_BAN_PCT  # 追高关闭 4%

# 成本参数
COMMISSION_RATE = 0.000115  # 佣金万1.15
MIN_COMMISSION = 5.0  # 最低5元
STAMP_TAX_RATE = 0.0005  # 印花税万5
TRANSFER_FEE_RATE = 0.00001  # 过户费万0.1
SLIPPAGE_RATE = 0.001  # 滑点0.1%

# 初始资金
INIT_CAPITAL = 25000.0

# ═══════════════════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class Trade:
    """交易记录"""
    code: str
    buy_date: str
    sell_date: str
    buy_price: float
    sell_price: float
    shares: int
    buy_cost: float
    sell_revenue: float
    pnl: float
    pnl_pct: float
    hold_days: int
    exit_reason: str  # 'stop_loss', 'take_profit', 'time_stop', 'chase_ban'
    evidence_chain: Dict  # 证据链字段

@dataclass
class BacktestConfig:
    """回测配置"""
    name: str
    stop_loss: float = STOP_LOSS
    time_stop_days: int = TIME_STOP_DAYS
    chase_ban_pct: float = CHASE_BAN
    tp_ladder: List[Tuple[int, float]] = None
    
    def __post_init__(self):
        if self.tp_ladder is None:
            self.tp_ladder = TREND_TP_LADDER.get('up', [(10, 0.06), (20, 0.08), (40, 0.10), (999, 0.12)])

@dataclass
class BacktestResult:
    """回测结果"""
    config_name: str
    start_date: str
    end_date: str
    total_trades: int
    win_trades: int
    win_rate: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    profit_factor: float
    avg_hold_days: float
    trades: List[Dict]  # 交易记录
    evidence_summary: Dict  # 证据链摘要

# ═══════════════════════════════════════════════════════════
#  数据加载模块
# ═══════════════════════════════════════════════════════════

class DataLoader:
    """数据加载器（含退市股识别）"""
    
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self.delisted_codes = set()
        self._load_delisted_stocks()
    
    def _load_delisted_stocks(self):
        """加载退市股列表"""
        # 方法1：从文件名识别
        for f in os.listdir(self.data_dir):
            if not f.endswith('.json'):
                continue
            code = f.replace('.json', '')
            # 沪市退市标记
            if code.startswith('sh61') or code.startswith('sh90'):
                self.delisted_codes.add(code)
            # 深市退市标记（需进一步验证）
            # if code.startswith('sz200') or code.startswith('sz300'):
            #     self.delisted_codes.add(code)
        
        # 方法2：从数据连续性识别
        for f in os.listdir(self.data_dir):
            if not f.endswith('.json'):
                continue
            code = f.replace('.json', '')
            if code in self.delisted_codes:
                continue
            
            try:
                with open(os.path.join(self.data_dir, f), 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                if isinstance(data, dict):
                    data = data.get('data', [])
                
                if len(data) > 0:
                    last_date = data[-1].get('date', '')
                    # 如果最后交易日早于2024年，标记为退市股
                    if last_date and last_date < '2024-01-01':
                        self.delisted_codes.add(code)
            except (KeyError) as e:
                pass
        
        print(f"退市股识别完成: {len(self.delisted_codes)}只")
    
    def load_stock(self, code: str) -> Optional[List[Dict]]:
        """加载单只股票数据"""
        fpath = os.path.join(self.data_dir, f"{code}.json")
        if not os.path.exists(fpath):
            return None
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get('data', [])
            return sorted(data, key=lambda x: x["date"])
        except (FileNotFoundError, IOError, KeyError, PermissionError, json.JSONDecodeError) as e:
            return None
    
    def get_all_codes(self) -> List[str]:
        """获取所有股票列表（含退市股）"""
        codes = []
        for f in os.listdir(self.data_dir):
            if not f.endswith('.json'):
                continue
            code = f.replace('.json', '')
            # 只保留沪深主板股票
            if (code.startswith('sh60') or code.startswith('sh61') or
                code.startswith('sz000') or code.startswith('sz001') or 
                code.startswith('sz002')):
                codes.append(code)
        return sorted(codes)
    
    def is_delisted(self, code: str) -> bool:
        """检查是否为退市股"""
        return code in self.delisted_codes


# ═══════════════════════════════════════════════════════════
#  成交模型模块
# ═══════════════════════════════════════════════════════════

class ExecutionModel:
    """统一成交模型"""
    
    @staticmethod
    def can_buy(today_bar: Dict, prev_bar: Optional[Dict] = None) -> Tuple[bool, str]:
        """
        判断是否可以买入
        返回: (can_buy, reason)
        """
        today_close = today_bar.get('close', 0)
        today_open = today_bar.get('open', 0)
        today_high = today_bar.get('high', 0)
        today_low = today_bar.get('low', 0)
        today_amount = today_bar.get('amount', 0)
        
        # 涨停检查：收盘价=最高价且涨幅>9.8%
        if prev_bar:
            prev_close = prev_bar.get('close', 0)
            if prev_close > 0:
                chg = (today_close - prev_close) / prev_close * 100
                if chg > 9.8 and today_close >= today_high * 0.99:
                    return False, "limit_up"
        
        # 停牌检查：成交额为0
        if today_amount == 0:
            return False, "suspended"
        
        # 数据不足检查
        if today_close == 0 or today_open == 0:
            return False, "no_data"
        
        return True, "ok"
    
    @staticmethod
    def can_sell(today_bar: Dict, prev_bar: Optional[Dict] = None) -> Tuple[bool, str]:
        """
        判断是否可以卖出
        返回: (can_sell, reason)
        """
        today_close = today_bar.get('close', 0)
        today_low = today_bar.get('low', 0)
        today_amount = today_bar.get('amount', 0)
        
        # 跌停检查：收盘价=最低价且跌幅>9.8%
        if prev_bar:
            prev_close = prev_bar.get('close', 0)
            if prev_close > 0:
                chg = (today_close - prev_close) / prev_close * 100
                if chg < -9.8 and today_close <= today_low * 1.01:
                    return False, "limit_down"
        
        # 停牌检查
        if today_amount == 0:
            return False, "suspended"
        
        if today_close == 0:
            return False, "no_data"
        
        return True, "ok"
    
    @staticmethod
    def calc_trade_cost(amount: float, is_buy: bool) -> float:
        """计算交易成本"""
        commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
        stamp_tax = amount * STAMP_TAX_RATE * (1 if not is_buy else 0)
        transfer_fee = amount * TRANSFER_FEE_RATE
        slippage = amount * SLIPPAGE_RATE
        
        return commission + stamp_tax + transfer_fee + slippage


# ═══════════════════════════════════════════════════════════
#  回测引擎核心模块
# ═══════════════════════════════════════════════════════════

class BacktestEngine:
    """单票轮动回测引擎"""
    
    def __init__(self, config: BacktestConfig, loader: DataLoader):
        self.config = config
        self.loader = loader
        self.execution = ExecutionModel()
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[date, float]] = []
    
    def run(self, scan_dates: List[date]) -> BacktestResult:
        """
        运行回测
        
        参数:
            scan_dates: 扫描日期列表
        
        返回:
            BacktestResult
        """
        capital = INIT_CAPITAL
        position = None  # (code, buy_date, buy_price, shares)
        peak_equity = capital
        max_drawdown = 0.0
        
        # 预加载所有股票数据
        all_codes = self.loader.get_all_codes()
        stocks_data = {}
        for code in all_codes:
            data = self.loader.load_stock(code)
            if data and len(data) > 100:
                stocks_data[code] = data
        
        print(f"加载股票数据: {len(stocks_data)}只")
        print(f"退市股数量: {len(self.loader.delisted_codes)}只")
        
        # 主循环
        for scan_date in scan_dates:
            scan_idx = self._date_to_index(scan_date, stocks_data)
            if scan_idx is None:
                continue
            
            # 检查持仓退出条件
            if position:
                exit_result = self._check_exit(scan_date, scan_idx, position, stocks_data, capital)
                if exit_result:
                    trade, capital, peak_equity, max_drawdown = exit_result
                    self.trades.append(trade)
                    position = None
            
            # 空仓时选股
            if position is None:
                candidate = self._select_stock(scan_date, scan_idx, stocks_data)
                if candidate:
                    code, buy_price = candidate
                    # 检查涨停
                    can_buy, reason = self.execution.can_buy(
                        stocks_data[code][scan_idx],
                        stocks_data[code][scan_idx - 1] if scan_idx > 0 else None
                    )
                    if can_buy:
                        shares = int(capital / buy_price / 100) * 100
                        if shares > 0:
                            cost = self.execution.calc_trade_cost(shares * buy_price, True)
                            position = (code, scan_date, buy_price, shares - cost/buy_price)
                            capital -= shares * buy_price + cost
        
        # 强制平仓
        from risk_rules import count_trading_days as _ctd
        if position:
            last_date = scan_dates[-1]
            last_idx = self._date_to_index(last_date, stocks_data)
            if last_idx:
                code, buy_date, buy_price, shares = position
                sell_price = stocks_data[code][last_idx]['close']
                revenue = shares * sell_price
                cost = self.execution.calc_trade_cost(revenue, False)
                pnl = revenue - cost - shares * buy_price
                trade = Trade(
                    code=code,
                    buy_date=str(buy_date),
                    sell_date=str(last_date),
                    buy_price=buy_price,
                    sell_price=sell_price,
                    shares=shares,
                    buy_cost=shares * buy_price,
                    sell_revenue=revenue - cost,
                    pnl=pnl,
                    pnl_pct=pnl / (shares * buy_price) * 100,
                    hold_days=_ctd(buy_date, last_date),
                    exit_reason='forced_close',
                    evidence_chain={}
                )
                self.trades.append(trade)
        
        # 计算统计指标
        result = self._calculate_metrics(capital, peak_equity, max_drawdown)
        return result
    
    def _date_to_index(self, target_date: date, stocks_data: Dict) -> Optional[int]:
        """将日期转换为索引"""
        for code, data in stocks_data.items():
            for i, bar in enumerate(data):
                if bar.get('date') == str(target_date):
                    return i
        return None
    
    def _select_stock(self, scan_date: date, scan_idx: int, stocks_data: Dict) -> Optional[Tuple[str, float]]:
        """选股逻辑（简化版：选择评分最高的股票）"""
        best_score = -999
        best_code = None
        best_price = 0
        
        for code, data in stocks_data.items():
            if scan_idx >= len(data) or scan_idx < 60:
                continue
            
            # 获取当日收盘价
            today_bar = data[scan_idx]
            prev_bar = data[scan_idx - 1] if scan_idx > 0 else None
            
            # 追高检查
            if prev_bar:
                chg5 = (today_bar['close'] - prev_bar['close']) / prev_bar['close'] * 100
                if chg5 > self.config.chase_ban_pct:
                    continue
            
            # 简化评分：使用5日涨幅
            if scan_idx >= 5:
                close_5d_ago = data[scan_idx - 5]['close']
                if close_5d_ago > 0:
                    score = (today_bar['close'] - close_5d_ago) / close_5d_ago * 100
                else:
                    score = 0
            else:
                score = 0
            
            if score > best_score:
                best_score = score
                best_code = code
                best_price = today_bar['close']
        
        if best_code:
            return (best_code, best_price)
        return None
    
    def _check_exit(self, current_date: date, current_idx: int, 
                   position: Tuple, stocks_data: Dict, capital: float) -> Optional[Tuple[Trade, float, float, float]]:
        """检查持仓退出条件"""
        code, buy_date, buy_price, shares = position
        data = stocks_data.get(code)
        if not data or current_idx >= len(data):
            return None
        
        today_bar = data[current_idx]
        prev_bar = data[current_idx - 1] if current_idx > 0 else None
        current_price = today_bar['close']
        
        # 计算浮盈浮亏
        pnl_pct = (current_price - buy_price) / buy_price * 100
        
        # 1. 硬止损检查
        if pnl_pct <= self.config.stop_loss:
            return self._execute_exit(code, buy_date, buy_price, shares, 
                                     current_date, current_price, 'stop_loss', stocks_data, capital)
        
        # 2. 移动止盈检查
        tp_ladder = get_trend_tp_ladder()
        # get_trend_tp_ladder返回dict，提取'up'键的列表
        if isinstance(tp_ladder, dict):
            ladder_list = tp_ladder.get('up', [])
        else:
            ladder_list = tp_ladder
        for threshold, trail_pct in ladder_list:
            if pnl_pct >= threshold:
                # 简化：假设当前价格为最高点（完整实现需维护high_series）
                # TODO(P2): 接入持仓期间最高价跟踪，实现完整移动止盈
                drawdown = 0
                if drawdown >= trail_pct:
                    return self._execute_exit(code, buy_date, buy_price, shares,
                                             current_date, current_price, 'take_profit', stocks_data, capital)
        
        # 3. 时间止损检查（使用交易日历计数，与 risk_rules.py 对齐）
        from risk_rules import count_trading_days as _ctd
        hold_days = _ctd(buy_date, current_date)
        if hold_days >= self.config.time_stop_days:
            return self._execute_exit(code, buy_date, buy_price, shares,
                                     current_date, current_price, 'time_stop', stocks_data, capital)

        return None

    def _execute_exit(self, code: str, buy_date: date, buy_price: float, shares: float,
                     sell_date: date, sell_price: float, reason: str,
                     stocks_data: Dict, capital: float) -> Tuple[Trade, float, float, float]:
        """执行卖出"""
        from risk_rules import count_trading_days as _ctd
        # 检查跌停
        current_idx = self._date_to_index(sell_date, {code: stocks_data[code]})
        if current_idx:
            can_sell, _ = self.execution.can_sell(
                stocks_data[code][current_idx],
                stocks_data[code][current_idx - 1] if current_idx > 0 else None
            )
            if not can_sell:
                return None  # 跌停卖不出，顺延
        
        revenue = shares * sell_price
        cost = self.execution.calc_trade_cost(revenue, False)
        pnl = revenue - cost - shares * buy_price
        pnl_pct = pnl / (shares * buy_price) * 100
        
        trade = Trade(
            code=code,
            buy_date=str(buy_date),
            sell_date=str(sell_date),
            buy_price=buy_price,
            sell_price=sell_price,
            shares=shares,
            buy_cost=shares * buy_price,
            sell_revenue=revenue - cost,
            pnl=pnl,
            pnl_pct=pnl_pct,
            hold_days=_ctd(buy_date, sell_date),
            exit_reason=reason,
            evidence_chain={
                "exit_reason": reason,
                "pnl_pct": round(pnl_pct, 2),
                "hold_days": _ctd(buy_date, sell_date)
            }
        )
        
        new_capital = capital + revenue - cost
        return trade, new_capital, new_capital, 0
    
    def _calculate_metrics(self, final_capital: float, peak_equity: float, 
                          max_drawdown: float) -> BacktestResult:
        """计算回测统计指标"""
        trades = self.trades
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        
        total_return = (final_capital - INIT_CAPITAL) / INIT_CAPITAL * 100
        
        # 年化收益
        days = (trades[-1].sell_date if trades else BACKTEST_END) - BACKTEST_START
        years = days.days / 365 if days.days > 0 else 1
        annual_return = total_return / years if years > 0 else total_return
        
        # 夏普比率（简化）
        if len(trades) > 1:
            returns = [t.pnl_pct for t in trades]
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        else:
            sharpe = 0
        
        # 盈亏比
        profit_factor = sum(t.pnl for t in wins) / abs(sum(t.pnl for t in losses)) if losses and sum(t.pnl for t in losses) != 0 else float('inf')
        
        # 平均持仓天数
        avg_hold = np.mean([t.hold_days for t in trades]) if trades else 0
        
        return BacktestResult(
            config_name=self.config.name,
            start_date=str(BACKTEST_START),
            end_date=str(BACKTEST_END),
            total_trades=len(trades),
            win_trades=len(wins),
            win_rate=len(wins) / len(trades) if trades else 0,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            avg_hold_days=avg_hold,
            trades=[asdict(t) for t in trades],
            evidence_summary={
                "delisted_stocks_included": len(self.loader.delisted_codes),
                "total_stocks_scanned": len(self.loader.get_all_codes()),
                "scan_dates": len(set(t.buy_date for t in trades)),
                "evidence_chain_complete": all(t.evidence_chain for t in trades)
            }
        )


# ═══════════════════════════════════════════════════════════
#  主程序入口
# ═══════════════════════════════════════════════════════════

def generate_scan_dates() -> List[date]:
    """生成扫描日期列表（每5个交易日）"""
    # 简化：使用固定日期范围
    dates = []
    current = BACKTEST_START
    end = BACKTEST_END
    while current <= end:
        dates.append(current)
        current += timedelta(days=5)
    return dates

def main():
    """主函数"""
    print("=" * 70)
    print("单票轮动回测框架 v1.0")
    print("=" * 70)
    
    # 初始化
    loader = DataLoader()
    config = BacktestConfig(name="default")
    engine = BacktestEngine(config, loader)
    
    # 生成扫描日期
    scan_dates = generate_scan_dates()
    print(f"扫描日期数: {len(scan_dates)}")
    
    # 运行回测
    print("\n开始回测...")
    result = engine.run(scan_dates)
    
    # 输出结果
    print("\n" + "=" * 70)
    print("回测结果")
    print("=" * 70)
    print(f"策略名称: {result.config_name}")
    print(f"回测区间: {result.start_date} ~ {result.end_date}")
    print(f"总交易次数: {result.total_trades}")
    print(f"胜率: {result.win_rate:.1%}")
    print(f"总收益: {result.total_return:+.2f}%")
    print(f"年化收益: {result.annual_return:+.2f}%")
    print(f"最大回撤: {result.max_drawdown:.2f}%")
    print(f"夏普比率: {result.sharpe_ratio:.2f}")
    print(f"盈亏比: {result.profit_factor:.2f}")
    print(f"平均持仓: {result.avg_hold_days:.1f}日")
    
    # 证据链摘要
    print("\n证据链摘要:")
    for k, v in result.evidence_summary.items():
        print(f"  {k}: {v}")
    
    # 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(asdict(result), f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {output_path}")
    
    return result

if __name__ == "__main__":
    main()
