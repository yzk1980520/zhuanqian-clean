"""快速回测对比脚本 - 用样本数据验证权重效果"""
import sys, os, json

# 临时设置PATH使用Python312
import subprocess
result = subprocess.run(
    ['where.exe', 'python'],
    capture_output=True, text=True
)
for line in result.stdout.strip().split('\n'):
    if 'Python312' in line:
        subprocess.run([line, '-c', 'import sys; sys.path.insert(0, r"D:\\open code\\zhuanqian"); from core.pipeline.tdx_core import STRATEGIES; s=STRATEGIES["综合"]; print(f"权重已加载: max_ret5_low={s.get(\"max_ret5_low\",0)}, rsi_strong={s.get(\"rsi_strong\",0)}, chg5_gt8={s.get(\"chg5_gt8\",0)}")'],
        check=True
        )
        break
