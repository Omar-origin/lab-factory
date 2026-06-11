# Lab Factory 免费测试版 Windows/macOS 使用说明

这份说明给内测用户使用。Lab Factory 的定位不是直接代写实验报告，而是帮助用户根据课程模板、老师要求和参考材料，定制一个用户可见、可编辑、可迭代的专属实验报告 skill，再由这个专属 skill 辅助完成草稿、占位、写回和二次整理。

当前版本是免费测试版，发行包未代码签名。Windows 可能出现 SmartScreen 提醒，macOS 可能提示无法验证开发者。请只把安装包发给可信测试用户。

## 下载安装包

下载页：

```text
https://github.com/Omar-origin/lab-factory/releases/tag/v0.1.0-beta.9
```

如果仓库是私有仓库，用户必须先拥有仓库访问权限。没有权限的用户看不到下载入口，需要你单独把压缩包发给他，或后续改成公开 Release。

下载文件：

- Windows 用户下载 `lab-factory-windows-x64.zip`。
- Apple Silicon Mac 用户下载 `lab-factory-macos-arm64.zip`。

当前 macOS 包只面向 Apple Silicon，也就是 M1/M2/M3/M4 这类 arm64 Mac。Intel Mac 暂时不在这个发行包范围内。

## Windows 安装

1. 解压 `lab-factory-windows-x64.zip`。

2. 打开解压后的 `installer` 文件夹，运行：

   ```text
   LabFactory-0.1.0-beta.9-Setup.exe
   ```

3. 如果 Windows 弹出 SmartScreen，确认来源可信后选择“更多信息”再选择“仍要运行”。这是因为免费测试版暂未做代码签名。

4. 安装完成后，默认安装位置通常是：

   ```text
   %LOCALAPPDATA%\Programs\Lab Factory
   ```

5. 打开 PowerShell，运行基础检查：

   ```powershell
   & "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" status
   & "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" check-runtime
   & "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" mcp-smoke
   ```

如果你安装时选择了其他目录，把命令里的路径替换成实际安装目录。

## macOS 安装

1. 解压 `lab-factory-macos-arm64.zip`。

2. 把二进制文件放到一个固定位置，例如：

   ```bash
   mkdir -p "$HOME/.local/bin"
   cp ~/Downloads/lab-factory-macos-arm64/dist/macos/lab-factory "$HOME/.local/bin/lab-factory"
   chmod +x "$HOME/.local/bin/lab-factory"
   ```

   macOS 包不会包含 `LabFactory-*-Setup.exe` 或 `lab-factory.exe`，这是正常的；macOS 可执行文件名是 `lab-factory`。如果你的解压目录不是 `~/Downloads/lab-factory-macos-arm64`，把上面的路径换成实际路径。

3. 如果 macOS 提示无法打开或无法验证开发者，或者运行时出现退出码 `137`、`killed: 9`、`Security policy would not allow process`，说明免费测试版被 Gatekeeper quarantine 拦截。确认来源可信后运行：

   ```bash
   xattr -dr com.apple.quarantine "$HOME/.local/bin/lab-factory"
   ```

4. 运行基础检查：

   ```bash
   "$HOME/.local/bin/lab-factory" status
   "$HOME/.local/bin/lab-factory" check-runtime
   "$HOME/.local/bin/lab-factory" mcp-smoke
   ```

5. 如果希望之后直接输入 `lab-factory`，把 `~/.local/bin` 加到 PATH。zsh 用户可以运行：

   ```bash
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
   source ~/.zshrc
   lab-factory status
   ```

## 激活测试版

如果你已经部署了远程授权服务，用户需要使用你发给他的激活码。示例里的授权地址要换成你自己的地址。

Windows PowerShell：

```powershell
$env:LAB_FACTORY_AUTH_URL="https://your-auth-domain.example"
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" activate "BETA-你的激活码"
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" status
```

macOS：

```bash
LAB_FACTORY_AUTH_URL="https://your-auth-domain.example" lab-factory activate "BETA-你的激活码"
LAB_FACTORY_AUTH_URL="https://your-auth-domain.example" lab-factory status
```

如果还没有部署远程授权服务，可以让免费内测用户通过安装器的 `--dev-allow` 模式使用。该模式只用于免费测试版，不应作为正式商业授权方案。

Windows：

```powershell
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" install --target both --dev-allow
```

macOS：

```bash
lab-factory install --target both --dev-allow
```

## 接入 Codex

Windows：

