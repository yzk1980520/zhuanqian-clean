import json
import os
import sys
from pathlib import Path

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))


@pytest.fixture
def isolated_registry(tmp_path):
    """隔离的 FactorRegistry fixture — 单源真源: 只注入 registry_dir 参数

    FactorRegistry.__init__(registry_dir=REGISTRY_DIR) 的默认值是函数签名层面绑定的,
    monkeypatch.setattr(factor_registry, "REGISTRY_DIR", ...) 只改模块级变量,
    改不了签名里的默认值。所以测试必须显式传 registry_dir, 不依赖模块级常量。
    注意: 不 patch 模块级常量, 这样 TestProductionIsolation 仍可读真源路径做护栏。
    """
    import core.scoring.factor_registry as factor_registry

    # 构造隔离环境
    reg = {"factors": {"chg5": {
        "factor_id": "chg5", "name": "c", "category": "m", "description": "d",
        "direction": "positive", "ic_mean": 0.0, "icir": 0.0}}}
    (tmp_path / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
    (tmp_path / "ic_history.json").write_text(json.dumps(
        {"history": {"chg5": [0.9, 0.8]}, "last_updated": "2026-10-06T19:22:00"}),
        encoding="utf-8")

    # 单源注入: 只传 registry_dir, 不 patch 任何模块级常量
    reg_obj = factor_registry.FactorRegistry(registry_dir=str(tmp_path))
    return reg_obj, tmp_path


class TestProductionIsolation:
    """回归护栏: 2026-10-10 事故 — 旧 fixture 只 patch 模块级常量 METADATA_FILE/IC_HISTORY_FILE,
    但 FactorRegistry.__init__ 的签名默认值 registry_dir=REGISTRY_DIR 在 def 时就已绑定,
    monkeypatch 改不了签名默认值 → 实例仍指向生产 data/factor_registry/ → 测试读写生产文件,
    chg5 的 ic_mean 被测试值覆盖。本测试断言跑完注册中心操作后生产文件 mtime 不变。"""

    def test_isolated_operations_do_not_touch_production(self, isolated_registry, monkeypatch):
        import core.scoring.factor_registry as factor_registry
        prod_meta = os.path.join(factor_registry.REGISTRY_DIR, "registry.json")
        if not os.path.exists(prod_meta):
            pytest.skip("生产 registry.json 不存在, 无护栏目标")
        before = os.stat(prod_meta).st_mtime_ns

        reg, _ = isolated_registry
        reg.update_ic("chg5", 0.05)
        reg.check_gate("chg5")

        after = os.stat(prod_meta).st_mtime_ns
        assert before == after, \
            "隔离失效: 注册中心操作改动了生产 registry.json (mtime %d → %d), 必须走 registry_dir 注入" % (before, after)
