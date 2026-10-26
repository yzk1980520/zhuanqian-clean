# -*- coding: utf-8 -*-
"""test_dl_import_degradation.py — DL预测 import 降级的根因可见性（SOUL准则9）

背景（2026-10-10 总管探针）:
  两条运行期 warning 中「dl_stock_predictor_torch模块未找到，跳过DL预测」
  的真实根因不是 import 路径（venv① 有 torch 时三种加载方式 _HAS_DL 全 True，
  路径已证伪），而是 worker②(py3.14 解释器) 缺 torch → dl_stock_predictor_torch.py:20
  顶层 `import torch` 失败 → 走 pipeline.py `except ImportError` 降级。

  旧实现把这次降级笼统打印成「模块未找到」，误导排障往"路径/模块文件缺失"上找，
  属异常吞噬埋雷（准则9：except 静默/误导 = P0）。本测试钉死：降级时必须暴露真实根因。

接缝（TDD 预先确认）: integrated_picker/pipeline.py 顶层 DL import 的 except ImportError
降级分支的可观测行为（打印文案指向真实根因，而非笼统"模块未找到"）。
"""
import os
import subprocess
import sys

# 统一用 venv① 解释器跑（记忆：worker② 缺 torch/scipy，跑 zhuanqian 测试会 ModuleNotFound）
_PY = os.path.join(os.path.expanduser("~"), ".quant-stock-picker", ".venv", "Scripts", "python.exe")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_pipeline_dl_import(code: str) -> str:
    """子进程隔离跑 pipeline 顶层 import（避免 sys.modules 污染 pytest 主进程）。"""
    env = dict(os.environ, _TEST_ROOT=_ROOT)
    r = subprocess.run([_PY, "-c", code], capture_output=True, text=True,
                       cwd=_ROOT, timeout=180, env=env)
    return (r.stdout or "") + (r.stderr or "")


def test_torch_missing_degrades_with_root_cause_not_misleading():
    """torch 不可用时: 降级必须暴露真实根因(torch/依赖)，不得误导成'模块未找到'。"""
    code = (
        "import sys, os\n"
        "sys.path.insert(0, os.environ['_TEST_ROOT'])\n"
        "sys.modules['torch'] = None  # 强令 torch 不可用(模拟 worker② 缺 torch)\n"
        "for _m in ('integrated_picker', 'integrated_picker.pipeline', 'factors.dl_stock_predictor_torch'):\n"
        "    sys.modules.pop(_m, None)\n"
        "import integrated_picker.pipeline as P\n"
        "assert P._HAS_DL is False, 'torch缺失应降级 _HAS_DL=False'\n"
    )
    out = _run_pipeline_dl_import(code)
    # GREEN 目标（当前 RED: 旧文案打"模块未找到"）:
    assert "模块未找到" not in out, (
        "准则9 误导文案仍存在(把依赖缺失报成模块缺失): " + out[-400:]
    )
    # 降级须指向真实根因 torch（而非笼统措辞）
    assert "torch" in out.lower(), (
        "降级未暴露真实根因(torch依赖缺失): " + out[-400:]
    )


def test_dl_still_active_when_torch_present():
    """对照: torch 可用时 DL 应保持激活（_HAS_DL=True），回归护栏。"""
    code = (
        "import sys, os\n"
        "sys.path.insert(0, os.environ['_TEST_ROOT'])\n"
        "import integrated_picker.pipeline as P\n"
        "assert P._HAS_DL is True, 'torch可用时DL应激活'\n"
    )
    out = _run_pipeline_dl_import(code)
    assert "未找到" not in out and "降级" not in out, (
        "torch可用不应触发DL降级: " + out[-300:]
    )
