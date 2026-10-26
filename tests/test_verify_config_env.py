"""t_8969284a P2: verify_config._load_hermes_env 多候选兜底单测.

覆盖 AC3 ≥5 用例:
  1. USERPROFILE 缺省（home 候选命中, .env 解析正确）
  2. HERMES_HOME 指向 profile 子目录（命中上两级候选）
  3. HERMES_HOME 指向根目录（命中 HERMES_HOME/.env 候选, 先于上两级）
  4. 全缺 → 返回 {}
  5. 命中候选日志行存在（可追溯哪个 .env 生效）
  6. 未命中日志行存在
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VC_PATH = ROOT / "scripts" / "verify_config.py"


def _load_vc():
    spec = importlib.util.spec_from_file_location("verify_config_t8969284a", VC_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _patch_home(monkeypatch, path: Path):
    """把 Path.home() 钉到受控目录（绕开 USERPROFILE/HOMEDRIVE 真实环境）。"""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls, _p=path: _p))


@pytest.fixture
def clean_env(monkeypatch):
    """清空 3 个相关 env, 保证候选行为确定。"""
    for k in ("USERPROFILE", "HERMES_HOME", "HOMEDRIVE", "HOMEPATH"):
        monkeypatch.delenv(k, raising=False)


def _write_env(p: Path, text="DEEPSEEK_API_KEY=sk-test\n# comment line\nAGNES_API_KEY='cpk-x'\n") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_userprofile_absent_home_candidate_hit(clean_env, monkeypatch, tmp_path, capsys):
    """USERPROFILE 缺省: home 候选（~/.hermes/.env）命中且解析正确。"""
    vc = _load_vc()
    _patch_home(monkeypatch, tmp_path)
    _write_env(tmp_path / ".hermes" / ".env")
    data = vc._load_hermes_env()
    assert data == {"DEEPSEEK_API_KEY": "sk-test", "AGNES_API_KEY": "cpk-x"}
    out = capsys.readouterr().out
    assert "命中候选 .env" in out and str(tmp_path / ".hermes" / ".env") in out


def test_hermes_home_profile_subdir_hit_parent_parent(clean_env, monkeypatch, tmp_path, capsys):
    """HERMES_HOME 指向 profile 子目录: 命中 hermes-home 根（parent.parent）.env。"""
    vc = _load_vc()
    _patch_home(monkeypatch, tmp_path)  # 无 .hermes → home 候选落空
    hh = tmp_path / "hh-root" / "profiles" / "laosan"
    hh.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hh))
    _write_env(tmp_path / "hh-root" / ".env")  # hh.parent.parent / .env
    data = vc._load_hermes_env()
    assert data["DEEPSEEK_API_KEY"] == "sk-test"
    out = capsys.readouterr().out
    assert "命中候选 .env" in out
    assert str(tmp_path / "hh-root" / ".env") in out


def test_hermes_home_root_dir_hit_direct(clean_env, monkeypatch, tmp_path, capsys):
    """HERMES_HOME 指向根目录: 命中 HERMES_HOME/.env（先于上两级候选）。"""
    vc = _load_vc()
    _patch_home(monkeypatch, tmp_path)
    hh_root = tmp_path / "hh-root"
    monkeypatch.setenv("HERMES_HOME", str(hh_root))
    _write_env(hh_root / ".env")
    _write_env(tmp_path / "hh-root2" / ".env", text="OTHER_KEY=should-not-win")  # 干扰候选, 不应命中
    data = vc._load_hermes_env()
    assert data["DEEPSEEK_API_KEY"] == "sk-test"
    assert "OTHER_KEY" not in data
    out = capsys.readouterr().out
    assert f"命中候选 .env: {hh_root / '.env'}" in out


def test_all_missing_returns_empty(clean_env, monkeypatch, tmp_path, capsys):
    """全候选缺失 → 返回 {}。"""
    vc = _load_vc()
    _patch_home(monkeypatch, tmp_path)  # 无 .hermes/.env
    data = vc._load_hermes_env()
    assert data == {}
    out = capsys.readouterr().out
    assert "未命中任何 .env 候选" in out


def test_hit_log_line_traceable(clean_env, monkeypatch, tmp_path, capsys):
    """命中日志行含具体路径, 哪个 .env 生效可追溯。"""
    vc = _load_vc()
    _patch_home(monkeypatch, tmp_path)
    target = tmp_path / "env-target" / ".env"
    _write_env(target)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "env-target"))
    vc._load_hermes_env()
    out = capsys.readouterr().out
    assert "[verify_config.env] 命中候选 .env:" in out
    assert str(target) in out


def test_parse_strips_quotes_and_comments(clean_env, monkeypatch, tmp_path):
    """解析面: 去引号、跳过注释/空行、保留含 = 的值。"""
    vc = _load_vc()
    _patch_home(monkeypatch, tmp_path)
    _write_env(
        tmp_path / ".hermes" / ".env",
        text='A="quoted"\nB=\'single\'\n# skip me\n\nC=a=b=c\n',
    )
    data = vc._load_hermes_env()
    assert data == {"A": "quoted", "B": "single", "C": "a=b=c"}
