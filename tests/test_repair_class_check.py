# P-C2 对照组测试: repair_class_check (P-C4 repair_class 四态标注审计)
# 老三切片 P-C4 (commit a11d8494, 虚报 d9477868 撤回后真件), 10/24 04:3x 补对照组
# 口径: run(root) 直调 + 合成注册表变体, 断言 C1~C5 五级故障全命中
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import repair_class_check  # noqa: E402

REAL = Path(__file__).resolve().parent.parent / "scripts" / "selfheal_recipes.json"


def _reg(root: Path, recipes=None, gating=None):
    """合成注册表入合成仓"""
    d = root / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    reg = {"recipes": recipes if recipes is not None else json.loads(REAL.read_text(encoding="utf-8"))["recipes"],
           "gating": gating if gating is not None else {"auto_enable": False, "witness_rule": "R1"}}
    (d / "selfheal_recipes.json").write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    return root


def _ok_recipe(**over):
    r = {"id": "x", "kind": "git-ff", "repair_class": "fixable", "owner_slice": "code",
         "enabled": False, "dry_run_first": True, "witness": "@t refdrift 复核",
         "argv": ["git", "push", "origin", "HEAD:main"]}
    r.update(over)
    return r


def test_t1_valid_registry_pass(tmp_path):
    root = _reg(tmp_path)
    r = repair_class_check.run(str(root))
    assert r["pass"] is True, (r["p0"], r["p1"])
    assert r["detail"]["recipe_count"] >= 8


def test_t2_c1_unknown_class_p0(tmp_path):
    root = _reg(tmp_path, recipes=[_ok_recipe(repair_class="magic_class")])
    r = repair_class_check.run(str(root))
    assert any("C1" in x for x in r["p0"]), r["p0"]


def test_t3_c1_missing_class_p0(tmp_path):
    root = _reg(tmp_path, recipes=[])
    (root / "scripts" / "selfheal_recipes.json").unlink()
    r = repair_class_check.run(str(root))
    assert any("注册表缺失" in x for x in r["p0"]), r["p0"]


def test_t4_c2_quarantine_enabled_p0(tmp_path):
    root = _reg(tmp_path, recipes=[_ok_recipe(repair_class="quarantine", enabled=True)])
    r = repair_class_check.run(str(root))
    assert any("C2" in x and "quarantine" in x for x in r["p0"]), r["p0"]


def test_t5_c4_owner_out_p1(tmp_path):
    root = _reg(tmp_path, recipes=[_ok_recipe(owner_slice="nobody")])
    r = repair_class_check.run(str(root))
    assert any("C4" in x for x in r["p1"]), r["p1"]


def test_t6_c5_gate_lock_p1(tmp_path):
    root = _reg(tmp_path, recipes=[_ok_recipe(enabled=True, witness="@t")],
                gating={"auto_enable": True})
    r = repair_class_check.run(str(root))
    assert any("C5" in x for x in r["p1"]), r["p1"]


def test_t7_real_registry_green(tmp_path):
    # 真注册表当前态: 全 enabled=false + auto_enable=false → 全绿 (开闸前基线)
    root = _reg(tmp_path)
    r = repair_class_check.run(str(root))
    assert r["pass"] is True, (r["p0"], r["p1"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
