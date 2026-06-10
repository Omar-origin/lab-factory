# Install Lab Factory For Agent

这份文件是给 Claude Code、Codex 或其他本地 coding agent 看的。用户可能只会给你一个压缩包路径、安装包路径或下载地址，并说“部署一下这个”。你的任务是完成 Lab Factory MCP 部署，不要开始写实验报告。

## 你要做什么

1. 解压用户给的 zip，或使用用户已经安装好的 Lab Factory。
2. 找到 `lab-factory` 或 `lab-factory.exe`。
3. 先运行基础自检和 MCP 握手测试。
4. 调用内置 `install` 命令接入 Claude Code、Codex，或两个都接入。
5. 如果用户有激活码，帮助用户激活。
6. 让用户重启 Claude Code/Codex，并验证 MCP 能被调用。

更完整的部署说明见 `docs/AGENT_MCP_DEPLOYMENT.md`。

## Windows 快速流程

如果用户给的是 `LabFactory-*-Setup.exe`，先运行安装包。默认安装位置通常是：

```text
%LOCALAPPDATA%\Programs\Lab Factory\lab-factory.exe
```

如果用户给的是 zip，解压后优先找：

```text
dist\windows\lab-factory.exe
```

先在 PowerShell 运行：

```powershell
& "C:\实际路径\lab-factory.exe" status
& "C:\实际路径\lab-factory.exe" check-runtime
& "C:\实际路径\lab-factory.exe" mcp-smoke
```

如果用户要接入 Claude Code：

```powershell
& "C:\实际路径\lab-factory.exe" install --target claude
```

如果用户要接入 Codex：

```powershell
& "C:\实际路径\lab-factory.exe" install --target codex
```

如果两个都接入：

```powershell
& "C:\实际路径\lab-factory.exe" install --target both
```

## macOS 快速流程

解压后优先找：

```text
dist/macos/lab-factory
```

macOS 包不会包含 `LabFactory-*-Setup.exe` 或 `lab-factory.exe`，这是正常的；macOS 可执行文件名是 `lab-factory`。

建议先把二进制复制到固定位置：

```bash
mkdir -p "$HOME/.local/bin"
cp "/解压目录/lab-factory-macos-arm64/dist/macos/lab-factory" "$HOME/.local/bin/lab-factory"
chmod +x "$HOME/.local/bin/lab-factory"
```

如果运行时出现 `Security policy would not allow process`、`killed: 9`、退出码 `137`，或 macOS 提示无法验证开发者，说明这个免费测试版二进制被 Gatekeeper quarantine 拦截。确认来源可信后，执行：

```bash
xattr -dr com.apple.quarantine "$HOME/.local/bin/lab-factory"
```

然后运行：

```bash
"$HOME/.local/bin/lab-factory" status
"$HOME/.local/bin/lab-factory" check-runtime
"$HOME/.local/bin/lab-factory" mcp-smoke
"$HOME/.local/bin/lab-factory" install --target both
```

## 授权参数

如果用户提供了授权服务地址，安装时加上：

```bash
--auth-url "https://授权服务地址" --product-id "lab-skill-factory-beta"
```

示例：

```bash
"/actual/path/lab-factory" install --target both --auth-url "https://授权服务地址" --product-id "lab-skill-factory-beta"
```

如果用户提供了激活码，运行：

```bash
"/actual/path/lab-factory" activate "激活码"
```

## 不要这样判断 MCP

不要通过直接运行下面命令是否停在前台来判断 MCP 是否可用：

```bash
lab-factory serve-mcp
```

`serve-mcp` 是 stdio MCP 子进程，只接受 MCP JSON-RPC 输入。请始终用：

```bash
lab-factory mcp-smoke
```

## 部署完成后回复用户

回复时只需要说明：

- 找到的 Lab Factory 路径。
- 已接入的客户端：Claude Code、Codex，或两者。
- `mcp-smoke` 是否通过。
- 是否已经激活。
- 是否需要重启 Claude Code/Codex。

不要在部署阶段开始创建实验报告 skill。
