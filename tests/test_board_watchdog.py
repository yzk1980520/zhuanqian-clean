# -*- coding: utf-8 -*-
"""
board_watchdog.py 单元测试（总管 2026-10-15 审查补测）
覆盖: resolve_launcher 候选链 / venv pyvenv.cfg 双检（10-15 弹窗事故回归护栏）/
      tools 回退 / 全失败 RuntimeError / start_board argv 装配
"""
import importlib.util
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_board_watchdog():
    spec = importlib.util.spec_from_file_location(
        "board_watchdog", ROOT / "scripts" / "board_watchdog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mkvenv(base: pathlib.Path, envname: str, with_cfg: bool = True,
           with_exe: bool = True) -> str:
    """构造 venv 目录, 返回 Scripts\\pythonw.exe 路径字符串。"""
    venv = base / envname / "venv"
    scripts = venv / "Scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    pyw = scripts / "pythonw.exe"
    if with_exe:
        pyw.write_bytes(b"PYW")
    if with_cfg:
        (venv / "pyvenv.cfg").write_text(
            "home = X\nimplementation = CPython\nuv = 0.12.3\n", encoding="utf-8")
    return str(pyw)


class TestResolveLauncher(unittest.TestCase):
    """resolve_launcher: 候选顺序 / 双检 / 回退 / 全失败"""

    def setUp(self):
        self.bw = load_board_watchdog()

    def _patch_lists(self, pywin_env, pywin_tools, pyexe):
        """把模块级候选列表指到 tmp 构造的路径 (hermetic, 不碰真实盘)。"""
        self._p1 = mock.patch.object(self.bw, "_PYWIN_ENV", pywin_env)
        self._p2 = mock.patch.object(self.bw, "_PYWIN_TOOLS", pywin_tools)
        self._p3 = mock.patch.object(self.bw, "_PYEXE_CANDIDATES", pyexe)
        self._p1.start(); self._p2.start(); self._p3.start()

    def tearDown(self):
        for p in (getattr(self, "_p1", None), getattr(self, "_p2", None),
                  getattr(self, "_p3", None)):
            if p:
                p.stop()

    def test_active_venv_wins(self):
        """候选1(现役 venv, exe+cfg 齐全) 优先于候选2。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            c1 = mkvenv(base, "active", with_cfg=True)
            c2 = mkvenv(base, "legacy", with_cfg=True)
            self._patch_lists([c1, c2], [], [])
            py, kw = self.bw.resolve_launcher()
            self.assertEqual(py, c1)
            self.assertEqual(kw, {})

    def test_broken_venv_skipped(self):
        """回归护栏(10-15 弹窗事故): pythonw 存在但 pyvenv.cfg 缺失 → 必须跳过该候选,
        否则会命中 venv launcher shim 弹模态框 'failed to locate pyvenv.cfg'。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            broken = mkvenv(base, "broken", with_cfg=False)   # 今晨 c5158a71 的形态
            good = mkvenv(base, "legacy", with_cfg=True)
            self._patch_lists([broken, good], [], [])
            py, kw = self.bw.resolve_launcher()
            self.assertEqual(py, good, "缺 pyvenv.cfg 的 venv 候选必须被跳过")
            self.assertEqual(kw, {})

    def test_broken_venv_exhausts_to_tools(self):
        """全部 venv 候选损坏 → 回退 tools pythonw (无 kwargs)。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            tools_pyw = base / "tools" / "python-3.14" / "pythonw.exe"
            tools_pyw.parent.mkdir(parents=True, exist_ok=True)
            tools_pyw.write_bytes(b"PW")
            self._patch_lists([], [str(tools_pyw)], [])
            py, kw = self.bw.resolve_launcher()
            self.assertEqual(py, str(tools_pyw))
            self.assertEqual(kw, {})

    def test_tools_python_exe_gets_no_window_flag(self):
        """pythonw 全失 → 回退 tools python.exe 时必须带 CREATE_NO_WINDOW。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            tools_exe = base / "tools" / "python-3.14" / "python.exe"
            tools_exe.parent.mkdir(parents=True, exist_ok=True)
            tools_exe.write_bytes(b"EXE")
            self._patch_lists([], [], [str(tools_exe)])
            py, kw = self.bw.resolve_launcher()
            self.assertEqual(py, str(tools_exe))
            self.assertEqual(kw, {"creationflags": 0x08000000})

    def test_all_candidates_missing_returns_none(self):
        self._patch_lists([], [], [])
        py, kw = self.bw.resolve_launcher()
        self.assertIsNone(py)
        self.assertEqual(kw, {})

    def test_start_board_raises_when_no_launcher(self):
        """全失败 → start_board 必须显式抛错 (不得静默吞异常, SOUL 准则9)。"""
        self._patch_lists([], [], [])
        with mock.patch.object(self.bw.subprocess, "Popen") as popen:
            with self.assertRaises(RuntimeError):
                self.bw.start_board()
            popen.assert_not_called()


class TestStartBoardWiring(unittest.TestCase):
    """start_board 装配: 单元素 argv(免转义) + DEVNULL + 返回 pid"""

    def setUp(self):
        self.bw = load_board_watchdog()

    def test_argv_single_element_and_returns_pid(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            pyw = mkvenv(base, "active", with_cfg=True)
            fake = mock.Mock(pid=4242)
            with mock.patch.object(self.bw, "_PYWIN_ENV", [pyw]), \
                 mock.patch.object(self.bw, "_PYWIN_TOOLS", []), \
                 mock.patch.object(self.bw, "_PYEXE_CANDIDATES", []), \
                 mock.patch.object(self.bw.subprocess, "Popen",
                                   return_value=fake) as popen:
                pid = self.bw.start_board()
            self.assertEqual(pid, 4242)
            args, kwargs = popen.call_args
            # argv: [py, script_path] — 空格路径零转义 (历史 bug 防回归)
            expected_script = str(ROOT / "dashboards" / "board_onboarding.py")
            self.assertEqual(args[0], [pyw, expected_script])
            self.assertEqual(kwargs["stdout"], self.bw.subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], self.bw.subprocess.DEVNULL)
            self.assertNotIn("creationflags", kwargs, "pythonw 无需无窗口 flag")


if __name__ == "__main__":
    unittest.main()
