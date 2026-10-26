#!/usr/bin/env python3
"""
AOCI索引构建测试套件
测试范围：配置验证、Git跟踪一致性、安全扫描
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


# 测试状态常量
PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


class TestResult:
    """测试用例结果"""
    
    def __init__(self, name: str, status: str, message: str = ""):
        self.name = name
        self.status = status
        self.message = message
    
    def __str__(self):
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}[self.status]
        return f"{icon} {self.name}: {self.message}"


def run_command(cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    """运行命令并返回结果"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as e:
        return -1, "", str(e)


def test_gitignore_consistency() -> TestResult:
    """测试.gitignore与.aoci/.gitignore一致性"""
    project_root = Path(__file__).parent.parent
    
    # 检查根.gitignore
    gitignore_path = project_root / ".gitignore"
    aoci_gitignore_path = project_root / ".aoci" / ".gitignore"
    
    if not gitignore_path.exists():
        return TestResult("Git跟踪一致性", FAIL, ".gitignore不存在")
    
    if not aoci_gitignore_path.exists():
        return TestResult("Git跟踪一致性", FAIL, ".aoci/.gitignore不存在")
    
    # 读取内容
    gitignore_content = gitignore_path.read_text()
    aoci_gitignore_content = aoci_gitignore_path.read_text()
    
    # 检查关键规则
    checks = [
        (".aoci/", "排除.aoci目录"),
        ("! .aoci/baseline.json", "白名单baseline.json"),
        ("! .aoci/config.json", "白名单config.json"),
    ]
    
    failed = []
    for pattern, desc in checks:
        if pattern not in gitignore_content:
            failed.append(f"缺少规则: {desc} ({pattern})")
    
    if failed:
        return TestResult("Git跟踪一致性", FAIL, "; ".join(failed))
    
    # 验证git跟踪状态
    tracked_files = []
    rc, stdout, _ = run_command(["git", "ls-files", ".aoci/", "aoci.*"])
    if rc == 0:
        tracked_files = [f.strip() for f in stdout.split('\n') if f.strip()]
    
    expected_tracked = [
        ".aoci/.gitignore",
        ".aoci/baseline.json",
        ".aoci/config.json",
        "aoci.txt",
        "aoci.code.txt",
        "aoci.meta.txt"
    ]
    
    missing = [f for f in expected_tracked if f not in tracked_files]
    if missing:
        return TestResult("Git跟踪一致性", FAIL, f"未跟踪文件: {missing}")
    
    return TestResult("Git跟踪一致性", PASS, f"跟踪{len(tracked_files)}个文件")


def test_config_structure() -> TestResult:
    """测试配置结构完整性"""
    project_root = Path(__file__).parent.parent
    config_path = project_root / ".aoci" / "config.json"
    
    if not config_path.exists():
        return TestResult("配置结构验证", FAIL, "config.json不存在")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return TestResult("配置结构验证", FAIL, f"JSON解析失败: {e}")
    
    # 检查必需字段
    required_fields = ["version", "locale", "index_path", "ai"]
    missing = [f for f in required_fields if f not in config]
    if missing:
        return TestResult("配置结构验证", FAIL, f"缺少字段: {missing}")
    
    # 检查AI配置
    ai_config = config.get("ai", {})
    ai_required = ["enabled", "provider", "base_url", "model", "api_key_env"]
    ai_missing = [f for f in ai_required if f not in ai_config]
    if ai_missing:
        return TestResult("配置结构验证", FAIL, f"AI配置缺少字段: {ai_missing}")
    
    # 检查API密钥环境变量
    api_key_env = ai_config.get("api_key_env", "")
    if api_key_env and not os.environ.get(api_key_env):
        return TestResult("配置结构验证", FAIL, f"环境变量{api_key_env}未设置")
    
    return TestResult("配置结构验证", PASS, "配置结构完整")