```powershell
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" install `
  --target codex `
  --auth-url "https://your-auth-domain.example" `
  --product-id "lab-skill-factory-beta"
```

macOS：

```bash
lab-factory install \
  --target codex \
  --auth-url "https://your-auth-domain.example" \
  --product-id "lab-skill-factory-beta"
```

这个命令会把 MCP 配置写入 Codex 配置文件。写入后重启 Codex，或重新打开当前 Codex 会话。

如果只是想先看会写入什么配置，不真正修改文件，可以加 `--dry-run`：

```bash
lab-factory install --target codex --auth-url "https://your-auth-domain.example" --dry-run
```

## 接入 Claude Code

Windows：

```powershell
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" install `
  --target claude `
  --auth-url "https://your-auth-domain.example" `
  --product-id "lab-skill-factory-beta"
```

macOS：

```bash
lab-factory install \
  --target claude \
  --auth-url "https://your-auth-domain.example" \
  --product-id "lab-skill-factory-beta"
```

Claude Code 需要本机已经安装并登录 `claude` CLI。如果命令提示找不到 `claude CLI`，说明用户还没有安装 Claude Code 的命令行工具。此时可以先让用户安装 Claude Code，或者让他使用命令输出里的手动 MCP 配置。

当前安装命令默认写入 Claude Code 的 `user` scope，也就是对该用户的所有项目生效。如果只想对当前项目生效，可以额外加：

```bash
--claude-scope local
```

如果某个 Claude Code 版本提示 `mcp add` 参数格式不兼容，可以使用下面的手动命令。注意 `--` 必须放在环境变量参数和 `lab-skill-factory` 之间。

Windows 示例：

```powershell
claude mcp add --scope user `
  -e LAB_FACTORY_AUTH_URL=https://your-auth-domain.example `
  -e LAB_FACTORY_PRODUCT_ID=lab-skill-factory-beta `
  -- lab-skill-factory `
  "C:\你安装的路径\Lab Factory\lab-factory.exe" `
  serve-mcp
```

macOS 示例：

```bash
claude mcp add --scope user \
  -e LAB_FACTORY_AUTH_URL=https://your-auth-domain.example \
  -e LAB_FACTORY_PRODUCT_ID=lab-skill-factory-beta \
  -- lab-skill-factory \
  "$HOME/.local/bin/lab-factory" \
  serve-mcp
```

## 第一次使用建议话术

接入 MCP 并重启客户端后，在 Codex 或 Claude Code 里这样说：

```text
请使用 lab-skill-factory。
这是我的实验报告模板：/你的/实验报告模板.docx
请先完整浏览模板并复述任务要求，然后一步步问我：
1. 哪些部分需要填写；
2. 有没有老师要求、课程要求或参考案例；
3. 有没有固定格式规范；
4. 需要填写哪些个人信息；
5. 文件命名方式是什么；
6. 是否必须使用指定软件、代码环境或实验工具。
需求确认清楚后，再帮我生成这个科目的专属实验报告 skill。
```

如果用户有参考案例，可以一开始就提供：

```text
参考案例只用于学习格式、篇幅、排版和老师偏好，不能照抄内容。
参考案例路径：/你的/参考案例.docx
```

如果你想让 Claude Code 或 Codex 直接帮你部署 MCP，而不是自己复制命令，可以把下面这份文档一起发给它：

```text
docs/AGENT_MCP_DEPLOYMENT.md
```

然后告诉它：

```text
请阅读 AGENT_MCP_DEPLOYMENT.md，并根据我的 lab-factory 可执行文件路径，帮我把 Lab Factory 部署为 MCP server。
```

## 推荐工作流程

1. 用户提供实验报告模板、任务书、老师要求、参考案例、源码或数据文件。

2. Agent 调用 Lab Factory 浏览材料，复述实验目的、提交要求、文件命名要求、必须使用的工具和需要填写的位置。

3. Agent 一问一答确认需求，不要一次性把所有问题抛给用户。

4. Lab Factory 生成该课程或该模板系列的专属 skill。

5. 专属 skill 先生成 `fill.md`，里面只包含用户确认要填补的内容、截图占位、用户待办和免责声明。

6. 用户确认 `fill.md` 没问题后，专属 skill 再复制原始 DOCX/MD，并根据 `fill-map.json` 把内容填入副本。

7. 第一版草稿只填补，不删除原文，不主动改原结构、字体、字号、排版。

8. 用户补充截图、真实数据或个人信息后，再让 agent 进行二次整理。

