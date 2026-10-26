# Provider/Model Sync 执行报告 2026-10-25

## 执行内容

### 1. 运行同步检测脚本
- 脚本：`hermes-home/scripts/nous_agnes_model_sync.py`
- 结果：检测到 2 项变更需要应用

### 2. 配置变更（已应用）

| 变更项 | 详情 |
|--------|------|
| **custom_providers** | 新增 `nous-portal-free` 提供者，含 4 个 Nous Portal 免费模型 |
| **custom_providers** | 新增 `agnes-2.0-flash` 到 Apihub.agnes-ai.com 模型列表 |
| **备份位置** | `backups/model_updates/config.yaml.bak_20261025_184724` |

### 3. 变更详情

**Nous Portal 免费模型**（新增 provider）：
```yaml
- api_key_env: NOUS_API_KEY
  base_url: https://inference-api.nousresearch.com/v1
  model: tencent/hy3:free
  models:
    tencent/hy3:free: {}
    poolside/laguna-s-2.1:free: {}
    stepfun/step-3.7-flash:free: {}
    poolside/laguna-xs-2.1:free: {}
  name: nous-portal-free
```

**Agnes AI 模型**（已存在，新增 agnes-2.0-flash）：
```yaml
models:
  agnes-2.5-flash: {}
  agnes-2.5-pro-alpha: {}
  agnes-2.5-pro-beta: {}
  agnes-3.0-flash: {}
  agnes-2.0-flash: {}    # 新增
```

### 4. Gateway 重启

| 操作 | 结果 |
|------|------|
| 旧进程 PID 23144 | 已终止 |
| 新进程 PID 14520 | 已启动 |
| 端口 8642 | LISTENING ✓ |

### 5. YAML 语法验证

```
PASS - custom_providers: 2 个
  - Apihub.agnes-ai.com: 5 models
  - nous-portal-free: 4 models
```

## 当前模型路由优先级

| 优先级 | Provider | 模型 | Key |
|--------|----------|------|-----|
| 主路由 | custom (agnes) | agnes-3.0-flash | AGNES_API_KEY |
| 备用1 | custom (agnes) | agnes-2.5-flash | AGNES_FREE_API_KEY |
| 备用2 | custom (agnes) | agnes-3.0-flash | AGNES_API_KEY |
| 新增 | nous-portal-free | tencent/hy3:free | NOUS_API_KEY |
| 新增 | nous-portal-free | poolside/laguna-s-2.1:free | NOUS_API_KEY |
| 新增 | nous-portal-free | stepfun/step-3.7-flash:free | NOUS_API_KEY |
| 新增 | nous-portal-free | poolside/laguna-xs-2.1:free | NOUS_API_KEY |

## Cron 注册建议

任务名：`AgnesModelAutoUpdate`
周期：每周一/四 09:00（北京时间）
命令：`python scripts/nous_agnes_model_sync.py`
模式：`no_agent` + `deliver=local`

## 注意事项

1. Nous Portal 免费模型需要 `NOUS_API_KEY` 环境变量
2. 年费 key 周配额耗尽时自动降级到免费 key（fallback_providers 已配置）
3. `agnes-2.0-flash` 已加入路由，可作为额外免费备用
4. Gateway 已重启，新配置生效
