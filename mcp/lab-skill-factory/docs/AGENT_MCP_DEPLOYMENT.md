# Lab Factory MCP Agent 部署说明

这份文档给 Claude Code、Codex 或其他本地 coding agent 阅读。目标是：用户把已经安装好的 `lab-factory.exe` 或 macOS `lab-factory` 路径交给你，你负责把它正确接入当前用户的 MCP 客户端。

不要把这份文档当成产品介绍。你只需要完成部署、验证和向用户说明下一步。

## 你需要先向用户确认

只问必要问题，优先一问一答。

1. 用户要接入哪个客户端：Claude Code、Codex，还是两个都接入。
2. Lab Factory 可执行文件路径。
3. 是否有授权服务地址 `LAB_FACTORY_AUTH_URL`。
4. 是否有激活码。
5. 用户希望配置对所有项目生效，还是只对当前项目生效。

如果用户不清楚安装路径：

- Windows 默认可能是 `%LOCALAPPDATA%\Programs\Lab Factory\lab-factory.exe`。
- Windows 用户自选安装目录时，让用户提供实际安装目录，或让用户从开始菜单找到 `Lab Factory CLI`，右键查看文件所在位置。
- macOS 常见路径是 `$HOME/.local/bin/lab-factory`。
- macOS zip 里的实际二进制通常是 `dist/macos/lab-factory`，不会有 `.exe` 或 Windows 安装包。

激活码模式必须同时提供激活码和授权服务地址。当前发行包不内置用户激活码数据库。如果两者都没有，按免费内测模式安装并显式使用 `--dev-allow`。

## macOS 内测处理

macOS 免费测试包未做正式 Developer ID 签名和公证。部署时建议先复制到固定位置：

```bash
mkdir -p "$HOME/.local/bin"
cp "/解压目录/lab-factory-macos-arm64/dist/macos/lab-factory" "$HOME/.local/bin/lab-factory"
chmod +x "$HOME/.local/bin/lab-factory"
```

如果运行 `status`、`check-runtime` 或 `mcp-smoke` 时出现退出码 `137`、`killed: 9`、`Security policy would not allow process`，或 macOS 提示无法验证开发者，说明被 Gatekeeper quarantine 拦截。确认来源可信后执行：

```bash
xattr -dr com.apple.quarantine "$HOME/.local/bin/lab-factory"
```

然后重新执行部署前验证。

## 部署前验证

先运行可执行文件的基础命令，确认文件路径正确。

Windows PowerShell 示例：

```powershell
& "C:\实际安装路径\Lab Factory\lab-factory.exe" status
& "C:\实际安装路径\Lab Factory\lab-factory.exe" check-runtime
& "C:\实际安装路径\Lab Factory\lab-factory.exe" mcp-smoke
```

macOS/Linux 示例：

```bash
"/actual/path/lab-factory" status
"/actual/path/lab-factory" check-runtime
"/actual/path/lab-factory" mcp-smoke
```

如果路径包含空格，必须加引号。不要猜路径。

不要通过“直接运行 `serve-mcp` 是否停留在前台或是否有输出”来判断 MCP 是否可用。`serve-mcp` 是 stdio MCP 子进程，只接受 MCP JSON-RPC 输入；使用 `mcp-smoke` 做握手验证。

## 优先使用内置 install 命令

如果可执行文件版本较新，优先让 Lab Factory 自己写配置。

Claude Code：

```powershell
& "C:\实际安装路径\Lab Factory\lab-factory.exe" install --target claude --auth-url "https://授权服务地址" --product-id "lab-skill-factory-beta"
```

Codex：

```powershell
& "C:\实际安装路径\Lab Factory\lab-factory.exe" install --target codex --auth-url "https://授权服务地址" --product-id "lab-skill-factory-beta"
```

两个都接入：

```powershell
& "C:\实际安装路径\Lab Factory\lab-factory.exe" install --target both --auth-url "https://授权服务地址" --product-id "lab-skill-factory-beta"
```

免费内测且没有激活码、授权地址时：

```powershell
& "C:\实际安装路径\Lab Factory\lab-factory.exe" install --target both --dev-allow
```

macOS/Linux 只需要把前面的 exe 路径换成实际二进制路径：

```bash
"/actual/path/lab-factory" install --target both --auth-url "https://授权服务地址" --product-id "lab-skill-factory-beta"
```

免费内测：

```bash
"/actual/path/lab-factory" install --target both --dev-allow
```

Claude Code 中项目级同名 MCP server 会覆盖用户级 server，而不是自动合并。安装器会读取当前有效的同名配置并合并 `env`，因此不要绕过安装器手写一份缺少授权变量的项目配置。

如果只是预览配置，不真正写入：

```bash
"/actual/path/lab-factory" install --target both --auth-url "https://授权服务地址" --dry-run
```

## Claude Code 手动部署

如果内置 `install --target claude` 失败，使用 Claude Code CLI 手动添加 MCP server。

重要：`-e` 和 `--env` 在部分 Claude Code 版本里是可变参数，必须在环境变量参数后放一个单独的 `--`，再写 server 名称和命令。不要使用旧格式：

```text
claude mcp add --transport stdio --env KEY=value lab-skill-factory -- command serve-mcp
```

这个旧格式在一些版本里会把 `lab-skill-factory` 当成环境变量参数，导致报错。