9. 二次整理阶段才允许删除用户确认可删的提示文字、统一排版、添加最终免责声明。

10. 用户确认最终结果后，agent 询问是否根据本次经验迭代专属 skill。只有用户确认后才更新规则。

## 常用命令

查看状态：

```bash
lab-factory status
```

检查运行依赖：

```bash
lab-factory check-runtime
```

检查 MCP stdio 握手：

```bash
lab-factory mcp-smoke
```

不要用“直接运行 `lab-factory serve-mcp` 是否有输出”来判断 MCP 是否正常。`serve-mcp` 是给 MCP 客户端启动的 stdio 子进程，正常情况下只读写 MCP JSON-RPC 消息；人工终端没有发送协议消息时，它没有普通交互界面。

查看 MCP 配置示例：

```bash
lab-factory export-config --client codex
lab-factory export-config --client claude_code
lab-factory export-config --client generic_stdio
```

清点实验材料：

```bash
lab-factory inspect /path/to/实验报告模板.docx /path/to/参考案例.docx
```

抽取 DOCX 结构：

```bash
lab-factory extract-docx /path/to/实验报告模板.docx
```

运行内置烟测：

```bash
lab-factory test
```

注意：`test` 属于开发和验收命令，普通用户一般不需要运行。

## 用户专属 skill 存放与修改

生成出来的专属 skill 建议让用户看见并可以修改。它本质上是用户自己的课程规则沉淀，里面应该只保存：

- 课程或模板的写作流程。
- 常见章节和填写规则。
- 格式要求和默认参数。
- 需要追问用户的问题。
- 截图、数据、代码、工具环境的处理方式。
- 用户确认后的迭代记录。

不要把以下内容写进专属 skill：

- 姓名、学号、账号、密码、token。
- 完整实验报告正文。
- 未脱敏的原始数据、截图、私有源码。
- 老师未公开材料或用户不希望长期保存的内容。

## 卸载

Windows：

1. 打开“设置”。
2. 进入“应用”。
3. 找到 `Lab Factory` 并卸载。

也可以运行安装目录里的 `unins000.exe`。

macOS：

1. 删除二进制文件：

   ```bash
   rm "$HOME/.local/bin/lab-factory"
   ```

2. 如果接入过 Codex，打开 `~/.codex/config.toml`，删除 `[mcp_servers.lab-skill-factory]` 相关配置。

3. 如果接入过 Claude Code，可以尝试：

   ```bash
   claude mcp remove lab-skill-factory
   ```

   如果 Claude Code 版本不支持这个命令，就在 Claude Code 的 MCP 配置中手动删除 `lab-skill-factory`。

## 常见问题

### GitHub 页面没有下载入口

先确认用户是否有私有仓库权限。没有权限时看不到 Release 附件。你可以把 zip 单独发给他，或后续把 Release 改成公开。

### Windows 提示有风险或无法运行

这是因为免费测试版还没有代码签名。确认文件来源可信后，可以从 SmartScreen 里选择“更多信息”再运行。正式商业化前应补齐代码签名。

### macOS 提示无法验证开发者

运行：

```bash
xattr -dr com.apple.quarantine "$HOME/.local/bin/lab-factory"
```

然后再执行：

```bash
"$HOME/.local/bin/lab-factory" status
```

### 客户端里看不到 lab-skill-factory

先确认安装配置命令是否执行成功：

```bash
lab-factory install --target codex --auth-url "https://your-auth-domain.example" --dry-run
```

然后重启 Codex 或 Claude Code。MCP 是客户端启动时加载的，很多情况下不重启不会生效。

### 激活失败

检查四件事：

- 激活码有没有输错。
- `LAB_FACTORY_AUTH_URL` 或 `--auth-url` 是否是正确的授权服务地址。
- 用户电脑能不能访问授权服务。
- 激活码是否超过设备数量限制或已过期。

### DOCX 格式被破坏

当前策略是先复制原文件，再尽量按锚点填补内容，不主动重排和删改。但复杂 DOCX 仍可能有风险，例如文本框、浮动图片、嵌入对象、公式、批注、修订模式等。遇到这类模板，应让 agent 只生成 `fill.md` 和插入位置说明，必要时由用户手动粘贴。

## 合规提醒

Lab Factory 生成的内容仅供学习参考。用户需要自行核验实验数据、代码运行结果、截图、结论和课程规范。不要把参考示例伪装成真实实验结果，也不要用它绕过课程或学校的学术要求。
