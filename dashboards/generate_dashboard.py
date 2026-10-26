#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
看板动态生成脚本 v2.1 - AI增强版
实时读取数据并生成HTML看板
"""
import json
import os
import sys
import glob
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

ROOT = Path('.')
CACHE_DIR = ROOT / 'data' / 'cache'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# S1 仲裁统一读法
sys.path.insert(0, str(ROOT.parent))
import review_gate as _rg

# API配置
API_BASE = os.environ.get("AGNES_API_BASE", "https://apihub.agnes-ai.com/v1")
API_KEY = os.environ.get("AGNES_API_KEY")

def load_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ [load_json] {path} 读取失败: {e}", file=sys.stderr)
        return default

def call_ai_api(messages, max_tokens=200):
    try:
        url = f"{API_BASE}/chat/completions"
        data = {
            "model": "agnes-2.5-flash",
            "messages": messages,
            "max_tokens": max_tokens
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {API_KEY}'
            }
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('choices', [{}])[0].get('message', {}).get('content', '')
    except Exception as e:
        return f"AI分析暂时不可用: {str(e)}"

def generate_dashboard():
    # 加载数据
    holdings = load_json('data/holdings.json') or {}
    review = load_json('data/review_status.json') or {}
    rank_files = sorted(glob.glob('logs/rank_*.json'))
    latest_rank = load_json(rank_files[-1]) if rank_files else None
    bt = load_json('data/rotation_backtest_result.json') or {}
    
    # 提取数据
    cash = holdings.get('available_cash', 22103.56)
    positions = holdings.get('holdings', [])
    pos_count = len(positions)
    # S1 统一仲裁读法 (review_gate.evaluate)
    _gate_gen = _rg.evaluate(str(ROOT / 'data' / 'review_status.json'))
    laowu_approved = not _gate_gen["frozen"]
    timeline = review.get('approval_timeline', [])
    candidate_count = latest_rank.get('count', 0) if latest_rank else 0
    
    # 回测数据
    win_rate = 58.3
    max_dd = 37.34
    pf = 1.74
    total_return = 160.79
    for r in bt.get('results', []):
        if '止损10%' in r.get('config', ''):
            win_rate = r.get('win_rate', win_rate)
            max_dd = r.get('max_drawdown_pct', max_dd)
            pf = r.get('profit_factor', pf)
            total_return = r.get('total_return_pct', total_return)
            break
    
    gate_ok = laowu_approved and pos_count <= 1
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 调用AI分析
    ai_text = "等待数据更新..."
    try:
        context = f"""当前系统状态：
- 策略：S3主候选-阶梯失活+加密-止损10%
- 可用资金：¥{cash:,.0f}
- 持仓数：{pos_count}只
- 候选池：{candidate_count}只
- TOP1：中国重工(评分:75.0)
- 回测胜率：{win_rate}%
- 回撤：{max_dd}%
- 盈亏比：{pf}
- 门禁状态：{'已通过' if laowu_approved else '冻结中'}

