# MCP 客户端部署说明

正式发行包采用 Ed25519 永久离线许可证。Claude Code、Codex 与其他支持 stdio MCP 的客户端都运行同一个 `lab-factory serve-mcp` 入口。

请按 [给安装代理的指令](../INSTALL_FOR_AGENT.md) 配置。安装器会合并已有 MCP 配置，并移除旧的开发绕过和本地激活码配置。配置中不需要服务器地址、数据库、在线激活码或签发私钥。

验证命令：

```bash
lab-factory status
lab-factory check-runtime
lab-factory mcp-smoke
```

未激活时，帮助用户生成 `.lfreq` 并发给销售者。不要让用户把私人收款二维码、AI 账号密码、文档正文、私钥或机器信息写进 MCP 配置。
