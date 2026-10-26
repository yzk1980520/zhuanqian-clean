#!/usr/bin/env python3
"""
Gateway守护进程 — 每30秒检查健康，异常自动重启
用法: python scripts/gateway_guardian.py
"""
import sys, time, os, json, urllib.request, subprocess
from pathlib import Path
from datetime import datetime

# 配置
GATEWAY_URL = "http://127.0.0.1:8642/health"
LOG_FILE = Path(__file__).parent.parent / "logs" / "gateway_guardian.log"
PID_FILE = Path(__file__).parent.parent / "data" / "gateway_guardian.pid"
CHECK_INTERVAL = 30  # 秒
MAX_RESTARTS = 5     # 每小时最多重启次数

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def check_health():
    try:
        req = urllib.request.Request(GATEWAY_URL, headers={"User-Agent": "guardian"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            return data.get("status") == "ok"
    except Exception as e:
        log(f"健康检查失败: {e}")
        return False

def restart_gateway():
    """重启Gateway"""
    log("尝试重启Gateway...")
    try:
        # 先尝试优雅停止
        subprocess.run(["hermes", "gateway", "stop"], timeout=10, capture_output=True)
        time.sleep(2)
    except (FileNotFoundError, OSError, subprocess.CalledProcessError):
        print(f"⚠️ [scripts\gateway_guardian.py] 兼容处理: except (FileNotFoundError, OSError, subprocess.CalledProcessError):", file=sys.stderr)
    # 启动新进程
    result = subprocess.run(
        ["hermes", "gateway", "start"],
        capture_output=True,
        text=True,
        timeout=30
    )
    if result.returncode == 0:
        log("Gateway重启成功")
        return True
    else:
        log(f"重启失败: {result.stderr}")
        return False

def check_rate_limit():
    """检查重启频率限制"""
    history_file = Path(__file__).parent.parent / "data" / "restart_history.json"
    try:
        if history_file.exists():
            history = json.loads(history_file.read_text())
        else:
            history = {"restarts": []}
        
        # 清除1小时前的记录
        cutoff = time.time() - 3600
        history["restarts"] = [t for t in history.get("restarts", []) if t > cutoff]
        
        if len(history["restarts"]) >= MAX_RESTARTS:
            log(f"重启限流: 最近1小时已重启{len(history['restarts'])}次")
            return False
        
        history["restarts"].append(time.time())
        history_file.write_text(json.dumps(history))
        return True
    except Exception as e:
        log(f"限流检查失败: {e}")
        return True

def main():
    # 写入PID
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    
    log("=" * 50)
    log("Gateway守护进程启动")
    log(f"监控: {GATEWAY_URL}")
    log(f"间隔: {CHECK_INTERVAL}秒")
    log("=" * 50)
    
    while True:
        try:
            if not check_health():
                log("Gateway无响应!")
                if check_rate_limit():
                    restart_gateway()
            else:
                log("Gateway健康 ✓")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            log("收到中断信号，退出")
            PID_FILE.unlink(missing_ok=True)
            sys.exit(0)
        except Exception as e:
            log(f"守护进程异常: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()