正确格式如下。

Windows PowerShell：

```powershell
claude mcp add --scope user `
  -e LAB_FACTORY_AUTH_URL=https://授权服务地址 `
  -e LAB_FACTORY_PRODUCT_ID=lab-skill-factory-beta `
  -- lab-skill-factory `
  "C:\实际安装路径\Lab Factory\lab-factory.exe" `
  serve-mcp
```

macOS/Linux：

```bash
claude mcp add --scope user \
  -e LAB_FACTORY_AUTH_URL=https://授权服务地址 \
  -e LAB_FACTORY_PRODUCT_ID=lab-skill-factory-beta \
  -- lab-skill-factory \
  "/actual/path/lab-factory" \
  serve-mcp
```

如果用户要求只对当前项目生效，把 `--scope user` 改成：

```text
--scope local
```

如果用户还没有授权服务，只是开发者临时内测，可以用下面的临时方式。不要把它作为正式分发方案。

```powershell
claude mcp add --scope user `
  -e LAB_FACTORY_DEV_ALLOW=1 `
  -- lab-skill-factory `
  "C:\实际安装路径\Lab Factory\lab-factory.exe" `
  serve-mcp
```

完成后验证：

```bash
claude mcp list
```

然后让用户重启 Claude Code。

## Codex 手动部署

如果内置 `install --target codex` 失败，手动编辑 Codex 配置文件：

```text
~/.codex/config.toml
```

Windows 下也可以让用户提供 Codex 配置文件实际位置；不要覆盖用户已有配置，只追加或替换 `lab-skill-factory` 这一段。

推荐 TOML：

```toml
[mcp_servers.lab-skill-factory]
command = "C:/实际安装路径/Lab Factory/lab-factory.exe"
args = ["serve-mcp"]

[mcp_servers.lab-skill-factory.env]
LAB_FACTORY_AUTH_URL = "https://授权服务地址"
LAB_FACTORY_PRODUCT_ID = "lab-skill-factory-beta"
```

Windows TOML 里推荐使用正斜杠 `/`，例如：

```toml
command = "C:/Users/omar/AppData/Local/Programs/Lab Factory/lab-factory.exe"
```

如果必须使用反斜杠，需要写成双反斜杠：

```toml
command = "C:\\Users\\omar\\AppData\\Local\\Programs\\Lab Factory\\lab-factory.exe"
```

开发者临时内测可以使用：

```toml
[mcp_servers.lab-skill-factory.env]
LAB_FACTORY_DEV_ALLOW = "1"
```

不要在正式用户配置里使用 `LAB_FACTORY_DEV_ALLOW=1`。

完成后让用户重启 Codex。

## 激活

如果配置了授权服务，接入后需要激活。

Windows：

```powershell
$env:LAB_FACTORY_AUTH_URL="https://授权服务地址"
& "C:\实际安装路径\Lab Factory\lab-factory.exe" activate "用户的激活码" --auth-url "https://授权服务地址"
```

macOS/Linux：

```bash
"/actual/path/lab-factory" activate "用户的激活码" --auth-url "https://授权服务地址"
```

如果用户通过 MCP 调用 `lab_factory_activate`，也可以输入同一个激活码。

激活后再运行：

```bash
"/actual/path/lab-factory" status
```

状态中应显示已激活，或显示远程授权 token 已保存。

## 部署完成后的测试话术

让用户在 Claude Code 或 Codex 里输入：

```text
请使用 lab-skill-factory，先检查工具状态。不要开始写实验报告，只告诉我 MCP 是否能正常调用。
```

如果能正常调用，再让用户测试完整流程：

```text
请使用 lab-skill-factory。
这是我的实验报告模板：<文件路径>
请先完整浏览模板并复述任务要求，然后一步步问我需要填写哪些部分、有没有老师要求或参考案例、格式规范、个人信息、文件命名方式和必须使用的实验工具。确认清楚后，再帮我生成这个科目的专属实验报告 skill。
```

## 不要做的事

- 不要直接改用户实验报告原文件。
- 不要替用户伪造真实实验数据、截图、运行结果。
- 不要把激活码、姓名、学号、账号、密码写进专属 skill。
- 不要覆盖用户已有 Claude Code 或 Codex 配置。
- 不要把 `LAB_FACTORY_DEV_ALLOW=1` 当成正式用户方案。
- 不要使用 Claude Code 的旧错误格式：环境变量参数后没有 `--` 就直接写 server 名。

## 排错

### Claude Code 报 Invalid environment variable format

原因通常是 `-e/--env` 后面没有用 `--` 结束选项解析。

改用：

```bash
claude mcp add --scope user -e KEY=value -- lab-skill-factory "/path/to/lab-factory" serve-mcp
```

### Claude Code 添加成功但新项目看不到

检查是否用了 `--scope local`。如果想所有项目可见，使用：

```bash
claude mcp add --scope user ...
```

### Codex 启动后看不到工具

检查 `~/.codex/config.toml` 里是否存在：

```toml
[mcp_servers.lab-skill-factory]
```

确认 `command` 路径存在，并重启 Codex。

### MCP 能看到但调用受保护工具失败

检查是否已激活。运行：

```bash
"/actual/path/lab-factory" status
```

如果显示未激活，先执行 `activate`，或确认 `LAB_FACTORY_AUTH_URL` 是否正确。
