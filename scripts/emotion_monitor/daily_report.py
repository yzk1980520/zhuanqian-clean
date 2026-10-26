#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场观察日报生成器
功能：整合情绪监控数据，生成每日市场观察报告
"""

import json
from datetime import datetime
from pathlib import Path
import akshare as ak

class MarketDailyReport:
    def __init__(self, date=None):
        self.date = date or datetime.now().strftime('%Y-%m-%d')
        self.report = {
            'date': self.date,
            'timestamp': datetime.now().isoformat(),
            'sections': {}
        }
    
    def collect_data(self):
        """收集市场数据"""
        print(f"[{datetime.now()}] 开始收集市场数据...")
        
        try:
            # 1. 获取全市场数据
            df = ak.stock_zh_a_spot_em()
            
            # 2. 计算基础指标
            up_count = len(df[df['涨跌幅'] > 0])
            down_count = len(df[df['涨跌幅'] < 0])
            flat_count = len(df[df['涨跌幅'] == 0])
            total_count = len(df)
            
            # 3. 计算涨跌比
            up_down_ratio = up_count / down_count if down_count > 0 else float('inf')
            
            # 4. 计算涨停/跌停数
            limit_up = len(df[df['涨跌幅'] > 9.5])
            limit_down = len(df[df['涨跌幅'] < -9.5])
            
            # 5. 计算炸板率（简化）
            broken = len(df[(df['涨跌幅'] >= 5) & (df['涨跌幅'] < 9.5)])
            zhaban_rate = (broken / limit_up * 100) if limit_up > 0 else 0
            
            # 6. 获取成交额（简化：取全部A股成交额总和）
            total_volume = df['成交额'].sum() / 1e8  # 转换为亿元
            
            self.report['sections']['basic_stats'] = {
                'date': self.date,
                'up_count': up_count,
                'down_count': down_count,
                'flat_count': flat_count,
                'total_count': total_count,
                'up_down_ratio': round(up_down_ratio, 2),
                'limit_up': limit_up,
                'limit_down': limit_down,
                'zhaban_rate': round(zhaban_rate, 2),
                'total_volume_100m': round(total_volume, 2)
            }
            
            print(f"✅ 基础数据统计完成:")
            print(f"   - 上涨: {up_count}只, 下跌: {down_count}只")
            print(f"   - 涨停: {limit_up}只, 跌停: {limit_down}只")
            print(f"   - 炸板率: {zhaban_rate:.2f}%")
            print(f"   - 成交额: {total_volume:.2f}亿")
            
        except Exception as e:
            self.report['sections']['data_collection_error'] = str(e)
            print(f"❌ 数据收集失败: {e}")
        
        return self
    
    def generate_report(self):
        """生成报告"""
        print(f"\n[{datetime.now()}] 开始生成市场观察日报...")
        
        # 1. 获取北向资金数据
        northbound_100m = 0
        try:
            from emotion_monitor.northbound import monitor_northbound_flow
            nb_result = monitor_northbound_flow(date=self.date)
            northbound_100m = nb_result.get('net_inflow_yuan', 0)
        except Exception as e:
            print(f"⚠️ 北向资金数据获取失败: {e}，使用默认值0")
        
        # 2. 市场状态判定
        basic = self.report.get('sections', {}).get('basic_stats', {})
        if basic:
            from scripts.emotion_monitor.market_regime_judge import judge_market_regime
            regime_result = judge_market_regime(
                volume_100m=basic.get('total_volume_100m'),
                zhaban_rate=basic.get('zhaban_rate'),
                up_down_ratio=basic.get('up_down_ratio'),
                northbound_100m=northbound_100m
            )
            self.report['sections']['market_regime'] = regime_result
        
        # 2. 生成报告文本
        report_text = self._format_report()
        
        return report_text
    
    def _format_report(self):
        """格式化报告"""
        lines = []
        lines.append("="*60)
        lines.append(f"【牛马·市场观察日报】{self.date}")
        lines.append("="*60)
        lines.append("")
        
        # 基础统计
        basic = self.report.get('sections', {}).get('basic_stats', {})
        if basic:
            lines.append("一、基础统计")
            lines.append(f"   上涨: {basic.get('up_count', 0)}只 | 下跌: {basic.get('down_count', 0)}只 | 平盘: {basic.get('flat_count', 0)}只")
            lines.append(f"   涨停: {basic.get('limit_up', 0)}只 | 跌停: {basic.get('limit_down', 0)}只")
            lines.append(f"   炸板率: {basic.get('zhaban_rate', 0):.2f}% | 涨跌比: {basic.get('up_down_ratio', 0):.2f}")
            lines.append(f"   成交额: {basic.get('total_volume_100m', 0):.2f}亿")
            lines.append("")
        
        # 市场状态
        regime = self.report.get('sections', {}).get('market_regime', {})
        if regime:
            lines.append("二、市场状态判定")
            lines.append(f"   环境状态: {regime.get('regime', '未知')}")
            lines.append(f"   置信度: {regime.get('confidence', 0):.0%}")
            lines.append(f"   市场信号: {', '.join(regime.get('signals', []))}")
            lines.append("")
            
            # 策略建议
            advice = regime.get('strategy_advice', {})
            if advice:
                lines.append("三、策略建议")
                lines.append(f"   仓位建议: {advice.get('仓位建议', 'N/A')}")
                lines.append(f"   入场时机: {advice.get('入场时机', 'N/A')}")
                lines.append(f"   止损纪律: {advice.get('止损纪律', 'N/A')}")
                lines.append(f"   持仓周期: {advice.get('持仓周期', 'N/A')}")
                lines.append(f"   风险等级: {advice.get('风险等级', 'N/A')}")
                lines.append(f"   操作建议: {advice.get('操作建议', 'N/A')}")
                lines.append("")
        
        lines.append("="*60)
        lines.append(f"生成时间: {self.report.get('timestamp', '')}")
        lines.append("="*60)
        
        return '\n'.join(lines)
    
    def save_report(self, output_dir='output'):
        """保存报告"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 保存JSON格式
        json_file = output_path / f"market_daily_report_{self.date}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(self.report, f, ensure_ascii=False, indent=2)
        
        # 保存文本格式
        text_file = output_path / f"market_daily_report_{self.date}.md"
        text_content = self._format_report()
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(text_content)
        
        print(f"\n💾 报告已保存:")
        print(f"   - JSON: {json_file}")
        print(f"   - 文本: {text_file}")
        
        return text_file

if __name__ == "__main__":
    # 生成日报
    report = MarketDailyReport()
    report.collect_data()
    report.generate_report()
    report.save_report()
