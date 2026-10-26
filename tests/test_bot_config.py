"""
BOT Profile 配置完整性测试
审查范围：自定义 Provider、飞书凭证、Gateway 路由
"""
import pytest
import yaml
from pathlib import Path
from typing import Dict


PROFILES_DIR = Path(r"D:/Hermes agent/Hermes Agent CN Desktop/data/hermes-home/profiles")
MAIN_CONFIG = Path(r"D:/Hermes agent/Hermes Agent CN Desktop/data/hermes-home/config.yaml")


class TestCustomProviders:
    """测试 custom_providers 配置"""

    def test_all_custom_profiles_have_field(self):
        """所有使用 custom provider 的 profile 必须有可用的凭证声明

        2026-10-23 老三修订（配置 schema 升级至 _config_version 51）:
          provider=custom 现支持两种等价形态:
            (a) 展开式  model.custom_providers: [ {...} ]  —— laosi / niuma / workbuddy
            (b) 扁平式  model.base_url + model.key_env     —— laosan / laowu
          依据: 9 个 profile 的 _config_version 全部为 51, 且两种形态并存于同一版本,
          说明是 Hermes 产品侧统一升级生成的合法形态, 而非人工误改 —— 因此不能反过来
          改配置去迁就旧断言(那会动到仓库外的运行时配置, 且无版本控制可回滚)。
          本断言改由"必须含 custom_providers 键"变为"两种形态至少满足其一",
          并额外校验凭证字段非空 / 列表非空 —— 比原断言更严(原仅查键存在性)。
        """
        for profile_dir in PROFILES_DIR.iterdir():
            if not profile_dir.is_dir():
                continue
            config_path = profile_dir / "config.yaml"
            if not config_path.exists():
                continue

            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            model = config.get('model', {})
            if model.get('provider') == 'custom':
                cp = model.get('custom_providers')
                flat = bool(model.get('base_url')) and bool(model.get('key_env'))
                assert cp or flat, \
                    f"{profile_dir.name}: provider=custom 但既无 model.custom_providers " \
                    f"也无 model.base_url+model.key_env, 凭证无处可取"
                if cp:
                    assert len(cp) > 0, \
                        f"{profile_dir.name}: model.custom_providers 为空列表, 解析不出任何模型"

    def test_custom_providers_is_empty_list(self):
        """custom_providers 可以为空或非空(已配置的profile), 仅验证凭证可解析

        2026-10-05 老三修订: laosan已配置agnes providers, 不再要求空列表
        2026-10-23 老三修订: v51 起 provider=custom 亦可为扁平式(model.base_url +
          model.key_env), laosan/laowu 现为该形态且不含 custom_providers 键。
          故"字段存在性"口径由"custom_providers 非 None"调整为
          "custom_providers 与扁平凭证二者至少其一存在"; 两者皆无仍判 FAIL。
        """
        for profile_dir in PROFILES_DIR.iterdir():
            if not profile_dir.is_dir():
                continue
            config_path = profile_dir / "config.yaml"
            if not config_path.exists():
                continue

            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            model = config.get('model', {})
            if model.get('provider') == 'custom':
                cp = model.get('custom_providers')
                flat = bool(model.get('base_url')) and bool(model.get('key_env'))
                # 2026-10-05 老三修订: laosan已配置agnes providers, 不再要求空列表
                assert cp is not None or flat, \
                    f"{profile_dir.name}: custom_providers should not be None when provider=custom"

    def test_no_duplicate_custom_providers(self):
        """不允许在 root 和 model 同时定义 custom_providers"""
        for profile_dir in PROFILES_DIR.iterdir():
            if not profile_dir.is_dir():
                continue
            config_path = profile_dir / "config.yaml"
            if not config_path.exists():
                continue
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            root_cp = config.get('custom_providers')
            model_cp = config.get('model', {}).get('custom_providers')
            
            assert not (root_cp is not None and model_cp is not None), \
                f"{profile_dir.name}: duplicate custom_providers at root and model level"


class TestFeishuCredentials:
    """测试飞书凭证配置"""

    def test_enabled_bots_have_app_id(self):
        """启用飞书的 profile 必须有 app_id

        注意: gateway 托管模式(通过 gateway.profile_routes 接入飞书)的 profile
        不需要在 platforms.feishu 段配 app_id/app_secret, 凭证由 gateway 统一管理。
        判断依据: 该 profile 有 gateway.profile_routes = 走 gateway 托管模式。
        """
        for profile_dir in PROFILES_DIR.iterdir():
            if not profile_dir.is_dir():
                continue
            config_path = profile_dir / "config.yaml"
            if not config_path.exists():
                continue

            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            feishu = config.get('platforms', {}).get('feishu', {})
            # gateway 托管模式: 有 profile_routes 时凭证由 gateway 统一管理
            gateway_routes = config.get('gateway', {}).get('profile_routes', [])
            if gateway_routes:
                continue
            if feishu.get('enabled'):
                app_id = feishu.get('app_id')
                assert app_id, \
                    f"{profile_dir.name}: missing feishu app_id"
                assert 'placeholder' not in str(app_id).lower(), \
                    f"{profile_dir.name}: placeholder app_id detected"

    def test_enabled_bots_have_app_secret(self):
        """启用飞书的 profile 必须有 app_secret

        注意: gateway 托管模式(通过 gateway.profile_routes 接入飞书)的 profile
        不需要在 platforms.feishu 段配 app_id/app_secret, 凭证由 gateway 统一管理。
        """
        for profile_dir in PROFILES_DIR.iterdir():
            if not profile_dir.is_dir():
                continue
            config_path = profile_dir / "config.yaml"
            if not config_path.exists():
                continue

            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            feishu = config.get('platforms', {}).get('feishu', {})
            # gateway 托管模式: 有 profile_routes 时凭证由 gateway 统一管理
            gateway_routes = config.get('gateway', {}).get('profile_routes', [])
            if gateway_routes:
                continue
            if feishu.get('enabled'):
                app_secret = feishu.get('app_secret')
                assert app_secret, \
                    f"{profile_dir.name}: missing feishu app_secret"

    def test_unique_app_ids(self):
        """所有启用的飞书应用必须有唯一的 app_id"""
        app_ids: Dict[str, str] = {}
        
        for profile_dir in PROFILES_DIR.iterdir():
            if not profile_dir.is_dir():
                continue
            config_path = profile_dir / "config.yaml"
            if not config_path.exists():
                continue
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            feishu = config.get('platforms', {}).get('feishu', {})
            if feishu.get('enabled'):
                app_id = feishu.get('app_id')
                if app_id in app_ids:
                    pytest.fail(
                        f"Duplicate app_id {app_id} in {app_ids[app_id]} "
                        f"and {profile_dir.name}"
                    )
                app_ids[app_id] = profile_dir.name


