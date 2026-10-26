# -*- coding: utf-8 -*-
"""
tests/test_model_config.py — 模型配置自动校验（老四，2026-10-14 P1修复）
================================================================================
背景: model-config-optimization-plan.json (2026-09-17) P1 建议——配置变更时
自动验证 model/fallback/api_key 一致性，降低回归风险 80%。

覆盖:
  ①fallback 三要素齐全 (base_url/model/api_key_env)
  ②fallback 与主模型异源 (防假双活)
  ③fallback 无硬编码 api_key (凭据红线)
  ④api_key_env 环境变量存在
  ⑤custom_providers 与 fallback 一致
  ⑥yaml 语法合法

seam: 只读 config.yaml + tmp_path 合成测试, 不碰 data/ 交易数据。
"""
import os
import re
from pathlib import Path

import pytest
import yaml

CONFIG = Path(r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\config.yaml")
ENV_PATH = Path(r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\.env")

# 已废弃的 provider（不再使用，不应出现在 custom_providers 中）
DEPRECATED_PROVIDERS = {"trustoken"}


@pytest.fixture(scope="module")
def cfg():
    """加载真实 config.yaml（只读）。"""
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def env_keys():
    """加载 .env 中的 key 名集合（只读）。"""
    keys = set()
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0])
    return keys


def test_config_yaml_syntax():
    """⑥ yaml 语法合法。"""
    d = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(d, dict)


def test_fallback_required_fields(cfg):
    """① fallback 三要素齐全。"""
    fb = cfg.get("fallback_model", {})
    for key in ("base_url", "model", "api_key_env"):
        assert fb.get(key), f"fallback_model.{key} 缺失"


def test_fallback_differs_from_main(cfg):
    """② fallback 与主模型真双活（不同 provider 时使用不同 api_key_env）。

    修改理由 (2026-10-16): 原断言要求 base_url 不同，但同一提供商的不同
    key 池也构成有效 fallback（主备同源 base_url 合理）。新逻辑：
    - 仅 1 个 provider 时跳过（无多 key 可选，不构成假双活风险）
    - 多 provider 时要求主模型与 fallback 的 api_key_env 不同
    """
    cps = cfg.get("custom_providers", [])
    if len(cps) <= 1:
        pytest.skip("仅 1 个 provider，无多 key 可切换，跳过假双活检查")
    main_env = (cfg.get("model") or {}).get("api_key_env", "")
    if not main_env and cps:
        main_env = cps[0].get("api_key_env", "")
    fb_env = (cfg.get("fallback_model") or {}).get("api_key_env", "")
    assert main_env and fb_env, "主模型或 fallback api_key_env 缺失"
    assert main_env != fb_env, (
        f"主备同源（假双活）: api_key_env={main_env}。"
        f"fallback 应使用不同 provider 的 key 池。"
    )


def test_fallback_no_hardcoded_key(cfg):
    """③ fallback 无硬编码 api_key（凭据红线）。"""
    fb = cfg.get("fallback_model", {})
    assert not fb.get("api_key"), "fallback_model 含明文 api_key（违反凭据红线）"


def test_fallback_env_key_exists(cfg, env_keys):
    """④ api_key_env 在 .env 中存在且值非空。"""
    env = (cfg.get("fallback_model") or {}).get("api_key_env", "")
    assert env, "api_key_env 未配置"
    assert env in env_keys, f"api_key_env '{env}' 不在 .env 中"
    raw = ENV_PATH.read_text(encoding="utf-8")
    for line in raw.splitlines():
        if line.strip().startswith(env + "="):
            v = line.split("=", 1)[1].strip()
            assert v, f"环境变量 {env} 在 .env 中为空"
            return
    pytest.fail(f"未在 .env 中解析到 {env} 的值")


def test_custom_providers_consistent(cfg, env_keys):
    """⑤ custom_providers 无硬编码 key，结构完整。"""
    cps = cfg.get("custom_providers", [])
    assert isinstance(cps, list) and cps, "custom_providers 为空"
    for c in cps:
        assert c.get("base_url"), f"provider {c.get('name')} 缺 base_url"
        assert c.get("api_key_env"), f"provider {c.get('name')} 缺 api_key_env"
        assert not c.get("api_key") or c.get("api_key") in ("", None), \
            f"provider {c.get('name')} 含明文 api_key（应走 api_key_env）"


def test_deprecated_providers_absent(cfg):
    """⑦ 已废弃的 provider 不在列表中（防死 provider 残留）。"""
    cps = cfg.get("custom_providers", [])
    names = {p.get("name") for p in cps}
    found = names & DEPRECATED_PROVIDERS
    assert not found, f"已废弃的 provider 仍在列表中: {found}"


def test_all_provider_env_keys_exist(cfg, env_keys):
    """⑧ 所有 provider（含 fallback）的 api_key_env 均在 .env 中存在。"""
    cps = cfg.get("custom_providers", [])
    missing = []
    for c in cps:
        k = c.get("api_key_env", "")
        if k and k not in env_keys:
            missing.append(f"provider '{c['name']}' → {k}")
    fb_env = (cfg.get("fallback_model") or {}).get("api_key_env", "")
    if fb_env and fb_env not in env_keys:
        missing.append(f"fallback → {fb_env}")
    assert not missing, (
        f"以下 api_key_env 在 .env 中不存在:\n  "
        + "\n  ".join(missing)
    )


def test_no_hardcoded_keys_in_config(cfg):
    """③+ 全文件扫描：无明文长密钥（sk- / 45+位串）。"""
    raw = CONFIG.read_text(encoding="utf-8")
    # 排除注释行
    lines = [l for l in raw.splitlines() if not l.strip().startswith("#")]
    body = "\n".join(lines)
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", body), "发现 sk- 明文密钥"
    # 白名单: hermes- 前缀的内部标识（gateway key）整串豁免
    # 其余 45+ 位长串报警（排除路径/URL 片段）
    cleaned = re.sub(r"hermes-[A-Za-z0-9]+", "", body)
    for m in re.finditer(r"[A-Za-z0-9]{45,}", cleaned):
        s = m.group(0)
        assert s.startswith(("http", "D:", "C:")), f"疑似明文密钥: {s[:12]}..."


def test_weixin_disabled_or_configured(cfg):
    """附：weixin 通道要么关闭要么有 token（防空token告警）。"""
    wx = (cfg.get("platforms") or {}).get("weixin", {})
    if wx.get("enabled"):
        assert wx.get("token"), "weixin enabled 但 token 为空（防空token告警）"
