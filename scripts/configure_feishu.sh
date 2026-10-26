# Feishu凭证配置脚本

```bash
#!/bin/bash
# 配置飞书机器人凭证

# 飞书App配置
export FEISHU_APP_ID="cli_aa18b9d5a338dbd3"
export FEISHU_APP_SECRET="[请在飞书开发者后台获取]"

# 添加到.hermes/.env
echo 'FEISHU_APP_ID=cli_aa18b9d5a338dbd3' >> ~/.hermes/.env
echo 'FEISHU_APP_SECRET=[请填写实际密钥]' >> ~/.hermes/.env

echo "飞书凭证已写入 ~/.hermes/.env"
echo "请更新 FEISHU_APP_SECRET 实际值后运行: hermes setup feishu"
```