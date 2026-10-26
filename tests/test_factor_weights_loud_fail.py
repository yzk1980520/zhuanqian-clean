#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_factor_weights_loud_fail.py — get_factor_weights() loud-fail 契约行为级测试

背景 (10-20 回滚事故审查认定的高危缺口):
  config_loader.get_factor_weights() (T2a 单源落地, 提交 3ddac836) 的契约是
  「配置异常 -> loud fail (RuntimeError), 禁止静默回退 config.json 默认权重」
  (函数 docstring + SOUL#9 + 任务单红线)。但既有测试对"静默回退"不敏感 ——
  若有人后来把 raise 改回 return 默认值, 既有测试仍会绿。本文件专补该检测能力:
  全部异常变体断言 pytest.raises(RuntimeError), 任一回退逻辑复活即红。

  降级自证 (2026-10-21 已完成): 把 5 处 raise RuntimeError 替换为 return 静默
  回退值后, 本文件 7 条异常变体用例全部转红; 恢复后全绿 (原始输出见交付报告)。
  2026-10-21 第二轮 (闭合 FINDING-1): 把 get_factor_weights() 的严格类型判定临时
  改回 float(v) 强转, test_quoted_numeric_string_loud_fails 与
  test_bool_weights_loud_fail 两条转红 (证明其对强转有检测力), 其余用例不受影响;
  恢复后全绿 (原始输出见交付报告)。
  本仓库铁律: 不能只跑绿, 要证明测试有检测能力。

实现要点:
  - get_factor_weights() 读模块级 PROJECT/factor_weights.json,
    经 monkeypatch 把 config_loader.PROJECT 注入 tempfile 临时目录,
    严禁碰生产 config.json / data/ / factor_weights.json。
  - 函数有进程内缓存 (_FACTOR_WEIGHTS_CACHE), 每条用例前后 clear_config_cache()。
  - 含正向对照 + 生产真源两条用例, 排除"注入失效导致恒绿"的假阳性。
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import config_loader


@pytest.fixture
def isolated_project(monkeypatch):
    """把因子权重真源路径隔离到 tempfile 临时目录 (不碰生产 factor_weights.json)。"""
    with tempfile.TemporaryDirectory(prefix="factor_weights_loudfail_") as td:
        monkeypatch.setattr(config_loader, "PROJECT", td)
        config_loader.clear_config_cache()  # 清进程内缓存, 否则读到上一次调用的结果
        yield Path(td)
        config_loader.clear_config_cache()


def _write_weights_doc(tmp_path, doc):
    (tmp_path / "factor_weights.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class TestLoudFailContract:
    """T2a loud-fail 契约: 配置异常必须抛 RuntimeError, 不得静默回退。"""

    def test_missing_file_loud_fails(self, isolated_project):
        """变体1: factor_weights.json 缺失 -> RuntimeError (禁止回退 config.json 默认权重)"""
        assert not (isolated_project / "factor_weights.json").exists()  # 前置: 确认文件真不在
        with pytest.raises(RuntimeError, match="Loud fail"):
            config_loader.get_factor_weights()
        # 失败后缓存不得被污染 (否则同进程后续调用会拿到坏状态)
        assert config_loader._FACTOR_WEIGHTS_CACHE is None

    def test_corrupted_json_loud_fails(self, isolated_project):
        """变体2: JSON 损坏 (非法语法) -> RuntimeError"""
        (isolated_project / "factor_weights.json").write_text(
            "{ this is not valid json ,,", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Loud fail"):
            config_loader.get_factor_weights()
        assert config_loader._FACTOR_WEIGHTS_CACHE is None

    def test_toplevel_not_object_loud_fails(self, isolated_project):
        """变体2b: JSON 合法但顶层不是对象 (数组) -> RuntimeError (结构非法同须 loud fail)"""
        (isolated_project / "factor_weights.json").write_text(
            json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(RuntimeError, match="Loud fail"):
            config_loader.get_factor_weights()
        assert config_loader._FACTOR_WEIGHTS_CACHE is None

    @pytest.mark.parametrize("bad_weights", [{}, []], ids=["empty_dict", "empty_list"])
    def test_empty_weights_loud_fails(self, isolated_project, bad_weights):
        """变体3: weights 段为空 (空 dict / 空 list) -> RuntimeError"""
        _write_weights_doc(isolated_project, {"version": "2.6", "weights": bad_weights})
        with pytest.raises(RuntimeError, match="Loud fail"):
            config_loader.get_factor_weights()
        assert config_loader._FACTOR_WEIGHTS_CACHE is None

    @pytest.mark.parametrize("bad_value", [None, "abc"], ids=["none_value", "non_numeric_str"])
    def test_non_numeric_weights_loud_fail(self, isolated_project, bad_value):
        """变体4: 权重含非数值 (None / 不可解析字符串) -> RuntimeError

        数值字符串 ("0.5") 与 bool 的拒绝见 test_quoted_numeric_string_loud_fails /
        test_bool_weights_loud_fail (2026-10-21 闭合 FINDING-1: 旧实现 float(v) 强转
        会静默放过二者, 与 docstring 承诺的"非数值 loud fail"相反)。
        """
        _write_weights_doc(isolated_project,
                           {"version": "2.6", "weights": {"lower_shadow": bad_value}})
        with pytest.raises(RuntimeError, match="Loud fail"):
            config_loader.get_factor_weights()
        assert config_loader._FACTOR_WEIGHTS_CACHE is None

    def test_quoted_numeric_string_loud_fails(self, isolated_project):
        """变体4b: 数值字符串 ("0.5") -> RuntimeError

        2026-10-21 闭合 FINDING-1 口径缝隙: docstring 承诺"非数值 -> loud fail",
        但旧实现以 float(v) 强转校验, float("0.5") 成功 -> 数值字符串被静默放行
        (配置里一个引号即可改变权重真源语义)。数值字符串属"非数值", 必须拒绝。
        """
        _write_weights_doc(isolated_project,
                           {"version": "2.6", "weights": {"a": "0.5"}})
        with pytest.raises(RuntimeError, match="Loud fail"):
            config_loader.get_factor_weights()
        assert config_loader._FACTOR_WEIGHTS_CACHE is None

    def test_bool_weights_loud_fail(self, isolated_project):
        """变体4c: bool (True/False) -> RuntimeError

        易错点: isinstance(True, int) 为 True 且 float(True)==1.0 —— 旧实现下 bool
        会被静默当成 1.0/0.0 放行。严格校验必须显式排除 bool。
        """
        _write_weights_doc(isolated_project,
                           {"version": "2.6", "weights": {"a": True, "b": False}})
        with pytest.raises(RuntimeError, match="Loud fail"):
            config_loader.get_factor_weights()
        assert config_loader._FACTOR_WEIGHTS_CACHE is None


class TestPositiveControl:
    """正向对照: 合法输入必须正常返回 —— 排除"注入失效导致恒绿"的假阳性。"""

    def test_valid_weights_returned_as_floats(self, isolated_project):
        """合法权重 -> 返回 float 权重字典 (证明注入链路真的通, 不是恒红)"""
        _write_weights_doc(isolated_project,
                           {"version": "2.6-test", "weights": {"a": 0.5, "b": 2}})
        weights = config_loader.get_factor_weights()
        assert weights == {"a": 0.5, "b": 2.0}
        assert all(isinstance(v, float) for v in weights.values())

    def test_production_truth_source_loads(self):
        """生产真源 (仓库根 factor_weights.json) 可加载且非全零 —— T2a 单源的基本盘。

        不注入临时目录, 直读真实文件; 本条红 = 单源本身缺失/损坏/全零。
        (降级自证运行时会在临时目录预置真实 factor_weights.json 副本。)
        """
        config_loader.clear_config_cache()  # 防跨用例缓存污染读到旧值
        try:
            weights = config_loader.get_factor_weights()
            assert isinstance(weights, dict) and weights, "生产 factor_weights.json 权重为空"
            assert all(isinstance(v, float) for v in weights.values()), "存在非 float 权重"
            assert any(v > 0 for v in weights.values()), "生产权重全为 0 (真源实质失效)"
        finally:
            config_loader.clear_config_cache()
