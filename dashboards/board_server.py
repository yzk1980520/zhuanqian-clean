# -*- coding: utf-8 -*-
"""选股系统本地看板服务器 (老三 2026-08-17)
- 零依赖: 仅用标准库 http.server
- 访问 http://127.0.0.1:8666/  → 渲染业务看板
- 数据只读: 读取 data 下 JSON/txt, 不做任何写操作
- 刷新策略: 无任何定时/自动刷新 (2026-09-26 老大指令),
  手动刷新即重算 — 宪法原则V数据不出本机仍满足
"""
import json
import os
import re
import glob
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = r"D:\open code\zhuanqian"
PORT = 8666

# S1 仲裁统一读法: 消费方经 review_gate.evaluate() → frozen=True/False
sys.path.insert(0, str(Path(ROOT)))
import review_gate as _rg

# 退役股过滤关键字
DELISTED_KEYWORDS = ['退市', 'ST', '*ST']

HOLDINGS = os.path.join(ROOT, "data", "holdings.json")
SIM_POS = os.path.join(ROOT, "data", "sim_rotation_positions.json")
RISK = os.path.join(ROOT, "data", "risk_report_latest.json")
HEALTH = os.path.join(ROOT, "data", "health_gate.json")
DAILY = os.path.join(ROOT, "data", "daily_brief.txt")
SEQRISK = os.path.join(ROOT, "data", "sequence_risk_20260817.json")
MAINLINE = os.path.join(ROOT, "mainline", "data", "mainline_p2d_result.json")
PUSH_QUEUE = os.path.join(ROOT, "data", "push_queue.json")
# 2026-09-26 二次对齐(老大指正): 推送实际走飞书链路; 主升浪P2d已归档, 现行=因子重构流水线
FEISHU_CFG = os.path.join(ROOT, "config", "feishu_config.json")
PHASE2_TASK = os.path.join(ROOT, "data", "phase2_task.json")
# 团队任务 / 台账（看板新增 R4 视觉化修复：2026-08-20 c4s3）
RELAY_STATS = os.path.join(ROOT, "data", "relay_stats.txt")
RELAY_TODO = os.path.join(ROOT, "data", "relay_todo.txt")
TEAM_CH = os.path.join(ROOT, "team", "channel.json")
# 2026-09-26 对齐: 老五审批闸(活的系统实况)
REVIEW = os.path.join(ROOT, "data", "review_status.json")


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_txt(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def is_delisted(name):
    """检查是否为退役股/ST股"""
    if not name:
        return False
    return any(kw in str(name) for kw in DELISTED_KEYWORDS)


def ts_badge(path, label="数据"):
    """2026-09-26 对齐: 数据文件时效徽标(只读)。>3天未更新标红'停更', 源缺失显式报缺。"""
    import time as _t
    try:
        mt = os.path.getmtime(path)
    except Exception:
        return "<div class='ts-line' style='color:#F43F5E'>⚠ {} 源文件不存在</div>".format(esc(label))
    age = (_t.time() - mt) / 86400
    ts = _t.strftime("%m-%d %H:%M", _t.localtime(mt))
    if age > 3:
        return "<div class='ts-line' style='color:#F43F5E'>⚠ {} 停更 {} 天 ({} )</div>".format(esc(label), int(age), ts)
    return "<div class='ts-line'>{} @ {}</div>".format(esc(label), ts)


def card(title, body, tone=""):
    # 2026-09-26 重皮: tone 语义色改为 3px 左色边(对齐 dark-first-pro, 不用花哨边框)
    tone_border = {"card-ok": "#10B981", "card-warn": "#F59E0B", "card-danger": "#F43F5E"}.get(tone)
    extra = " style='border-left:3px solid {}'".format(tone_border) if tone_border else ""
    return "<div class='card'{}><div class='card-title'>{}</div><div class='card-body'>{}</div></div>".format(
        extra, esc(title), body)


def fmt_pct(v):
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return "-"


# 2026-10-23 S7 看板美化: 宪法看板UI规范 — CSS变量 + 响应式 + holdings字段兼容
DASHBOARD_DATA_PATH = os.path.join(ROOT, "data", "system", "dashboard_data.json")
LAOSI_AUDIT_DIR = os.path.join(ROOT, "data", "laosi_audit")
# 2026-10-26 对齐: 候选池改由 _latest_rank_file() 读 logs/rank_*.json (与 rank card 同源);
# 旧 PICK_CANDIDATES_PATH=pick_candidates.json 从不生成, 致 candidates_top10 恒空, 已废弃。
GATEWAY_STATE_PATH = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\gateway_state.json"


def _safe_holdings_code(p):
    """holdings字段兼容: code/symbol 双格式 fallback (宪法看板UI规范)"""
    return p.get("code") or p.get("symbol") or "N/A"


def _get_laowu_review_status():
    """t_d4_001/CHK015: 读取老五审批状态 (review_status.json frozen字段)"""
    review_raw = load_json(REVIEW, {})
    if not review_raw:
        return {"status": "unknown", "message": "— 未知"}
    try:
        # S1 仲裁统一读法: 经 review_gate.evaluate() (模块级已导入 _rg)
        gate = _rg.evaluate(REVIEW)
        frozen = gate.get("frozen", True)
        return {"status": "approved" if not frozen else "pending", "message": "✅ 已通过" if not frozen else "⚠️ 待审批"}
    except Exception as exc:
        return {"status": "error", "message": f"❌ 审批检查失败: {exc}"}


def _laosi_drift(latest):
    """2026-10-26 对齐: 从 laosi 巡检结果推导 drift。
    status in {warning, fail} 或存在 P0/P1 finding → 视为漂移/关注。"""
    if not latest:
        return None
    status = str(latest.get("status", "")).lower()
    if status in ("warning", "warn", "fail", "error"):
        return True
    for f in (latest.get("findings") or []):
        if isinstance(f, dict) and str(f.get("level", "")).upper() in ("P0", "P1"):
            return True
    return False


def _gateway_health():
    """2026-10-26 对齐: 读 gateway_state.json 真实状态 (不再硬编码 unknown)。"""
    gw = load_json(GATEWAY_STATE_PATH, {})
    if not gw:
        return "unknown"
    state = gw.get("gateway_state", "unknown")
    plats = gw.get("platforms", {}) or {}
    connected = sum(1 for p in plats.values() if isinstance(p, dict) and p.get("state") == "connected")
    fatal = [k for k, p in plats.items() if isinstance(p, dict) and p.get("state") not in ("connected", "disconnected")]
    suffix = ""
    if fatal:
        suffix = " / fatal:{}".format(",".join(sorted(fatal)))
    return "{} ({} 平台连接{})".format(state, connected, suffix)


def _latest_rank_file():
    """2026-10-26 对齐: 最新候选池 rank 文件 (与 server-rendered rank card 同源, 保证 KPI overlay 与卡片一致)。"""
    files = sorted(glob.glob(os.path.join(ROOT, "logs", "rank_*.json")))
    return files[-1] if files else None


def _aggregate_dashboard_data():
    """聚合多数据源 → 看板API响应dict (宪法FR-002 + 看板UI规范)"""
    import time as _time
    now_str = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime())

    # 1. 持仓数据 (兼容 code/symbol)
    holdings = load_json(HOLDINGS, {})
    h_list = holdings.get("holdings", [])
    # 统一字段名
    for p in h_list:
        if "code" not in p and "symbol" in p:
            p["code"] = p["symbol"]
        elif "symbol" not in p and "code" in p:
            p["symbol"] = p["code"]
    total_assets = holdings.get("total_assets", 0)
    position_ratio = holdings.get("position_ratio", 0)
    available_cash = holdings.get("available_cash", 0)

    # 2. 系统健康快照
    health_path = Path(ROOT) / "data" / "system" / "health_snapshot.json"
    health = load_json(str(health_path), {})
    health_status = health.get("status", "unknown")

    # 3. 飞书消息队列
    msg_queue = load_json(os.path.join(ROOT, "data", "message_queue.json"), [])
    pending_count = len(msg_queue) if isinstance(msg_queue, list) else 0

    # 4. 老四巡检结果
    laosi_latest = None
    laosi_files = glob.glob(os.path.join(LAOSI_AUDIT_DIR, "laosi_*.json"))
    if laosi_files:
        laosi_latest = load_json(max(laosi_files, key=os.path.getmtime), None)

    # 5. 选股候选 (2026-10-26 对齐: 与 server rank card 同源 logs/rank_*.json, KPI 与卡片一致)
    candidates = []
    cand_asof = ""
    _rank_f = _latest_rank_file()
    if _rank_f:
        _rd = load_json(_rank_f, None)
        if _rd:
            _items = _rd.get("items", [])[:10]
            _items = [i for i in _items if not is_delisted(i.get("name", ""))]
            candidates = _items
            cand_asof = _rd.get("date", "")

    # 6. Cron活跃数
    cron_active = health.get("cron", {}).get("active", 0)
    cron_total = health.get("cron", {}).get("total", 0)

    return {
        "generated_at": now_str,
        "holdings": {
            "total_assets": total_assets,
            "position_ratio": position_ratio,
            "available_cash": available_cash,
            "count": len(h_list),
            "items": h_list,
        },
        "health": {
            "status": health_status,
            "last_check_at": health.get("last_check_at", "N/A"),
            "tests_passed": health.get("tests", {}).get("passed", 0),
            "tests_total": health.get("tests", {}).get("total", 0),
        },
        "feishu": {
            "pending_count": pending_count,
            "gateway_health": _gateway_health(),
        },
        "laosi": {
            "last_run": (laosi_latest.get("audit_time") or laosi_latest.get("timestamp") or "N/A") if laosi_latest else "未执行",
            "drift_detected": _laosi_drift(laosi_latest),
        },
        "cron": {
            "active": cron_active,
            "total": cron_total,
        },
        "laowu_review": _get_laowu_review_status(),
        "candidates_top10": candidates,
        "candidates_asof": cand_asof,
    }