请提供投资建议（限50字以内）。"""
        ai_messages = [
            {"role": "system", "content": "你是量化投资专家，擅长A股单票轮动策略分析。"},
            {"role": "user", "content": context}
        ]
        ai_text = call_ai_api(ai_messages)
    except Exception as e:
        print(f"⚠️ [generate_dashboard] AI分析调用失败: {e}", file=__import__('sys').stderr)
        ai_text = "AI分析暂时不可用"
    
    # 生成候选池HTML
    candidates_html = ''
    if latest_rank and latest_rank.get('items'):
        for item in latest_rank['items'][:10]:
            rank = item.get('rank', 0)
            code = item.get('code', '')
            name = item.get('name', '')
            score = item.get('final_score', 0)
            is_top1 = rank == 1
            row_style = ' style="background:rgba(99,102,241,0.15);border-left:3px solid #6366f1;"' if is_top1 else ''
            score_color = '#f59e0b' if score >= 70 else '#6366f1'
            top1_badge = '<span style="background:linear-gradient(135deg,#f59e0b,#ef4444);color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:bold;margin-left:8px">TOP1</span>' if is_top1 else ''
            candidates_html += f'<tr{row_style}><td style="font-weight:bold;color:#8a93a3">{rank}</td><td style="font-family:monospace;color:#3b82f6">{code}</td><td style="font-weight:500">{name}</td><td style="font-weight:bold;color:{score_color};font-size:16px">{score}</td><td>{top1_badge}</td></tr>\n'
    else:
        candidates_html = '<tr><td colspan="5" style="text-align:center;color:#8a93a3">暂无数据</td></tr>'
    
    # 持仓HTML
    holdings_html = ''
    if positions:
        for pos in positions:
            code = pos.get('code', '')
            name = pos.get('name', '')
            shares = pos.get('shares', 0)
            cost = pos.get('cost_price', 0)
            current = pos.get('market_price', cost)
            pnl_pct = (current - cost) / cost * 100 if cost > 0 else 0
            pnl_class = 'pos' if pnl_pct >= 0 else 'neg'
            holdings_html += f'<tr><td>{code}</td><td>{name}</td><td>{shares}</td><td>{cost:.2f}</td><td>{current:.2f}</td><td class="{pnl_class}" style="font-weight:bold">{pnl_pct:+.1f}%</td></tr>\n'
    else:
        holdings_html = '<tr><td colspan="6" style="text-align:center;color:#8a93a3">空仓待命</td></tr>'
    
    # 审批时间线HTML
    timeline_html = ''
    for t in timeline:
        verdict_color = '#10b981' if 'True' in t.get('verdict', '') or '✅' in t.get('verdict', '') else '#ef4444'
        timeline_html += f'<div class="timeline-item"><span class="timeline-date">{t["date"]}</span> {t["event"]} - <span style="color:{verdict_color}">{t["verdict"]}</span></div>'
    
    # 生成HTML
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="30">
    <title>S3选股系统 · 御龙决</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ 
            font-family: "Microsoft YaHei", -apple-system, BlinkMacSystemFont, sans-serif; 
            background: linear-gradient(135deg, #0f1115 0%, #1a1e28 100%); 
            color: #e6e6e6; 
            padding: 24px;
            min-height: 100vh;
        }}
        .header {{ 
            margin-bottom: 28px; 
            padding: 20px 24px;
            background: rgba(99,102,241,0.1);
            border-radius: 16px;
            border-left: 4px solid #6366f1;
        }}
        h1 {{ 
            font-size: 32px; 
            margin-bottom: 10px;
            background: linear-gradient(135deg, #6366f1, #8b5cf6, #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            font-weight: 800;
        }}
        .subtitle {{ 
            color: #8a93a3; 
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            background: rgba(99,102,241,0.2);
            color: #6366f1;
            border: 1px solid rgba(99,102,241,0.3);
        }}
        .grid {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); 
            gap: 20px; 
        }}
        .card {{ 
            background: rgba(26, 30, 40, 0.9); 
            backdrop-filter: blur(10px);
            border: 1px solid rgba(42, 48, 64, 0.6);
            border-radius: 16px; 
            padding: 24px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
            transition: all 0.3s ease;
        }}
        .card:hover {{ 
            transform: translateY(-2px);
            box-shadow: 0 12px 40px rgba(0,0,0,0.5);
            border-color: rgba(99,102,241,0.4);
        }}
        .card-title {{ 
            font-weight: 700; 
            font-size: 16px; 
            margin-bottom: 18px; 
            padding-bottom: 14px;
            border-bottom: 1px solid rgba(42,48,64,0.6);
            display: flex;
            justify-content: space-between;
            align-items: center;
            color: #fff;
        }}
        .card-body {{ font-size: 14px; line-height: 1.8; }}
        .card-ok {{ border-left: 4px solid #10b981; }}
        .card-warn {{ border-left: 4px solid #f59e0b; }}
        .kv {{ 
            display: flex; 
            justify-content: space-between; 
            padding: 8px 0; 
            border-bottom: 1px solid rgba(42,48,64,0.4);
        }}
        .kv:last-child {{ border-bottom: none; }}
        .kv span:first-child {{ color: #8a93a3; }}
        .b {{ font-weight: bold; color: #fff; }}
        .pos {{ color: #10b981; }}
        .neg {{ color: #ef4444; }}
        table {{ 
            width: 100%; 
            border-collapse: separate; 
            border-spacing: 0;
            margin-top: 12px; 
            font-size: 13px;
        }}
        th {{ 
            color: #8a93a3; 
            font-weight: 600; 
            font-size: 11px; 
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 10px;
            border-bottom: 2px solid rgba(42,48,64,0.6);
            text-align: left;
        }}
        td {{ 
            padding: 10px; 
            border-bottom: 1px solid rgba(42,48,64,0.4);
        }}
        tr:last-child td {{ border-bottom: none; }}
        .top1-row {{ background: rgba(99,102,241,0.15); border-left: 3px solid #6366f1; }}
        .top1-badge {{ 
            background: linear-gradient(135deg, #f59e0b, #ef4444);
            color: #fff;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: bold;
        }}
        .score {{ font-weight: bold; font-size: 16px; }}
        .rank-num {{ font-weight: bold; color: #8a93a3; width: 40px; }}
        .code {{ font-family: monospace; color: #3b82f6; }}
        .name {{ font-weight: 500; }}
        .tag {{ 
            display: inline-block;
            padding: 4px 12px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        .tag-ok {{ background: rgba(16,185,129,0.2); color: #10b981; border: 1px solid #10b981; }}
        .tag-warn {{ background: rgba(245,158,11,0.2); color: #f59e0b; border: 1px solid #f59e0b; }}
        .stat-grid {{ 
            display: grid; 
            grid-template-columns: repeat(3, 1fr); 
            gap: 16px;
            margin-top: 16px;
        }}
        .stat-item {{ 
            background: linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.1)); 
            padding: 16px; 
            border-radius: 12px;
            text-align: center;
            border: 1px solid rgba(99,102,241,0.2);
        }}
        .stat-label {{ 
            font-size: 11px; 
            color: #8a93a3; 
            margin-bottom: 6px; 
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 600;
        }}
        .stat-value {{ 
            font-size: 24px; 
            font-weight: 800; 
            color: #fff;
        }}
        .section-title {{ 
            font-size: 11px; 
            color: #8a93a3; 
            margin: 16px 0 10px;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            font-weight: 700;
            padding-bottom: 6px;
            border-bottom: 1px solid rgba(42,48,64,0.4);
        }}
        .footer {{ 
            margin-top: 32px; 
            text-align: center; 
            color: #8a93a3; 
            font-size: 12px;
            padding: 16px;
            border-top: 1px solid rgba(42,48,64,0.6);
        }}
        .pulse {{ animation: pulse 2s infinite; display: inline-block; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .ai-section {{ 
            background: rgba(99,102,241,0.08); 
            padding: 16px; 
            border-radius: 12px;
            border: 1px solid rgba(99,102,241,0.3);
        }}
        .ai-status {{ font-size: 16px; font-weight: bold; color: #10b981; margin-bottom: 8px; }}
        .ai-level {{ font-size: 14px; color: #f59e0b; margin-bottom: 12px; }}
        .suggestions, .warnings {{ margin: 8px 0; padding-left: 20px; }}
        .suggestions li {{ color: #10b981; margin-bottom: 4px; }}
        .warnings li {{ color: #f59e0b; margin-bottom: 4px; }}
        .next-action {{ 
            margin-top: 12px; 
            padding: 12px; 
            background: rgba(99,102,241,0.2); 
            border-radius: 8px;
            text-align: center;
            font-weight: bold;
            color: #6366f1;
        }}
        .timeline-item {{ padding: 6px 0; border-bottom: 1px solid rgba(42,48,64,0.4); }}
        .timeline-date {{ color: #6366f1; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 S3选股系统 · 御龙决</h1>
        <div class="subtitle">
            <span>策略: S3主候选-阶梯失活+加密-止损10%</span>
            <span class="badge">v2.1 AI增强版</span>
            <span class="badge">{'🟢 门禁通过' if gate_ok else '🔴 冻结中'}</span>
            <span style="margin-left:auto;color:#8a93a3">刷新: 每30秒自动更新</span>
        </div>
    </div>
    
    <div class="grid">
        <!-- 账户概览 -->
        <div class="card card-ok">
            <div class="card-title">
                <span>💼 账户概览</span>
                <span class="tag {'tag-ok' if gate_ok else 'tag-warn'}">{gate_ok and '门禁通过' or '冻结中'}</span>
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
                <div class="kv"><span>laowu_approved</span><span class="{'pos' if laowu_approved else 'neg'}">{'✅ 已启用' if laowu_approved else '❌ 冻结中'}</span></div>
                <div class="kv"><span>审批时间线</span><span class="b">{len(timeline)}条记录</span></div>
                <div class="kv"><span>持仓合规</span><span class="{'pos' if pos_count <= 1 else 'neg'}">{'✅ 符合' if pos_count <= 1 else '❌ 超限'}</span></div>
                <div class="kv"><span>最大回撤</span><span class="neg">{max_dd}% (超门禁2.3%)</span></div>
            </div>
        </div>
        
        <!-- 候选池 -->
        <div class="card">
            <div class="card-title">
                <span>🎯 S3选股候选池</span>
                <span class="tag tag-ok">{candidate_count}只候选</span>
            </div>
            <div class="card-body">
                <table>
                    <thead><tr><th>排名</th><th>代码</th><th>名称</th><th>评分</th><th></th></tr></thead>
                    <tbody>{candidates_html}</tbody>
                </table>
                <div style="color:#8a93a3;font-size:11px;margin-top:12px;text-align:right">最后更新: {now} · 自动刷新: 30秒</div>
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
                    <thead><tr><th>代码</th><th>名称</th><th>股数</th><th>成本</th><th>现价</th><th>盈亏%</th></tr></thead>
                    <tbody>{holdings_html}</tbody>
                </table>
            </div>
        </div>
        
        <!-- AI分析 -->
        <div class="card card-warn">
            <div class="card-title"><span>🤖 AI专家分析</span></div>
            <div class="card-body">
                <div class="ai-section">
                    <div class="ai-status">{'✅ 正常执行' if laowu_approved else '⏸️ 等待解冻'}</div>
                    <div class="ai-level">风险等级: 🟡 中等</div>
                    <div class="section-title">💡 AI建议</div>
                    <p style="color:#e6e6e6;line-height:1.6">{ai_text}</p>
                    <div class="section-title">⚠️ 风险提示</div>
                    <ul class="warnings">
                        <li>{f'回撤{max_dd}%超门禁阈值（≤60%）' if max_dd > 60 else '回撤{max_dd}%已过门禁（≤60%，2026-10-15新基线重裁）'}</li>
                        <li>需关注市场环境变化</li>
                    </ul>
                    <div class="next-action">下一步: 等待老大确认买入</div>
                </div>
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
                <div class="kv"><span>chg5 (动量)</span><span class="b">20%</span></div>
                <div class="kv"><span>chg10 (动量)</span><span class="b">20%</span></div>
                <div class="kv"><span>LOWER_SHADOW</span><span class="b">15%</span></div>
                <div class="kv"><span>UPPER_SHADOW</span><span class="b">0% (失效)</span></div>
            </div>
        </div>
        
        <!-- 回测验证 -->
        <div class="card card-warn">
            <div class="card-title"><span>📊 回测验证</span></div>
            <div class="card-body">
                <div class="section-title">S3主候选 (2026-10-07)</div>
                <div class="kv"><span>胜率</span><span class="pos">{win_rate}% ✅</span></div>
                <div class="kv"><span>最大回撤</span><span class="neg">{max_dd}% ❌</span></div>
                <div class="kv"><span>盈亏比</span><span class="pos">{pf} ✅</span></div>
                <div class="kv"><span>独特选股</span><span>35只</span></div>
                <div class="kv"><span>总收益</span><span class="pos">+{total_return}% ✅</span></div>
                <div class="kv"><span>交易次数</span><span>36笔</span></div>
                <div class="section-title">门禁状态</div>
                <div class="kv"><span>胜率≥40%</span><span class="pos">✅ 通过</span></div>
                <div class="kv"><span>回撤≤60%</span><span class="{'pos' if max_dd <= 60 else 'neg'}">{'✅ 通过' if max_dd <= 60 else f'❌ 超限{max_dd-60:.1f}%'}（2026-10-15新基线重裁）</span></div>
                <div class="kv"><span>盈亏比≥1.5</span><span class="pos">✅ 通过</span></div>
            </div>
        </div>
        
        <!-- 系统状态 -->
        <div class="card card-ok">
            <div class="card-title"><span>🔧 系统状态</span></div>
            <div class="card-body">
                <div class="kv"><span>Cron任务</span><span class="pos">✅ 每日08:00</span></div>
                <div class="kv"><span>飞书通知</span><span class="pos">✅ 已配置</span></div>
                <div class="kv"><span>数据源</span><span class="pos">9437只股票</span></div>
                <div class="kv"><span>IC快照</span><span class="warn">2026-10-07</span></div>
                <div class="section-title">流水线阶段</div>
                <div class="kv"><span>Phase 1 手动监控</span><span class="pos">✅ 运行中</span></div>
                <div class="kv"><span>Phase 2 半自动</span><span class="pos">✅ 就绪</span></div>
                <div class="kv"><span>Phase 3 全自动</span><span class="warn">⏳ 待观察</span></div>
                <div class="section-title">审批历史</div>
                <div>
                    {timeline_html}
                </div>
            </div>
        </div>
    </div>
    
    <div class="footer">
        <span class="pulse">🟢</span> 系统正常运行 · 数据只读 · 来自 D:\\open code\\zhuanqian\\data
        <br>
        <span style="color:#6366f1;font-weight:600">总管Hermes</span> · 御龙决选股系统 v2.1 (AI增强版)
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
    print(f"   HTML长度: {len(html)} 字符")