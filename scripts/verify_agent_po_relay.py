#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_agent_po_relay.py — 8 agent po中继接口对齐验证 (总管 2026-10-26)

对齐契约 (docs/agent_api_contract.md):
  - 端点:  http://127.0.0.1:8642/p/{profile}/v1/chat/completions
  - 认证:  各 profile .env 的 API_SERVER_KEY (Bearer)
  - model: niuma=agnes-2.5-flash, 其余=agnes-3.0-flash
  - 冷启动: atomcode/首次调用 provider 懒加载, 需 timeout>=45s
  - 输出:  全 home_channel=主群 oc_032f...(防 admission_conflict 需分流)

退出码: 0=全通, 1=有断点
"""
import urllib.request, json, os, sys

HERMES = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
PORT = "8642"
# model 契约: 各 profile 自身 default
MODEL = {"niuma": "agnes-2.5-flash"}
DEFAULT_MODEL = "agnes-3.0-flash"
# 冷启动容忍: 首次调用懒加载 provider, atomcode 尤甚
TIMEOUT = 45
PROFILES = ["zongguan","laosi","laowu","laosan","opencode","atomcode","niuma","workbuddy"]

def get_key(p):
    """取有效 API_SERVER_KEY: 跳过 *** 脱敏占位/空值, 取最后一个含 hermes- 的真 key 行。
    (2026-10-26 workbuddy .env 曾混入 API_SERVER_KEY=*** 脏行导致首匹配读到占位→401)"""
    envf = os.path.join(HERMES, "profiles", p, ".env")
    valid = None
    try:
        for line in open(envf, encoding="utf-8"):
            if line.startswith("API_SERVER_KEY="):
                v = line.split("=",1)[1].strip()
                if v and v != "***" and "hermes-" in v:
                    valid = v
    except Exception:
        pass
    return valid or ""

def ping(p):
    key = get_key(p)
    model = MODEL.get(p, DEFAULT_MODEL)
    url = f"http://127.0.0.1:{PORT}/p/{p}/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps({"model": model,
                         "messages": [{"role":"user","content":"ping"}],
                         "max_tokens": 3}).encode(),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = json.loads(r.read())
        return r.status, body["choices"][0]["message"]["content"][:20]

def main():
    # gateway 在线?
    try:
        import socket
        s = socket.create_connection(("127.0.0.1", int(PORT)), timeout=3); s.close()
        print(f"✅ gateway :{PORT} online")
    except Exception as e:
        print(f"❌ gateway :{PORT} offline: {e}")
        sys.exit(1)

    ok = 0
    for p in PROFILES:
        model = MODEL.get(p, DEFAULT_MODEL)
        try:
            st, content = ping(p)
            mark = "✅" if st == 200 else "❌"
            if st == 200: ok += 1
            print(f"{mark} {p:<10} {model:<16} HTTP {st} {content}")
        except Exception as e:
            print(f"❌ {p:<10} {model:<16} {str(e)[:50]}")
    print(f"\n=== po中继对齐: {ok}/{len(PROFILES)} 通 ===")
    sys.exit(0 if ok == len(PROFILES) else 1)

if __name__ == "__main__":
    main()
