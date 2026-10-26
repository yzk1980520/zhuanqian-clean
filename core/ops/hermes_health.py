import os
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""hermes_health.py — Hermes CN Desktop 彻底重启工具
功能：杀进程 → 清残留(锁/PID/Gateway日志/cron锁) → 重启桌面
"""
import psutil, os, time, subprocess, glob, logging
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    logger = logging.getLogger("hermes_health")
    
    HERMES_HOME = 'D:/Hermes agent/Hermes Agent CN Desktop/data/hermes-home'
    # 2026-09-27 修: 旧路径 hermes-agent-cn-desktop.exe 因应用更新失败已消失,
    # 新入口为 apps/desktop/release/win-unpacked/Hermes.exe (取自桌面快捷方式解析, 09-23 构建)
    DESKTOP_EXE = 'D:/Hermes agent/Hermes Agent CN Desktop/apps/desktop/release/win-unpacked/Hermes.exe'
    # S6 基地化：原根目录 hardcoded 路径，现改为基于模块位置的相对路径
_PROJECT_FILE = Path(__file__).resolve()
PROJECT = str(_PROJECT_FILE.parents[2])  # core/ops/ -> core/ -> project root
    
    print("=" * 60)
    print("  Hermes CN Desktop 完全重启")
    print("=" * 60)
    
    # Step 1: Kill all Hermes processes
    print("\n[1/4] 终止Hermes进程...")
    killed = 0
    for p in psutil.process_iter(['pid', 'name']):
        try:
            if 'hermes' in p.info['name'].lower():
                p.kill()
                killed += 1
                print(f"  ✝  PID {p.info['pid']} {p.info['name']}")
        except Exception as e:
            # P0-2修复: 杀单个进程失败打debug(不影响继续遍历)
            logger.debug("终止单个进程失败 pid=%s: %s", getattr(p.info, 'get', lambda *_: '?')('pid'), e)
    print(f"  ✅ 已终止 {killed} 个进程")
    time.sleep(3)
    
    # Step 2: Verify all Hermes processes are dead
    print("\n[2/4] 确认全部终止...")
    for _ in range(5):
        survivors = []
        for p in psutil.process_iter(['pid', 'name']):
            try:
                if 'hermes' in p.info['name'].lower():
                    survivors.append(p.info['pid'])
            except Exception as e:
                # P0-2修复: 不再空吞
                logger.debug("校验存活时读取进程失败: %s", e)
        if not survivors:
            print("  ✅ 全部进程已终止")
            break
        print(f"  ⏳ 等待中... 剩余: {survivors}")
        time.sleep(2)
    
    # Step 3: Clean up lock/pid files
    print("\n[3/4] 清理残留文件...")
    cleaned = 0
    
    # Gateway & PID files (容错: 单文件被占用/删除失败只警告跳过, 不中断重启流程)
    for f in os.listdir(HERMES_HOME):
        if f.startswith('gateway') and f.endswith(('.pid', '.lock', '.json', '.log')):
            fp = os.path.join(HERMES_HOME, f)
            try:
                os.remove(fp)
                cleaned += 1
            except OSError as e:
                print(f"  ⚠ 跳过 {f}: {e}")

    # Cron locks
    cron_dir = os.path.join(HERMES_HOME, 'cron')
    lock_files = ['.jobs.lock', '.tick.lock', 'ticker_heartbeat', 'ticker_last_success']
    for lf in lock_files:
        p = os.path.join(cron_dir, lf)
        if os.path.exists(p):
            try:
                os.remove(p)
                cleaned += 1
            except OSError as e:
                print(f"  ⚠ 跳过 cron/{lf}: {e}")

    # PID files in scripts dir
    for pidf in glob.glob(os.path.join(HERMES_HOME, 'scripts', '*.pid')):
        try:
            os.remove(pidf)
            cleaned += 1
        except OSError as e:
            print(f"  ⚠ 跳过 {os.path.basename(pidf)}: {e}")
    
    print(f"  ✅ 已清理 {cleaned} 个残留文件")
    
    # Step 4: Restart desktop
    print(f"\n[4/4] 启动桌面...")
    subprocess.Popen([DESKTOP_EXE])
    print(f"  🚀 {DESKTOP_EXE}")
    print(f"\n{'=' * 60}")
    print(f"  桌面已重启，请等待10-15秒后重新连接")
    print(f"  新runtime将获得正常PID")
    print(f"{'=' * 60}")
