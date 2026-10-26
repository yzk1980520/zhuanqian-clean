#!/usr/bin/env python3
"""
financial-analysis API Key 配置工具
用于配置华泰证券金融分析服务的认证密钥
"""

import os
import sys
import logging
from pathlib import Path
import argparse

# 导入公共模块
from common import (
    validate_api_key,
    ensure_directory,
    safe_write_text,
    logger
)

def detect_current_config():
    """检测当前配置状态"""
    home = Path.home()
    
    # 检查可能的配置位置
    config_paths = [
        home / ".htsc-skills" / "config",
        home / ".hermes" / "skills" / "financial-analysis" / ".env",
        Path.cwd() / ".env",
    ]
    
    results = []
    for path in config_paths:
        if path.exists():
            content = path.read_text(encoding="utf-8")
            results.append({
                "path": str(path),
                "exists": True,
                "has_ht_apikey": "HT_APIKEY" in content or "htapikey" in content.lower(),
                "content_preview": content[:100] + "..." if len(content) > 100 else content
            })
        else:
            results.append({
                "path": str(path),
                "exists": False,
                "has_ht_apikey": False,
                "content_preview": ""
            })
    
    return results


def show_status():
    """显示当前配置状态"""
    
    configs = detect_current_config()
    
    for cfg in configs:
        status = "✅ 存在" if cfg["exists"] else "❌ 不存在"
        key_status = "✅ 已配置" if cfg["has_ht_apikey"] else "⚠️ 未配置"
        
        print(f"\n{status} {cfg['path']}")
        key_status = "已配置" if cfg["has_ht_apikey"] else "未配置"
        print(f"  HT_APIKEY: {key_status}")
        if cfg["content_preview"]:
            print(f"  内容预览: {cfg['content_preview'][:80]}...")
    
    # 检查环境变量
    env_key = os.environ.get("HT_APIKEY", "")
    if env_key:
        print(f"\n环境变量 HT_APIKEY: ✅ 已设置 ({env_key[:8]}...){len(env_key)}字符")
    else:
        print(f"\n环境变量 HT_APIKEY: ❌ 未设置")
    


def create_default_config():
    """创建默认配置文件"""
    home = Path.home()
    config_dir = home / ".htsc-skills"
    config_file = config_dir / "config"
    
    # 创建目录
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建配置文件
    if not config_file.exists():
        content = """# 华泰证券金融分析配置
# 获取API Key: https://ai.zhangle.com

# 后端服务地址（默认不需要修改）
FINANCIAL_ANALYSIS_SERVICE_URL=https://ai.zhangle.com

# 认证密钥（必填）
HT_APIKEY=
"""
        config_file.write_text(content, encoding="utf-8")
        print(f"✅ 已创建配置文件: {config_file}")
    else:
        print(f"⚠️ 配置文件已存在: {config_file}")


def set_api_key(api_key: str):
    """设置API Key"""
    # 验证API Key格式
    if not validate_api_key(api_key):
        error_msg = f"API Key格式错误，应为ht_开头的44字符字符串"
        print(f"❌ {error_msg}")
        raise ValueError(error_msg)
    
    # 写入到 .htsc-skills/config
    home = Path.home()
    config_dir = home / ".htsc-skills"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config"
    
    content = f"""# 华泰证券金融分析配置
HT_APIKEY={api_key}
FINANCIAL_ANALYSIS_SERVICE_URL=https://ai.zhangle.com
"""
    config_file.write_text(content, encoding="utf-8")
    print(f"✅ API Key 已配置: {config_file}")
    
    # 同时写入 skill 目录的 .env（如果目录存在）
    skill_dir = Path(__file__).parent.parent / "financial-analysis"
    if skill_dir.exists():
        env_file = skill_dir / ".env"
        env_content = f"""# financial-analysis 环境变量
HT_APIKEY={api_key}
FINANCIAL_ANALYSIS_SERVICE_URL=https://ai.zhangle.com
"""
        safe_write_text(env_file, env_content)
        print(f"✅ 同时写入 .env: {env_file}")


def main():
    parser = argparse.ArgumentParser(description="financial-analysis API Key 配置工具")
    parser.add_argument("--status", action="store_true", help="显示当前配置状态")
    parser.add_argument("--init", action="store_true", help="初始化配置文件")
    parser.add_argument("--set", metavar="KEY", help="设置API Key")
    parser.add_argument("--prompt", action="store_true", help="交互式设置API Key")
    
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    if args.status:
        show_status()
    elif args.init:
        create_default_config()
    elif args.set:
        set_api_key(args.set)
    elif args.prompt:
        key = input("API Key: ").strip()
        if key:
            set_api_key(key)
        else:
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
