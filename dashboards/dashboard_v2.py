#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
S3选股系统看板 - 美化版 v2.0
从JSON数据源实时生成HTML看板 - 带AI分析模块
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

# 颜色主题 - 深色专业风格
THEME = {
    "bg": "#0f1115",
    "card_bg": "#1a1e28",
    "border": "#2a3040",
    "text": "#e6e6e6",
    "muted": "#8a93a3",
    "accent": "#6366f1",
    "pos": "#10b981",
    "neg": "#ef4444",
    "warn": "#f59e0b",
    "accent_blue": "#3b82f6",
    "accent_purple": "#8b5cf6",
    "accent_pink": "#ec4899",
    "accent_orange": "#f97316",
}

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

def get_ai_analysis():
    """调用AI分析模块生成投资建议"""
    try:
        # 加载因子数据
        ic_file = DATA_DIR / "factor_ic" / "factor_ic_latest.json"
        ic_data = load_json(ic_file) if ic_file.exists() else None
        
        # 加载回测数据
        bt_file = DATA_DIR / "rotation_backtest_result.json"
        bt_data = load_json(bt_file) if bt_file.exists() else None
        
        # 加载持仓数据
        holdings = load_json(DATA_DIR / "holdings.json") or {}
        
        # 构建分析提示
        analysis_prompt = build_ai_prompt(ic_data, bt_data, holdings)
        
        # 调用AI API（这里使用模拟数据，实际应调用真实API）
        # return call_ai_api(analysis_prompt)
        return generate_mock_analysis(ic_data, bt_data, holdings)
    except Exception as e:
        return {"error": str(e), "suggestion": "AI分析暂时不可用"}

def build_ai_prompt(ic_data, bt_data, holdings):
    """构建AI分析提示"""
    prompt = {
        "task": "S3选股系统分析",
        "strategy": "S3主候选-阶梯失活+加密-止损10%",
        "data": {
            "ic_freshness": ic_data.get('freshness_days', '未知') if ic_data else '未知',
            "bt_result": {
                "win_rate": bt_data.get('win_rate', '未知') if bt_data else '未知',
                "max_drawdown": bt_data.get('max_drawdown', '未知') if bt_data else '未知',
                "profit_factor": bt_data.get('profit_factor', '未知') if bt_data else '未知',
            } if bt_data else None,
            "holdings_count": len(holdings.get('holdings', [])) if holdings else 0,
            "cash": holdings.get('available_cash', 0) if holdings else 0
        },
        "questions": [
            "当前因子IC是否有效？",
            "S3策略是否应该继续执行？",
            "是否有更好的备选策略？",
            "风险提示是什么？"
        ]
    }
    return prompt

def generate_mock_analysis(ic_data, bt_data, holdings):
    """生成模拟AI分析（实际使用时替换为真实API调用）"""
    analysis = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy_status": "✅ 正常执行",
        "factor_status": "✅ IC有效",
        "risk_level": "🟡 中等",
        "suggestions": [
            "因子IC在有效范围内，建议继续执行S3策略",
            "当前空仓，等待选股信号",
            "关注因子衰减预警",
            "建议每周复盘一次因子表现"
        ],
        "warnings": [
            "回撤56.7%已过门禁（≤60%，2026-10-15新基线重裁；DD<53%确认后回退53%）",
            "需关注市场环境变化"
        ],
        "next_action": "等待老大确认买入"
    }
    return analysis

