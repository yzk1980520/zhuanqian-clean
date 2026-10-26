# DEPRECATED → use scripts/check_all.py health
# -*- coding: utf-8 -*-
"""
fallback_health_check.py — provider fallback 健康探测（老四，2026-10-14）
================================================================================
背景: 原 fallback 曾"静默失效"（本地服务未起/限流），无人察觉 → 质量不稳根因之一。
功能: 探测 fallback 端点可达性 + chat 端到端，失效时 P1 告警（alert_log.jsonl）。
用法: python scripts/fallback_health_check.py [--dry-run]
数据红线: 只读 config.yaml + 只写 alert_log.jsonl / fallback_health.json；
         不碰 trade_log/holdings。

变更记录:
  2026-10-14 v1 老四初版
  2026-10-14 v2 老四 P2/P3 修复:
    - P2: 告警去重/冷却（同故障 N 小时内只告警一次，防刷屏）
    - P3: STATUS_FILE 写入改走 atomic_json（项目规范）
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
import atomic_json  # 系统规范: JSON 只用 atomic_json

CONFIG = Path(r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\config.yaml")
ALERT_LOG = PROJECT / "data" / "alert_log.jsonl"
STATUS_FILE = PROJECT / "data" / "fallback_health.json"
COOLDOWN_FILE = PROJECT / "data" / "fallback_health_cooldown.json"
ALERT_COOLDOWN_HOURS = 6  # P2: 同故障 6 小时内只告警一次（防刷屏）


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_alert(level: str, message: str, source: str = "fallback_health"):
    """P0/P1 告警追加 alert_log.jsonl（与 scripts/alert_engine.log_alert 同格式）。"""
    entry = {"timestamp": _now(), "level": level, "source": source, "message": message}
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _should_alert(fingerprint: str) -> bool:
    """P2: 去重/冷却。同一故障指纹在冷却期内 → 不再告警。返回 True=应告警。"""
    now = time.time()
    state = atomic_json.atomic_load(str(COOLDOWN_FILE), default={}) or {}
    last = state.get(fingerprint, 0)
    if now - last < ALERT_COOLDOWN_HOURS * 3600:
        return False
    state[fingerprint] = now
    # 清理过期指纹（> 7天）
    state = {k: v for k, v in state.items() if now - v < 7 * 86400}
    atomic_json.atomic_dump(state, str(COOLDOWN_FILE), ensure_ascii=False)
    return True


def load_fallback():
    """从 config.yaml 读 fallback_model（只读）。"""
    import yaml
    d = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return d.get("fallback_model", {})


def probe(fb: dict) -> tuple[bool, str]:
    """探测 fallback chat 端到端。返回 (ok, detail)。"""
    base = (fb.get("base_url") or "").rstrip("/")
    model = fb.get("model") or ""
    env = fb.get("api_key_env") or ""
    key = os.environ.get(env, "")
    if not base or not model:
        return False, "fallback 配置不完整"
    if not key:
        return False, f"环境变量 {env} 缺失"
    body = json.dumps({"model": model,
                       "messages": [{"role": "user", "content": "OK"}],
                       "max_tokens": 5}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode())
            content = d["choices"][0]["message"]["content"]
            return True, f"HTTP {r.status} 回复={content[:20]!r}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} ({e.reason})"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    dry = "--dry-run" in sys.argv[1:]
    fb = load_fallback()
    ok, detail = probe(fb)
    status = {
        "timestamp": _now(),
        "fallback_base_url": fb.get("base_url"),
        "fallback_model": fb.get("model"),
        "healthy": ok,
        "detail": detail,
    }
    if not dry:
        # P3: 走 atomic_json（项目规范）
        atomic_json.atomic_dump(status, str(STATUS_FILE), ensure_ascii=False)
    print(f"[fallback_health] {'✅ 健康' if ok else '❌ 失效'} — {detail}")
    if not ok:
        # P2: 去重/冷却
        fp = f"{fb.get('base_url')}|{detail.split('(')[0].strip()}"
        if _should_alert(fp):
            _log_alert("P1", f"🟡 [fallback_health] provider fallback 失效: "
                             f"{fb.get('base_url')} ({detail})。降级链可能断档，请检查。",
                       "fallback_health")
            print("[ALERT-P1] 已追加 alert_log.jsonl")
        else:
            print(f"[ALERT-SUPPRESSED] 冷却期内（{ALERT_COOLDOWN_HOURS}h），跳过重复告警")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
