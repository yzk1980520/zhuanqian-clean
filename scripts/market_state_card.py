"""环境门 + 市场状态雷达 (P0-C 2026-09-02)

输出：output/market_state.html（VChart CDN 单文件）
"""
import os, sys, json, datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

from core.pipeline.tdx_core import get_tdx_data

OUT = os.path.join(PROJECT_DIR, "output", "market_state.html")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build() -> str:
    mkt = load_json(os.path.join(PROJECT_DIR, "data", "market_state_cache.json"))
    signal = load_json(os.path.join(PROJECT_DIR, "data", "daily_signal.json"))
    result = mkt.get("result", {})
    sub = result.get("sub_scores", {})
    radar_names = list(sub.keys())
    radar_values = [sub[k]["score"] for k in radar_names]
    weights = result.get("strategy_weights", {})
    w_names = list(weights.keys())
    w_values = [round(weights[k] * 100, 1) for k in w_names]
    gate_detail = signal.get("gate_detail", {})
    position_advice = result.get("position_advice", "")
    market_score = result.get("market_score", 0)
    market_label = result.get("market_label", "")
    gate_status = gate_detail.get("status", "")
    sh_close = gate_detail.get("sh_close", 0)
    ma250_now = gate_detail.get("ma250", 0)
    pos_ratio = gate_detail.get("position_ratio", 0)

    gate_color = "#4caf7d" if gate_status == "open" else "#f5222d"
    gate_icon = "OPEN" if gate_status == "open" else "CLOSED"

    ts = datetime.datetime.fromtimestamp(result.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M")

    # 上证/MA250
    sh_data = get_tdx_data("sh000001", days=260)
    if sh_data and len(sh_data) >= 250:
        closes = [float(d["close"]) for d in sh_data[-250:]]
        dates = [str(d["date"]) for d in sh_data[-250:]]
        ma250 = [round(sum(closes[max(0, i-249):i+1]) / 250, 2) for i in range(len(closes))]
        sh_json = json.dumps({"dates": dates, "closes": closes, "ma250": ma250}, ensure_ascii=False)
    else:
        sh_json = "{}"

    radar_names_str = ", ".join([f"{{'name':'{n}','max':100}}" for n in radar_names])
    radar_json = json.dumps({"names": radar_names, "values": radar_values}, ensure_ascii=False)
    w_json = json.dumps({"names": w_names, "values": w_values}, ensure_ascii=False)

    score_chips = ""
    colors = ["#1890ff", "#f5222d", "#4caf7d", "#f0b429", "#8884d8"]
    for n, v, c in zip(radar_names, radar_values, colors):
        score_chips += f"<div class='score-chip' style='border-left-color:{c}'><span>{n}</span><b>{v}</b></div>"

    tmpl = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>御龙决 · 环境门 &amp; 市场状态</title>
<link rel="stylesheet" href="https://unpkg.com/@visactor/vchart@2.1.6/dist/vchart.css">
<script src="https://unpkg.com/@visactor/vchart@2.1.6/dist/vchart.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{font-family:'Microsoft YaHei',sans-serif;background:#0f1117;color:#e6e8ee;min-height:100vh}
.app{max-width:900px;margin:0 auto;padding:24px 16px 48px}
.header{display:flex;justify-content:space-between;align-items:center;padding:12px 0;margin-bottom:20px;border-bottom:1px solid #232636}
.header h1{font-size:20px}.meta{font-size:12px;color:#8a93a3}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#1a1e2a;border:1px solid #2a3040;border-radius:12px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,0.3)}
.full{grid-column:1/-1}.card h2{font-size:14px;color:#8a93a3;margin-bottom:10px;font-weight:400}
.gate-box{display:flex;align-items:center;gap:16px;padding:20px 24px;background:#131620;border-radius:10px;border:2px solid %gate_color%;margin-bottom:16px}
.gate-info{font-size:14px;line-height:1.8}.gate-info b{font-size:20px;font-weight:700;color:%gate_color%}
.chart{height:280px;background:#131620;border-radius:8px}
.score-row{display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.score-chip{background:#131620;border-radius:6px;padding:6px 10px;font-size:12px;border-left:3px solid}
.score-chip span{color:#8a93a3;margin-right:4px}
.footer{text-align:center;font-size:11px;color:#555;margin-top:24px;padding-top:12px;border-top:1px solid #232636}
</style></head><body>
<div class="app">
<div class="header"><h1>御龙决 · 环境门 &amp; 市场状态</h1><span class="meta">数据 %ts% | 仓位建议 %position_advice%</span></div>
<div class="gate-box"><div style="font-size:24px">%gate_icon%</div>
<div class="gate-info"><div>上证 <b>%sh_close%</b> vs MA250 <b>%ma250%</b></div>
<div>建议仓位 %pos_ratio%% | 综合评分 %market_score% (%market_label%)</div></div></div>
<div class="grid">
<div class="card"><h2>市场五维评分</h2><div class="score-row">%score_chips%</div><div id="radar" class="chart"></div></div>
<div class="card"><h2>策略权重分布</h2><div id="donut" class="chart"></div></div>
<div class="card full"><h2>上证250日收盘价 vs MA250</h2><div id="sh" class="chart"></div></div>
</div>
<div class="footer">数据源：market_state_cache.json + daily_signal.json + TDX 上证日线</div>
</div>
<script>
const V=window.VChart;
new V.Chart(document.getElementById('radar'),{
  type:'radar',data:[{id:'d',values:%radar_json%}],
  indicator:[%radar_names_str%],
  xField:'name',yField:'value',theme:'dark',
}).renderSync();
new V.Chart(document.getElementById('donut'),{
  type:'pie',data:[{id:'w',values:%w_json%}],
  angleField:'value',colorField:'name',
  innerRadius:0.5,outerRadius:0.85,theme:'dark',
}).renderSync();
const shd=JSON.parse('%sh_json%');
if(shd.dates){
  new V.Chart(document.getElementById('sh'),{
    type:'line',data:[{id:'d',values:shd.dates.map((date,i)=>({date,close:shd.closes[i],ma250:shd.ma250[i]}))}],
    xField:'date',yField:['close','ma250'],seriesField:'y',
    axis:{xAxis:{label:{rotate:90,fontSize:9}}},theme:'dark',
  }).renderSync();
}
</script>
</body></html>"""

    html = tmpl.replace("%gate_color%", gate_color) \
        .replace("%gate_icon%", f"{'🟢' if gate_status == 'open' else '🔴'} {gate_icon}") \
        .replace("%sh_close%", f"{sh_close:.2f}") \
        .replace("%ma250%", f"{ma250_now:.2f}") \
        .replace("%pos_ratio%", f"{pos_ratio*100:.0f}") \
        .replace("%market_score%", str(market_score)) \
        .replace("%market_label%", market_label) \
        .replace("%position_advice%", position_advice) \
        .replace("%ts%", ts) \
        .replace("%score_chips%", score_chips) \
        .replace("%radar_json%", radar_json) \
        .replace("%radar_names_str%", radar_names_str) \
        .replace("%w_json%", w_json) \
        .replace("%sh_json%", sh_json)
    return html


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    html = build()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[P0-C] {OUT} ({len(html)} bytes)")


if __name__ == "__main__":
    main()