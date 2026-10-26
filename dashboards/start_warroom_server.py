#!/usr/bin/env python3
"""
启动作战台服务器
用法: python start_warroom_server.py
"""
import os
import sys
import subprocess
import time
import webbrowser
from pathlib import Path

def main():
    project_dir = Path(__file__).parent.parent
    dashboards_dir = project_dir / "dashboards"
    server_script = dashboards_dir / "board_server.py"
    
    # 检查服务器脚本是否存在
    if not server_script.exists():
        print(f"❌ 服务器脚本不存在: {server_script}")
        return 1
    
    # 检查端口是否已被占用
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 8666))
    sock.close()
    
    if result == 0:
        print("✅ 端口8666已被占用，服务器可能已在运行")
        print("🌐 尝试访问: http://127.0.0.1:8666/warroom.html")
        webbrowser.open("http://127.0.0.1:8666/warroom.html")
        return 0
    
    # 启动服务器
    print("🚀 启动作战台服务器...")
    print(f"📁 工作目录: {project_dir}")
    print(f"🌐 访问地址: http://127.0.0.1:8666/")
    print(f"🌐 作战台: http://127.0.0.1:8666/warroom.html")
    print("按 Ctrl+C 停止服务器\n")
    
    try:
        # 使用子进程启动服务器
        proc = subprocess.Popen(
            [sys.executable, str(server_script)],
            cwd=str(dashboards_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # 等待服务器启动
        time.sleep(2)
        
        # 检查进程是否还在运行
        if proc.poll() is None:
            print("✅ 服务器启动成功")
            webbrowser.open("http://127.0.0.1:8666/warroom.html")
            
            # 保持进程运行
            proc.wait()
        else:
            print(f"❌ 服务器启动失败，退出码: {proc.returncode}")
            # 输出错误信息
            stdout, stderr = proc.communicate()
            if stdout:
                print(f"标准输出: {stdout}")
            if stderr:
                print(f"标准错误: {stderr}")
            return proc.returncode
    except KeyboardInterrupt:
        print("\n⏹️  服务器已停止")
        return 0
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
