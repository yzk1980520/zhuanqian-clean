# -*- coding: utf-8 -*-
"""R3 TDD: factor_registry 唯一真源(根版)钉死断言

K45 终审放行 R3: 归档 scripts/factor_registry.py(D2 安全流程)。
归档前本测试为 RED(影子存在), 归档后 GREEN(唯一源)。

Seam(公共行为, 非实现细节):
  S1: 无影子 — scripts/factor_registry.py 不得存在
  S2: 双 path(scripts+root, 日监控/计算脚本真实执行序) import 必解析根版
  S3: scripts-only path 下 import 必须 ModuleNotFoundError(唯一源性质)
  S4: 根版保留全部消费方所需 API(R3b 兼容守卫: register/update_ic/FactorMetadata/get_registry/register_factor)
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SHADOW = os.path.join(SCRIPTS, "factor_registry.py")
PY = sys.executable  # 测试解释器本身(vpython), 子进程同款 → 解释器一致


def _run(code: str, cwd: str = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, "-c", code], capture_output=True, text=True, timeout=120, cwd=cwd
    )


def test_s1_no_shadow_file():
    """S1: 影子文件必须已归档"""
    assert not os.path.exists(SHADOW), (
        f"R3 未完成: 影子 scripts/factor_registry.py 仍存在 → {SHADOW}\n"
        "归档动作: cp 到 .trash/<ts>/ + md5 断言 + rm(见 CHANGELOG R3 条目)"
    )


def test_s2_double_path_import_resolves_root():
    """S2: 双 path(scripts 在前, root 在后 — 日监控 L35-36 真实执行序) 必解析根版

    证据锚点: r0_probe.py 实跑输出 resolved=D:\\open code\\zhuanqian\\factor_registry.py
    """
    code = (
        "import sys; _base = [p for p in sys.path if 'zhuanqian' not in p or 'site-packages' in p];"
        "sys.path[:] = ["
        f"{SCRIPTS!r}, {ROOT!r}]"
        " + _base;"
        "import core.scoring.factor_registry as fr; print(fr.__file__)"
    )
    r = _run(code)
    assert r.returncode == 0, f"双 path import 失败: {r.stderr[-400:]}"
    out = r.stdout.strip().replace("\\", "/")
    assert "/scripts/" not in out, f"双 path 仍命中 scripts 影子版: {out}"
    assert out.endswith("/factor_registry.py"), out


def test_s3_scripts_only_import_absent():
    """S3: scripts-only path 下 import 必失败(唯一源性质 — 影子彻底消除)"""
    code = (
        "import sys; _base = [p for p in sys.path if 'zhuanqian' not in p];"
        "sys.path[:] = ["
        f"{SCRIPTS!r}]"
        " + _base;"
        "import core.scoring.factor_registry as fr; print(fr.__file__)"
    )
    r = _run(code, cwd=SCRIPTS)
    assert r.returncode != 0, (
        f"scripts-only path 仍能 import core.scoring.factor_registry → 影子未清: {r.stdout}{r.stderr[-200:]}"
    )
    assert "ModuleNotFoundError" in (r.stderr or ""), (
        f"非 ModuleNotFoundError 的失败另有隐情: {r.stderr[-400:]}"
    )


def test_s4_root_module_consumer_api():
    """S4: 根版保留全部热消费方 API(R3b 清单逐一对应, 归档不得伤及)"""
    code = (
        "import sys; sys.path.insert(0, "
        f"{ROOT!r});"
        "import core.scoring.factor_registry as fr;"
        "assert hasattr(fr, 'FactorMetadata'), '缺 FactorMetadata(compute_rep/test 消费)';"
        "assert hasattr(fr, 'get_registry') and hasattr(fr, 'register_factor'), '缺便捷入口';"
        "need = [m for m in ('register', 'update_ic', 'get', 'list_factors', 'check_gate') if hasattr(fr.FactorRegistry, m)];"
        "assert len(need) == 5, '根版 FactorRegistry 缺消费方法: %s' % need;"
        "print('OK')"
    )
    r = _run(code)
    assert r.returncode == 0 and r.stdout.strip() == "OK", (
        f"根版消费方 API 不完整: {r.stderr[-400:]}"
    )
