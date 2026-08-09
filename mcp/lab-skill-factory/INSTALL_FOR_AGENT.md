# 给安装代理的指令

安装 MCP 配置：

```bash
lab-factory install --target both --purchase-url "微信联系销售者" \
  --support-email support@example.com --feedback-email feedback@example.com
```

不要要求服务器地址、在线激活码、数据库或私钥。随后帮助用户运行：

```bash
lab-factory license-request --output device.lfreq
```

提示用户把请求文件发给销售者，收到 `.lflicense` 后执行 `activate`。不得把源码开发用的 `LAB_FACTORY_DEV_ALLOW` 写入用户配置。
