# -*- coding: utf-8 -*-
"""risk_rules.py — S6基地化修复 (2026-10-23, 卡 t_303fc7e3) 根级透明代理shim。

原根级 risk_rules.py (TSS红线模块, 905行) 已由S6(186665b6)迁入 core/risk/risk_rules_impl.py。
S6初版shim为拷贝式(仅re-export 18个公开名), 遗留3项语义断链, 本修复升级为透明代理:
- D2: 未再导出私有名 _emit_time_stop_unknown_alert → tests/test_risk_rules.py
  TestTimeStopUnknown 6项fixture ERROR (fixture做属性patch+私有名import)。
- D3: 拷贝式shim的属性patch不回传实现模块 → 消费方monkeypatch/mock.patch语义
  与迁前 `import risk_rules` 直接指向实现体不一致 (tests fixture的
  risk_rules._emit_time_stop_unknown_alert = X 需落地到实现模块命名空间)。
- D6: 原 `python risk_rules.py` 直跑入口 (场景演示+移动止损自检双__main__块) 丢失。
本shim职责:
1. 根级 import 兼容: 全部顶层名(含下划线私有名)经代理get转发, 消费文件零改写不断链。
2. 透明代理: 属性 get/set/del 全部转发到 core.risk.risk_rules_impl。
3. `python risk_rules.py` 直接脚本入口: 经 runpy 委托实现模块的 __main__ 逻辑。
回滚点 = git revert 本修复commit。TSS重戳与契约广播见 .agent/true-source-stamp.json 待办。
"""
import os
import sys
import types
import importlib as _importlib

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_IMPL = _importlib.import_module("core.risk.risk_rules_impl")


class _ShimModule(types.ModuleType):
    """根级 risk_rules 透明代理: 未定义属性 get/set/del 转发到实现模块。"""

    def __init__(self, module_name, impl):
        types.ModuleType.__init__(self, module_name)
        object.__setattr__(self, "_impl", impl)
        object.__setattr__(self, "__file__", os.path.join(_ROOT, "risk_rules.py"))
        object.__setattr__(self, "__doc__", __doc__)

    def __getattr__(self, name):
        # PEP 562 模块级缺省属性查找 → 实现模块
        return getattr(self._impl, name)

    def __setattr__(self, name, value):
        if name.startswith("__") and name.endswith("__"):
            return types.ModuleType.__setattr__(self, name, value)
        setattr(self._impl, name, value)

    def __delattr__(self, name):
        delattr(self._impl, name)


if __name__ == "__main__":
    import runpy
    sys.modules.pop("core.risk.risk_rules_impl", None)  # shim 已预加载该模块 → 弹出后由 runpy 重执行, 消除 RuntimeWarning
    runpy.run_module("core.risk.risk_rules_impl", run_name="__main__")
else:
    # 被 import 时替换 sys.modules["risk_rules"] 为透明代理 (import 完成后外部拿到代理)
    sys.modules[__name__] = _ShimModule(__name__, _IMPL)
