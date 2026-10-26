#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
positioner.py — 仓位管理器

功能:
  1. 根据S3闸门状态计算目标仓位
  2. 执行调仓决策
  3. 更新持仓文件

用法:
  python positioner.py --dry-run
  python positioner.py --execute
"""
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


class Positioner:
    """仓位管理器"""
    
    def __init__(self, config_path: str = "data/config.json"):
        """
        初始化仓位管理器
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.holdings_path = Path("data/holdings.json")
        self.holdings = self._load_holdings()
    
    def _load_config(self) -> Dict:
        """加载配置"""
        if self.config_path.exists():
            return json.loads(self.config_path.read_text(encoding='utf-8'))
        return {}
    
    def _load_holdings(self) -> Dict:
        """加载持仓"""
        if self.holdings_path.exists():
            return json.loads(self.holdings_path.read_text(encoding='utf-8'))
        return {
            "positions": [],
            "cash": 0.0,
            "total_assets": 0.0,
            "updated_at": datetime.now().isoformat()
        }
    
    def check_s3_gates(self) -> Dict:
        """
        检查S3闸门状态
        
        Returns:
            闸门状态字典
        """
        gates = {
            "gate1": {"status": "unknown", "detail": ""},
            "gate2": {"status": "unknown", "detail": ""},
            "gate3": {"status": "unknown", "detail": ""},
            "gate4": {"status": "unknown", "detail": ""},
        }
        
        # 闸1: 环境门
        sh_path = Path("data/sh_index.json")
        if sh_path.exists():
            d = json.loads(sh_path.read_text())
            sh_close = d.get('close', 0)
            ma250 = d.get('ma250', 0)
            gates["gate1"] = {
                "status": "open" if sh_close >= ma250 else "closed",
                "detail": f"sh={sh_close}, ma250={ma250}"
            }
        
        # 闸2: 老五审批 (B3: 走 review_gate 唯一仲裁读法, fail-safe, final_verdict/B1 否决)
        import review_gate
        _g2 = review_gate.evaluate(str(Path("data/review_status.json")))
        gates["gate2"] = {
            "status": "frozen" if _g2["frozen"] else "approved",
            "detail": f"review_gate source={_g2['source']}: {_g2['reason']}"
        }
        
        # 闸3: 配置就绪
        config_path = Path("data/config.json")
        gates["gate3"] = {
            "status": "ready" if config_path.exists() else "missing",
            "detail": "config.json存在" if config_path.exists() else "config.json缺失"
        }
        
        # 闸4: S3闸门（从配置读取）
        s3_cap = self.config.get('trade_params', {}).get('position_ratio', 0.5)
        gates["gate4"] = {
            "status": "active" if s3_cap > 0 else "inactive",
            "detail": f"s3_cap={s3_cap}"
        }
        
        return gates
    
    def calculate_target_position(self) -> Dict:
        """
        计算目标仓位
        
        Returns:
            目标仓位字典
        """
        gates = self.check_s3_gates()
        
        # 所有闸门满足才开仓
        all_gates_ok = all(
            g["status"] in ["open", "approved", "ready", "active"]
            for g in gates.values()
        )
        
        if not all_gates_ok:
            return {
                "action": "hold",
                "target_positions": [],
                "reason": "S3闸门未完全满足",
                "gates": gates
            }
        
        # 闸门满足，执行调仓
        target_ratio = self.config.get('trade_params', {}).get('position_ratio', 0.5)
        total_assets = self.holdings.get('total_assets', 0)
        target_value = total_assets * target_ratio
        
        return {
            "action": "rebalance",
            "target_ratio": target_ratio,
            "target_value": target_value,
            "gates": gates
        }
    
    def execute_rebalance(self, dry_run: bool = True) -> Dict:
        """
        执行调仓
        
        Args:
            dry_run: 是否dry-run模式
            
        Returns:
            执行结果
        """
        target = self.calculate_target_position()
        
        if target["action"] == "hold":
            return {
                "success": True,
                "action": "hold",
                "reason": target["reason"]
            }
        
        if dry_run:
            return {
                "success": True,
                "action": "rebalance",
                "dry_run": True,
                "target": target
            }
        
        # 实际执行调仓（简化版）
        # TODO: 实现实际调仓逻辑
        return {
            "success": False,
            "action": "rebalance",
            "message": "实际调仓逻辑未实现"
        }


def main():
    parser = argparse.ArgumentParser(description='仓位管理器')
    parser.add_argument('--dry-run', action='store_true', help='Dry-run模式')
    parser.add_argument('--execute', action='store_true', help='实际执行')
    parser.add_argument('--check-gates', action='store_true', help='检查闸门状态')
    
    args = parser.parse_args()
    
    positioner = Positioner()
    
    if args.check_gates:
        gates = positioner.check_s3_gates()
        print("=" * 70)
        print("🚪 S3闸门状态")
        print("=" * 70)
        for name, info in gates.items():
            status_icon = "✅" if info["status"] in ["open", "approved", "ready", "active"] else "❌"
            print(f"  {status_icon} {name}: {info['status']} ({info['detail']})")
        print()
        
        all_ok = all(g["status"] in ["open", "approved", "ready", "active"] for g in gates.values())
        if all_ok:
            print("✅ 所有闸门满足，可以开仓")
        else:
            print("❌ 闸门未完全满足，保持持仓")
        
        return
    
    if args.execute:
        result = positioner.execute_rebalance(dry_run=False)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        result = positioner.execute_rebalance(dry_run=True)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
