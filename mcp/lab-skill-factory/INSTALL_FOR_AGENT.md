# 给安装代理的指令

安装 MCP 配置：

```bash
lab-factory install --target both --purchase-url "https://lab.elyther.top/plans" \
  --support-email "QQ群923937311" --feedback-email "QQ群923937311" \
  --control-url https://lab.elyther.top
```

公开授权域名由销售者提供；不要索要数据库、管理员 Token 或任何私钥。随后帮助用户运行：

```bash
lab-factory activate-key '销售者提供的密钥' \
  --accept-terms-version 1.0 --confirm-age-18
```

密钥会绑定当前安装。换机需要销售者在中控重置；不得把源码开发用的 `LAB_FACTORY_DEV_ALLOW` 或卖家管理员 Token 写入用户配置。
