# Runbook：老大人工单点（Hermes治理方案v1 T6，2026-10-15 总管）

> 背景：R3 人工单点未收敛 —— webhook 重建 / bot 拉群 / 网关重启 / PAT 授权全靠口口相传。
> 本 runbook 四项各配验收命令，照做即可。做完一项删一项，全做完关闭本文档。
> 关联：`mainline/docs/hermes-governance-plan_2026-10-15.md` 第五节。

---

## 1. gh fine-grained PAT 加 zhuanqian 权限（T4/CI 闭环前置，**优先做**）

**现状**：gh PAT 对 `yzk1980520/zhuanqian` 无权限（查询全 404）→ CI 远程 Actions 结果无法核验，
审查闭环在"本地 85 passed"处卡住（本地已做等价验证）。

**操作**（GitHub 网页）：
1. Settings → Developer settings → Fine-grained tokens → 找到现有 PAT
2. Repository access 勾 **Only select repositories** → 加 `yzk1980520/zhuanqian`
3. Permissions → 至少勾：Contents (Read)、Metadata (Read)、Actions (Read)

**验收**（在 D:\open code\zhuanqian 执行，任一通过即可）：
```powershell
gh api repos/yzk1980520/zhuanqian/actions/runs --jq '.workflow_runs[0].{name, conclusion, updated_at}'
# 或
curl -s -H "Authorization: token <PAT>" https://api.github.com/repos/yzk1980520/zhuanqian/actions/runs | findstr conclusion
```
看到最近一次 workflow run 的 conclusion（success/failure）= 通过。

---

## 2. 重建自定义机器人 webhook（health_monitor 触达恢复）

**现状**：`010b9197-…` 自定义机器人已死（飞书 19007 静默失败，10-14 实证）；
health_monitor 响应体校验已修（不再静默），但通道仍需重建。

**操作**（飞书）：
1. 主群（`oc_100a06…`）→ 设置 → 群机器人 → 添加机器人 → 自定义机器人
2. 安全设置选"签名校验"，复制 webhook_url + secret

**入库**：更新 `config/feishu_config.json`（webhook_url / secret / enabled:true）

**验收**：
```powershell
python -c "import sys; sys.path.insert(0,'.'); import cron_message_sender as c; print('webhook 通道:', '✅' if c.send_feishu_webhook('【webhook 重建验收】') else '❌')"
```
群内 10 秒内可见该消息 = 通过。

---

## 3. 「管事」bot 拉进总管群 + 重启网关（zongguan 新凭证生效）

**现状**：zongguan profile 新凭证 `cli_aa442d065138dc10` 已配，但 bot 未在群内 + 网关未重启，
8 群路由全员挤主群（配置-事实漂移，T5 对账对象）。

**操作**：
1. 飞书总管群（`oc_032fc…`）→ 设置 → 群机器人 → 添加「管事」bot（zongguan 应用）
2. 重启网关：
```powershell
hermes gateway restart
```

**验收**：
```powershell
# 1) 群机器人列表含管事: 飞书UI 总管群 设置→群机器人 目视确认(最稳), 或向总管群发一条测试消息@管事 能收到回复
# 2) 网关起来且单实例锁不再报 duplicate
hermes gateway status                          # running + 无 "duplicate instance" 日志 = 通过
```

---

## 4. PAT 之外的遗留：gitcode.com DNS 韧性（G4，非人工单点，仅列备忘）

gitcode 间歇 DNS 失败（疑为 9-29 断推送诱因）。已缓解：`check_remote_main_freshness.py`
ls-remote 3 次重试 + 24h 新鲜度监控 + QSP_GitSync 每日 09:30 自愈推送。
若再发 DNS 断供：查 `data/remote_freshness.log` 的 P1 行 → `nslookup gitcode.com` 确认 → 换 8.8.8.8 或等窗口恢复，QSP_GitSync 下轮自动补推。

---

## 使用规则

- 每完成一项：在 `docs/channel-changelog.md` 记一条（谁/何时/为何/恢复条件），并把本节对应条目删除。
- 全部完成 → 本文档移 `docs/archive/`。
