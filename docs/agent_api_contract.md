# Agent po中继接口对齐契约

> 总管 2026-10-26 建立。8 个 Hermes agent profile 相互调用的接口契约，配套验证脚本 `scripts/verify_agent_po_relay.py`（8/8 PASS）。

## 1. 端点与认证
| 项 | 值 |
|---|---|
| 端点 | `http://127.0.0.1:8642/p/{profile}/v1/chat/completions` |
| 认证 | 各 profile `.env` 的 `API_SERVER_KEY`（Bearer，8 profile 统一 `hermes-d…f33d`, len 55） |
| body | OpenAI 兼容 `{"model":..., "messages":[...], "max_tokens":N}` |

## 2. 各 profile 的 model（异构，设计保留）
| profile | provider | default model |
|---|---|---|
| zongguan | nous | agnes-3.0-flash |
| laosi / laowu / laosan / opencode / atomcode | custom(apihub.agnes-ai.com) | agnes-3.0-flash |
| niuma | custom | **agnes-2.5-flash** |
| workbuddy | custom | agnes-3.0-flash（保留 2.5 中间层） |

**调用方传给 po中继的 model 参数会被忽略**——po中继一律用目标 profile 自身 default。验证：niuma 传 3.0-flash 仍返回 2.5 结果。故调用契约 = 端点区分 profile，model 随 profile，不随调用方。

## 3. 冷启动容忍
- 首次调用某 profile 的 po中继会懒加载 provider 连接，**atomcode 尤慢**（首个必超时）。
- 调用方 timeout **≥ 45s**（verify_agent_po_relay.py 已用 45s）。
- 付费池 AGNES_API_KEY 偶发 `custom rate-limited`（HTTP 200 但限流提示），重试即可。

## 4. 输出（飞书）对齐与 admission_conflict
- 8 profile `home_channel` 统一主群 `oc_032fc1473f869b657ffcfbdf495bae1e`。
- 副作用：8 agent 的 watch/PO 通知同打主群，撞长对话时框架 `api_server_response_admissions.py` 串行化 → 409 丢包（admission_conflict，日志 10-14~10-25 高频）。
- 定性：**框架自我保护**（非数据故障）。治本 = 各 agent 通知分流到子频道 或 gateway 加 admission 队列重试。属老大"统一主群"取舍，记录待拍板，未擅改。

## 5. 已修复的对齐缺陷（2026-10-26）
- **workbuddy .env 埋雷**：`API_SERVER_KEY=***` 脱敏占位脏行（.env 第3行）与真 key 行并存 → po中继验证首匹配读到 `***` → 401。已删脏行（备份 `.env.bak_dirty_20261026`）。
- **verify get_key 加固**：跳过 `***`/非 `hermes-` 值，取最后有效真 key 行，防再次踩脏行。
- 全 8 profile .env 其他 `=***` 行（AGNES/GLM/OPENROUTER 等脱敏占位）为正常 scrub 产物，不影响 API_SERVER_KEY 功能。

## 验证
```
python scripts/verify_agent_po_relay.py   # 期望: 8/8 通, exit 0
```
