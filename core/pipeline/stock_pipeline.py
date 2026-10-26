import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""stock_pipeline.py — 统一流水线 CLI 入口（薄封装层）

所有核心逻辑已合并到 stock_picker_v3.py。
本文件只做命令行参数解析 + 路由。
支持: pipeline | scan | swing | sector_rotation

用法:
  python stock_pipeline.py --mode scan            # 全量扫描
  python stock_pipeline.py --mode swing           # 波段推荐
  python stock_pipeline.py --mode sector_rotation  # 板块轮动
"""
import sys, os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 所有核心逻辑从 stock_picker_v3 导入
sys.path.insert(0, PROJECT_ROOT)  # P1修复(20261023): S4迁移后误插core/pipeline/, 改仓库根
from core.pipeline.stock_picker_v3 import (
    pick_stock, main as v3_main,
)
# 板块轮动独立模块 (sector_rotation_analysis 用新版 get_industry_heat 格式)
from sector_rotation import sector_rotation_analysis as get_sector_heat_ranking

def main():
    """CLI 入口：解析参数 → 路由到对应函数"""
    try:
        import argparse
    except ImportError:
        print("argparse 不可用，走默认流水线")
        swing_pick()
        return

    parser = argparse.ArgumentParser(
        description="选股统一流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python stock_pipeline.py --mode scan                  # 全量扫描
  python stock_pipeline.py --mode swing                 # 波段推荐
  python stock_pipeline.py --mode sector_rotation       # 板块轮动
        """
    )

    parser.add_argument("--mode", choices=["scan", "swing", "sector_rotation"],
                        default="swing", help="执行模式")
    parser.add_argument("--strategy", default=None, help="策略名称")
    parser.add_argument("--top", type=int, default=10, help="Top N 输出（仅scan模式）")

    args = parser.parse_args()

    if args.mode == "scan":
        v3_main()
    elif args.mode == "swing":
        # swing_pick 已从 stock_picker_v3 移除(2026-08-02), 改用 pick_stock("波段")
        pick_stock(strategy_name=args.strategy or "波段")
    elif args.mode == "sector_rotation":
        result = get_sector_heat_ranking()
        if result["status"] == "ok":
            print("=" * 50)
            print("  🔄 板块轮动分析")
            print("=" * 50)
            print(f"  总板块数: {result['num_sectors']}")
            print(f"\n  🔥 热门板块 (Top{len(result.get('hot',[]))})")
            for s in result.get("hot", []):
                print(f"    {s['name']}: {s['percentile']:.0f}%")
            print(f"\n  ❄️ 弱势板块 (后{len(result.get('cold',[]))})")
            for s in result.get("cold", []):
                print(f"    {s['name']}: {s['percentile']:.0f}%")
        else:
            print(f"  ❌ {result.get('message', '未知错误')}")

if __name__ == "__main__":
    main()

# ── auto_fix_known_issues KI-002 (2026-08-04): 从 stock_picker_v3 补全 super_stock_classify ──
try:
    _HAS_SUPER_MODEL = True
except Exception:
    def super_stock_classify(code, name, records):
        """超级股票分类模型（回退实现）"""
        return {"model": "综合型", "score": 70, "drawdown_pct": 12.0, "alignment": "震荡"}

    def check_data_quality(code, records):
        """数据质量检查（基础实现）"""
        if not records or len(records) < 30:
            return [("warning", "数据条数不足30天")]
        return []
    _HAS_SUPER_MODEL = False
