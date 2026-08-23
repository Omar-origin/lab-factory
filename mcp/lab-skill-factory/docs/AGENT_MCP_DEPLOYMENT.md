# MCP 客户端部署说明

正式商业发行包采用“在线密钥 + Ed25519 24 小时租约”。Claude Code、Codex 与其他支持 stdio MCP 的客户端都运行同一个 `lab-factory serve-mcp` 入口；旧 `.lflicense` 仅作为兼容入口。

请按 [给安装代理的指令](../INSTALL_FOR_AGENT.md) 配置。安装器会合并已有 MCP 配置，并移除旧的开发绕过和本地激活码配置。配置中只需要公开的 `LAB_FACTORY_CONTROL_URL`；不得写入管理员 Token、数据库 Secret、租约私钥或正式许可证私钥。

验证命令：

```bash
lab-factory status
lab-factory check-runtime
lab-factory mcp-smoke
```

未激活时，帮助用户执行 `activate-key` 并输入销售者提供的密钥。不要让用户把私人收款二维码、AI 账号密码、文档正文、管理员 Token、私钥或机器信息写进 MCP 配置。
