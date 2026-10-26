#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes配置优化脚本
自动诊断并优化配置问题
"""

import json
import os
import subprocess
import sys
from pathlib import Path

def check_env_vars():
    """检查环境变量配置"""
    env_file = Path.home() / ".hermes" / ".env"
    required = ["DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "ZAI_API_KEY"]
    
    results = {}
    if env_file.exists():
        with open(env_file, 'r') as f:
            content = f.read()
        for key in required:
            results[key] = key in content and "null" not in content
    return results

def check_profiles():
    """检查Profile配置"""
    profiles_dir = Path.home() / ".hermes" / "profiles"
    results = {}
    
    for profile_name in ["opencode", "atomcode", "niuma"]:
        profile_dir = profiles_dir / profile_name
        config_file = profile_dir / "config.yaml"
        if config_file.exists():
            results[profile_name] = "configured"
        else:
            results[profile_name] = "missing"
    return results

def check_fallback_chain():
    """检查fallback配置"""
    main_config = Path.home() / ".hermes" / "config.yaml"
    if main_config.exists():
        with open(main_config, 'r') as f:
            content = f.read()
        return "fallback_providers" in content
    return False

def generate_optimized_config():
    """生成优化后的主配置文件"""
    return """# Hermes 主配置 - 优化版
model:
  provider: agnes
  default: agnes-2.5-flash
  api_key: ${AGNES_API_KEY}
  base_url: https://apihub.agnes-ai.com/v1
  api_mode: chat_completions
  transport: openai_chat
  temperature: 0.3
  max_tokens: 8192

providers:
  deepseek:
    name: DeepSeek
    base_url: https://api.deepseek.com
    api_mode: chat_completions
    transport: openai_chat
    model: deepseek-v4-flash
    api_key: ${DEEPSEEK_API_KEY}
  zai:
    name: 智谱 GLM
    base_url: https://open.bigmodel.cn/api/paas/v4
    api_mode: chat_completions
    transport: openai_chat
    model: glm-4.7-flash
    api_key: ${ZAI_API_KEY}
  openrouter:
    name: OpenRouter
    base_url: https://openrouter.ai/api/v1
    api_mode: chat_completions
    transport: openai_chat
    model: google/gemma-4-31b-it:free
    api_key_env: OPENROUTER_API_KEY

# 优化fallback链
fallback_providers:
  - provider: deepseek
    model: deepseek-v4-flash
  - provider: zai
    model: glm-4.7-flash
  - provider: openrouter
    model: google/gemma-4-31b-it:free

# 团队角色模型分配
team_models:
  总管:
    primary: agnes-2.5-flash
    fallback: deepseek-v4-flash
  老三:
    primary: deepseek-v4-flash
    fallback: glm-4.7-flash
  老五:
    primary: glm-4.7-flash
    fallback: openrouter/google/gemma-4-31b-it:free
  牛马:
    primary: openrouter/google/gemma-4-31b-it:free
    fallback: deepseek-v4-flash

display:
  interface: tui
  language: zh
  skin: default
  tool_progress: minimal

agent:
  max_turns: 100
  tool_use_enforcement: true

compression:
  enabled: true
  threshold: 0.3
  target_ratio: 0.15

memory:
  memory_enabled: true
  user_profile_enabled: true
  provider: builtin

security:
  redact_secrets: true
  tirith_enabled: false

approvals:
  mode: smart

platforms:
  weixin:
    enabled: true
"""

def main():
    
    # 1. 检查环境变量
    env_status = check_env_vars()
    for key, present in env_status.items():
        status = "✅" if present else "❌"
        print(f"  {status} {key}")
    
    # 2. 检查Profiles
    profile_status = check_profiles()
    for name, status in profile_status.items():
        icon = "✅" if status == "configured" else "❌"
        print(f"  {icon} {name}: {status}")
    
    # 3. 检查fallback
    has_fallback = check_fallback_chain()
    print(f"  {'✅' if has_fallback else '❌'} fallback_providers配置")
    
    # 4. 优化建议
    if not env_status.get("ZAI_API_KEY"):
        pass
    if not env_status.get("OPENROUTER_API_KEY"):
        pass
    
    # 保存优化配置
    config_path = Path(__file__).parent.parent / "docs" / "optimized_hermes_config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(generate_optimized_config())
    
    print(f"✅ 配置已保存到: {config_path}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
