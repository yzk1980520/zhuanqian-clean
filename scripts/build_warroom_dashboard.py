#!/usr/bin/env python3
"""Auto-generate warroom.html from structured data sources.
2026-09-24 total-pipe refactor: pulls all data, builds HTML in one shot.
"""
import json, os, sys, datetime, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dashboards", "warroom.html")

def today_str():
    return datetime.date.today().isoformat()

def load(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def esc(s):
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_holding_cards(holdings):
    """持仓卡 + 迷你收益图 (2026-09-26 修复)
    原实现 import build_dashboard._build_holding_cards —— 该函数并不存在,
    一直走 fallback 导致卡片"现价-/市值-"。现直接用 tdx_core 实时行情实现。
    止损优先取 holdings 中实际维护的 stop_loss(可能已人工调整), 缺省回退 成本*0.92。
    行情不可用时退回台账最近价(last_price/market_price), 保证卡片不出现'-'。
    """
    sys.path.insert(0, ROOT)
    from core.pipeline.tdx_core import get_tdx_data
    cards = ""
    js = []
    for idx, h in enumerate(holdings):
        code = h.get("code", "")
        name = h.get("name", code)
        cost = h.get("cost_price", 0) or 0
        shares = h.get("shares", 0) or 0
        if not code or not cost:
            continue
        try:
            data = get_tdx_data(code, 30) or []
        except Exception:
            data = []
        if data and len(data) >= 3:
            dates = [str(d["date"]) for d in data]
            closes = [float(d["close"]) for d in data]
            highs = [float(d["high"]) for d in data]
            latest = closes[-1]
            peak = max(highs)
        else:
            latest = float(h.get("last_price") or h.get("market_price") or cost)
            peak = max(latest, cost)
            dates, closes = [], []
        stop_loss = float(h.get("stop_loss") or (cost * 0.92))
        value = round(latest * shares, 0) if shares else 0
        pnl = round((latest / cost - 1) * 100, 1)
        pnl_cls = "pos" if pnl >= 0 else "neg"
        arrow = "+" if pnl >= 0 else ""
        chart_id = "h-{}".format(idx)
        cards += (
            "<div class='hold-card'><div class='hold-head'><h3>{}</h3><span>{}</span>"
            "<span class='pnl {}'>{}{}%</span></div>"
            "<div class='hold-stats'><span>成本{:.2f}</span><span>现价{:.2f}</span>"
            "<span>止损{:.2f}</span><span>最高{:.2f}</span><span>市值{:,.0f}</span></div>"
            "<div id='{}' class='mini-chart'></div></div>"
        ).format(esc(name), esc(code), pnl_cls, arrow, pnl,
                 cost, latest, stop_loss, peak, value, chart_id)
        if closes:
            # 2026-09-26 重皮: 收益曲线红涨绿跌(A股惯例), 成本线=灰白, 止损线=信号金
            line_color = "#F43F5E" if pnl >= 0 else "#10B981"
            opt = {
                "backgroundColor": "transparent",
                "tooltip": {"trigger": "axis",
                            "backgroundColor": "#1C1C20", "borderColor": "#27272A",
                            "textStyle": {"color": "#FAFAFA", "fontSize": 11}},
                "grid": {"left": 42, "right": 14, "top": 18, "bottom": 30},
                "xAxis": {"type": "category", "data": dates,
                          "axisLabel": {"rotate": 45, "fontSize": 9, "color": "#71717A",
                                        "fontFamily": "JetBrains Mono, Cascadia Mono, Consolas, monospace"},
                          "axisLine": {"lineStyle": {"color": "#27272A"}}},
                "yAxis": {"type": "value", "scale": True,
                          "axisLabel": {"color": "#71717A",
                                        "fontFamily": "JetBrains Mono, Cascadia Mono, Consolas, monospace"},
                          "splitLine": {"lineStyle": {"color": "#27272A"}}},
                "series": [{
                    "type": "line", "data": closes, "smooth": True,
                    "lineStyle": {"color": line_color, "width": 2},
                    "itemStyle": {"color": line_color},
                    "areaStyle": {"color": line_color, "opacity": 0.12},
                    "markLine": {
                        "silent": True, "symbol": "none",
                        "data": [
                            {"yAxis": cost, "name": "成本{}".format(cost),
                             "label": {"formatter": "成本{}".format(cost), "color": "#A1A1AA",
                                       "fontSize": 9, "position": "insideEndTop"},
                             "lineStyle": {"color": "#A1A1AA", "type": "dashed"}},
                            {"yAxis": stop_loss, "name": "止损{}".format(stop_loss),
                             "label": {"formatter": "止损{}".format(stop_loss), "color": "#F59E0B",
                                       "fontSize": 9, "position": "insideEndBottom"},
                             "lineStyle": {"color": "#F59E0B", "type": "dashed"}},
                        ]
                    }
                }]
            }
            js.append("echarts.init(document.getElementById('{}')).setOption({});".format(
                chart_id, json.dumps(opt, ensure_ascii=False)))
    return cards, js


def build():
    gen_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    today = today_str()

    # ── 持仓数据 ──
    hold = load(os.path.join(ROOT, "data", "holdings.json"), {})
    holdings = hold.get("holdings", [])
    # 2026-09-26 美化: KPI 持仓市值一目了然
    _hold_value = 0.0
    for _h in holdings:
        _px = _h.get("last_price") or _h.get("market_price") or 0
        _hold_value += (float(_px or 0)) * (_h.get("shares") or 0)
    hold_value_disp = "持仓市值 ¥{:,.0f}".format(_hold_value) if _hold_value else "空仓待命"
    cash = hold.get("available_cash", 0)
    pos_ratio = hold.get("position_ratio", 0)
    updated_at = hold.get("updated_at", "")
    note = hold.get("note", "")

    # ── 候选池：取最新 rank 文件 ──
    rank_files = sorted(glob.glob(os.path.join(ROOT, "logs", "rank_*.json")))
    latest_rank = None
    if rank_files:
        with open(rank_files[-1], "r", encoding="utf-8") as f:
            latest_rank = json.load(f)

    rank_date = latest_rank.get("date", today) if latest_rank else today
    items = latest_rank.get("items", [])[:9] if latest_rank else []
    rank_count = latest_rank.get("count", len(items)) if latest_rank else len(items)

    # ── 市场状态缓存（雷达图 + market_score 来源） ──
    mkt_cache = load(os.path.join(ROOT, "data", "market_state_cache.json"), {})
    result = mkt_cache.get("result", {})
    mkt_score = result.get("market_score", 0)
    mkt_label = result.get("market_label", "") or "—"

    # ── 环境门 ──
    signal = load(os.path.join(ROOT, "data", "daily_signal.json"), {})
    gate = signal.get("gate", signal.get("gate_detail", {}))
    gate_status = gate.get("status", "closed")
    sh_close_raw = gate.get("sh_close")
    ma250_raw = gate.get("ma250")
    # 2026-09-26: 源数据缺失时从本地TDX上证日线只读兜底(服务端不写盘), 仍取不到才显示 '—'
    _idx = None
    if sh_close_raw is None or ma250_raw is None:
        try:
            from update_gate_index import read_sh_index
            _idx = read_sh_index()
            if _idx:
                if sh_close_raw is None:
                    sh_close_raw = _idx["close"]
                if ma250_raw is None:
                    ma250_raw = _idx["ma250"]
        except Exception:
            print(f"🔴 [scripts\build_warroom_dashboard.py] CR-01: except Exception:", file=sys.stderr)
    sh_close_disp = "{:,.2f}".format(float(sh_close_raw)) if sh_close_raw else "—"
    ma250_disp = "{:,.2f}".format(float(ma250_raw)) if ma250_raw else "—"
    # 2026-09-26 美化: 收盘对MA250差值/状态/数据日期, 一目了然(红=上方偏多, 绿=下方偏空)
    _gate_date = gate.get("gate_date") or (_idx.get("date") if isinstance(_idx, dict) else None)
    gate_date_note = "{} 收盘".format(str(_gate_date)[5:]) if _gate_date else "TDX本地日线"
    try:
        _diff = (float(sh_close_raw) / float(ma250_raw) - 1) * 100
        gate_diff = "{:+.2f}%".format(_diff)
        diff_cls = "up" if _diff > 0 else "dn"
        gate_state = "位于MA250上方" if _diff > 0 else "位于MA250下方"
    except Exception:
        gate_diff, diff_cls, gate_state = "—", "", "数据待补"
    position_advice = signal.get("position_advice", "") or (
        "软门: 门关, 建议仓位≤50% (不否决选股)"
    )
    signal_timestamp = signal.get("timestamp", "")

    # 2026-09-26 重皮: 门控三态对齐 dark-first-pro 色板(放行=绿/软关=信号金/禁止=红)
    if gate_status == "open":
        gate_icon, gate_color = "OPEN", "#10B981"
    elif gate_status == "soft":
        gate_icon, gate_color = "软关", "#F59E0B"
    else:
        gate_icon, gate_color = "CLOSED", "#F43F5E"
    gate_ts_display = signal_timestamp[:16].replace("T", " ") if signal_timestamp else "N/A"

    # ── 回测KPI ──
    bt = load(os.path.join(ROOT, "backtest_result.json"), {})
    win_rate = bt.get("胜率", 31.6)
    excess_5 = bt.get("超额收益5日", -0.16)
    ex5_cls = "up" if (isinstance(excess_5, (int, float)) and excess_5 >= 0) else "dn"

    # ── 空仓状态卡片的恆定文本（仓位 0 时显示） ──
    empty_hold_card = ""
    if not holdings:
        empty_hold_card = (
            "<div class='hold-card' style='background:#0A0A0B;border:1px solid #27272A;border-left:3px solid #F59E0B'>"
            "<div class='hold-head'><h3>空仓状态</h3><span>等待新信号</span></div>"
            "<div class='hold-stats'><span>可用资金 {:,.0f} 元</span><span>持仓 0</span><span>全仓待命</span></div>"
            "</div>".format(cash)
        )

    # ── 持仓K线卡片（2026-09-26 起用本地实时实现, 不再依赖不存在的 import） ──
    kline_cards = ""
    kline_js = []
    if holdings:
        kline_cards, kline_js = _build_holding_cards(holdings)

    # ── 因子Walk-Forward表 ──
    wf_files = sorted(glob.glob(os.path.join(ROOT, "data", "audit", "walk_forward_purged_*.json")), reverse=True)
    wf_rows = ""
    if wf_files:
        wf = load(wf_files[0], {})
        # 2026-09-26 重皮: 结论色对齐新色板(通过=绿/偏弱=信号金/未过=红), IC 数字列 mono
        for f, s in wf.get("summary", {}).items():
            conc = s.get("conclusion", "?")
            if "PASS" in conc:
                color, label = "#10B981", "通过"
            elif "WEAK" in conc:
                color, label = "#F59E0B", "可用偏弱"
            else:
                color, label = "#F43F5E", esc(conc)
            wf_rows += "<tr><td>{}</td><td class='num'>{:.4f}</td><td class='num'>{:.4f}</td><td class='num' style='color:{}'>{}</td></tr>".format(
                esc(f), s.get("avg_train_ic", 0), s.get("avg_test_ic", 0), color, label)

    if not wf_rows:
        wf_rows = "<tr><td colspan='4' style='color:#71717A'>暂无 Walk-Forward 验证数据</td></tr>"

    # ── 候选池表格行 ──
    rank_rows = ""
    for it in items:
        r = it.get("rank", "-")
        code = it.get("code", "-")
        name = it.get("name", "-")
        score = it.get("final_score", 0)
        score_cls = "pos" if score >= 80 else ("warn" if score >= 70 else "neg")
        tag = ""
        if r == 1:
            tag = "<span class='rank-tag top1'>TOP1</span>"
            row_cls = " class='rank-top1'"
        elif r == 2:
            tag = "<span class='rank-tag top2'>TOP2</span>"
            row_cls = ""
        elif r == 3:
            tag = "<span class='rank-tag top3'>TOP3</span>"
            row_cls = ""
        else:
            row_cls = ""
        rank_rows += "<tr{}><td>{}</td><td class='num'>{}</td><td>{}</td><td class='num {}'><b>{}</b></td><td></td></tr>".format(
            row_cls, tag, esc(code), esc(name), score_cls, score)

    if not rank_rows:
        rank_rows = "<tr><td colspan='6' style='color:#71717A'>暂无候选池数据</td></tr>"

    # ── 雷达图数据 ──
    mkt_cache = load(os.path.join(ROOT, "data", "market_state_cache.json"), {})
    result = mkt_cache.get("result", {})
    sub_scores = result.get("sub_scores", {})
    radar_names = list(sub_scores.keys())
    radar_values = [sub_scores[k].get("score", 50) for k in radar_names]
    radar_indicators = [{"name": n, "max": 100} for n in radar_names]

    radar_opt = {
        "backgroundColor": "transparent",
        "tooltip": {"backgroundColor": "#1C1C20", "borderColor": "#27272A",
                    "textStyle": {"color": "#FAFAFA", "fontSize": 11}},
        "radar": {
            "indicator": radar_indicators,
            "radius": "65%", "center": ["50%", "55%"],
            "axisName": {"color": "#A1A1AA", "fontSize": 11},
            "splitLine": {"lineStyle": {"color": "#27272A"}},
            "splitArea": {"areaStyle": {"color": ["#17171B", "#1C1C20"]}},
            "axisLine": {"lineStyle": {"color": "#27272A"}},
        },
        "series": [{
            "type": "radar",
            "data": [
                {"value": radar_values, "name": "市场评分",
                 "areaStyle": {"color": "rgba(245,158,11,0.18)"},
                 "lineStyle": {"color": "#F59E0B", "width": 2},
                 "itemStyle": {"color": "#F59E0B"}},
                {"value": [60] * len(radar_names), "name": "及格线60",
                 "areaStyle": None,
                 "lineStyle": {"color": "#71717A", "type": "dashed", "width": 1},
                 "itemStyle": {"color": "#71717A"}, "symbol": "none"},
            ]
        }]
    }
    radar_json = json.dumps(radar_opt, ensure_ascii=False)

    # ── HTML组装（改用 .replace() 链，避免 % 运算符与 CSS/JS 中括号冲突） ──
    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>御龙决 · 作战台</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:#0A0A0B;color:#FAFAFA;min-height:100vh;font-family:'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif}
.app{max-width:1320px;margin:0 auto;padding:24px 20px 48px}
.header{display:flex;justify-content:space-between;align-items:baseline;padding:10px 0 14px;margin-bottom:16px;border-bottom:1px solid #27272A}
.header h1{font-size:19px;font-weight:600;letter-spacing:1px}
.brand{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:11px;color:#71717A;margin-left:12px;letter-spacing:2px;font-weight:400}
.meta{font-size:11px;color:#71717A}
.meta b{color:#A1A1AA;font-weight:400;font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace}
.gate-strip{display:flex;align-items:center;gap:24px;background:#141417;border:1px solid #27272A;border-left:3px solid @@gate_color@@;border-radius:10px;padding:12px 20px;margin-bottom:14px}
.gate-badge{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:13px;font-weight:700;color:@@gate_color@@;border:1px solid @@gate_color@@;border-radius:6px;padding:5px 12px;letter-spacing:2px;white-space:nowrap}
.gate-metrics{display:flex;gap:32px;flex:1}
.gm span{display:block;font-size:10px;color:#71717A;margin-bottom:3px}
.gm b{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:17px;font-weight:700;color:#FAFAFA}
.gm i{display:block;font-style:normal;font-size:10px;color:#71717A;margin-top:2px}
.gm b.up{color:#F43F5E}.gm b.dn{color:#10B981}
.gate-advice{font-size:12px;color:#A1A1AA;text-align:right;max-width:280px;line-height:1.8}
.kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
.kpi{background:#141417;border:1px solid #27272A;border-radius:10px;padding:14px 16px}
.kpi span{display:block;font-size:11px;color:#71717A;margin-bottom:6px}
.kpi b{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:26px;font-weight:700;color:#FAFAFA}
.kpi i{display:block;font-style:normal;font-size:10px;color:#71717A;margin-top:5px}
.kpi b.up{color:#F43F5E}.kpi b.dn{color:#10B981}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.card{background:#141417;border:1px solid #27272A;border-radius:12px;padding:16px}
.full{grid-column:1/-1}
.card h2{font-size:12px;color:#71717A;margin-bottom:10px;font-weight:400;letter-spacing:1px}
.mini-chart{height:180px;margin-top:8px}
.chart{height:280px}
.hold-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.hold-card{background:#1C1C20;border-radius:10px;padding:12px 14px;border:1px solid #27272A}
.hold-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.hold-head h3{font-size:14px;font-weight:600;color:#FAFAFA}
.hold-head span{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:11px;color:#71717A}
.hold-head .pnl{margin-left:auto;font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:15px;font-weight:700}
.pos{color:#F43F5E}.neg{color:#10B981}
.hold-stats{display:flex;gap:6px;flex-wrap:wrap;font-size:10px}
.hold-stats span{background:#0A0A0B;padding:3px 8px;border-radius:4px;font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;color:#A1A1AA}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:6px 8px;border-bottom:1px solid #27272A;text-align:left}
th{color:#71717A;font-weight:400;font-size:10px;letter-spacing:1px}
td.num,.num{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace}
.footer{text-align:center;font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:10px;color:#71717A;margin-top:24px;padding-top:12px;border-top:1px solid #27272A}
.s-hi{color:#F43F5E}.s-mid{color:#F59E0B}.s-lo{color:#A1A1AA}.warn{color:#F59E0B}
.rank-top1{background:#1C1C20;border-left:3px solid #F59E0B}
.rank-tag{display:inline-block;padding:1px 7px;border-radius:3px;font-size:10px;margin-left:6px;font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace}
.rank-tag.top1{background:#F59E0B;color:#0A0A0B;font-weight:700}
.rank-tag.top2,.rank-tag.top3{background:#27272A;color:#A1A1AA}
</style></head><body>
<div class="app">
<div class="header"><h1>御龙决 · 作战台<span class="brand">ZHUANQIAN · WARROOM</span></h1><span class="meta">生成 <b>@@gen_ts@@</b> · 数据时效 <b>@@gate_ts@@</b> · 手动刷新即实时</span></div>
<div class="gate-strip">
<div class="gate-badge">@@gate_icon@@</div>
<div class="gate-metrics">
<div class="gm"><span>上证收盘</span><b>@@sh_close@@</b><i>@@gate_date_note@@</i></div>
<div class="gm"><span>MA250 牛熊线</span><b>@@ma250@@</b><i>250日均线</i></div>
<div class="gm"><span>收盘 / MA250</span><b class="@@diff_cls@@">@@gate_diff@@</b><i>@@gate_state@@</i></div>
<div class="gm"><span>市场评分</span><b>@@mkt_score@@</b><i>@@mkt_label@@</i></div>
</div>
<div class="gate-advice">@@position_advice@@</div>
</div>
<div class="kpi-row">
<div class="kpi"><span>回测胜率</span><b>@@win_rate@@%</b><i>全量回测口径</i></div>
<div class="kpi"><span>5日超额</span><b class="@@ex5_cls@@">@@ex5@@</b><i>相对基准</i></div>
<div class="kpi"><span>持仓数</span><b>@@hold_count@@</b><i>@@hold_value@@</i></div>
<div class="kpi"><span>环境门</span><b style="color:@@gate_color@@">@@gate_icon@@</b><i>@@gate_state@@</i></div>
</div>
<div class="grid">
<div class="card full"><h2>持仓K线（收盘价+成本线+止损线）</h2><div class="hold-grid">@@kline_cards@@@@empty_hold_card@@</div></div>
<div class="card"><h2>市场五维雷达</h2><div id="radar" class="chart"></div></div>
<div class="card"><h2>因子 Walk-Forward 验证</h2><table><tr><th>因子</th><th>训练IC</th><th>测试IC</th><th>结论</th></tr>@@wf_rows@@</table></div>
<div class="card full"><h2>候选池排序 (@@rank_date@@)</h2><table>
<tr><th>排名</th><th>代码</th><th>名称</th><th>综合评分</th><th>备注</th></tr>
@@rank_rows@@
</table></div>
</div>
<div class="footer">ZHUANQIAN WARROOM V2.2 · 数据源 TDX本地日线 / HOLDINGS / SIGNAL / AUDIT / RANK · 手动刷新即实时 · 生成 @@gen_ts@@</div>
</div>
<script>
@@kline_js@@
echarts.init(document.getElementById('radar')).setOption(@@radar_json@@);
</script>
</body></html>"""

    html = html.replace("@@gen_ts@@", gen_ts) \
        .replace("@@gate_ts@@", gate_ts_display) \
        .replace("@@position_advice@@", esc(position_advice)) \
        .replace("@@gate_icon@@", gate_icon) \
        .replace("@@sh_close@@", sh_close_disp) \
        .replace("@@ma250@@", ma250_disp) \
        .replace("@@mkt_score@@", str(mkt_score)) \
        .replace("@@gate_color@@", gate_color) \
        .replace("@@win_rate@@", str(win_rate)) \
        .replace("@@ex5@@", "{:+.2f}%".format(excess_5)) \
        .replace("@@hold_count@@", str(len(holdings))) \
        .replace("@@kline_cards@@", kline_cards) \
        .replace("@@empty_hold_card@@", empty_hold_card) \
        .replace("@@wf_rows@@", wf_rows) \
        .replace("@@rank_date@@", rank_date) \
        .replace("@@rank_rows@@", rank_rows) \
        .replace("@@kline_js@@", "\n".join(kline_js)) \
        .replace("@@radar_json@@", radar_json) \
        .replace("@@gate_date_note@@", gate_date_note) \
        .replace("@@diff_cls@@", diff_cls) \
        .replace("@@gate_diff@@", gate_diff) \
        .replace("@@gate_state@@", esc(gate_state)) \
        .replace("@@mkt_label@@", esc(mkt_label)) \
        .replace("@@ex5_cls@@", ex5_cls) \
        .replace("@@hold_value@@", esc(hold_value_disp))
    return html


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    html = build()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] 作战台已更新")
    print(f"  文件: {OUT}")
    print(f"  大小: {len(html)} bytes")
    hold = load(os.path.join(ROOT, "data", "holdings.json"), {})
    print(f"  持仓: {len(hold.get('holdings', []))} 只")
    print(f"  可用现金: {hold.get('available_cash', 0):,.2f} 元")
    print(f"  仓位比: {hold.get('position_ratio', 0) * 100:.0f}%")
    return 0

if __name__ == "__main__":
    sys.exit(main())
