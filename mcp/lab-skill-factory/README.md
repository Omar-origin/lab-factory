# Lab Factory 免费测试版

这是 `skills/lab-skill-factory` 的产品包装层。当前定位不是黑盒代写实验报告，而是：

- 一个 CLI 产品入口：`lab-factory`。
- 一个标准 stdio MCP 接口：`lab-factory serve-mcp`。
- 一套用户可见、可编辑、可迭代的专属科目 skill 生成流程。

核心工厂逻辑负责材料清点、DOCX/MD 解析、模板保全、spec 校验、专属 skill 脚手架、fill-map 校验和受控写回；专属 skill 负责某个用户、某门课、某类模板的实际实验报告流程。

## 当前能力

- `lab_factory_status`：查看激活状态和本地配置。
- `lab_factory_activate`：输入免费测试版激活码。
- `lab_factory_check_runtime`：检查 DOCX/MD 处理依赖。
- `lab_factory_export_client_config`：导出 Claude Code、Codex 或通用 stdio MCP 配置。
- `lab_factory_inspect_materials`：清点任务书、模板、参考案例、源码、截图和数据。
- `lab_factory_extract_docx_outline`：抽取 DOCX 段落、表格、锚点和文末提交要求。
- `lab_factory_validate_skill_spec`：校验定制前的 `skill-spec.md`。
- `lab_factory_scaffold_subject_skill`：生成用户可编辑的专属科目/模板 skill。
- `lab_factory_validate_scaffolded_skill`：校验生成后的专属 skill。
- `lab_factory_validate_fill_map`：校验专属 skill 生成的 `fill-map.json`。
- `lab_factory_apply_fill_map`：复制 DOCX/MD 原文件并按 fill-map 填入副本，源文件保持只读。
- `lab_factory_get_factory_guidance`：返回流程、授权、兼容性和质量边界建议。

## CLI 使用

源码模式：

```bash
python3 /Users/omar/Documents/New\ project/mcp/lab-skill-factory/cli.py status
python3 /Users/omar/Documents/New\ project/mcp/lab-skill-factory/cli.py check-runtime
python3 /Users/omar/Documents/New\ project/mcp/lab-skill-factory/cli.py serve-mcp
```

二进制模式：

```bash
/path/to/lab-factory status
/path/to/lab-factory check-runtime
/path/to/lab-factory serve-mcp
```

常用 CLI 子命令：

```bash
lab-factory activate <activation-code>
lab-factory inspect <材料路径...>
lab-factory extract-docx <模板.docx>
lab-factory validate-spec <skill-spec.md>
lab-factory scaffold-skill <skill-spec.md> <输出目录>
lab-factory validate-skill <专属skill目录>
lab-factory validate-fill-map <fill-map.json>
lab-factory apply-fill-map <fill-map.json> --output <草稿副本.docx>
lab-factory test
```

## MCP 接入

MCP server 的启动方式统一为：

```bash
lab-factory serve-mcp
```

源码模式配置示例：

```json
{
  "mcpServers": {
    "lab-skill-factory": {
      "command": "python3",
      "args": [
        "/Users/omar/Documents/New project/mcp/lab-skill-factory/cli.py",
        "serve-mcp"
      ],
      "env": {
        "LAB_FACTORY_SKILL_ROOT": "/Users/omar/Documents/New project/skills/lab-skill-factory",
        "LAB_FACTORY_LICENSE_DB": "/Users/omar/Documents/New project/mcp/lab-skill-factory/activation_codes.json"
      }
    }
  }
}
```

二进制模式配置示例：

```json
{
  "mcpServers": {
    "lab-skill-factory": {
      "command": "/path/to/lab-factory",
      "args": ["serve-mcp"],
      "env": {
        "LAB_FACTORY_AUTH_URL": "https://your-domain.example",
        "LAB_FACTORY_PRODUCT_ID": "lab-skill-factory-beta"
      }
    }
  }
}
```

配置示例文件在：

- `client-configs/claude-code.example.json`
- `client-configs/codex.example.toml`
- `client-configs/generic-stdio.example.json`

也可以连接 MCP 后调用 `lab_factory_export_client_config`，传入 `claude_code`、`codex` 或 `generic_stdio`。

## 安装脚本

源码内测安装：

```bash
python3 /Users/omar/Documents/New\ project/mcp/lab-skill-factory/cli.py install --target both
```

二进制内测安装：

```bash
/path/to/lab-factory install \
  --target both \
  --auth-url https://your-domain.example \
  --product-id lab-skill-factory-beta
```

先查看将写入的配置：

```bash
/path/to/lab-factory install --target both --dry-run
```

`--target` 可以是 `claude`、`codex` 或 `both`。Claude Code 依赖本机 `claude` CLI；Codex 默认写入 `~/.codex/config.toml`，可用 `--codex-config` 指定路径。