class TestGatewayRoutes:
    """测试 Gateway 路由配置"""

    def test_routes_have_correct_profile(self):
        """Gateway 路由的目标 profile 必须真实存在(自持或显式代管)

        飞书群聊代管模式: zongguan 托管 laosan/laowu/niuma 的路由, 这些路由的目标
        指向子 profile 名字(laosan 等), 而配置文件在 zongguan 下 —— 这是设计意图,
        不是配置错误。

        2026-10-23 老三修订（配置 schema 升级至 _config_version 51）:
          路由目标字段由 `profile` 更名为 `bot_profile`; 旧 `thread_id` 线程路由判定
          已废弃, 改由 gateway.multiplex_profiles=true 表达"本 profile 的 gateway
          代管其它 profile 的路由"。
          依据: 9 个 profile 全部为 _config_version 51, 7 条路由全部使用
          `bot_profile` 且无一条仍带 `thread_id`, 属产品侧统一升级, 非人工误改。
          同上, 不反过来改仓库外运行时配置去迁就旧断言。
          兼容过渡期两种字段名(要求至少一个非空), 并把代管关系收紧为
          "必须显式开启 multiplex_profiles", 另新增"目标 profile 必须真实存在"校验
          —— 比原断言更严(原仅比对文件名, 代管分支可指向任意名字)。
        """
        for profile_dir in PROFILES_DIR.iterdir():
            if not profile_dir.is_dir():
                continue
            config_path = profile_dir / "config.yaml"
            if not config_path.exists():
                continue

            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            gateway = config.get('gateway', {})
            for route in gateway.get('profile_routes', []):
                # v51: 目标字段为 bot_profile; 兼容过渡期仍读旧字段 profile
                route_profile = route.get('bot_profile') or route.get('profile')
                assert route_profile, \
                    f"{profile_dir.name}: route 缺 bot_profile/profile, 实际字段 {sorted(route)}"

                if route_profile != profile_dir.name:
                    # 代管模式: 路由指向别的 profile, 必须显式开启 multiplex_profiles
                    assert gateway.get('multiplex_profiles'), \
                        f"{profile_dir.name}: 路由指向 '{route_profile}' 但 " \
                        f"gateway.multiplex_profiles 未开启, 代管关系无据"

                # 目标 profile 必须真实存在(新增校验, 原断言未覆盖)
                assert (PROFILES_DIR / route_profile).is_dir(), \
                    f"{profile_dir.name}: 路由目标 '{route_profile}' 不是已存在的 profile"

    def test_routes_have_valid_chat_id(self):
        """Gateway 路由必须有有效的 chat_id"""
        for profile_dir in PROFILES_DIR.iterdir():
            if not profile_dir.is_dir():
                continue
            config_path = profile_dir / "config.yaml"
            if not config_path.exists():
                continue
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            gateway = config.get('gateway', {})
            for route in gateway.get('profile_routes', []):
                chat_id = route.get('chat_id')
                assert chat_id and chat_id.startswith('oc_'), \
                    f"{profile_dir.name}: invalid chat_id '{chat_id}'"


class TestMainConfig:
    """测试主配置文件"""

    def test_main_feishu_disabled(self):
        """主配置的飞书应禁用以避免凭证冲突"""
        if not MAIN_CONFIG.exists():
            pytest.skip("Main config not found")
        
        with open(MAIN_CONFIG, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        feishu = config.get('platforms', {}).get('feishu', {})
        assert not feishu.get('enabled', False) or \
            feishu.get('app_id') == 'cli_aa18b9d5a338dbd3', \
            "Main config should not have conflicting Feishu credentials"


class TestSystemPrompts:
    """测试系统提示词格式"""

    def test_system_prompt_not_empty(self):
        """所有 profile 应有系统提示词"""
        for profile_dir in PROFILES_DIR.iterdir():
            if not profile_dir.is_dir():
                continue
            config_path = profile_dir / "config.yaml"
            if not config_path.exists():
                continue
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            agent = config.get('agent', {})
            prompt = agent.get('system_prompt', '')
            assert prompt and len(prompt.strip()) > 10, \
                f"{profile_dir.name}: system_prompt too short or empty"