def test_security_no_leaks() -> TestResult:
    """安全检查：无敏感信息泄露"""
    project_root = Path(__file__).parent.parent
    
    # 定义敏感模式（更精确的匹配）
    sensitive_patterns = [
        (r"cpk-[a-zA-Z0-9]{30,}", "AGES API Key"),
        (r"hermes-decuria-[a-zA-Z0-9]{20,}", "Hermes Token"),
        (r"em_[a-zA-Z0-9]{30,}", "EM API Key"),
    ]
    
    docs_dir = project_root / "mainline" / "docs"
    if not docs_dir.exists():
        return TestResult("安全扫描", SKIP, "文档目录不存在")
    
    leaks = []
    for md_file in docs_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding='utf-8')
            for pattern, desc in sensitive_patterns:
                import re
                if re.search(pattern, content):
                    leaks.append(f"{md_file.name}: 发现{desc}")
        except Exception:
            print(f"🔴 [tests\test_aoci_config.py] CR-01: except Exception:", file=sys.stderr)
    if leaks:
        return TestResult("安全扫描", FAIL, "; ".join(leaks[:3]))
    
    return TestResult("安全扫描", PASS, "未发现敏感信息泄露")


def test_index_files_exist() -> TestResult:
    """测试索引文件存在性"""
    project_root = Path(__file__).parent.parent
    
    required_files = [
        "aoci.txt",
        "aoci.code.txt",
        "aoci.meta.txt",
        ".aoci/baseline.json",
        ".aoci/config.json",
    ]
    
    missing = []
    for file_path in required_files:
        full_path = project_root / file_path
        if not full_path.exists():
            missing.append(file_path)
    
    if missing:
        return TestResult("索引文件存在性", FAIL, f"缺失文件: {missing}")
    
    # 检查aoci.code.txt是否为空（预期行为）
    code_file = project_root / "aoci.code.txt"
    if code_file.exists():
        content = code_file.read_text().strip()
        if content == "#AOCI-CODE-VOLUME: 1":
            return TestResult("索引文件存在性", PASS, "骨架文件存在，索引待构建")
    
    return TestResult("索引文件存在性", PASS, "索引文件正常")


def test_aoci_binary() -> TestResult:
    """测试AOCI二进制可用性"""
    # 查找aoci.exe
    possible_paths = [
        r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\bin\aoci.exe",
        "aoci",
    ]
    
    aoci_exe = None
    for path in possible_paths:
        if os.path.isfile(path):
            aoci_exe = path
            break
    
    if not aoci_exe:
        return TestResult("AOCI二进制", SKIP, "未找到aoci.exe")
    
    # 测试版本命令
    rc, stdout, stderr = run_command([aoci_exe, "--version"])
    if rc != 0:
        return TestResult("AOCI二进制", FAIL, f"版本命令失败: {stderr}")
    
    if "aoci version" not in stdout.lower():
        return TestResult("AOCI二进制", FAIL, f"输出格式异常: {stdout}")
    
    return TestResult("AOCI二进制", PASS, stdout.strip())


def test_baseline_integrity() -> TestResult:
    """测试基线文件完整性"""
    project_root = Path(__file__).parent.parent
    baseline_path = project_root / ".aoci" / "baseline.json"
    
    if not baseline_path.exists():
        return TestResult("基线完整性", FAIL, "baseline.json不存在")
    
    try:
        with open(baseline_path, 'r', encoding='utf-8') as f:
            baseline = json.load(f)
    except json.JSONDecodeError as e:
        return TestResult("基线完整性", FAIL, f"JSON解析失败: {e}")
    
    # 检查关键字段
    required_keys = ["version", "created_at", "updated_at", "files"]
    missing = [k for k in required_keys if k not in baseline]
    if missing:
        return TestResult("基线完整性", FAIL, f"缺少字段: {missing}")
    
    files_count = len(baseline.get("files", []))
    if files_count < 100:
        return TestResult("基线完整性", FAIL, f"文件数过少: {files_count}")
    
    return TestResult("基线完整性", PASS, f"基线包含{files_count}个文件")


def main():
    """运行所有测试"""
    tests = [
        test_aoci_binary,
        test_gitignore_consistency,
        test_config_structure,
        test_security_no_leaks,
        test_index_files_exist,
        test_baseline_integrity,
    ]
    
    results = []
    for test_fn in tests:
        try:
            result = test_fn()
            results.append(result)
        except Exception as e:
            results.append(TestResult(test_fn.__name__, FAIL, f"异常: {e}"))
    
    # 汇总报告
    print("\n" + "="*60)
    print("AOCI索引构建测试套件")
    print("="*60 + "\n")

    for result in results:
        print(result)

    # 统计
    pass_count = sum(1 for r in results if r.status == PASS)
    fail_count = sum(1 for r in results if r.status == FAIL)
    skip_count = sum(1 for r in results if r.status == SKIP)

    print(f"\n总计: {len(results)}个测试")
    print(f"通过: {pass_count}, 失败: {fail_count}, 跳过: {skip_count}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
