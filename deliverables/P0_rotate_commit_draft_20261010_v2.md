# P0 rotate 后一键推 commit 草稿
# 执行时机: 老大完成 AGNES rotate (新 key mint 后)
# 此文件为草稿, 未 push

## 待老大完成:
## 1. AGNES 后台换发新 AGNES_API_KEY
## 2. 替换 ~/.hermes/.env 中的 AGNES_API_KEY 行(不显旧值, 仅替换值)
## 3. 重启 gateway

## 执行以下命令 (push 到双远端, 同时打标签):
##   cd "D:/open code/zhuanqian"
##   git add .env
##   git commit -m "P0安全: rotate AGNES_API_KEY (旧key sk-aHO...已作废, 数据不出本机红线恢复)

##   git tag -a rotate-done-20261010 -m 'P0 rotate完成: 旧AGNES_API_KEY(sk-aHO...)已作废, 双远端已标' HEAD
##   git push origin main --tags
##   git push gitcode main --tags
##   git tag -a rotate-done-20261010 --local-only  # 仅本地tag(如果远端不可达)

## 内容: 仅 .env 路径变更 (无 key 字面量, 无 429)
## 风险: 极低 (仅标记, 不重写历史)
