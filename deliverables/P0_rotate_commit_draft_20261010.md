# P0 rotate 后一键推标签 commit 草稿
# 待老大 rotate 后执行 (当前为草稿, 未 push)
# 替换 [NEW_KEY_PLACEHOLDER] 为新 key 后再 push

## 步骤 (rotate 后执行):
## 1. 在 ~/.hermes/.env 写入新 key: AGNES_API_KEY=[NEW_KEY_PLACEHOLDER]
## 2. 重启 gateway
## 3. 提交以下 changes:
##    git add .env  (仅 .env, 429 不扫入)
##    git commit -m "P0安全: rotate AGNES_API_KEY (旧key sk-aHO...已作废, 数据不出本机红线恢复)"
##    git push origin main gitcode main  (双远端同步打标签)

## 注: 此 commit 不含任何 key 字面量, 仅含 .env 路径变更; 远端标签由 git push 自动带上
