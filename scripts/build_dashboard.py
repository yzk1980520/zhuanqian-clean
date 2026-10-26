"""御龙决作战台：4 图整合 (P0-B 2026-09-02)
CDN 切换 ECharts 5.4.3
"""
import os, sys, json, datetime, glob

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

from position_card import get_holdings
from core.pipeline.tdx_core import get_tdx_data

OUT = os.path.join(PROJECT_DIR, "dashboards", "warroom.html")
STOP_LOSS_PCT = 0.08


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build() -> str:
    holdings = get_holdings()
    holding_cards = ""
    hold_js = []  # list of echarts init JS strings

    for idx, h in enumerate(holdings):
        code = h.get("code", "")
        name = h.get("name", code)
        cost = h.get("cost_price", 0)
        shares = h.get("shares", 0) or 0
        if not code or not cost:
            continue
        data = get_tdx_data(code, days=30)
        if not data or len(data) < 3:
            continue
        dates = [str(d["date"]) for d in data]
        closes = [float(d["close"]) for d in data]
        highs = [float(d["high"]) for d in data]
        latest = closes[-1]
        pnl = round((latest / cost - 1) * 100, 1)
        peak = max(highs)
        stop_loss = round(cost * (1 - STOP_LOSS_PCT), 3)
        value = round(latest * shares, 0) if shares else 0
        chart_id = "h-{}".format(idx)
        pnl_class = "pos" if pnl >= 0 else "neg"
        pnl_arrow = "+" if pnl >= 0 else ""

        holding_cards += "<div class='hold-card'><div class='hold-head'><h3>{}</h3><span>{}</span><span class='pnl {}'>{}</span></div><div class='hold-stats'><span>成本{:.2f}</span><span>现价{:.2f}</span><span>止损{:.2f}</span><span>最高{:.2f}</span><span>市值{:.0f}</span></div><div id='{}' class='mini-chart'></div></div>".format(
            name, code, pnl_class, "{}{}%".format(pnl_arrow, pnl), cost, latest, stop_loss, peak, value, chart_id)

        # Build ECharts option as Python dict → JSON
        opt = {
            "backgroundColor": "transparent",
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 35, "right": 20, "top": 15, "bottom": 35},
            "xAxis": {"type": "category", "data": dates,
                      "axisLabel": {"rotate": 45, "fontSize": 8, "color": "#8a93a3"},
                      "axisLine": {"lineStyle": {"color": "#2a3040"}}},
            "yAxis": {"type": "value",
                      "axisLabel": {"color": "#8a93a3"},
                      "splitLine": {"lineStyle": {"color": "#252b3a"}}},
            "series": [{
                "type": "line", "data": closes, "smooth": True,
                "lineStyle": {"color": "#4caf7d", "width": 2},
                "itemStyle": {"color": "#4caf7d"},
                "areaStyle": {"color": "rgba(76,175,125,0.15)"},
                "markLine": {
                    "silent": True, "symbol": "none",
                    "data": [
                        {"yAxis": cost, "name": "成本{}".format(cost),
                         "label": {"formatter": "成本{}".format(cost), "color": "#1890ff"},
                         "lineStyle": {"color": "#1890ff", "type": "dashed"}},
                        {"yAxis": stop_loss, "name": "止损{}".format(stop_loss),
                         "label": {"formatter": "止损{}".format(stop_loss), "color": "#f5222d"},
                         "lineStyle": {"color": "#f5222d", "type": "dashed"}},
                    ]
                }
            }]
        }
        opt_json = json.dumps(opt, ensure_ascii=False)
        hold_js.append("echarts.init(document.getElementById('{}')).setOption({});".format(chart_id, opt_json))

    # 市场状态
    mkt = load_json(os.path.join(PROJECT_DIR, "data", "market_state_cache.json"))
    result = mkt.get("result", {})
    sub = result.get("sub_scores", {})
    radar_names = list(sub.keys())
    radar_values = [sub[k]["score"] for k in radar_names]
    position_advice = result.get("position_advice", "")
    market_score = result.get("market_score", 0)
    market_label = result.get("market_label", "")

    # 环境门
    signal = load_json(os.path.join(PROJECT_DIR, "data", "daily_signal.json"))
    gate_detail = signal.get("gate_detail", {})
    gate_status = gate_detail.get("status", "closed")
    gate_color = "#4caf7d" if gate_status == "open" else "#f5222d"
    gate_icon_text = "OPEN" if gate_status == "open" else "CLOSED"
    sh_close = gate_detail.get("sh_close", 0)
    ma250 = gate_detail.get("ma250", 0)

    # 回测
    bt = load_json(os.path.join(PROJECT_DIR, "backtest_result.json"))
    win_rate = bt.get("胜率", 0)
    excess_5 = bt.get("超额收益5日", 0)

    # WF
    # WF 结论本地化
    def _wf_conclusion(raw):
        if "PASS" in raw:
            return "通过 ✅"
        return "可用偏弱 🟡" if "WEAK" in raw else raw

    wf_files = sorted(glob.glob(os.path.join(PROJECT_DIR, "data", "audit", "walk_forward_purged_*.json")), reverse=True)
    wf_table = ""
    if wf_files:
        wf = load_json(wf_files[0])
        for f in wf.get("factors", []):
            s = wf.get("summary", {}).get(f, {})
            c = "#4caf7d" if "PASS" in s.get("conclusion", "") else "#f0b429"
            wf_table += "<tr><td>{}</td><td>{:.4f}</td><td>{:.4f}</td><td style='color:{}'>{}</td></tr>".format(
                f, s.get('avg_train_ic', 0), s.get('avg_test_ic', 0), c, _wf_conclusion(s.get('conclusion', '?')))

    gate_icon = "OPEN" if gate_status == "open" else "CLOSED"
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    gate_ts = signal.get("timestamp", "")
    # 环境门优先级标注
    gate_priority = ""
    if gate_status == "closed":
        gate_priority = " | ⚠️门闭：仓位建议仅供参考，实际以环境门≤30%为准"

    hold_js_str = "\n".join(hold_js)

    # 雷达图 ECharts option
    radar_indicators = [{"name": n, "max": 100} for n in radar_names]
    # 60分及格圈（虚线）
    radar_opt = {
        "backgroundColor": "transparent", "tooltip": {},
        "radar": {
            "indicator": radar_indicators,
            "radius": "65%", "center": ["50%", "55%"],
            "axisName": {"color": "#e6e8ee", "fontSize": 11},
            "splitLine": {"lineStyle": {"color": "#2a3040"}},
            "splitArea": {"areaStyle": {"color": ["#131620", "#1a1e2a"]}},
            "axisLine": {"lineStyle": {"color": "#2a3040"}},
        },
        "series": [{
            "type": "radar",
            "data": [
                {"value": radar_values, "name": "市场评分",
                 "areaStyle": {"color": "rgba(24,144,255,0.25)"},
                 "lineStyle": {"color": "#1890ff", "width": 2},
                 "itemStyle": {"color": "#1890ff"}},
                {"value": [60] * len(radar_names), "name": "及格线60",
                 "areaStyle": None,
                 "lineStyle": {"color": "#f0b429", "type": "dashed", "width": 1},
                 "itemStyle": {"color": "#f0b429"},
                 "symbol": "none"},
            ]
        }]
    }
    radar_opt_json = json.dumps(radar_opt, ensure_ascii=False)

    tmpl = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>御龙决 · 作战台</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{font-family:'Microsoft YaHei',sans-serif;background:#0f1117;color:#e6e8ee;min-height:100vh}
.app{max-width:1200px;margin:0 auto;padding:20px 16px 48px}
.header{display:flex;justify-content:space-between;align-items:center;padding:10px 0;margin-bottom:16px;border-bottom:1px solid #232636}
.header h1{font-size:20px}.meta{font-size:12px;color:#8a93a3}
.gate-box{display:flex;align-items:center;gap:16px;padding:14px 24px;background:#131620;border-radius:10px;border:2px solid %gate_color%;margin-bottom:16px}
.gate-info{font-size:14px;line-height:1.8}.gate-info b{color:%gate_color%;font-size:18px;font-weight:700}
.kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px}
.kpi{background:#131620;border-radius:8px;padding:10px;text-align:center}
.kpi span{display:block;font-size:10px;color:#8a93a3;margin-bottom:2px}
.kpi b{font-size:16px;font-weight:700}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#1a1e2a;border:1px solid #2a3040;border-radius:12px;padding:14px;box-shadow:0 2px 8px rgba(0,0,0,0.3)}
.full{grid-column:1/-1}.card h2{font-size:13px;color:#8a93a3;margin-bottom:8px;font-weight:400}
.mini-chart{height:200px}.chart{height:260px}
.hold-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin-bottom:8px}
.hold-card{background:#131620;border-radius:8px;padding:10px;border:1px solid #252b3a}
.hold-head{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.hold-head h3{font-size:14px;font-weight:600}.hold-head span{font-size:11px;color:#6ea8fe}
.hold-head .pnl.pos{color:#4caf7d;margin-left:auto}.hold-head .pnl.neg{color:#e06c6c;margin-left:auto}
.hold-stats{display:flex;gap:8px;flex-wrap:wrap;font-size:10px;color:#8a93a3;margin-bottom:4px}
.hold-stats span{background:#0f1117;padding:2px 6px;border-radius:4px}
table{width:100%;border-collapse:collapse;font-size:11px}
th,td{padding:4px 6px;border-bottom:1px solid #252b3a;text-align:left}
th{color:#8a93a3;font-weight:400;font-size:10px}
.footer{text-align:center;font-size:10px;color:#555;margin-top:20px;padding-top:10px;border-top:1px solid #232636}
</style></head><body>
<div class="app">
<div class="header"><h1>御龙决 · 作战台</h1><span class="meta">生成 %ts% | 数据时效 %gate_ts% | %position_advice%%gate_priority%</span></div>
<div class="gate-box"><div style="font-size:20px">%gate_icon%</div>
<div class="gate-info"><div>上证 <b>%sh_close%</b> vs MA250 <b>%ma250%</b></div><div>市场评分 %market_score% (%market_label%) | 仓位建议 %position_advice%</div></div></div>
<div class="kpi-row">
<div class="kpi"><span>胜率</span><b>%win_rate%</b></div>
<div class="kpi"><span>5日超额</span><b>%ex5%</b></div>
<div class="kpi"><span>持仓数</span><b>%hold_count%</b></div>
<div class="kpi"><span>环境门</span><b style="color:%gate_color%">%gate_icon_text%</b></div>
</div>
<div class="grid">
<div class="card full"><h2>持仓K线（收盘价+成本线+止损线）</h2><div class="hold-grid">%holdings%</div></div>
<div class="card"><h2>市场五维雷达</h2><div id="radar" class="chart"></div></div>
<div class="card"><h2>因子 Walk-Forward 验证</h2><table><tr><th>因子</th><th>训练IC</th><th>测试IC</th><th>结论</th></tr>%wf_table%</table></div>
</div>
<div class="footer">御龙决作战台 V1 | ECharts 5.4.3 | 数据源：TDX + holdings + market_state_cache + backtest_result + walk_forward</div>
</div>
<script>
%hold_js%
echarts.init(document.getElementById('radar')).setOption(%radar_opt%);
</script>
</body></html>"""

    html = tmpl.replace("%gate_color%", gate_color) \
        .replace("%ts%", ts) \
        .replace("%gate_ts%", gate_ts) \
        .replace("%gate_priority%", gate_priority) \
        .replace("%position_advice%", position_advice) \
        .replace("%gate_icon%", gate_icon) \
        .replace("%sh_close%", "{:.0f}".format(sh_close)) \
        .replace("%ma250%", "{:.0f}".format(ma250)) \
        .replace("%market_score%", str(market_score)) \
        .replace("%market_label%", market_label) \
        .replace("%win_rate%", str(win_rate) + "%") \
        .replace("%ex5%", "{:+.2f}%".format(excess_5)) \
        .replace("%hold_count%", str(len(holdings))) \
        .replace("%gate_icon_text%", gate_icon_text) \
        .replace("%holdings%", holding_cards) \
        .replace("%wf_table%", wf_table) \
        .replace("%hold_js%", hold_js_str) \
        .replace("%radar_opt%", radar_opt_json)
    return html


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    html = build()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()