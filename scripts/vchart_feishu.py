"""VChart 飞书嵌入 — 持仓走势图 PNG 生成 + 飞书图片消息 (2026-09-01)

关键：飞书不能渲染 VChart 的 JS HTML，必须走 matplotlib 转 PNG → lark-cli --image
lark-cli --image 只接受 cwd 相对路径（绝对路径和..被拒绝），所以图表保存到 cwd。

红线：不修改 risk_rules.py / trailing_vs_fixed.py / simulate_trading.py
"""
import os
import sys
import json
import subprocess
from datetime import date

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

import matplotlib
matplotlib.use("Agg")  # 无头模式，不需要 GUI
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from position_card import get_holdings
from core.pipeline.tdx_core import get_tdx_data

# ── 常量 ──
STOP_LOSS_PCT = 0.08
LARK_CLI = r"D:\npm-global\lark-cli.cmd"
ROOT = 'D:/open code/zhuanqian/scripts'


# 群ID单一配置源 (2026-09-28 总管根治): 群ID变更只改 feishu_chat_id.txt 一处
def _load_feishu_chat_id():
    """群ID单一配置源(2026-09-28 总管根治): 只改 仓库根/feishu_chat_id.txt 一处, 全脚本跟随。"""
    import os as _os
    d = _os.path.dirname(_os.path.abspath(__file__))
    if _os.path.basename(d) == "scripts":
        d = _os.path.dirname(d)
    try:
        with open(_os.path.join(d, "feishu_chat_id.txt"), encoding="utf-8") as _f:
            v = _f.read().strip()
            return v or "oc_100a06a1c71d5f8b1e58f1e420cadd1a"
    except Exception:
        return "oc_100a06a1c71d5f8b1e58f1e420cadd1a"

CHAT_ID = _load_feishu_chat_id()


def draw_position_chart(code: str, name: str, cost: float, days: int = 30) -> str | None:
    """
    用 matplotlib 画单只持仓走势图，返回 PNG 相对路径（cwd 相对），失败返回 None。
    图表内容：收盘价折线 + 成本线(蓝虚线) + 止损线(红虚线) + 最高价标注
    """
    data = get_tdx_data(code, days=days)
    if not data or len(data) < 3:
        print(f"[VChart] {code} TDX 数据不足", file=sys.stderr)
        return None

    dates = [d["date"] for d in data]
    closes = [float(d["close"]) for d in data]
    highs = [float(d["high"]) for d in data]
    lows = [float(d["low"]) for d in data]
    latest = closes[-1]
    stop_loss = cost * (1 - STOP_LOSS_PCT)
    peak = max(highs)
    pnl_pct = (latest / cost - 1) * 100

    # ── 用 CJK 字体 ──
    try:
        plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        print(f"🔴 [scripts\vchart_feishu.py] CR-01: except Exception:", file=sys.stderr)
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=120)
    fig.patch.set_facecolor("#fafafa")

    # 面积填充（高低价区间）
    ax.fill_between(dates, lows, highs, alpha=0.12, color="#1890ff")

    # 收盘价折线
    ax.plot(dates, closes, color="#333333", linewidth=1.8, label=f"收盘价 {latest:.2f}")

    # 最高价标注
    peak_idx = highs.index(peak)
    ax.annotate(
        f"最高 {peak:.2f}",
        xy=(dates[peak_idx], peak),
        xytext=(0, 10),
        textcoords="offset points",
        fontsize=8,
        color="#f5222d",
        ha="center",
        arrowprops=dict(arrowstyle="->", color="#f5222d", lw=0.8),
    )

    # 成本线（蓝色虚线）
    ax.axhline(cost, color="#1890ff", linestyle="--", linewidth=1.2, alpha=0.8)
    ax.text(
        dates[-1], cost, f"  成本 {cost}", va="bottom",
        fontsize=8, color="#1890ff",
    )

    # 止损线（红色虚线）
    ax.axhline(stop_loss, color="#f5222d", linestyle="--", linewidth=1.2, alpha=0.8)
    ax.text(
        dates[-1], stop_loss, f"  止损 {stop_loss:.2f}", va="top",
        fontsize=8, color="#f5222d",
    )

    # 坐标轴
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, days // 10)))
    fig.autofmt_xdate()
    ax.grid(axis="y", alpha=0.3, linestyle=":")

    # 标题 + 副标题
    pnl_str = f"{pnl_pct:+.1f}%"
    ax.set_title(f"{name} {code}", fontsize=13, fontweight="bold", pad=10)
    ax.text(
        0.01, 0.97,
        f"持仓{days}日  浮盈{pnl_str}  成本{cost}",
        transform=ax.transAxes, fontsize=8, va="top",
        color="#555555",
    )

    plt.tight_layout()

    # 文件名（cwd 相对，lark-cli 要求）
    png_name = f"{code}_position_chart.png"
    out_path = os.path.join(PROJECT_DIR, png_name)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)

    print(f"[VChart] {code} → {png_name} ({os.path.getsize(out_path)} bytes)", file=sys.stderr)
    return png_name


def send_chart_to_feishu(png_rel_path: str) -> bool:
    """
    用 lark-cli --image 发送图片到飞书。
    必须在 PROJECT_DIR 下运行（lark-cli --image 只接受 cwd 相对路径）。
    """
    if not os.path.exists(os.path.join(PROJECT_DIR, png_rel_path)):
        print(f"[VChart] 文件不存在: {png_rel_path}", file=sys.stderr)
        return False

    r = subprocess.run(
        [LARK_CLI, "im", "+messages-send",
         "--chat-id", CHAT_ID,
         "--image", png_rel_path,
         "--as", "user"],
        capture_output=True, text=True, timeout=45, cwd=PROJECT_DIR,
    )

    if r.returncode != 0:
        print(f"[VChart] 飞书发送失败 exit={r.returncode} stderr={r.stderr[:200]}", file=sys.stderr)
        return False

    try:
        out = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        print(f"[VChart] 输出非 JSON: {r.stdout[:200]}", file=sys.stderr)
        return False

    mid = (out.get("data") or {}).get("message_id", "")
    print(f"[VChart] OK image message_id={mid}", file=sys.stderr)
    return out.get("ok", False)


def generate_and_send_all(dry_run: bool = False) -> int:
    """
    生成所有持仓的图表并发送到飞书，返回成功发送数。
    """
    holdings = get_holdings()
    sent = 0

    for h in holdings:
        code = h.get("code", "")
        name = h.get("name", code)
        cost = h.get("cost", 0) or h.get("buy_price", 0)
        if not code or not cost:
            continue

        png = draw_position_chart(code, name, cost)
        if not png:
            continue

        if dry_run:
            print(f"[Dry-run] 跳过发送: {png}")
        else:
            if send_chart_to_feishu(png):
                sent += 1

    return sent


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    n = generate_and_send_all(dry_run=dry)
    print(f"完成: {n} 张图表" + (" (dry-run)" if dry else " 已发送飞书"))