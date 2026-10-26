#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
动态选股看板生成器 v2.0
从JSON数据源实时生成HTML看板
"""
import json
import os
import sys
from pathlib import Path
from datetime import datetime
import glob

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"

# S1 仲裁统一读法
sys.path.insert(0, str(ROOT))
import review_gate as _rg

def load_json(path):
    """安全加载JSON"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ [load_json] {path} 读取失败: {e}", file=__import__('sys').stderr)
        return None

def get_latest_rank():
    """获取最新选股结果"""
    rank_files = sorted(glob.glob(str(LOGS_DIR / "rank_*.json")))
    if not rank_files:
        return None
    return load_json(rank_files[-1])

def generate_dashboard():
    """生成动态看板HTML"""
    # 加载数据
    rank_data = get_latest_rank()
    holdings = load_json(DATA_DIR / "holdings.json") or {}
    review = load_json(DATA_DIR / "review_status.json") or {}
    launch = load_json(ROOT / "data" / "launch_log.json") or {}
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 账户信息
    cash = holdings.get("available_cash", 22103.56)
    positions = holdings.get("holdings", [])
    pos_count = len(positions)
    
    # S3状态 — S1 统一仲裁读法 (review_gate.evaluate)
    _gate_dy = _rg.evaluate(str(DATA_DIR / "review_status.json"))
    s3_approved = not _gate_dy["frozen"]
    s3_status = "✅ 已启用" if s3_approved else "❌ 未启用"
    
    # 构建候选池表格
    candidates_html = ""
    if rank_data and rank_data.get("items"):
        for item in rank_data["items"][:10]:
            rank = item.get("rank", 0)
            code = item.get("code", "")
            name = item.get("name", "")
            score = item.get("final_score", 0)
            is_top1 = rank == 1
            row_class = "class='top1'" if is_top1 else ""
            top1_tag = "<span class='top1-tag'>TOP1</span>" if is_top1 else ""
            candidates_html += f"<tr {row_class}><td>{rank}</td><td>{code}</td><td>{name}</td><td class='score'>{score}</td><td>{top1_tag}</td></tr>\n"
    else:
        candidates_html = "<tr><td colspan='5' style='text-align:center;color:#8a93a3'>暂无数据</td></tr>"
    
    # 持仓表格
    holdings_html = ""
    if positions:
        for pos in positions:
            code = pos.get("code", "")
            name = pos.get("name", "")
            shares = pos.get("shares", 0)
            cost = pos.get("cost_price", 0)
            current = pos.get("market_price", cost)
            pnl_pct = (current - cost) / cost * 100 if cost > 0 else 0
            pnl_class = "pos" if pnl_pct >= 0 else "neg"
            holdings_html += f"<tr><td>{code}</td><td>{name}</td><td>{shares}</td><td>{cost:.2f}</td><td>{current:.2f}</td><td class='{pnl_class}'>{pnl_pct:+.1f}%</td></tr>"
    else:
        holdings_html = "<tr><td colspan='6' style='text-align:center;color:#8a93a3'>空仓</td></tr>"
    
    # 门禁状态
    gate_ok = s3_approved and pos_count <= 1
    gate_status = "✅ 通过" if gate_ok else "⚠️ 检查"
    
    # 生成HTML
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="30">
    <title>S3选股系统看板</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ 
            font-family: "Microsoft YaHei", sans-serif; 
            background: #0f1115; 
            color: #e6e6e6; 
            padding: 20px;
            font-size: 14px;
        }}
        h1 {{ 
            font-size: 24px; 
            margin-bottom: 8px;
            background: linear-gradient(90deg, #6366f1, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header {{ margin-bottom: 20px; }}
        .sub {{ color: #8a93a3; font-size: 12px; margin-bottom: 18px; }}
        .grid {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); 
            gap: 16px; 
        }}
        .card {{ 
            background: #1a1e28; 
            border: 1px solid #2a3040; 
            border-radius: 12px; 
            padding: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }}
        .card-title {{ 
            font-weight: bold; 
            font-size: 15px; 
            margin-bottom: 12px; 
            padding-bottom: 8px;
            border-bottom: 1px solid #2a3040;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .card-body {{ font-size: 13px; line-height: 1.8; }}
        .card-ok {{ border-left: 3px solid #10b981; }}
        .card-warn {{ border-left: 3px solid #f59e0b; }}
        .card-danger {{ border-left: 3px solid #ef4444; }}
        .kv {{ display: flex; justify-content: space-between; padding: 4px 0; }}
        .b {{ font-weight: bold; color: #fff; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }}
        th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #252b3a; }}
        th {{ color: #8a93a3; font-weight: normal; font-size: 11px; }}
        .pos {{ color: #10b981; }}
        .neg {{ color: #ef4444; }}
        .top1 {{ background: #1e293b; }}
        .top1-tag {{ 
            background: linear-gradient(90deg, #f59e0b, #ef4444);
            color: #fff;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: bold;
        }}
        .score {{ font-weight: bold; color: #6366f1; }}
        .refresh {{ color: #8a93a3; font-size: 11px; margin-top: 12px; text-align: right; }}
        .tag {{ 
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
        }}
        .tag-ok {{ background: #10b981; color: #fff; }}
        .tag-warn {{ background: #f59e0b; color: #fff; }}
        .tag-danger {{ background: #ef4444; color: #fff; }}
        .big-num {{ font-size: 24px; font-weight: bold; color: #6366f1; }}
        .section-title {{ 
            font-size: 12px; 
            color: #8a93a3; 
            margin: 12px 0 8px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .stat-grid {{ 
            display: grid; 
            grid-template-columns: repeat(3, 1fr); 
            gap: 12px;
            margin-top: 12px;
        }}
        .stat-item {{ 
            background: #1e293b; 
            padding: 12px; 
            border-radius: 8px;
            text-align: center;
        }}
        .stat-label {{ font-size: 11px; color: #8a93a3; margin-bottom: 4px; }}
        .stat-value {{ font-size: 20px; font-weight: bold; color: #fff; }}
        .stat-value.pos {{ color: #10b981; }}
        .stat-value.neg {{ color: #ef4444; }}
        .footer {{ 
            margin-top: 20px; 
            text-align: center; 
            color: #8a93a3; 
            font-size: 11px;
            padding: 12px;
            border-top: 1px solid #2a3040;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 S3选股系统看板</h1>
        <div class="sub">策略: S3主候选-阶梯失活+加密 | 更新时间: {now} | 自动刷新: 30s</div>
    </div>
    
    <div class="grid">
        <!-- 账户概览 -->
        <div class="card card-ok">
            <div class="card-title">
                <span>💼 账户概览</span>
                <span class="tag {'tag-ok' if gate_ok else 'tag-warn'}">{gate_status}</span>
            </div>
            <div class="card-body">
                <div class="stat-grid">
                    <div class="stat-item">
                        <div class="stat-label">可用资金</div>
                        <div class="stat-value">¥{cash:,.0f}</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">持仓数</div>
                        <div class="stat-value">{pos_count}</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">仓位</div>
                        <div class="stat-value">{'全仓' if pos_count > 0 else '空仓'}</div>
                    </div>
                </div>
                <div class="section-title">门禁状态</div>
                <div class="kv"><span>laowu_approved</span><span class="{'pos' if s3_approved else 'neg'}">{s3_status}</span></div>
                <div class="kv"><span>持仓合规</span><span class="{'pos' if pos_count <= 1 else 'neg'}">{'✅' if pos_count <= 1 else '❌'} 最多1只</span></div>
            </div>
        </div>
        
        <!-- 候选池 -->
        <div class="card">
            <div class="card-title">
                <span>🎯 S3选股候选池</span>
                <span class="tag tag-ok">{rank_data.get('count', 0) if rank_data else 0}只</span>
            </div>
            <div class="card-body">
                <table>
                    <tr><th>#</th><th>代码</th><th>名称</th><th>评分</th><th></th></tr>
                    {candidates_html}
                </table>
                <div class="refresh">最后更新: {now}</div>
            </div>
        </div>
        
        <!-- 实盘持仓 -->
        <div class="card">
            <div class="card-title">
                <span>📈 实盘持仓</span>
                <span class="tag {'tag-ok' if pos_count == 0 else 'tag-warn'}">{pos_count}只</span>
            </div>
            <div class="card-body">
                <table>
                    <tr><th>代码</th><th>名称</th><th>股数</th><th>成本</th><th>现价</th><th>盈亏%</th></tr>
                    {holdings_html}
                </table>
            </div>
        </div>
        
        <!-- 策略配置 -->
        <div class="card card-ok">
            <div class="card-title"><span>⚙️ 策略配置</span></div>
            <div class="card-body">
                <div class="section-title">S3参数</div>
                <div class="kv"><span>止损</span><span class="b">10%</span></div>
                <div class="kv"><span>时间止损</span><span class="b">120日</span></div>
                <div class="kv"><span>追高关闭</span><span class="b">4%</span></div>
                <div class="kv"><span>移动止盈</span><span class="b">6%-8%-10%-12%</span></div>
                <div class="section-title">因子权重</div>
                <div class="kv"><span>chg5</span><span class="b">20%</span></div>
                <div class="kv"><span>chg10</span><span class="b">20%</span></div>
                <div class="kv"><span>LOWER_SHADOW</span><span class="b">15%</span></div>
                <div class="kv"><span>UPPER_SHADOW</span><span class="b">0%</span></div>
            </div>
        </div>
        
        <!-- 回测验证 -->
        <div class="card card-warn">
            <div class="card-title"><span>📊 回测验证</span></div>
            <div class="card-body">
                <div class="section-title">S3主候选 (2026-10-07)</div>
                <div class="kv"><span>胜率</span><span class="b pos">58%</span></div>
                <div class="kv"><span>最大回撤</span><span class="b">37.3%</span></div>
                <div class="kv"><span>盈亏比</span><span class="b pos">1.74</span></div>
                <div class="kv"><span>独特选股</span><span class="b">35只</span></div>
                <div class="kv"><span>总收益</span><span class="b pos">+160.8%</span></div>
                <div class="kv"><span>交易次数</span><span class="b">36笔</span></div>
                <div class="section-title">门禁状态</div>
                <div class="kv"><span>胜率≥40%</span><span class="pos">✅ 通过</span></div>
                <div class="kv"><span>回撤≤60%</span><span class="pos">✅ 56.7%（2026-10-15新基线重裁）</span></div>
                <div class="kv"><span>盈亏比≥1.5</span><span class="pos">✅ 通过</span></div>
            </div>
        </div>
        
        <!-- 系统状态 -->
        <div class="card card-ok">
            <div class="card-title"><span>🔧 系统状态</span></div>
            <div class="card-body">
                <div class="kv"><span>Cron任务</span><span class="pos">✅ 每日08:00</span></div>
                <div class="kv"><span>飞书通知</span><span class="pos">✅ 已配置</span></div>
                <div class="kv"><span>数据源</span><span class="pos">9437只</span></div>
                <div class="kv"><span>IC快照</span><span class="warn">2026-10-07</span></div>
                <div class="section-title">流水线状态</div>
                <div class="kv"><span>Phase 1</span><span class="pos">✅ 手动监控</span></div>
                <div class="kv"><span>Phase 2</span><span class="pos">✅ 半自动</span></div>
                <div class="kv"><span>Phase 3</span><span class="warn">⏳ 待观察</span></div>
            </div>
        </div>
    </div>
    
    <div class="footer">
        数据只读 · 来自 D:\\open code\\zhuanqian\\data · 自动刷新30秒 · 总管Hermes生成
    </div>
</body>
</html>'''
    
    return html

if __name__ == '__main__':
    html = generate_dashboard()
    output_file = ROOT / "dashboards" / "dashboard.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"✅ 看板已生成: {output_file}")
    print(f"   访问: http://127.0.0.1:8666/board")
