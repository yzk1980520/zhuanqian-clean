# -*- coding: utf-8 -*-
"""test_live_filter_guards.py -- 实盘选股池过滤器的回归断言

背景(2026-10-19 L3 P0-A):
  scripts/auto_live_pipeline.py 调用 is_tradable_code(code) 时【不传 name】,
  而 tdx_data.is_tradable_code 的 ST/退市段是 `if name and is_st_stock(name)`,
  name 恒空 ⇒ 整段静默跳过 ⇒ 195 只 ST/退市股全部进入评分
  (实测 ST人福 99 分排第 1)。已修: :405 改为
  `is_tradable_code(code, name_cache.get(code, ""))`。

方法学铁律(2026-10-18): 「过滤器/校验存在但静默不生效, 系统上报一切正常」
  是本项目头号病史, 已 5 次。⇒ 每个过滤器必须有一条回归断言。
本文件即实盘选股池三条排除规则的断言:
  1. 板块: 创业板/科创板/北证 一律挡(D6 老大 2026-10-18 拍板)
  2. ST/*ST: 挡
  3. 含"退"(退市整理期/已退): 挡
外加一条「不传 name 就会漏」的反向断言 —— 这正是 P0-A 的失效模式,
  若有人再把 name 参数去掉, 这条会立刻红。
"""
import os
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from tdx_data import is_tradable_code, is_st_stock, should_include  # noqa: E402


# ------------------------------------------------------- 1. 板块白名单 (D6)
BLOCKED_BOARDS = [
    ("sz300001", "创业板"),
    ("sz300750", "创业板"),
    ("sh688001", "科创板"),
    ("sh688981", "科创板"),
    ("bj430047", "北证"),
    ("sh510300", "ETF(sh51)"),
    ("sh588000", "ETF(sh58)"),
    ("sz159915", "ETF(sz15)"),
]

ALLOWED_BOARDS = [
    "sh600519", "sh601398", "sh603288", "sh605588",
    "sz000001", "sz001979", "sz002594", "sz003816",
]


@pytest.mark.parametrize("code,label", BLOCKED_BOARDS)
def test_board_blocked(code, label):
    """D6 老大拍板: 创业板/科创板/北证/ETF 一律挡(不看 name 也应挡)。"""
    assert should_include(code) is False, "%s(%s) 板块白名单应挡" % (code, label)
    assert is_tradable_code(code) is False, "%s(%s) 不传 name 也应被挡" % (code, label)
    assert is_tradable_code(code, "某某股份") is False, \
        "%s(%s) 传了正常 name 仍应被挡" % (code, label)


@pytest.mark.parametrize("code", ALLOWED_BOARDS)
def test_board_allowed(code):
    """沪深主板 60/00/01/02/03 应放行(正常名称)。"""
    assert should_include(code) is True, "%s 主板应放行" % code
    assert is_tradable_code(code, "某某股份") is True, "%s 主板正常名应放行" % code


# ------------------------------------------------------------ 2/3. ST 与退
ST_NAMES = ["ST人福", "*ST海航", "ST康美", "*ST众泰"]
DELIST_NAMES = ["某某退", "长航油运退", "退市锐电", "某某退市"]


@pytest.mark.parametrize("name", ST_NAMES)
def test_st_blocked(name):
    """ST/*ST 必须挡。"""
    assert is_st_stock(name) is True, "%s 应判为 ST" % name
    assert is_tradable_code("sh600079", name) is False, "ST(%s) 应被挡" % name


@pytest.mark.parametrize("name", DELIST_NAMES)
def test_delisting_blocked(name):
    """含'退'(退市整理期/已退)必须挡。"""
    assert is_st_stock(name) is True, "%s 应判为退市" % name
    assert is_tradable_code("sz000001", name) is False, "退市(%s) 应被挡" % name


# ------------------------------------------- 4. P0-A 失效模式的反向断言(核心)
def test_missing_name_would_leak_st():
    """P0-A 失效模式的栅栏: 不传 name 时 ST 会漏进来。

    这条断言不是"期望行为", 而是把失效模式钉死:
      如果不传 name ⇒ is_tradable_code 返回 True(漏)
      如果传了 name  ⇒ 返回 False(挡)
    将来若有人把 :405 的 name 参数去掉, 生产会漏, 但本条仍绿 ——
    所以真正的护栏是下一跳: 生产调用点必须传 name(见下条断言)。
    """
    assert is_tradable_code("sh600079", "ST人福") is False, "传 name 必须挡住 ST"
    # 记录失效模式: 不传 name 则漏(这正是 2026-10-19 的 P0 现场)
    assert is_tradable_code("sh600079") is True, \
        "不传 name 时 ST 会漏 —— 这是已知失效模式; 若此行变红说明逻辑已改, 需同步复核生产调用点"


def test_prod_call_site_passes_name():
    """生产调用点必须传 name(源码级断言, 防 P0-A 复发)。

    2026-10-19 P0-A: scripts/auto_live_pipeline.py 调 is_tradable_code(code)
    不传 name ⇒ ST/退市 195 只全进评分。已修为传 name_cache.get(code, "")。
    本断言直接读源码, 若将来有人改回单参调用, 立刻红。
    """
    path = os.path.join(PROJECT, "scripts", "auto_live_pipeline.py")
    assert os.path.exists(path), "找不到 scripts/auto_live_pipeline.py"
    src = open(path, encoding="utf-8").read()
    assert "is_tradable_code(code, name_cache.get(" in src, \
        "生产调用点没传 name — P0-A 复发风险: 应形如 is_tradable_code(code, name_cache.get(code, \"\"))"
    assert "load_name_cache" in src, "生产路径应加载名称缓存用于 ST/退市判定"


def test_no_bare_single_arg_call_in_prod():
    """生产脚本里不得出现单参数 is_tradable_code(code) 调用。

    用 AST 精确匹配真实调用点(不做文本匹配 —— 文本会命中注释/文档串里的字样,
    本文件自己就有, 会出现自指假红)。扫描范围=scripts/*.py 且排除 test_*
    (本文件刻意保留单参调用用于钉住失效模式, 不算违规)。
    """
    import ast
    import glob
    hits = []
    for f in sorted(glob.glob(os.path.join(PROJECT, "scripts", "*.py"))):
        base = os.path.basename(f)
        if base.startswith("test_"):
            continue
        try:
            tree = ast.parse(open(f, encoding="utf-8").read(), filename=f)
        except SyntaxError as e:
            print(f"🔴 [test_live_filter_guards.py:132] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 SyntaxError → 兜底, 异常={e}", file=sys.stderr)
            continue  # 语法坏文件由别的门禁管, 这里不重复报
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name != "is_tradable_code":
                continue
            n_args = len(node.args) + len(node.keywords)
            if n_args < 2 and not any(kw.arg == "name" for kw in node.keywords):
                hits.append("%s:%d 单参调用(第2参 name 缺失)" % (base, node.lineno))
    assert not hits, "生产脚本发现单参数 is_tradable_code 调用(会漏 ST/退市): %s" % hits