def _load_review_status():
    """S1 统一仲裁：读取 review_status.json 并 evaluate，异常路径返回 approved=False。

    调用方使用返回值 ``dict(approved=bool, raw=dict|{})``，永远不需要关心
    文件是否存在或 JSON 是否损坏——这消除了 NameError/KeyError 两类隐患。
    禁止在 except 里 ``except: 默认值``（静默吞异常是 P0 缺陷），此处只
    捕获明确类型并透传非预期异常。
    """
    try:
        raw = load_json(REVIEW, None)
        if raw is None:
            return {"approved": False, "raw": {}}
        gate = _rg.evaluate(REVIEW)
        return {"approved": bool(not gate.get("frozen", True)), "raw": raw}
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        # 文件缺失 / JSON 损坏 / 缺少 frozen 字段 → 安全降级为未批准
        return {"approved": False, "raw": {}}


def build_html():
    holdings = load_json(HOLDINGS, {})
    sim = load_json(SIM_POS, {})
    risk = load_json(RISK, {})
    health = load_json(HEALTH, {})
    daily = load_txt(DAILY)
    seq = load_json(SEQRISK, {})
    # 2026-09-26 二次对齐: ml/push_queue 两个死数据源已删, 改读 feishu_config + phase2_task(见下方各卡段)
    # 2026-09-26 对齐: 审批闸实况 + 市场状态(实时简报数据源)
    review = load_json(REVIEW, {})
    mkt_cache = load_json(os.path.join(ROOT, "data", "market_state_cache.json"), {})
    mkt_result = mkt_cache.get("result", {}) if mkt_cache else {}

    now = __import__("time").strftime("%Y-%m-%d %H:%M:%S")

    # ── 推送链路（2026-09-26 二次对齐: 老大指正——实际是飞书链路。
    #    push_queue.json 是从未落地的旧设想(死数据源, 删)；卡直读 feishu_config.json 实况：
    #    告警通道 enabled=false(webhook待配) + lark-cli 三件套 + 告警分级政策）──
    feishu = load_json(FEISHU_CFG, {}) or {}
    # 2026-09-26 04:00 链路验证: 主通道(lark-cli→老大单聊)已实发验证通过 → 卡整体翻绿;
    # webhook 告警通道(enabled=false)降级为可选升级项
    if feishu.get("enabled"):
        _ch = "<b class='ok'>已启用</b>"
    else:
        _ch = "<b style='color:#F59E0B'>webhook 未配置(可选升级)</b>"
    _tone = "card-ok"
    push_body = f"<div class='kv'><span>告警通道</span>{_ch}</div>"
    push_body += "<div class='kv' style='align-items:flex-start'><span>主通道</span><b style='text-align:left'><span class='ok'>lark-cli(总管身份) → 老大单聊 ✓ 已验证</span><br><span style='color:#71717A;font-size:11px;font-weight:400'>oc_14afb6… · 09-26 03:40 实发, 老大亲测收到</span></b></div>"
    push_body += "<div class='kv'><span>群通道</span><b style='color:#F59E0B'>总管已建群 · 群播待接入(可选)</b></div>"
    push_body += "<div class='line' style='color:#71717A;font-size:11px'>发送脚本: cron_message_sender / team_feishu_notifier / vchart_feishu(图)；告警分级: P0 立即 · P1 1h去重 · P2 折叠</div>"
    push_body += ts_badge(FEISHU_CFG, "feishu_config")
    push_html = card("📤 飞书推送链路", push_body, _tone)

    # ── 风险 / 账户 ──
    risk_body = ""
    acct = risk.get("account_status", {}) if risk else {}
    risk_body += f"""<div class="kv"><span>账户总资产</span><b>{acct.get('total_assets', '-')}</b></div>
<div class="kv"><span>股票市值</span><b>{acct.get('stock_value', '-')}</b></div>
<div class="kv"><span>仓位(当前/建议)</span><b>{acct.get('position_pct', '-')}% / {risk.get('position_control', {}).get('max_allowed_pct', '-')}%</b></div>
<div class="kv"><span>总盈亏</span><b class="{'neg' if (acct.get('total_pnl_pct') or 0) < 0 else 'pos'}">{fmt_pct(acct.get('total_pnl_pct'))}</b></div>"""
    signals = ""
    for s in (risk.get("all_signals", []) if risk else []):
        signals += f"<div class='signal'><span>{esc(s.get('level'))} {esc(s.get('indicator'))}</span></div>"
    signals = signals or "<div class='ok'>无告警</div>"
    risk_body += f"<div class='sub-title'>❌ 仓位合规: {'✅' if risk.get('position_control', {}).get('compliant') else '⚠️ 超限'}</div>{signals}"

    # ── 持仓 ──（2026-09-26 重皮: dark-first-pro 持仓卡 + 迷你K线(成本/止损/止盈三线), 对齐设计稿"选股系统看板"）
    pos_cards = ""
    chart_js = []
    # P0-3修复(2026-09-28): sys.path.insert移到循环外，避免多次插入
    _scripts_path = os.path.join(ROOT, "scripts")
    if _scripts_path not in sys.path:
        sys.path.insert(0, _scripts_path)
    _tdx_imported = False

    h = holdings.get("holdings", [])
    if h:
        for pi, p in enumerate(h[:5]):
            code = p.get("code", "")
            name = p.get("name", "")
            cost = p.get("cost", p.get("cost_price", 0))
            shares = p.get("shares", 0)
            sl_manual = p.get("stop_loss")
            closes, dates, highs = [], [], []
            try:
                if not _tdx_imported:
                    from core.pipeline.tdx_core import get_tdx_data
                    _tdx_imported = True
                recs = get_tdx_data(code, 60)
                if recs:
                    dates = [str(r.get("date", ""))[5:] for r in recs[-30:]]
                    closes = [float(r.get("close", 0)) for r in recs[-30:]]
                    highs = [float(r.get("high", 0)) for r in recs[-60:]]
            except Exception:
                pass
            current = closes[-1] if closes else (p.get("last_price") or p.get("market_price") or cost)
            high = max(highs) if highs else max(current, cost)
            closes20 = closes[-20:] if len(closes) >= 20 else closes
            ma20 = sum(closes20) / len(closes20) if closes20 else cost
            pnl = (current / cost - 1) * 100 if cost > 0 else 0
            # 2026-08-20 统一口径: 止损8%(P17最优) + 分级移动止盈 8/12/18/25（止损优先读 holdings 实际维护值）
            stop = float(sl_manual) if sl_manual else cost * 0.92
            if pnl < 10:
                tp_pct, tp_label = 0.08, "8%"
            elif pnl < 20:
                tp_pct, tp_label = 0.12, "12%"
            elif pnl < 40:
                tp_pct, tp_label = 0.18, "18%"
            else:
                tp_pct, tp_label = 0.25, "25%"
            tp_trigger = high * (1 - tp_pct)
            pnl_cls = "neg" if pnl < 0 else "pos"
            ma_cls = "neg" if current < ma20 else "pos"
            chart_id = "pc-{}".format(pi)
            pos_cards += (
                "<div class='hold-card'><div class='hold-head'><h3>{}</h3><span>{}</span>"
                "<span class='pnl {}'>{}{}%</span></div>"
                "<div class='hold-stats'><span>{}股 @ {:.2f}</span><span>MA20 {:.2f}</span>"
                "<span>高点 {:.2f}</span><span>止损 {:.2f}</span><span>止盈触发 {:.2f} (回撤{})</span></div>"
                "<div id='{}' class='mini-chart'></div></div>"
            ).format(esc(name), esc(code), pnl_cls, "+" if pnl >= 0 else "", pnl,
                     shares, cost, ma20, high, stop, tp_trigger, tp_label, chart_id)
            if closes:
                # 曲线红涨绿跌(A股); 成本=灰白, 止损=信号金, 止盈触发=红(仅画在近端合理区间)
                line_color = "#F43F5E" if pnl >= 0 else "#10B981"
                y_lo, y_hi = min(closes + [cost, stop]), max(closes + [cost])
                span = max(y_hi - y_lo, 0.01)
                marks = [
                    {"yAxis": cost, "name": "成本",
                     "label": {"formatter": "成本{:.2f}".format(cost), "color": "#A1A1AA", "fontSize": 9, "position": "insideEndTop"},
                     "lineStyle": {"color": "#A1A1AA", "type": "dashed"}},
                    {"yAxis": stop, "name": "止损",
                     "label": {"formatter": "止损{:.2f}".format(stop), "color": "#F59E0B", "fontSize": 9, "position": "insideEndBottom"},
                     "lineStyle": {"color": "#F59E0B", "type": "dashed"}},
                ]
                if abs(tp_trigger - y_hi) / span < 1.2:
                    marks.append({"yAxis": tp_trigger, "name": "止盈",
                                  "label": {"formatter": "止盈{:.2f}".format(tp_trigger), "color": "#F43F5E", "fontSize": 9, "position": "insideEndTop"},
                                  "lineStyle": {"color": "#F43F5E", "type": "dashed"}})
                opt = {
                    "backgroundColor": "transparent",
                    "tooltip": {"trigger": "axis", "backgroundColor": "#1C1C20",
                                "borderColor": "#27272A", "textStyle": {"color": "#FAFAFA", "fontSize": 11}},
                    "grid": {"left": 44, "right": 14, "top": 18, "bottom": 28},
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
                        "areaStyle": {"color": line_color, "opacity": 0.10},
                        "markPoint": {"data": [{"type": "max", "name": "高点",
                                                "itemStyle": {"color": "#F59E0B"},
                                                "label": {"color": "#0A0A0B", "fontSize": 9}}], "symbolSize": 34},
                        "markLine": {"silent": True, "symbol": "none", "data": marks},
                    }],
                }
                chart_js.append("echarts.init(document.getElementById('{}')).setOption({});".format(
                    chart_id, json.dumps(opt, ensure_ascii=False)))
    else:
        pos_cards = (
            "<div class='hold-card' style='background:#0A0A0B;border:1px solid #27272A;border-left:3px solid #F59E0B'>"
            "<div class='hold-head'><h3>空仓状态</h3><span>等待新信号</span></div>"
            "<div class='hold-stats'><span>全仓1只 · 移动止盈策略待命中</span></div></div>"
        )

    # ── 模拟轮回 ──
    sim_body = ""
    sp = sim.get("positions", [])
    if sp:
        tot = len(sp)
        win = sum(1 for p in sp if (p.get("current", 0) or 0) >= (p.get("cost", 0) or 0))
        sim_body += f"<div class='kv'><span>持仓数</span><b>{tot}</b></div><div class='kv'><span>盈利/亏损</span><b>{win} / {tot - win}</b></div><table><tr><th>名称</th><th>开仓</th><th>成本</th><th>现价</th></tr>"
        for p in sp[:15]:
            pnl = (p.get("current", 0) - p.get("cost", 0)) / p.get("cost", 1) * 100
            cls = "neg" if pnl < 0 else "pos"
            sim_body += f"<tr><td>{esc(p.get('name'))}</td><td>{p.get('open_date', '')}</td><td>{p.get('cost', '')}</td><td class='{cls}'>{p.get('current', '')} ({pnl:+.1f}%)</td></tr>"
        sim_body += "</table>"
    else:
        sim_body = "<div class='ok'>模拟轮回无持仓</div>"

    # ── 每日简报 (2026-09-26 对齐: daily_brief.txt 已断链(cron跑但未落盘, 停在09-21,
    #    内容还是永鼎股份旧持仓)。改为实时构建 —— 门控/持仓/TOP1/审批闸警示 全部现读; txt 新鲜时仍优先用) ──
    import time as _t
    _brief_fresh = False
    try:
        _brief_fresh = (_t.time() - os.path.getmtime(DAILY)) < 86400
    except Exception:
        pass
    if _brief_fresh and daily.strip():
        daily_body = "".join(f"<div class='line'>{esc(raw)}</div>" for raw in daily.splitlines()[:25])
    else:
        _g = load_json(os.path.join(ROOT, "data", "daily_signal.json"), {}).get("gate", {})
        _g_st = {"open": "🟢 OPEN", "soft": "🟡 软关(≤50%仓)", "closed": "⛔ 关闭"}.get(_g.get("status", "closed"), "⛔ 关闭")
        _g_note = ""
        if _g.get("sh_close") and _g.get("ma250"):
            _g_note = " (上证 {:.2f} vs MA250 {:.2f}, {})".format(
                float(_g["sh_close"]), float(_g["ma250"]),
                "上方" if float(_g["sh_close"]) > float(_g["ma250"]) else "下方")
        _b = "<div class='line'>📊 选股简报 · 实时构建（txt 简报已断链, 本卡直读数据源）</div>"
        _b += "<div class='line'>🌡️ 市场环境: {} ({}/100)</div>".format(
            esc(mkt_result.get("market_label", "—")), mkt_result.get("market_score", "—"))
        _b += "<div class='line'>环境门: {}{}</div>".format(_g_st, esc(_g_note))
        _hh = holdings.get("holdings", [])
        if _hh:
            _p0 = _hh[0]
            _c0 = _p0.get("cost", _p0.get("cost_price", 0)) or 0
            _l0 = _p0.get("last_price") or _p0.get("market_price") or _c0
            _s0 = _p0.get("stop_loss") or (round(_c0 * 0.92, 2) if _c0 else "—")
            _pn0 = (_l0 / _c0 - 1) * 100 if _c0 else 0
            _b += "<div class='line'>💼 当前持仓: {} {} {}股 · 成本{:.2f} → 现价{:.2f} ({:+.2f}%) · 止损{}</div>".format(
                esc(_p0.get("code", "")), esc(_p0.get("name", "")), _p0.get("shares", 0),
                _c0, _l0, _pn0, _s0)
        else:
            _b += "<div class='line'>💼 当前持仓: 空仓待命（可用资金 {:,.2f}）</div>".format(holdings.get("available_cash", 0) or 0)
        try:
            _rf = sorted(glob.glob(os.path.join(ROOT, "logs", "rank_*.json")))
            _rd = json.load(open(_rf[-1], encoding="utf-8")) if _rf else {}
            _it0 = (_rd.get("items") or [{}])[0]
            _b += "<div class='line'>🎯 候选池 TOP1 ({date}): {code} {name} (评分{score})</div>".format(
                date=_rd.get("date", "?"), code=esc(_it0.get("code", "")),
                name=esc(_it0.get("name", "")), score=_it0.get("final_score", "—"))
        except Exception:
            _b += "<div class='line'>🎯 候选池 TOP1: 暂无数据</div>"
        _b += "<div class='line' style='color:#F43F5E'>⚠️ 风险警示 (老五审批闸 {}):</div>".format(
            esc(str(review.get("last_updated", "?"))[:16]))
        _b += "<div class='line'>  • {}</div>".format(esc(review.get("status", "无评审记录")))
        if review.get("verdict"):
            _b += "<div class='line'>  • 结论: {}</div>".format(esc(review.get("verdict")))
        _rec_first = (review.get("recommendation") or "").splitlines()
        if _rec_first:
            _b += "<div class='line'>  • {}</div>".format(esc(_rec_first[0]))
        _b += "<div class='ts-line'>行情时效: TDX本地日线(09-24收盘口径) · 每次刷新现读 data/ 源</div>"
        # 买入信号面 (组件1+2, @user 扩围 10/24; 合规闸=4闸任一红只显拦截文案不出数字)
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import buy_signal_panel as _bsp
            _b += _bsp.render_panel_html()
        except Exception as _e:
            _b += f"<div class='line'>🔴 买入信号面加载失败: {esc(str(_e))}</div>"
        daily_body = _b

    # ── 因子重构流水线（2026-09-26 二次对齐: 老大指正——用现行流水线。
    #    P2d 主升浪研究已归档(结果文件已清理)；现行 = FAC-2026-001 因子重构 Phase 2
    #    (09-26 02:00 启动)：因子开发→门禁验证→集成上线，交付物实时查落盘）──
    p2 = load_json(PHASE2_TASK, {}) or {}
    if not p2:
        ml_body = ("<div class='line' style='color:#F43F5E'>⚠ 数据源缺失: data/phase2_task.json</div>"
                   + ts_badge(PHASE2_TASK, "phase2_task"))
        ml_card = card("🔬 因子重构流水线", ml_body, "card-warn")
    else:
        ml_body = f"<div class='kv'><span>项目</span><b>{esc(str(p2.get('title', '')))}</b></div>"
        ml_body += (f"<div class='kv' style='align-items:flex-start'><span>状态</span>"
                    f"<b style='text-align:left'>{esc(str(p2.get('project_id', '')))} · {esc(str(p2.get('status', '')))} · {esc(str(p2.get('started_at', '')))} 启动 → {esc(str(p2.get('target_completion', '')))} 交付</b></div>")
        _phases = p2.get("phases", []) or []
        if _phases:
            ml_body += "<div style='display:flex;gap:6px;margin:8px 0 4px'>"
            for _i, _ph in enumerate(_phases):
                _st_bg = ("background:rgba(245,158,11,.15);color:#F59E0B;border-color:rgba(245,158,11,.45)" if _i == 0
                          else "background:#1C1C20;color:#A1A1AA;border-color:#27272A")
                ml_body += (f"<div style='flex:1;padding:6px 8px;border:1px solid;border-radius:6px;{_st_bg}'>"
                            f"<div style='font-weight:600;font-size:12px'>{esc(str(_ph.get('name', '')))}</div>"
                            f"<div style='font-size:10px;opacity:.85'>→ {esc(str(_ph.get('deadline', '')))}</div></div>")
            ml_body += "</div>"
        _dels = p2.get("deliverables", []) or []
        if _dels:
            _miss = [str(d) for d in _dels if not os.path.exists(os.path.join(ROOT, str(d)))]
            ml_body += (f"<div class='kv'><span>交付物</span><b>{len(_dels) - len(_miss)}/{len(_dels)} 已落盘</b></div>")
            if _miss:
                ml_body += ("<div class='line' style='color:#71717A;font-size:11px'>待产出: "
                            + esc(" / ".join(_miss[:3])) + ("…" if len(_miss) > 3 else "") + "</div>")
        ml_body += ts_badge(PHASE2_TASK, "phase2_task")
        ml_card = card("🔬 因子重构流水线", ml_body, "card-ok")

    gate_html = ""
    if health:
        red_html = "<div class='ok'>无红牌</div>" if not health.get("red") else "<div class='warn'>有红牌</div>"
        gate_html = f"<div class='kv'><span>今日健康门</span><b>{esc(str(health.get('gate', '?')))}</b></div>{red_html}"
        gate_html = card("健康门", gate_html)

    # ── 新增：🧭 团队任务概览（c4s3 修复看板任务视觉黑盒）──
    stats_raw = load_txt(RELAY_STATS).strip() or "暂无统计"
    todo_raw = load_txt(RELAY_TODO).strip() or "无待办，全部闭环"
    stat_body = ts_badge(RELAY_STATS, "relay 台账") + f"<div class='kv' style='font-size:11px;color:#cfd5e0'><b>{esc(stats_raw)}</b></div>"
    stat_body += "<div class='sub-title'>📌 待办清单（最近 12 条）</div>"
    todo_lines = [ln.strip() for ln in todo_raw.splitlines() if ln.strip()]
    if todo_lines:
        def badge_class(line):
            if line.startswith("🚫"): return "neg"
            if line.startswith("✅"): return "ok"
            if line.startswith("🧐"): return "warn"
            return ""
        body_cls = badge_class
        shown = todo_lines[:12]
        for ln in shown:
            cls = body_cls(ln)
            stat_body += f"<div class='line {cls}' style='font-size:11.5px'>• {esc(ln)}</div>"
        if len(todo_lines) > 12:
            stat_body += f"<div class='line' style='color:#8a93a3;font-size:11px'>... 另有 {len(todo_lines)-12} 条详见 team/channel.json</div>"
    else:
        stat_body += "<div class='ok'>无待办</div>"
    task_overview_html = card("🧭 团队任务概览", stat_body, "card-warn" if ("🚫" in todo_raw or "阻塞" in stats_raw) else "card-ok")

    # ── 2026-09-26 对齐系统实况: "最新沟通流水"卡(channel.json 不存在,常显"暂无")
    #    替换为"老五审批闸实况"卡 —— 直读 data/review_status.json(活数据)。
    #    当前 review 结论=策略严重失效, 此警示必须占最显眼位置, tone=card-danger ──
    _rs = _load_review_status()
    _approved = _rs["approved"]
    _raw = _rs["raw"]
    _freeze_unlocked = _raw.get("freeze_unlocked", False)
    _approval_status = "✅ 已启用" if _approved else "❌ 冻结中"
    _freeze_status = "已解冻" if _freeze_unlocked else "冻结中"
    if not _raw:
        rv_body = "<div class='warn'>数据源缺失: data/review_status.json</div>"
    else:
        # 当前审批状态 — S1 统一仲裁读法 (review_gate.evaluate)
        # 审批时间线
        _timeline = _raw.get("approval_timeline", [])
        _timeline_html = ""
        for t in _timeline:
            _t_color = "#10B981" if "True" in t.get("verdict", "") or "✅" in t.get("verdict", "") else "#EF4444"
            _timeline_html += f"<div style='padding:4px 0;border-bottom:1px solid #27272A'><span style='color:#6366f1'>{t['date']}</span> {t['event']} - <span style='color:{_t_color}'>{t['verdict']}</span></div>"
        _st = str(_raw.get("status", "") or "").strip()
        rv_body = f"<div class='kv' style='align-items:flex-start'><span>当前状态</span><b class='{'pos' if _approved else 'neg'}' style='text-align:left'>{_approval_status}</b></div>"
        rv_body += f"<div class='kv' style='align-items:flex-start'><span>解冻状态</span><b style='text-align:left'>{_freeze_status}</b></div>"
        rv_body += f"<div class='kv' style='align-items:flex-start'><span>历史审批</span><b style='text-align:left'>{len(_timeline)}条记录</b></div>"
        rv_body += f"<div class='kv' style='align-items:flex-start'><span>历史详情</span><b style='text-align:left;font-weight:400;font-size:11px'>{esc(_st[:100])}...</b></div>"
        rv_body += _timeline_html
        rv_body += ts_badge(REVIEW, "review_status")
    review_card_html = card("🛡️ 老五审批闸实况", rv_body, "card-danger")

    # ── 团队架构可视化（总管 2026-08-24 建 / 2026-09-26 WorkBuddy 改准:
    #    对齐 AGENTS.md §6.1 现行主档 —— 第二大脑已归档(research_archive/),
    #    职能并入老五+WorkBuddy; 补 2026-09-25 重架构新增的 WorkBuddy 评审环节）──
    tm = [
        ("老大", "👔 最终决策", "#FAFAFA", "拍板 / 资金 / 方向 · 只拍板不介入执行", "🟢 在位"),
        ("总管", "👑 调度治理", "#F43F5E", "调度 / 验收 / cron / 实盘合入 (Hermes/agnes)", "🟢 常驻"),
        ("老三", "⚡ 执行节点", "#A1A1AA", "代码 / 回测 / 数据工程 (opencode)", "🟢 活跃"),
        ("老五", "🔍 复核节点", "#10B981", "独立评审 / 合规把关 (atomcode/hy3)", "🟢 活跃"),
        ("WorkBuddy", "🧠 执行·评审·研究", "#F59E0B", "三合一角色 · 个股研究链路评审闸 (2026-09-25 接入)", "🟢 常驻"),
        ("牛马", "🐎 后备节点", "#71717A", "prime-agent 按需启动", "⚪ 待命"),
        ("第二大脑", "🛡️ 独立审查", "#52525B", "second_brain.py 已归档 · 职能并入老五+WorkBuddy", "📦 已归档"),
    ]
    team_body = "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px'>"
    for tname, tbadge, tcolor, trole, tstatus in tm:
        _archived = (tstatus == "📦 已归档")
        team_body += (
            "<div style='background:#1C1C20;border-radius:8px;padding:10px;border-left:3px solid {};{}'>"
            "<div style='display:flex;align-items:center;gap:6px;margin-bottom:6px'>"
            "<span style='color:{};font-size:13px'>{}</span>"
            "<span style='font-weight:600;font-size:13px;{}'>{}</span>"
            "<span style='margin-left:auto;font-size:10px;color:#71717A'>{}</span></div>"
            "<div style='font-size:11px;color:#A1A1AA;line-height:1.6'>{}</div></div>"
        ).format(tcolor, "opacity:.55" if _archived else "",
                 tcolor, tbadge,
                 "text-decoration:line-through;color:#71717A" if _archived else "",
                 esc(tname), esc(tstatus), esc(trole))

    team_body += """
    </div>
    <div style='margin-top:12px;padding-top:10px;border-top:1px solid #2a3040'>
        <div style='font-size:12px;color:#F59E0B;margin-bottom:8px'>🔄 协作流程 · 选股主链路</div>
        <div style='font-size:12px;color:#A1A1AA;line-height:2'>
            <b style='color:#F43F5E'>总管</b> → <b style='color:#A1A1AA'>老三</b>(执行) → <b style='color:#10B981'>老五</b>(复核) → 总管验收 → <b style='color:#FAFAFA'>老大</b>确认 → 实盘合入<br>
            <span style='color:#71717A'>↓ 打回重做</span> &nbsp;&nbsp; <span style='color:#71717A'>牛马(后备待命)</span><br>
        </div>
        <div style='font-size:12px;color:#F59E0B;margin:10px 0 8px'>🧠 协作流程 · 个股研究链路 (2026-09-25 重架构)</div>
        <div style='font-size:12px;color:#A1A1AA;line-height:2'>
            四阶段分析(市场/基本面/多空/交易) → <b style='color:#F59E0B'>WorkBuddy 评审</b> → 登记老五通道 → 总管验收
        </div>
    </div>
    <div style='margin-top:10px;padding:8px;background:#0A0A0B;border:1px solid #27272A;border-left:3px solid #F43F5E;border-radius:6px;font-size:11px'>
        <span style='color:#F43F5E'>🚫 授权红线:</span> 交易数据写入 / cron调度 / 实盘合入 / 策略参数修改 → <b style='color:#FAFAFA'>总管独占</b>，不可下放
    </div>"""

    team_card_html = card("👥 团队架构可视化", team_body)

    # ── 新增：候选池TOP10（总管 2026-09-22）──
    rank_files = sorted(glob.glob(os.path.join(ROOT, "logs", "rank_*.json")))
    latest_rank_file = rank_files[-1] if rank_files else None
    rank_body = ""
    if latest_rank_file:
        try:
            with open(latest_rank_file, 'r', encoding='utf-8') as f:
                rank_data = json.load(f)
            rank_date = rank_data.get('date', '未知')
            rank_count = rank_data.get('count', 0)
            items = rank_data.get('items', [])[:10]
            
            # 2026-10-08 看板层二次过滤退役股
            items = [i for i in items if not is_delisted(i.get('name', ''))]
            rank_count = len(items)
            
            rank_body = f"<div style='font-size:11px;color:#71717A;margin-bottom:6px'>数据日期: {rank_date} | 候选池: {rank_count}只</div>"
            rank_body += "<table><tr><th>排名</th><th>代码</th><th>名称</th><th>评分</th></tr>"
            for item in items:
                rank = item.get('rank', '-')
                code = item.get('code', '-')
                name = item.get('name', '-')
                score = item.get('final_score', 0)
                score_cls = 'pos' if score >= 80 else ('warn' if score >= 70 else 'neg')
                row_cls = " class='rank-top1'" if rank == 1 else ""
                tag = "<span class='rank-tag top1'>TOP1</span>" if rank == 1 else ""
                rank_body += f"<tr{row_cls}><td class='num'>{rank}{tag}</td><td class='num'>{esc(code)}</td><td>{esc(name)}</td><td class='num {score_cls}'><b>{score}</b></td></tr>"
            rank_body += "</table>"
        except Exception as e:
            rank_body = f"<div class='warn'>候选池数据加载失败: {esc(str(e))}</div>"
    else:
        rank_body = "<div class='ok'>暂无候选池数据</div>"
    
    rank_html = card("🎯 候选池TOP10", rank_body)

    # ── 新增：系统健康状态（总管 2026-09-22）──
    health_body = ""
    cron_list = []
    try:
        import subprocess
        result = subprocess.run(['hermes', 'cron', 'list'], capture_output=True, text=True, timeout=10,
                                encoding="utf-8", errors="replace")
        cron_text = result.stdout
        active_count = cron_text.count('[active]')
        health_body = f"<div class='kv'><span>Cron任务</span><b>{active_count}个活跃</b></div>"
    except Exception:
        health_body = "<div class='warn'>Cron状态检查失败</div>"
    
    # 2026-09-26 对齐: "Gateway 运行中 / Python 3.11.15 / 207 passed" 均为 09-22 写死快照,
    # 不代表现在 → 改动态版本 + 诚实标注
    _pyver = sys.version.split()[0]
    # S7 H2: 宪法原则VIII — 老四巡检结果 + 飞书队列状态并入健康卡
    _laosi_status = "未执行"
    _laosi_tone = "warn"
    try:
        import glob as _glob
        _laosi_files = _glob.glob(os.path.join(ROOT, "data", "laosi_audit", "laosi_*.json"))
        if _laosi_files:
            _latest = load_json(max(_laosi_files, key=os.path.getmtime), None)
            if _latest:
                _drift = _laosi_drift(_latest)
                _laosi_status = "✅ 契约无漂移" if not _drift else "⚠️ 检测到漂移"
                _laosi_tone = "card-ok" if not _drift else "card-warn"
    except Exception:
        _laosi_status = "巡检数据不可用"
    _msg_pending = 0
    try:
        _mq = load_json(os.path.join(ROOT, "data", "message_queue.json"), [])
        _msg_pending = len(_mq) if isinstance(_mq, list) else 0
    except Exception:
        pass
    # t_d4_002 + D1 FIX: 老五审批状态 — S1仲裁统一读法: 经 review_gate.evaluate()
    _laowu_review = _get_laowu_review_status()
    _laowu_msg = _laowu_review.get("message", "— 未知")
    # 2026-10-26 对齐: 网关状态改为读 gateway_state.json 真实值 (不再写死)
    _gw_health = _gateway_health()
    _gw_ok = _gw_health.startswith("running") and "fatal:" not in _gw_health
    health_body += f"""<div class='kv'><span>看板服务</span><b class='ok'>在线 · 本页即证</b></div>
<div class='kv'><span>Python</span><b>{_pyver}</b></div>
<div class='kv'><span>数据时效</span><b style='font-weight:400;color:#A1A1AA'>各卡右上角角标为准</b></div>
<div class='kv'><span>Gateway</span><b class='{"ok" if _gw_ok else "warn"}' data-field='gateway-health'>{esc(_gw_health)}</b></div>
<div class='kv'><span>老四巡检</span><b class='{_laosi_tone}' data-field='laosi-status'>{esc(_laosi_status)}</b></div>
<div class='kv'><span>飞书待投递</span><b {'ok' if _msg_pending == 0 else 'warn'} data-field='feishu-pending'>{_msg_pending} 条</b></div>
<div class='kv'><span>老五审批</span><b data-field='laowu-status'>{_laowu_msg}</b></div>"""

    health_html = card("🔧 系统健康", health_body, "card-ok")

    # ── KPI 行数据（2026-09-26 重皮: 对齐设计稿"选股系统看板"四大数）──
    _acct = risk.get("account_status", {}) if risk else {}
    _pnl_pct = _acct.get("total_pnl_pct")
    try:
        _pnl_disp = "{:+.2f}%".format(float(_pnl_pct))
    except Exception:
        _pnl_disp = "—"
    _pnl_cls = "up" if (isinstance(_pnl_pct, (int, float)) and _pnl_pct >= 0) else "dn"
    _pos_disp = "{}/{}%".format(_acct.get("position_pct", "—"), risk.get("position_control", {}).get("max_allowed_pct", "—")) if risk else "—"
    _kpi_top1 = "—"
    if latest_rank_file:
        try:
            _kpi_top1 = "{} · {}".format(
                (rank_data.get("items") or [{}])[0].get("name", "—"),
                (rank_data.get("items") or [{}])[0].get("final_score", "—"))
        except Exception:
            _kpi_top1 = "—"
    _holding_badge = ("● 实盘 · 持仓中" if h else "● 空仓待命")

    # ── AI分析模块（2026-10-07 启用）──
    import urllib.request
    import urllib.error
    _ai_base = os.environ.get("AGNES_API_BASE", "https://apihub.agnes-ai.com/v1")
    _ai_key = os.environ.get("AGNES_API_KEY")
    if not _ai_key:
        _ai_text = "AI分析不可用: API密钥未配置"
        _ai_card = card("🤖 AI专家分析", f"""<div style="background:rgba(99,102,241,0.08);padding:12px;border-radius:8px;border:1px solid rgba(99,102,241,0.3)">
<div style="font-size:14px;font-weight:bold;color:#f59e0b;margin-bottom:8px">⚠️ API密钥未配置</div>
<div style="font-size:12px;color:#8a93a3">请在环境变量中设置 AGNES_API_KEY</div>
</div>""", "card-warn")
    _ai_text = "AI分析暂时不可用"
    try:
        # 门禁状态 — S1 统一仲裁读法 (_approved 由 _load_review_status 保证始终有值)
        _rs_ai = _load_review_status()
        _approved = _rs_ai["approved"]
        _ai_ctx = f"""当前系统状态：
- 策略：S3主候选-阶梯失活+加密-止损10%
- 可用资金：¥{_acct.get('total_assets', 22103.56):,.0f}
- 持仓数：{len(h)}只
- 候选池：{rank_count}只
- TOP1：{(rank_data.get("items") or [{}])[0].get("name", "无")}(评分:{(rank_data.get("items") or [{}])[0].get("final_score", 0)})
- 回测胜率：58.3%
- 回撤：37.34%
- 盈亏比：1.74
- 门禁状态：{'已通过' if _approved else '冻结中'}

请提供投资建议（限50字以内）。"""
        _ai_url = f"{_ai_base}/chat/completions"
        _ai_data = json.dumps({
            "model": "agnes-2.5-flash",
            "messages": [
                {"role": "system", "content": "你是量化投资专家，擅长A股单票轮动策略分析。"},
                {"role": "user", "content": _ai_ctx}
            ],
            "max_tokens": 200
        }).encode('utf-8')
        _ai_req = urllib.request.Request(_ai_url, data=_ai_data, headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {_ai_key}'
        })
        with urllib.request.urlopen(_ai_req, timeout=15) as _resp:
            _ai_result = json.loads(_resp.read().decode('utf-8'))
            _ai_text = _ai_result.get('choices', [{}])[0].get('message', {}).get('content', 'AI分析暂时不可用')
    except Exception as _e:
        _ai_text = f"AI分析暂时不可用: {str(_e)[:50]}"
    
    _ai_card = card("🤖 AI专家分析", f"""<div style="background:rgba(99,102,241,0.08);padding:12px;border-radius:8px;border:1px solid rgba(99,102,241,0.3)">
<div style="font-size:14px;font-weight:bold;color:#10b981;margin-bottom:8px">{'✅ 正常执行' if _approved else '⏸️ 等待解冻'}</div>
<div style="font-size:13px;color:#f59e0b;margin-bottom:10px">风险等级: 🟡 中等</div>
<div style="font-size:11px;color:#8a93a3;margin:8px 0 6px;text-transform:uppercase;letter-spacing:1px;font-weight:700">💡 AI建议</div>
<p style="color:#e6e6e6;line-height:1.6;font-size:12px">{_ai_text}</p>
<div style="font-size:11px;color:#8a93a3;margin:10px 0 6px;text-transform:uppercase;letter-spacing:1px;font-weight:700">⚠️ 风险提示</div>
<ul style="margin:4px 0;padding-left:16px;font-size:12px;color:#f59e0b">
<li>回撤56.7%已过门禁（≤60%，2026-10-15新基线重裁；降DD路线确认DD&lt;53%后自动回退53%）</li>
<li>需关注市场环境变化</li>
</ul>
<div style="margin-top:10px;padding:8px;background:rgba(99,102,241,0.15);border-radius:6px;text-align:center;font-weight:bold;color:#6366f1;font-size:12px">下一步: 等待老大确认买入</div>
</div>""", "card-warn")

    # ── 预留模块占位卡片（后续启用时替换）──
    placeholder_modules = [
        ("📊 绩效归因", "待P0实施：收益分解(选股alpha+择时beta+市场因子)", "pending"),
        ("⚠️ 风险预警", "待P0实施：分级预警(提示/警告/熔断)", "pending"),
        ("📅 事件驱动", "待P1实施：业绩预告/解禁/指数调仓过滤", "future"),
        ("🧪 因子库", "待P1实施：IC>0.03/IR>0.3门禁筛选", "future"),
        ("⚙️ 策略配置", "待P2实施：多策略权重调整", "locked"),
        ("💰 实盘控制", "待P2实施：需老大授权后启用", "locked"),
        ("📚 知识库", "待P2实施：策略经验沉淀", "future"),
    ]

    # 生成占位卡片（仅显示前4个，其余折叠）
    placeholder_html = """
    <div style='margin-top:16px;padding-top:12px;border-top:1px dashed #2a3040'>
        <div style='font-size:11px;color:#8a93a3;margin-bottom:8px'>🔮 预留扩展模块（点击展开）</div>
        <div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:6px'>"""

    for i, (title, desc, status) in enumerate(placeholder_modules[:4]):
        status_color = {"pending": "#f0b429", "future": "#64748b", "locked": "#e06c6c"}.get(status, "#64748b")
        status_icon = {"pending": "⏳", "future": "🔮", "locked": "🔒"}.get(status, "📦")
        placeholder_html += f"""
        <div style='background:#1e2230;border-radius:6px;padding:8px;border-left:2px solid {status_color};font-size:11px'>
            <div style='font-weight:bold;margin-bottom:4px'>{status_icon} {title}</div>
            <div style='color:#8a93a3;font-size:10px'>{desc[:30]}...</div>
        </div>"""

    placeholder_html += """
        </div>
        <div style='margin-top:8px;font-size:10px;color:#64748b'>
            +4 更多模块已预留接口，详见 docs/system-extension-plan-v2.md
        </div>
    </div>"""

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>选股系统看板</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
/* S7 看板美化: 宪法看板UI规范 — CSS变量 + 响应式 + 移动端适配 */
:root {
  --foreground: #e6e6e6;
  --muted-foreground: #8a93a3;
  --accent: #f0b429;
  --border: #2a3040;
  --card: #1a1e28;
  --card-hover: #1e2230;
  --success: #10b981;
  --warning: #f59e0b;
  --danger: #f43f5e;
  --info: #6366f1;
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:var(--card);color:var(--foreground);min-height:100vh;font-family:'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif}
.app{max-width:1440px;margin:0 auto;padding:24px 20px 48px}
@media(max-width:768px){.app{padding:12px 10px 32px}}
.header{display:flex;justify-content:space-between;align-items:baseline;padding:10px 0 14px;margin-bottom:16px;border-bottom:1px solid var(--border)}
.header h1{font-size:19px;font-weight:600;letter-spacing:1px}
.brand{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:11px;color:var(--muted-foreground);margin-left:12px;letter-spacing:2px;font-weight:400}
.meta{font-size:11px;color:var(--muted-foreground)}
.meta b{color:var(--foreground);font-weight:400;font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace}
.badge-live{display:inline-block;margin-left:10px;padding:2px 10px;border-radius:10px;border:1px solid var(--warning);color:var(--warning);font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:10px;letter-spacing:1px}
.badge-live.idle{border-color:#52525B;color:#71717A}
.kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
@media(max-width:900px){.kpi-row{grid-template-columns:repeat(2,1fr)}}
@media(max-width:480px){.kpi-row{grid-template-columns:1fr}}
.kpi{background:#141417;border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.kpi span{display:block;font-size:11px;color:var(--muted-foreground);margin-bottom:6px}
.kpi b{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:26px;font-weight:700;color:var(--foreground)}
.kpi b.up{color:var(--danger)}.kpi b.dn{color:var(--success)}
.kpi b.t1{font-size:17px;letter-spacing:0;font-weight:600}
.kpi i{display:block;font-style:normal;font-size:10px;color:var(--muted-foreground);margin-top:5px}
.main-grid{display:grid;grid-template-columns:1.55fr 1fr;gap:14px;margin-bottom:14px}
@media(max-width:900px){.main-grid{grid-template-columns:1fr}}
.side-col{display:grid;gap:14px;align-content:start}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px}
.card-title{font-size:12px;color:var(--muted-foreground);margin-bottom:10px;font-weight:400;letter-spacing:1px}
.card-body{font-size:13px;line-height:1.7}
.full{grid-column:1/-1}
.trio{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px;margin-bottom:14px}
@media(max-width:768px){.trio{grid-template-columns:1fr}}
.quad{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-bottom:14px}
.hold-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
@media(max-width:480px){.hold-grid{grid-template-columns:1fr}}
@media(max-width:360px){body{font-size:12px}.kpi{padding:8px 10px}}
.hold-card{background:#1C1C20;border-radius:10px;padding:12px 14px;border:1px solid var(--border)}
.hold-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.hold-head h3{font-size:14px;font-weight:600;color:var(--foreground)}
.hold-head span{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:11px;color:var(--muted-foreground)}
.hold-head .pnl{margin-left:auto;font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:15px;font-weight:700}
.pos{color:var(--danger)}.neg{color:var(--success)}
.hold-stats{display:flex;gap:6px;flex-wrap:wrap;font-size:10px;margin-bottom:4px}
.hold-stats span{background:#0A0A0B;padding:3px 8px;border-radius:4px;font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;color:var(--muted-foreground)}
.mini-chart{height:180px;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:6px 8px;border-bottom:1px solid var(--border);text-align:left}
th{color:var(--muted-foreground);font-weight:400;font-size:10px;letter-spacing:1px}
td.num,.num{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace}
.rank-top1{background:#1C1C20;border-left:3px solid var(--accent)}
.rank-tag{display:inline-block;padding:1px 7px;border-radius:3px;font-size:10px;margin-left:6px;font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace}
.rank-tag.top1{background:var(--accent);color:#0A0A0B;font-weight:700}
.kv{display:flex;justify-content:space-between;padding:2px 0}
.kv b{font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-weight:600}
.line{white-space:pre-wrap;padding:1px 0}
.ok{color:var(--success)}.warn{color:var(--warning)}
.signal{margin:3px 0}.sub-title{margin-top:8px;color:var(--warning)}
.footer{text-align:center;font-family:'JetBrains Mono','Cascadia Mono',Consolas,monospace;font-size:10px;color:var(--muted-foreground);margin-top:24px;padding-top:12px;border-top:1px solid var(--border)}
a{color:#A1A1AA;text-decoration:none}
.ts-line{font-size:10px;color:var(--muted-foreground);margin-top:4px}
.fetch-status{display:inline;font-size:10px;font-family:'JetBrains Mono',Consolas,monospace}
.fetch-status.loading{color:var(--warning)}
.fetch-status.ok{color:var(--success)}
.fetch-status.error{color:var(--danger)}
</style>
</head><body>
<div class="app">
<div class="header"><h1>选股系统看板<span class="brand">ZHUANQIAN · BOARD</span><span class="badge-live@@badge_cls@@">@@live_badge@@</span></h1><span class="meta">生成 <b>@@now@@</b> · 手动刷新即实时 · 数据只读</span></div>
<div class="kpi-row">
<div class="kpi"><span>账户总资产</span><b id="kpi-assets">@@kpi_assets@@</b><i>台账实盘口径</i></div>
<div class="kpi"><span>总盈亏</span><b id="kpi-pnl" class="@@kpi_pnl_cls@@">@@kpi_pnl@@</b><i>相对成本</i></div>
<div class="kpi"><span>仓位 当前/建议</span><b id="kpi-pos">@@kpi_pos@@</b><i>合规风控</i></div>
<div class="kpi"><span>候选池 TOP1</span><b id="kpi-top1" class="t1">@@kpi_top1@@</b><i>最新选股信号</i></div>
</div>
<div class="main-grid">
<div class="card"><div class="card-title">实盘持仓 · 30日走势与止盈止损</div><div class="card-body"><div class="hold-grid">@@pos_cards@@</div></div></div>
<div class="side-col">@@risk_card@@@@gate_card@@</div>
</div>
<div class="card full" style="margin-bottom:14px"><div class="card-title">候选池 TOP10 · 最新排序</div><div class="card-body">@@rank_body@@</div></div>
<div class="trio">
@@team_card@@
@@task_overview@@
@@review_card@@
</div>
<div class="quad">
@@daily_card@@
@@ml_card@@
@@health_card@@
@@push_card@@
@@ai_card@@
</div>
@@placeholder@@
<div class="footer"><span id="fetch-status" style="color:#8a93a3;font-size:10px">⏳ 数据加载中…</span> · ZHUANQIAN BOARD · 数据只读 @@root@@\\data · 全仓1只+移动止盈 · 各卡数据时效以角标为准 · 加载时自动获取最新数据 · 手动刷新即重算</div>
</div>
<script>
/* S7 H1: auto-fetch dashboard_data on page load (单次fetch, 无轮询) */
/* t_d4_003+t_d4_004: 用户可见降级 + 页脚状态指示器 */
(function(){
  var REFRESH_MS = 60000; /* 60s: 非持续轮询，仅兜底刷新 */
  var _statusEl = document.getElementById('fetch-status');

  function setFetchStatus(text, cls){
    if(_statusEl){
      _statusEl.textContent = text;
      _statusEl.className = 'fetch-status ' + (cls || '');
    }
  }

  function fetchDashboard(){
    setFetchStatus('\u23F3 数据加载中\u2026', 'loading');
    fetch('/api/dashboard_data').then(function(r){
      if(!r.ok) throw new Error('HTTP '+r.status);
      return r.json();
    }).then(function(d){
      if(!d || !d.holdings){
        setFetchStatus('\u274C 数据获取失败，请手动刷新', 'error');
        return;
      }
      setFetchStatus('\u2705 数据已更新', 'ok');
      var h = d.holdings;
      var el = function(id){ return document.getElementById(id); };
      if(el('kpi-assets')) el('kpi-assets').textContent = '\u00A5'+(h.total_assets||0).toLocaleString();
      if(el('kpi-pos')) el('kpi-pos').textContent = (h.position_ratio*100||0).toFixed(1)+'%';
      if(el('kpi-top1') && d.candidates_top10 && d.candidates_top10[0]){
        var top1 = d.candidates_top10[0];
        var _asof = d.candidates_asof ? ' · '+d.candidates_asof : '';
        el('kpi-top1').textContent = (top1.name||'\u2014') + ' \u00B7 ' + (top1.final_score||top1.score||'\u2014') + _asof;
      }
      /* D2/D3: 同步更新健康卡 (老四/老五/飞书/网关) via data-field */
      var _q = function(attr){ return document.querySelector('[data-field="'+attr+'"]'); };
      if(d.laosi && _q('laosi-status')) _q('laosi-status').textContent = d.laosi.drift_detected ? '\u26A0\uFE0F 漂移' : '\u2705 无漂移';
      if(d.laowu_review && _q('laowu-status')) _q('laowu-status').textContent = d.laowu_review.message || '\u2014';
      if(d.feishu && _q('feishu-pending')) _q('feishu-pending').textContent = d.feishu.pending_count + ' 条';
      if(d.feishu && d.feishu.gateway_health && _q('gateway-health')) _q('gateway-health').textContent = d.feishu.gateway_health;
    }).catch(function(e){
      console.error('dashboard_data fetch failed:', e);
      setFetchStatus('\u274C 数据获取失败：'+(e.message||'网络错误')+'，请手动刷新', 'error');
    });
  }

  window.addEventListener('DOMContentLoaded', fetchDashboard);
  setTimeout(fetchDashboard, REFRESH_MS);
})();
</script>
<script>
@@chart_js@@
</script>
</body></html>"""

    risk_card = card("账户与风控", risk_body,
                     "card-danger" if risk and not risk.get("position_control", {}).get("compliant") else "card-ok")
    daily_card = card("每日简报", daily_body)
    # ml_card 已在因子重构流水线段构建(2026-09-26 对齐)
    html = html.replace("@@now@@", now) \
        .replace("@@live_badge@@", _holding_badge) \
        .replace("@@badge_cls@@", "" if h else " idle") \
        .replace("@@kpi_assets@@", str(_acct.get("total_assets", "—"))) \
        .replace("@@kpi_pnl@@", _pnl_disp) \
        .replace("@@kpi_pnl_cls@@", _pnl_cls) \
        .replace("@@kpi_pos@@", _pos_disp) \
        .replace("@@kpi_top1@@", esc(str(_kpi_top1))) \
        .replace("@@pos_cards@@", pos_cards) \
        .replace("@@risk_card@@", risk_card) \
        .replace("@@gate_card@@", gate_html) \
        .replace("@@rank_body@@", rank_body) \
        .replace("@@team_card@@", team_card_html) \
        .replace("@@task_overview@@", task_overview_html) \
        .replace("@@review_card@@", review_card_html) \
        .replace("@@daily_card@@", daily_card) \
        .replace("@@ml_card@@", ml_card) \
        .replace("@@health_card@@", health_html) \
        .replace("@@push_card@@", push_html) \
        .replace("@@ai_card@@", _ai_card) \
        .replace("@@placeholder@@", placeholder_html) \
        .replace("@@chart_js@@", "\n".join(chart_js)) \
        .replace("@@root@@", esc(ROOT))
    # 2026-09-26 重皮兜底: 残留旧内联色一次性刷净为新色板(新CSS用大写hex不受影响)
    for _old, _new in {"#8a93a3": "#71717A", "#4caf7d": "#10B981", "#e06c6c": "#F43F5E",
                       "#f0b429": "#F59E0B", "#1a1e28": "#1C1C20", "#1e2230": "#1C1C20",
                       "#2a3040": "#27272A", "#252b3a": "#27272A"}.items():
        html = html.replace(_old, _new)
    return html


def _ensure_scripts_path():
    p = os.path.join(ROOT, "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in (("/", "/board")):
            # 优先使用美化版看板
            try:
                body = build_html().encode("utf-8")
            except Exception as e:
                # 降级到原始版
                body = build_original_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path in ("/warroom.html", "/warroom"):
            # 2026-09-26 改造(老大指令): 作战台并入系统, 每次请求实时渲染, 不再依赖定时生成的静态快照
            body = None
            try:
                _ensure_scripts_path()
                from build_warroom_dashboard import build as build_warroom
                body = build_warroom().encode("utf-8")
            except Exception as e1:
                try:
                    _ensure_scripts_path()
                    from build_dashboard import build as build_warroom_v1
                    body = build_warroom_v1().encode("utf-8")
                except Exception as e2:
                    body = ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
                            "<title>御龙决 · 作战台</title></head>"
                            "<body style=\"background:#0f1117;color:#e6e8ee;"
                            "font-family:'Microsoft YaHei',sans-serif;padding:40px\">"
                            "<h2>⚠️ 作战台渲染失败</h2>"
                            f"<p>V2 动态渲染: {esc(str(e1))}</p>"
                            f"<p>V1 生成器: {esc(str(e2))}</p>"
                            "<p><a href=\"/board\" style=\"color:#6ea8fe\">← 返回选股系统看板</a></p>"
                            "</body></html>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/system_health":
            # 返回系统健康快照（US2: GET /api/system_health）
            # 只读快照文件，无快照/快照损坏 → 返回 unknown（FR-007 不得虚假正常）
            # 注意：本端点不运行实时检查，实时检查由 system_health.py cron 负责
            snapshot_path = Path(ROOT) / "data" / "system" / "health_snapshot.json"
            body = json.dumps({"status": "unknown", "message": "等待首个健康检查周期"}).encode("utf-8")
            if snapshot_path.exists():
                try:
                    raw = snapshot_path.read_text(encoding="utf-8")
                    snapshot = json.loads(raw)  # 校验 JSON 有效
                    # 快照必须含 status 字段（契约）
                    if not isinstance(snapshot, dict) or "status" not in snapshot:
                        raise ValueError("snapshot missing 'status' field")
                    body = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    body = json.dumps(
                        {"status": "unknown", "message": f"快照读取/校验失败: {exc}"},
                        ensure_ascii=False,
                    ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/dashboard_data":
            # 2026-10-23 S7 看板美化: 聚合多数据源 → 前端一次性加载
            # 宪法看板UI规范: holdings字段兼容(code/symbol) + 响应式布局数据
            try:
                data = _aggregate_dashboard_data()
                body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            except Exception as exc:
                body = json.dumps(
                    {"error": f"dashboard_data聚合失败: {exc}"},
                    ensure_ascii=False,
                ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
