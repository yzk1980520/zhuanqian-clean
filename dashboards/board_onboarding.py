#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_onboarding.py — 看板 Onboarding 服务 (总管 2026-10-15 → 2026-10-21 浏览器适配)

定位: 轻量 HTTP 服务, 监听 127.0.0.1:3011。
端点:
  /onboarding, /  → HTML 引导页（浏览器直接可看）
  /health         → JSON 状态（watchdog 健康探测 + 程序化访问）

v3 (2026-10-15): 修复 boot popup 事故后的配套服务
v4 (2026-10-21): 浏览器适配 — /onboarding 改返回 HTML, /health 保留 JSON
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 3011
HOST = "127.0.0.1"
ROOT = Path(__file__).resolve().parents[1]

_ONBOARDING_HTML = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>选股系统 · Onboarding</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0A0A0B;color:#FAFAFA;font-family:'Noto Sans SC','Microsoft YaHei',sans-serif;
  min-height:100vh;display:flex;align-items:center;justify-content:center}}
.card{{background:#141417;border:1px solid #27272A;border-radius:12px;padding:32px;
  max-width:520px;width:90%}}
.card h1{{font-size:18px;font-weight:600;margin-bottom:12px}}
.card p{{font-size:13px;color:#A1A1AA;line-height:1.8}}
.badge{{display:inline-block;padding:2px 10px;border-radius:10px;font-size:11px;
  font-family:'JetBrains Mono',Consolas,monospace;letter-spacing:1px}}
.badge.ok{{border:1px solid #10B981;color:#10B981}}
.kv{{display:flex;justify-content:space-between;padding:4px 0;font-size:13px}}
.kv span{{color:#71717A}}
.kv b{{font-family:'JetBrains Mono',Consolas,monospace;font-weight:600}}
a{{color:#A1A1AA;text-decoration:none}}
footer{{margin-top:20px;padding-top:12px;border-top:1px solid #27272A;
  font-size:10px;color:#71717A;font-family:'JetBrains Mono',Consolas,monospace;
  text-align:center}}
</style></head><body>
<div class="card">
  <h1>📊 选股系统 · 看板服务 <span class="badge ok">ONLINE</span></h1>
  <div class="kv"><span>服务名</span><b>board_onboarding</b></div>
  <div class="kv"><span>监听地址</span><b>{HOST}:{PORT}</b></div>
  <div class="kv"><span>健康端点</span><b>/health → JSON</b></div>
  <div class="kv"><span>业务看板</span><b><a href="http://127.0.0.1:8666/">http://127.0.0.1:8666/</a></b></div>
  <p style="margin-top:12px;color:#71717A">
    本端点供 watchdog 健康探测使用。业务数据请访问上方 8666 看板。
  </p>
  <footer>ZHUANQIAN · BOARD ONBOARDING · 数据只读</footer>
</div>
</body></html>"""


class OnboardingHandler(BaseHTTPRequestHandler):
    """Onboarding + 健康端点处理器"""

    def do_GET(self):
        path = self.path.rstrip("/") or "/"

        if path in ("/", "/onboarding"):
            # HTML 引导页 — 浏览器直接可看
            body = _ONBOARDING_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/health":
            # JSON 状态 — watchdog 健康探测 / 程序化访问
            body = json.dumps({
                "status": "ok",
                "service": "board_onboarding",
                "port": PORT,
                "host": HOST,
                "ready": True,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass  # 静默日志, 避免 watchdog 刷屏


def main():
    """启动 onboarding 服务"""
    server = ThreadingHTTPServer((HOST, PORT), OnboardingHandler)
    try:
        print(f"board_onboarding 监听 {HOST}:{PORT}", file=sys.stderr, flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        print("board_onboarding 收到中断信号, 停止", file=sys.stderr, flush=True)
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