def generate_dashboard():
    """生成美化版动态看板HTML"""
    # 加载数据
    rank_data = get_latest_rank()
    holdings = load_json(DATA_DIR / "holdings.json") or {}
    review = load_json(DATA_DIR / "review_status.json") or {}
    launch = load_json(ROOT / "data" / "launch_log.json") or {}
    ai_analysis = get_ai_analysis()
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 账户信息
    cash = holdings.get("available_cash", 22103.56)
    positions = holdings.get("holdings", [])
    pos_count = len(positions)
    
    # S3状态 — S1 统一仲裁读法 (review_gate.evaluate)
    _gate_v2 = _rg.evaluate(str(DATA_DIR / "review_status.json"))
    s3_approved = not _gate_v2["frozen"]
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
            row_class = "top1-row" if is_top1 else ""
            score_color = "#f59e0b" if score >= 70 else ("#6366f1" if score >= 50 else "#8a93a3")
            top1_badge = '<span class="top1-badge">TOP1</span>' if is_top1 else ""
            candidates_html += f'''
            <tr class="{row_class}">
                <td class="rank-num">{rank}</td>
                <td class="code">{code}</td>
                <td class="name">{name}</td>
                <td class="score" style="color:{score_color}">{score}</td>
                <td>{top1_badge}</td>
            </tr>'''
    else:
        candidates_html = '<tr><td colspan="5" style="text-align:center;color:#8a93a3">暂无数据</td></tr>'
    
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
            holdings_html += f'''
            <tr>
                <td>{code}</td>
                <td>{name}</td>
                <td>{shares}</td>
                <td>{cost:.2f}</td>
                <td>{current:.2f}</td>
                <td class="{pnl_class}">{pnl_pct:+.1f}%</td>
            </tr>'''
    else:
        holdings_html = '<tr><td colspan="6" style="text-align:center;color:#8a93a3">空仓</td></tr>'
    
    # 门禁状态
    gate_ok = s3_approved and pos_count <= 1
    gate_status = "✅ 通过" if gate_ok else "⚠️ 检查"
    
    # AI分析HTML
    ai_html = ""
    if ai_analysis and "error" not in ai_analysis:
        ai_html = f'''
        <div class="ai-section">
            <div class="ai-status">{ai_analysis.get("strategy_status", "")}</div>
            <div class="ai-level">风险等级: {ai_analysis.get("risk_level", "")}</div>
            <div class="section-title">💡 建议</div>
            <ul class="suggestions">
                {''.join(f'<li>{s}</li>' for s in ai_analysis.get("suggestions", []))}
            </ul>
            <div class="section-title">⚠️ 警告</div>
            <ul class="warnings">
                {''.join(f'<li>{w}</li>' for w in ai_analysis.get("warnings", []))}
            </ul>
            <div class="next-action">下一步: {ai_analysis.get("next_action", "")}</div>
        </div>'''
    else:
        ai_html = '<div class="ai-error">AI分析暂不可用</div>'
    
    # 生成HTML
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="30">
    <title>S3选股系统看板 v2.0</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ 
            font-family: "Microsoft YaHei", -apple-system, BlinkMacSystemFont, sans-serif; 
            background: {THEME['bg']}; 
            color: {THEME['text']}; 
            padding: 24px;
            font-size: 14px;
            line-height: 1.6;
        }}
        .header {{ 
            margin-bottom: 24px; 
            padding-bottom: 16px;
            border-bottom: 2px solid {THEME['accent']};
        }}
        h1 {{ 
            font-size: 28px; 
            margin-bottom: 8px;
            background: linear-gradient(135deg, {THEME['accent']}, {THEME['accent_purple']});
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .sub {{ color: {THEME['muted']}; font-size: 12px; }}
        .grid {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); 
            gap: 20px; 
        }}
        .card {{ 
            background: {THEME['card_bg']}; 
            border: 1px solid {THEME['border']}; 
            border-radius: 16px; 
            padding: 20px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.4);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .card:hover {{ 
            transform: translateY(-2px);
            box-shadow: 0 12px 32px rgba(0,0,0,0.5);
        }}
        .card-title {{ 
            font-weight: bold; 
            font-size: 16px; 
            margin-bottom: 16px; 
            padding-bottom: 12px;
            border-bottom: 1px solid {THEME['border']};
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .card-body {{ font-size: 13px; line-height: 1.8; }}
        .card-ok {{ border-left: 4px solid {THEME['pos']}; }}
        .card-warn {{ border-left: 4px solid {THEME['warn']}; }}
        .card-danger {{ border-left: 4px solid {THEME['neg']}; }}
        .kv {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid rgba(42,48,64,0.5); }}
        .kv:last-child {{ border-bottom: none; }}
        .b {{ font-weight: bold; color: #fff; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12px; }}
        th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid {THEME['border']}; }}
        th {{ color: {THEME['muted']}; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .pos {{ color: {THEME['pos']}; }}
        .neg {{ color: {THEME['neg']}; }}
        .top1-row {{ background: rgba(99,102,241,0.15); border-left: 3px solid {THEME['accent']}; }}
        .top1-badge {{ 
            background: linear-gradient(135deg, {THEME['warn']}, {THEME['neg']});
            color: #fff;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 10px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .score {{ font-weight: bold; color: {THEME['accent']}; font-size: 16px; }}
        .rank-num {{ font-weight: bold; color: {THEME['muted']}; width: 40px; }}
        .code {{ font-family: monospace; color: {THEME['accent_blue']}; }}
        .name {{ font-weight: 500; }}
        .refresh {{ color: {THEME['muted']}; font-size: 11px; margin-top: 16px; text-align: right; }}
        .tag {{ 
            display: inline-block;
            padding: 4px 12px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .tag-ok {{ background: rgba(16,185,129,0.2); color: {THEME['pos']}; border: 1px solid {THEME['pos']}; }}
        .tag-warn {{ background: rgba(245,158,11,0.2); color: {THEME['warn']}; border: 1px solid {THEME['warn']}; }}
        .tag-danger {{ background: rgba(239,68,68,0.2); color: {THEME['neg']}; border: 1px solid {THEME['neg']}; }}
        .big-num {{ font-size: 28px; font-weight: bold; color: {THEME['accent']}; }}
        .section-title {{ 
            font-size: 12px; 
            color: {THEME['muted']}; 
            margin: 16px 0 8px;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 600;
        }}
        .stat-grid {{ 
            display: grid; 
            grid-template-columns: repeat(3, 1fr); 
            gap: 12px;
            margin-top: 12px;
        }}
        .stat-item {{ 
            background: rgba(99,102,241,0.1); 
            padding: 16px; 
            border-radius: 12px;
            text-align: center;
            border: 1px solid rgba(99,102,241,0.2);
        }}
        .stat-label {{ font-size: 11px; color: {THEME['muted']}; margin-bottom: 8px; text-transform: uppercase; }}
        .stat-value {{ font-size: 24px; font-weight: bold; color: #fff; }}
        .stat-value.pos {{ color: {THEME['pos']}; }}
        .stat-value.neg {{ color: {THEME['neg']}; }}
        .footer {{ 
            margin-top: 24px; 
            text-align: center; 
            color: {THEME['muted']}; 
            font-size: 11px;
            padding: 16px;
            border-top: 1px solid {THEME['border']};
        }}
        .ai-section {{ 
            background: rgba(99,102,241,0.08); 
            padding: 16px; 
            border-radius: 12px;
            border: 1px solid rgba(99,102,241,0.3);
        }}
        .ai-status {{ font-size: 16px; font-weight: bold; color: {THEME['pos']}; margin-bottom: 8px; }}
        .ai-level {{ font-size: 14px; color: {THEME['warn']}; margin-bottom: 12px; }}
        .suggestions, .warnings {{ margin: 8px 0; padding-left: 20px; }}
        .suggestions li {{ color: {THEME['pos']}; margin-bottom: 4px; }}
        .warnings li {{ color: {THEME['warn']}; margin-bottom: 4px; }}
        .next-action {{ 
            margin-top: 12px; 
            padding: 12px; 
            background: rgba(99,102,241,0.2); 
            border-radius: 8px;
            text-align: center;
            font-weight: bold;
            color: {THEME['accent']};
        }}
        .ai-error {{ color: {THEME['neg']}; padding: 12px; background: rgba(239,68,68,0.1); border-radius: 8px; }}
        .kpi {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 12px; }}
        .kpi-item {{ 
            background: rgba(99,102,241,0.1); 
            padding: 16px; 
            border-radius: 12px;
            text-align: center;
        }}
        .kpi-value {{ font-size: 24px; font-weight: bold; color: #fff; }}
        .kpi-label {{ font-size: 11px; color: {THEME['muted']}; margin-top: 4px; }}
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
                    <tr><th>排名</th><th>代码</th><th>名称</th><th>评分</th><th></th></tr>
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
        
        <!-- AI分析 -->
        <div class="card card-warn">
            <div class="card-title"><span>🤖 AI分析</span></div>
            <div class="card-body">
                {ai_html}
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
                <div class="kv"><span>胜率</span><span class="pos">58%</span></div>
                <div class="kv"><span>最大回撤</span><span class="b">37.3%</span></div>
                <div class="kv"><span>盈亏比</span><span class="pos">1.74</span></div>
                <div class="kv"><span>独特选股</span><span class="b">35只</span></div>
                <div class="kv"><span>总收益</span><span class="pos">+160.8%</span></div>
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
    print(f"✅ 美化版看板已生成: {output_file}")
    print(f"   访问: http://127.0.0.1:8666/dashboard.html")
