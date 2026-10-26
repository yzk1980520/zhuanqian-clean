#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py health
# -*- coding: utf-8 -*-
"""系统审查脚本 - 自动化回归测试与边界情况检查"""
import json
import subprocess
from pathlib import Path
from datetime import datetime
import sys

base = Path('D:/open code/zhuanqian')
audit_dir = base / 'output' / 'audit'

def run_command(cmd, cwd=None):
    """运行命令并返回结果"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=True,
            cwd=cwd or base
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return -1, '', str(e)

def _find_bare_except_lines(text: str) -> list:
    """返回裸 `except:` (吞所有异常, 静默吞没) 的行号列表 (0 起).
    精确匹配行 = `except:` 后仅空白/注释, 不匹配 `except Xxx:`/`except (A,B):`.
    """
    import re
    bare = re.compile(r'^\s*except\s*:\s*(#.*)?$')
    return [i for i, ln in enumerate(text.splitlines()) if bare.match(ln)]


def check_code_quality():
    """检查代码质量"""
    print('=' * 80)
    print('🔍 代码质量审查')
    print('=' * 80)
    
    issues = []
    
    # 检查静默异常吞没 (B3 附带修复: 原 L37 孤儿 except 无配对 try + cmd 未定义, 预存语法错导致
    # 本审计脚本整体不可编译。重建为纯 Python 扫描裸 `except:` — 绕开 shell 转义陷阱, 逻辑抽成
    # _find_bare_except_lines 纯函数可测。)
    print('\n【检查静默异常吞没】')
    _bare_except = []
    for _py in [p for p in base.rglob('*.py') if 'venv' not in str(p) and '.bak_' not in p.name]:
        try:
            _text = _py.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            print(f"🔴 [scripts\system_audit_checker.py] CR-01: except Exception:", file=sys.stderr)
        for _i in _find_bare_except_lines(_text):
            _ln = _text.splitlines()[_i].strip()
            _bare_except.append(f'{_py}:{_i+1}: {_ln}')
    if _bare_except:
        issues.append({'type': 'P0', 'issue': '发现静默异常吞没(裸 except:)', 'detail': '\n'.join(_bare_except)})
        print(f'  ❌ 发现 {len(_bare_except)} 处裸 except: 静默吞没')
        print('\n'.join(_bare_except))
    else:
        print('  ✅ 未发现静默异常吞没')
    
    # 检查因子权重配置
    print('\n【检查因子权重配置】')
    config_path = base / 'config.json'
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            weights = config.get('factor_weights', {})
            total = sum(weights.values())
            if abs(total - 1.0) > 0.01:
                issues.append({'type': 'P0', 'issue': f'因子权重和≠1.0: {total:.4f}', 'detail': ''})
                print(f'  ❌ 因子权重和={total:.4f}（应为1.0）')
            else:
                print(f'  ✅ 因子权重和={total:.4f}')
        except Exception as e:
            issues.append({'type': 'P0', 'issue': f'config.json解析错误: {str(e)}', 'detail': ''})
            print(f'  ❌ config.json解析错误: {e}')
    else:
        issues.append({'type': 'P0', 'issue': 'config.json不存在', 'detail': ''})
        print('  ❌ config.json不存在')
    
    return issues

def check_factor_ic():
    """检查因子IC数据"""
    print('\n' + '=' * 80)
    print('📊 因子IC数据审查')
    print('=' * 80)
    
    issues = []
    
    ic_path = base / 'data' / 'new_factor_ic_v2.json'
    if ic_path.exists():
        try:
            ic_data = json.loads(ic_path.read_text())
            print(f'\n【因子IC统计】')
            for name, data in ic_data.items():
                ic_mean = data.get('ic_mean', 0)
                ic_std = data.get('ic_std', 1)
                icir = data.get('icir', 0)
                sample_size = data.get('sample_size', 0)
                status = data.get('status', 'unknown')
                
                print(f'  {name}:')
                print(f'    IC均值: {ic_mean:+.4f}')
                print(f'    IC标准差: {ic_std:.4f}')
                print(f'    ICIR: {icir:.4f}')
                print(f'    样本量: {sample_size}')
                print(f'    状态: {status}')
                
                # 检查边界情况
                if sample_size < 30:
                    issues.append({'type': 'P1', 'issue': f'{name}样本量过小({sample_size})', 'detail': ''})
                    print(f'    ⚠️ 样本量过小(<30)')
                
                if abs(ic_mean) > 0.99:
                    issues.append({'type': 'P1', 'issue': f'{name}IC值极端({ic_mean})', 'detail': '可能过拟合'})
                    print(f'    ⚠️ IC值极端(>0.99)，可能过拟合')
                
                if icir < 0.5:
                    issues.append({'type': 'P2', 'issue': f'{name}ICIR较低({icir:.4f})', 'detail': ''})
                    print(f'    ⚠️ ICIR较低(<0.5)')
            
            # 检查有效因子数
            active_count = sum(1 for d in ic_data.values() if d.get('status') == 'active')
            print(f'\n【有效因子统计】')
            print(f'  活跃因子数: {active_count}/{len(ic_data)}')
            if active_count < 2:
                issues.append({'type': 'P0', 'issue': '有效因子数<2', 'detail': f'当前{active_count}个'})
                print(f'  ❌ 有效因子数不足(<2)')
            else:
                print(f'  ✅ 有效因子数充足(≥2)')
                
        except Exception as e:
            issues.append({'type': 'P0', 'issue': f'new_factor_ic_v2.json解析错误: {str(e)}', 'detail': ''})
            print(f'  ❌ 解析错误: {e}')
    else:
        issues.append({'type': 'P0', 'issue': 'new_factor_ic_v2.json不存在', 'detail': ''})
        print('  ❌ new_factor_ic_v2.json不存在')
    
    return issues

def check_gate_status():
    """检查闸门状态"""
    print('\n' + '=' * 80)
    print('🚪 闸门状态审查')
    print('=' * 80)
    
    issues = []
    
    sh_path = base / 'data' / 'sh_index.json'
    if sh_path.exists():
        try:
            sh_data = json.loads(sh_path.read_text())
            close = sh_data.get('close', 0)
            ma250 = sh_data.get('ma250', 0)
            gap = (close / ma250 - 1) * 100 if ma250 > 0 else 0
            
            print(f'\n【闸门状态】')
            print(f'  上证指数: {close:.2f}')
            print(f'  MA250: {ma250:.2f}')
            print(f'  差距: {gap:+.2f}%')
            
            if close > ma250:
                print(f'  状态: ✅ 门开')
            else:
                print(f'  状态: ❌ 门关')
                issues.append({'type': 'P1', 'issue': '闸1门关', 'detail': f'差{gap:+.2f}%'})
            
            # 检查边界情况：恰好等于MA250
            if abs(close - ma250) < 0.01:
                issues.append({'type': 'P0', 'issue': 'sh恰好等于ma250，浮点精度问题', 'detail': ''})
                print(f'  ⚠️ sh恰好等于ma250，需检查浮点精度')
                
        except Exception as e:
            issues.append({'type': 'P0', 'issue': f'sh_index.json解析错误: {str(e)}', 'detail': ''})
            print(f'  ❌ 解析错误: {e}')
    else:
        issues.append({'type': 'P0', 'issue': 'sh_index.json不存在', 'detail': ''})
        print('  ❌ sh_index.json不存在')
    
    return issues

def check_review_status():
    """检查审批状态"""
    print('\n' + '=' * 80)
    print('📝 审批状态审查')
    print('=' * 80)
    
    issues = []
    
    review_path = base / 'data' / 'review_status.json'
    if review_path.exists():
        try:
            review_data = json.loads(review_path.read_text())
            approved = review_data.get('laowu_approved', False)
            
            print(f'\n【审批状态】')
            print(f'  laowu_approved: {approved}')
            
            if not approved:
                print(f'  状态: 🔴 冻结')
                issues.append({'type': 'P1', 'issue': '闸2冻结', 'detail': 'laowu_approved=False'})
            else:
                print(f'  状态: ✅ 已批准')
            
            # 检查状态矛盾 (B3: 顶层 laowu_approved vs final_verdict 一致性; 替代嵌套死读 laowu.approved
            # — 嵌套 laowu 非 dict, 永 None, 旧矛盾检测形同虚设/假绿)
            final_verdict = review_data.get('final_verdict')
            if final_verdict is not None:
                fv_pass = (str(final_verdict).strip().upper() == "PASS") or (final_verdict is True)
                if fv_pass != approved:
                    issues.append({'type': 'P0', 'issue': '审批状态矛盾',
                                   'detail': f'laowu_approved={approved} vs final_verdict={final_verdict}'})
                    print(f'  ❌ 审批状态矛盾: laowu_approved={approved} vs final_verdict={final_verdict}')
                else:
                    print(f'  ✅ 审批状态一致 (laowu_approved={approved}, final_verdict={final_verdict})')
            else:
                print(f'  ✅ 审批状态 (无 final_verdict 字段, laowu_approved={approved})')
                
        except Exception as e:
            issues.append({'type': 'P0', 'issue': f'review_status.json解析错误: {str(e)}', 'detail': ''})
            print(f'  ❌ 解析错误: {e}')
    else:
        issues.append({'type': 'P0', 'issue': 'review_status.json不存在', 'detail': ''})
        print('  ❌ review_status.json不存在')
    
    return issues

def check_test_coverage():
    """检查测试覆盖率"""
    print('\n' + '=' * 80)
    print('🧪 测试覆盖率审查')
    print('=' * 80)
    
    issues = []
    
    # 检查test目录
    test_dir = base / 'tests'
    if test_dir.exists():
        test_files = list(test_dir.glob('*.py'))
        print(f'\n【测试文件】')
        print(f'  测试文件数: {len(test_files)}')
        
        if len(test_files) < 5:
            issues.append({'type': 'P1', 'issue': '测试文件数不足(<5)', 'detail': f'当前{len(test_files)}个'})
            print(f'  ⚠️ 测试文件数不足')
        else:
            print(f'  ✅ 测试文件数充足')
    else:
        issues.append({'type': 'P1', 'issue': 'tests目录不存在', 'detail': ''})
        print('  ❌ tests目录不存在')
    
    # 检查关键测试用例
    critical_tests = [
        'test_s3_ladder_config.py',
        'test_factor_ic.py',
        'test_gate_mechanism.py'
    ]
    
    print(f'\n【关键测试用例】')
    for test in critical_tests:
        test_path = test_dir / test if test_dir.exists() else base / test
        if test_path.exists():
            print(f'  ✅ {test}')
        else:
            print(f'  ❌ {test} 缺失')
            issues.append({'type': 'P1', 'issue': f'关键测试用例缺失: {test}', 'detail': ''})
    
    return issues

def main():
    """主函数"""
    print('=' * 80)
    print('🔍 御龙决系统审查 - 自动化回归测试')
    print(f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 80)
    print()
    
    all_issues = []
    
    # 执行各项检查
    all_issues.extend(check_code_quality())
    all_issues.extend(check_factor_ic())
    all_issues.extend(check_gate_status())
    all_issues.extend(check_review_status())
    all_issues.extend(check_test_coverage())
    
    # 汇总结果
    print('\n' + '=' * 80)
    print('📊 审查结果汇总')
    print('=' * 80)
    
    p0_issues = [i for i in all_issues if i['type'] == 'P0']
    p1_issues = [i for i in all_issues if i['type'] == 'P1']
    p2_issues = [i for i in all_issues if i['type'] == 'P2']
    
    print(f'\n【问题统计】')
    print(f'  P0（紧急）: {len(p0_issues)}个')
    print(f'  P1（重要）: {len(p1_issues)}个')
    print(f'  P2（优化）: {len(p2_issues)}个')
    
    if p0_issues:
        print(f'\n【P0问题详情】')
        for issue in p0_issues:
            print(f'  ❌ {issue["issue"]}')
            if issue['detail']:
                print(f'     详情: {issue["detail"]}')
    
    if p1_issues:
        print(f'\n【P1问题详情】')
        for issue in p1_issues:
            print(f'  ⚠️ {issue["issue"]}')
            if issue['detail']:
                print(f'     详情: {issue["detail"]}')
    
    # 保存结果
    audit_result = {
        'timestamp': datetime.now().isoformat(),
        'total_issues': len(all_issues),
        'p0_count': len(p0_issues),
        'p1_count': len(p1_issues),
        'p2_count': len(p2_issues),
        'issues': all_issues
    }
    
    result_path = audit_dir / 'system_audit_result_20261006.json'
    result_path.write_text(json.dumps(audit_result, indent=2, ensure_ascii=False))
    print(f'\n✅ 审查结果已保存: {result_path}')
    
    # 返回退出码
    return 1 if p0_issues else 0

if __name__ == '__main__':
    sys.exit(main())
