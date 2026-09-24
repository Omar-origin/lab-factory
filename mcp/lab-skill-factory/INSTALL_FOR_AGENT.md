# 给本机 Agent 的安装说明

用户把本产品的 Agent ZIP 交给你并说“帮我安装”时，按 ZIP 根目录中的 `INSTALL_FOR_AGENT.md` 操作。你必须运行在用户本机，并有读取文件、执行本机命令和编辑用户选择的 MCP 配置的能力。纯网页聊天没有这些权限时，停止并说明这一限制。

先确认系统架构，再从 GitHub Release 下载对应的 `SHA256SUMS.txt` 并校验 ZIP；解压后还要按包内清单校验可执行文件或 Windows 安装器。任一校验不匹配都不要运行。安装文件可能显示 Windows SmartScreen 或 macOS Gatekeeper 提示；本 Beta 没有正式代码签名/公证，不得静默关闭系统保护或要求管理员密码。由用户本人查看提示并决定。

只配置用户实际使用的 MCP 宿主，并保留其他配置。`lab-factory install` 支持自动合并 Codex 和 Claude Code 配置；WorkBuddy/Kimi 等宿主按其当前版本的 stdio MCP 格式合并，保持程序路径稳定并确认 `args` 为 `serve-mcp`。具体配置路径由宿主版本决定，不得臆造后覆盖用户文件。DeepSeek 等模型需要经由有本机文件和 stdio MCP 能力的宿主；网页模型本身不能远程安装桌面程序。

安装后运行 `status`、`check-runtime` 和 `mcp-smoke`，让用户重启宿主，再确认工具已出现。授权密钥由用户本人通过官网购买和激活；不要索要、代填、回显或写入密钥。不要输入管理员 Token、数据库凭证、租约私钥或开发绕过变量。
