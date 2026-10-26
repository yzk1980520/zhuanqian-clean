# -*- coding: utf-8 -*-
"""core package — 选股系统核心模块。由基地化 S1-S5 分步迁入。"""
import sys
from pathlib import Path
_CORE_ROOT = Path(__file__).resolve().parent.parent
if str(_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_ROOT))
