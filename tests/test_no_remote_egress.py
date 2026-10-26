#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_no_remote_egress.py — 硬约束 C2「数据不出本机」机器强制守卫

背景(2026-10-17 红线处置 O-3):
    supabase_data.py 原为 Supabase REST 接入层, update_holdings() 会 POST 实盘持仓到远程表、
    append_trade_log() 会 POST 交易流水、save_config()/save_scan() 同样外传。
    调用处一律裸 try + except: pass, 外传失败完全静默 —— 不报错、不留痕。
    此前仅因 .env 缺 SUPABASE_URL/SUPABASE_SECRET_KEY 才未实际外传, 补两行配置即激活。

处置:
    不是"关掉开关", 而是删除网络出口, 让红线变成"能力不存在"。
    本测试把这条红线固化成机器判定 —— 任何人重新引入外传路径, 这里立刻红灯。

判据说明:
    「数据不出本机」约束的是**出向(egress)**, 不是入向。
    向东方财富/妙想等外部源**取行情**属入向, 合规(外部源仅作备源与校验), 不在拦截范围。
    因此本测试只扫描"持有实盘数据的写入链路"模块, 不做全库网络禁用。
"""
import os
import re
import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 出向(egress)网络原语: 会把数据发到本机之外
EGRESS_PATTERNS = [
    r"urllib\.request\.urlopen",
    r"urllib\.request\.Request",
    r"requests\.(post|put|patch|delete)",
    r"http\.client\.HTTPS?Connection",
    r"socket\.create_connection",
    r"smtplib\.",
    r"ftplib\.",
]
EGRESS_RE = re.compile("|".join(EGRESS_PATTERNS))

# 实盘数据写入链路: 这些模块持有 holdings/trade_log 的写权限, 绝不允许出现出向网络调用
WRITE_PATH_MODULES = [
    "supabase_data.py",
    "atomic_json.py",
    "trade_tracker.py",
    "portfolio_review.py",
    "orchestrator.py",
    "integrated_picker.py",
]


def _read(name):
    """读取被守护的模块源码

    文件缺失时**必须硬失败**: 本测试是 O-3 红线的机器守卫, 一旦被守护的文件
    被删除/改名, 静默 skip 会让守卫整体失效且报表依旧全绿 —— 守卫绝不能
    因为"目标消失"而自动解除。故此处一律 pytest.fail 并点名缺失路径。
    """
    path = os.path.join(PROJECT, name)
    if not os.path.exists(path):
        pytest.fail(
            f"[C2红线守卫失效] 被守护的文件不存在: {path}\n"
            f"  (相对路径 {name})\n"
            f"  该文件是本红线守卫的守护目标, 被删除或改名会让守卫静默失效。\n"
            f"  若确为精简删除, 请先更新 tests/test_no_remote_egress.py 的守护清单, "
            f"而不是让它悄悄跳过。"
        )
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _strip_docstrings(src):
    """去掉模块/函数/类文档串与行注释, 只留可执行代码

    理由: 本测试的历史沿革写在文档串里, 会提到 SUPABASE_URL 等字样;
    文档串不是能力, 不应触发红线。只扫"会被执行的代码"才是准确判据。
    """
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src  # 解析失败则退化为全文扫描(宁可误报也不漏报)
    drop = set()
    for node in ast.walk(tree):
        # 真正的文档串(必须是首条语句)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ds = ast.get_docstring(node, clean=False)
            if ds:
                drop.add(ds)
        # 裸字符串表达式: 写在 import 之后的"伪文档串", get_docstring 取不到, 同样不是可执行能力
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            drop.add(node.value.value)
    for ds in drop:
        src = src.replace(ds, "")
    return src


def _find_egress(src):
    hits = []
    code = _strip_docstrings(src)
    for i, line in enumerate(code.splitlines(), 1):
        stripped = line.split("#")[0]  # 忽略行注释
        if EGRESS_RE.search(stripped):
            hits.append((i, line.strip()[:120]))
    return hits


class TestNoRemoteEgressOnDataWritePath:
    """实盘数据写入链路禁止任何出向网络调用"""

    @pytest.mark.parametrize("mod", WRITE_PATH_MODULES)
    def test_write_path_has_no_egress(self, mod):
        hits = _find_egress(_read(mod))
        assert not hits, (
            f"[C2红线] {mod} 出现出向网络调用, 实盘数据可能外传本机:\n"
            + "\n".join(f"  L{ln}: {txt}" for ln, txt in hits)
            + "\n\n若确为入向取行情(如东财接口), 请把该逻辑移出本模块再放行。"
        )


class TestSupabaseCapabilityRemoved:
    """Supabase 外传能力必须是不存在, 而不是被配置关掉"""

    def test_supabase_module_has_no_egress(self):
        """supabase_data.py 不得残留任何网络出口"""
        hits = _find_egress(_read("supabase_data.py"))
        assert not hits, (
            f"[O-3] supabase_data.py 仍残留网络出口:\n"
            + "\n".join(f"  L{ln}: {txt}" for ln, txt in hits)
        )

    def test_update_holdings_removed(self):
        """update_holdings(POST 实盘持仓到远程表)必须彻底移除, 不得复活"""
        src = _read("supabase_data.py")
        assert "def update_holdings" not in src, (
            "[O-3] supabase_data.update_holdings 已复活 —— 该函数会 POST 实盘持仓到远程表, 违反 C2"
        )

    def test_is_connected_always_false(self):
        """远程通道恒不可用: is_connected() 必须返回 False, 禁止读环境变量复活"""
        import supabase_data
        assert supabase_data.is_connected() is False, (
            "[O-3] supabase_data.is_connected() 返回了 True —— 远程通道被复活, 实盘数据可能外传"
        )

    def test_no_supabase_env_secret_leak(self):
        """不得再读取 Supabase 密钥环境变量(能力已移除, 留着只会诱导补配置复活外传)"""
        # 只扫可执行代码: 文档串里的历史沿革说明不算能力
        src = _strip_docstrings(_read("supabase_data.py"))
        for token in ("SUPABASE_URL", "SUPABASE_SECRET_KEY"):
            assert token not in src, (
                f"[O-3] supabase_data.py 代码中仍引用 {token} —— 补上配置即可复活外传, 必须彻底清除"
            )


class TestAppendTradeLogLocalOnly:
    """append_trade_log 保留本地写入语义(它有真实本地行为, 不能简单删掉)"""

    def test_appends_to_local_data_dir(self):
        src = _read("supabase_data.py")
        assert "def append_trade_log" in src, "append_trade_log 的本地写入语义必须保留"
        # 本地写入必须落到 data/ 下的真源, 不得写回根目录死副本
        assert '"trade_log.json"' in src or "'trade_log.json'" in src
        assert "_DATA_DIR" in src, "append_trade_log 必须写 data/ 真源, 不得写根目录死副本"
