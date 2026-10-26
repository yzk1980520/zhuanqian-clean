#!/usr/bin/env python3
"""
AtomCode Bridge - Hermes集成适配器
用于调用AtomCode CLI进行代码分析和重构
"""

import subprocess
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import sys

# 导入公共模块
from common import (
    find_atomcode,
    DEFAULT_TIMEOUT,
    COMPLEX_ANALYSIS_TIMEOUT,
    logger
)

# 跨平台查找AtomCode路径（2026-10-15 总管: 缺席时不再 import 期 sys.exit(1) —
# import 期退出会随 pytest 收集测试文件而炸掉整个 CI(INTERNALERROR exit 3), 改推迟到调用期）
ATOMCODE_PATH = find_atomcode()
if not ATOMCODE_PATH:
    logger.error("AtomCode未找到，请先安装: npm install -g @atomcode/cli")
else:
    logger.info(f"使用AtomCode路径: {ATOMCODE_PATH}")
DEFAULT_MODEL = "agnes-2.5-flash"

def run_atomcode(
    prompt: str,
    cwd: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    no_tools: bool = False,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    调用AtomCode CLI执行分析任务
    
    Args:
        prompt: 分析提示
        cwd: 工作目录
        model: 模型名称（覆盖配置）
        provider: Provider名称（覆盖配置）
        timeout: 超时时间（秒）
        no_tools: 是否禁用工具（只输出文本）
        verbose: 是否输出详细信息
    
    Returns:
        包含stdout、stderr、returncode、provider、model的字典
    """
    # 2026-10-15 总管: 调用期校验 — ATOMCODE_PATH 缺席时显式抛 RuntimeError
    # (原 import 期 sys.exit(1) 的语义, 不再污染 import 语义, CI 可安全收集)
    if not ATOMCODE_PATH:
        raise RuntimeError("AtomCode未找到，请先安装: npm install -g @atomcode/cli")
    cmd = [ATOMCODE_PATH]
    
    # 添加参数
    cmd.extend(["-p", prompt])
    if cwd:
        cmd.extend(["-C", cwd])
    if model:
        cmd.extend(["--model", model])
    if provider:
        cmd.extend(["--provider", provider])
    if no_tools:
        cmd.append("--no-tools")
    cmd.append("--no-telemetry")
    cmd.extend(["--output-format", "jsonl"])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd
        )
        
        # 解析JSONL输出
        response = {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr[:500] if result.stderr else "",
            "provider": None,
            "model": None,
            "tokens": None
        }
        
        # 解析第一行获取元信息
        for line in result.stdout.split('\n')[:10]:
            line = line.strip()
            if not line.startswith('{'):
                continue
            
            try:
                data = json.loads(line)
                if data.get('type') == 'run.started':
                    response['provider'] = data.get('provider')
                    response['model'] = data.get('model')
                    logger.info(f"Provider: {response['provider']}, Model: {response['model']}")
                elif data.get('type') == 'usage':
                    response['tokens'] = {
                        'prompt': data.get('prompt_tokens'),
                        'completion': data.get('completion_tokens'),
                        'elapsed_ms': data.get('elapsed_ms')
                    }
            except json.JSONDecodeError as e:
                logger.warning(f"JSON解析警告: {e}")
        
        # 提取最终回复
        lines = result.stdout.strip().split('\n')
        for line in reversed(lines):
            if '"type":"assistant.message"' in line or '"type": "assistant.message"' in line:
                try:
                    data = json.loads(line)
                    content = data.get('message', {}).get('content', [])
                    for item in content:
                        if item.get('type') == 'text':
                            response['content'] = item.get('text', '')
                            logger.debug(f"提取到回复内容，长度: {len(response['content'])}")
                            break
                except json.JSONDecodeError as e:
                    logger.warning(f"解析assistant.message失败: {e}")
                break
        
        return response
        
    except subprocess.TimeoutExpired:
        logger.error(f"AtomCode执行超时 ({timeout}s)")
        return {
            "success": False,
            "returncode": -1,
            "error": f"Timeout after {timeout}s",
            "provider": None,
            "model": None
        }
    except FileNotFoundError as e:
        logger.error(f"AtomCode可执行文件未找到: {e}")
        return {
            "success": False,
            "returncode": -1,
            "error": f"AtomCode not found: {e}",
            "provider": None,
            "model": None
        }
    except Exception as e:
        logger.error(f"AtomCode执行异常: {type(e).__name__}: {e}")
        return {
            "success": False,
            "returncode": -1,
            "error": f"{type(e).__name__}: {str(e)}",
            "provider": None,
            "model": None
        }


def analyze_code(project_dir: str, query: str, **kwargs) -> str:
    """
    分析代码库并返回结果

    Args:
        project_dir: 项目目录
        query: 分析查询
        **kwargs: 其他参数传递给 run_atomcode

    Returns:
        分析结果字符串
    """
    if not project_dir:
        raise ValueError("project_dir不能为空")
    if not query:
        raise ValueError("query不能为空")

    prompt = f"""分析项目: {project_dir}

查询: {query}

请提供：
1. 核心问题诊断
2. 具体代码位置（文件:行号）
3. 改进建议（如适用）"""
    
    response = run_atomcode(prompt, cwd=project_dir, **kwargs)
    
    if response['success']:
        return json.dumps(response, ensure_ascii=False, indent=2)
    else:
        return f"错误: {response.get('error', '未知错误')}"


def main():
    """命令行接口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='AtomCode Bridge')
    parser.add_argument('-p', '--prompt', help='分析提示')
    parser.add_argument('-C', '--cwd', help='工作目录')
    parser.add_argument('--model', help='模型名称')
    parser.add_argument('--provider', help='Provider名称')
    parser.add_argument('--no-tools', action='store_true', help='禁用工具')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT, help='超时时间')
    parser.add_argument('--json', action='store_true', help='输出JSON格式')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    
    args = parser.parse_args()
    
    if args.prompt:
        response = run_atomcode(
            args.prompt,
            cwd=args.cwd,
            model=args.model,
            provider=args.provider,
            timeout=args.timeout,
            no_tools=args.no_tools
        )
        
        if args.json:
            # 2026-10-15 总管修: --json 分支原为 no-op(pass), 评审输出被静默吞掉
            # (R5/R6 假死根因); 现输出完整 response JSON 供落盘/审计
            print(json.dumps(response, ensure_ascii=False, indent=2))
        else:
            if response['success']:
                print(f"Provider: {response.get('provider', 'N/A')}")
                print(f"Model: {response.get('model', 'N/A')}")
                print(f"Tokens: {response.get('tokens', 'N/A')}")
            else:
                print(f"❌ 失败: {response.get('error', '未知错误')}")
                sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
