# -*- coding: utf-8 -*-
"""
因子库索引系统 — 统一管理和查询所有因子库

用途: 提供因子元数据、门禁状态、快速检索
"""
import json
import os
from typing import Dict, List, Optional
from datetime import datetime


class FactorIndexManager:
    """因子索引管理器"""
    
    def __init__(self, index_path: str = None):
        self.index_path = index_path or os.path.join(os.path.dirname(__file__), "factor_index.json")
        self.index = {
            "version": "1.0.0",
            "created_at": datetime.now().isoformat(),
            "libraries": {},
            "statistics": {}
        }
        self._load()
    
    def _load(self):
        """加载索引文件"""
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    self.index = json.load(f)
            except Exception:
                pass
    
    def _save(self):
        """保存索引文件"""
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)
    
    def register_library(self, library_name: str, library_path: str):
        """注册因子库"""
        index_file = os.path.join(library_path, "factor_index.json")
        if os.path.exists(index_file):
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    lib_index = json.load(f)
                
                self.index["libraries"][library_name] = lib_index
                self._update_statistics()
                self._save()
                return True
            except Exception as e:
                print(f"❌ 加载{library_name}索引失败: {e}")
                return False
        return False
    
    def _update_statistics(self):
        """更新统计信息"""
        total_factors = 0
        valid_factors = 0
        categories = {}
        
        for lib_name, lib_data in self.index["libraries"].items():
            total_factors += lib_data.get("total_count", 0)
            valid_factors += lib_data.get("valid_count", 0)
            
            for cat, count in lib_data.get("categories", {}).items():
                categories[cat] = categories.get(cat, 0) + count
        
        self.index["statistics"] = {
            "total_libraries": len(self.index["libraries"]),
            "total_factors": total_factors,
            "valid_factors": valid_factors,
            "categories": categories,
            "last_updated": datetime.now().isoformat()
        }
    
    def search_factors(self, keyword: str = None, category: str = None,
                       min_ic: float = None, min_icir: float = None) -> List[Dict]:
        """搜索因子"""
        results = []
        
        for lib_name, lib_data in self.index["libraries"].items():
            for factor in lib_data.get("factors", []):
                # 关键词匹配
                if keyword and keyword.lower() not in factor.get("name", "").lower():
                    continue
                
                # 类别过滤
                if category and factor.get("category") != category:
                    continue
                
                # IC门槛
                if min_ic is not None and abs(factor.get("ic_mean", 0)) < min_ic:
                    continue
                
                # ICIR门槛
                if min_icir is not None and factor.get("icir", 0) < min_icir:
                    continue
                
                results.append({
                    **factor,
                    "library": lib_name
                })
        
        # 按IC绝对值排序
        results.sort(key=lambda x: abs(x.get("ic_mean", 0)), reverse=True)
        return results
    
    def get_top_factors(self, n: int = 10, category: str = None) -> List[Dict]:
        """获取Top N因子"""
        return self.search_factors(min_ic=0.03, min_icir=0.3, category=category)[:n]
    
    def get_library_info(self, library_name: str) -> Optional[Dict]:
        """获取库信息"""
        return self.index["libraries"].get(library_name)
    
    def generate_report(self) -> str:
        """生成因子库报告"""
        stats = self.index.get("statistics", {})
        
        report = []
        report.append("=" * 60)
        report.append("QuantSkills 因子库索引报告")
        report.append("=" * 60)
        report.append(f"版本: {self.index.get('version', '1.0.0')}")
        report.append(f"创建时间: {self.index.get('created_at', 'N/A')}")
        report.append(f"最后更新: {stats.get('last_updated', 'N/A')}")
        report.append("")
        
        report.append("## 库概览")
        report.append(f"- 因子库数量: {stats.get('total_libraries', 0)}")
        report.append(f"- 总因子数: {stats.get('total_factors', 0)}")
        report.append(f"- 有效因子数: {stats.get('valid_factors', 0)}")
        report.append(f"- 有效率: {stats.get('valid_factors', 0)/max(stats.get('total_factors', 1), 1)*100:.1f}%")
        report.append("")
        
        report.append("## 分类统计")
        for cat, count in sorted(stats.get("categories", {}).items(), key=lambda x: -x[1]):
            report.append(f"- {cat}: {count}个")
        report.append("")
        
        report.append("## 各库详情")
        for lib_name, lib_data in self.index["libraries"].items():
            report.append(f"\n### {lib_name}")
            report.append(f"- 总数: {lib_data.get('total_count', 0)}")
            report.append(f"- 有效: {lib_data.get('valid_count', 0)}")
            report.append(f"- 类别: {', '.join(lib_data.get('categories', {}).keys())}")
        
        return "\n".join(report)


if __name__ == "__main__":
    manager = FactorIndexManager()
    
    # 注册已存在的因子库
    base_path = os.path.dirname(__file__)
    manager.register_library("volume_stat", os.path.join(base_path, "volume_stat"))
    manager.register_library("risk_pattern", os.path.join(base_path, "risk_pattern"))
    
    # 生成报告
    report = manager.generate_report()
    print(report)
    
    # 保存索引
    manager._save()
    print(f"\n✅ 索引已保存至 {manager.index_path}")
    
    # 测试搜索
    print("\n## Top 5 有效因子:")
    top_factors = manager.get_top_factors(5)
    for i, f in enumerate(top_factors, 1):
        print(f"  {i}. {f['factor_id']} ({f['library']}) - IC={f['ic_mean']:.4f}")