## 用户可编辑专属 skill

生成出来的专属 skill 建议可见、可编辑。它只保存课程级流程、模板结构、填写规则、默认格式、常见提问、finalize 边界和版本记录。

不能写入专属 skill 的内容：

- 姓名、学号、账号、密码、token。
- 完整报告正文、原始数据、截图、私有源码。
- 老师未公开材料或用户不希望沉淀的私人资料。

这样产品形态就是：核心 CLI/MCP 尽量受保护，用户自己的课程规则层保持透明、可改、可迭代。

## Python 依赖

当前核心 MCP 只依赖 Python 标准库。DOCX 写回阶段推荐随产品打包：

- 必带：`python-docx`、`lxml`。
- 可选增强：`docxtpl`、`mammoth`、`pywin32`。

默认策略仍然是 `python-docx + lxml`：先完整复制原文件，再尽量按锚点填补，不主动重排、不主动删原内容。`docxtpl` 只适合受控占位符模板；`mammoth` 更适合只读抽取；`pywin32` 只适合 Windows + Microsoft Word 自动化增强。

## 远程授权

免费内测也建议走远程授权链路，方便后续升级为付费授权。

启动测试服务：

```bash
LAB_AUTH_ADMIN_TOKEN="换成你的管理员token" \
python3 /Users/omar/Documents/New\ project/mcp/lab-skill-factory/auth/remote_auth_service.py \
  --host 127.0.0.1 \
  --port 8765 \
  --db /Users/omar/lab-auth.sqlite3
```

创建测试激活码：

```bash
curl -X POST https://your-domain.example/admin/create-code \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"activation_code":"BETA-001-随机码","label":"tester-001","max_devices":2}'
```

用户侧配置 `LAB_FACTORY_AUTH_URL` 后会优先走远程授权；没有配置时才使用本地 `activation_codes.json`。

## 构建发行包

macOS 构建：

```bash
bash /Users/omar/Documents/New\ project/mcp/lab-skill-factory/build/build_macos.sh
```

输出：

```text
mcp/lab-skill-factory/dist/macos/lab-factory
```

Windows 构建，在 Windows PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp\lab-skill-factory\build\build_windows.ps1
```

输出：

```text
mcp\lab-skill-factory\dist\windows\lab-factory.exe
```

Windows 安装包构建需要 Inno Setup 6：

```powershell
choco install innosetup -y
powershell -ExecutionPolicy Bypass -File .\mcp\lab-skill-factory\build\build_windows_installer.ps1
```

输出：

```text
mcp\lab-skill-factory\dist\windows\installer\LabFactory-0.1.0-beta-Setup.exe
```

安装包是每用户安装，默认安装到 `%LOCALAPPDATA%\Programs\Lab Factory`，不需要管理员权限。安装器只安装 `lab-factory.exe`、README 和客户端配置示例，并创建开始菜单入口；不会自动修改 Claude Code 或 Codex 配置。用户安装后需要明确运行：

```powershell
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" install --target codex
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" install --target claude
```

也可以直接从开始菜单打开 `Install Codex MCP Config` 或 `Install Claude Code MCP Config` 快捷方式。当前 beta 安装器不会自动修改用户 PATH。

仓库内提供 GitHub Actions workflow：`.github/workflows/build-lab-factory-beta.yml`，会在 macOS runner 和 Windows runner 分别构建并上传 artifact。Windows artifact 会同时包含 `lab-factory.exe` 和 Inno Setup 安装包。

macOS 和 Windows 不能共用同一个二进制；MCP 协议、CLI 子命令和 Python 代码是同一套，但发行包必须分别构建和测试。

## 20 个样例测试

源码模式：

```bash
python3 /Users/omar/Documents/New\ project/mcp/lab-skill-factory/cli.py test
```

二进制模式：

```bash
/path/to/lab-factory test
```

测试覆盖 20 个轻量样例：Markdown/DOCX、插入、占位替换、表格填补、截图占位、小结、工具环境和参考边界。通过条件包括输出文件存在、填补内容存在、源文件 hash 未变化。

## 商业化边界

当前是免费测试版，不等于商业级保护。正式商业化还需要：

- macOS 代码签名、公证和安装包。
- Windows Authenticode 签名、安装包和杀软误报处理。
- HTTPS 远程授权服务、后台管理、设备解绑、撤销授权和日志审计。
- 支付、订单、激活码发放、退款和客服流程。
- 自动更新机制。
- 更完整的 DOCX 复杂模板测试，尤其是页眉页脚、文本框、公式、域、嵌入对象和旧 `.doc`。
- 隐私政策、用户协议、免责声明和课程合规边界说明。
- Windows 真机测试，因为 macOS 构建出的二进制不能代表 Windows 行为。
