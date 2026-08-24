# Lab Factory

Lab Factory 是面向课程实验报告工作流的本地 MCP 工具与 Skill Factory，帮助用户根据课程材料和指定模板定制实验报告专属 skill，并在本地完成 DOCX 报告处理。

## 官网

产品介绍、购买与订单查询：<https://lab.alan.elyther.top/buy>

## 项目内容

- `skills/lab-skill-factory/`：实验报告专属 skill 工厂及 v2 工作流。
- `skills/universal-lab-report/`：通用实验报告 skill。
- `mcp/lab-skill-factory/`：Lab Factory MCP 服务端、客户端、授权流程和 Cloudflare 商业中控。
- `mcp/lab-skill-factory/docs/`：部署、用户使用和商业授权文档。

报告内容默认在本地处理；在线服务只负责商业授权和短期租约，不读取用户的报告正文。

## 快速开始

安装运行时依赖：

```bash
python3 -m pip install -r mcp/lab-skill-factory/runtime-requirements.txt
```

运行测试：

```bash
python3 mcp/lab-skill-factory/scripts/run_beta_smoke_tests.py
python3 mcp/lab-skill-factory/scripts/run_v2_tests.py
python3 mcp/lab-skill-factory/scripts/run_autopilot_tests.py
```

用户安装 MCP 配置：

```bash
lab-factory install --target both \
  --purchase-url "https://lab.alan.elyther.top/buy" \
  --support-email "QQ群923937311" \
  --feedback-email "QQ群923937311" \
  --control-url "https://lab.alan.elyther.top"
```

## 文档

- [MCP 使用与开发说明](mcp/lab-skill-factory/README.md)
- [给安装代理的指令](mcp/lab-skill-factory/INSTALL_FOR_AGENT.md)
- [Windows / macOS 使用说明](mcp/lab-skill-factory/docs/WINDOWS_MAC_USAGE.md)
- [Cloudflare 商业中控部署](mcp/lab-skill-factory/docs/CLOUDFLARE_COMMERCIAL_DEPLOYMENT.md)
- [Lab Skill Factory 说明](skills/lab-skill-factory/README.md)

## 安全提示

不要将管理员 Token、数据库 Secret、租约私钥、许可证私钥或本地激活文件提交到仓库。发布更新包时，请先公布 SHA-256，用户核对后再安装。
