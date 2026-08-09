# Lab Factory MCP

Lab Factory 1.x 是面向课程实验报告工作流的本地 MCP 工具。当前付费内测采用纯离线人工闭环，不需要服务器、域名、数据库或支付接口。

## v2.1 报告自动驾驶

新报告以可用 DOCX 为产品入口：首次确认 8 维稳定偏好并完整披露模板/默认格式，之后自动推进低风险步骤，只在结构变化、低置信度定位、硬门禁和最终 DOCX 处暂停。专属 Skill 在报告完成后以学习摘要形式受控更新。

主要 MCP 工具：

- `lab_factory_v2_prepare_autopilot`
- `lab_factory_v2_answer_questions`
- `lab_factory_v2_confirm_checkpoint`
- `lab_factory_v2_advance_autopilot`
- `lab_factory_v2_autopilot_status`

默认使用 `balanced`，正常任务只有 preflight 和最终 DOCX 两个常规确认点。旧 v2.0 会话继续使用 strict 流程；`fast` 暂未开放。

## 当前商业闭环

- 用户通过微信/支付宝向你付款。
- 用户运行 `license-request` 生成本机 `.lfreq` 文件并发给你。
- 你在自己的设备上用 Ed25519 私钥签发 `.lflicense`，再发回用户。
- 客户端只内置公钥，导入后永久离线验签；私钥永不进入发行包。
- 授权绑定随机安装 ID，不读取用户名、机器名或硬件指纹。
- 使用数据默认不记录；用户同意后仅在本机记录白名单字段，主动导出后自行发邮件。
- 更新包由你人工发送，用户先核对 SHA-256，再按说明安装。
- 草稿/终稿固定追加一次 AI 辅助生成声明，无法安全追加时阻止 Finalize。

离线方案的明确限制：已经发出的许可证无法远程吊销，也无法自动限制换绑频率。换机、退款例外和分销统计都通过本地签发台账人工处理。

## 首次初始化签发者

只执行一次。私钥路径应放在仓库外，并做离线备份：

```bash
python3 mcp/lab-skill-factory/auth/commercial_admin.py init-issuer \
  --private-key ~/.lab-factory-issuer/issuer-private.json \
  --public-key mcp/lab-skill-factory/license_public_key.json
```

然后重新构建发行包，公钥会被打包进去。不要提交或发送私钥。

## 每次签发

```bash
python3 mcp/lab-skill-factory/auth/commercial_admin.py issue-license \
  --private-key ~/.lab-factory-issuer/issuer-private.json \
  --request 用户设备.lfreq \
  --output 用户设备.lflicense \
  --channel-id campus-a \
  --customer-ref order-001
```

默认台账保存在私钥同目录的 `license-ledger.jsonl`。只把 `.lflicense` 发给对应用户。

## 用户使用

```bash
lab-factory install --target both --purchase-url "微信联系销售者" \
  --support-email support@example.com --feedback-email feedback@example.com
lab-factory license-request --output device.lfreq
lab-factory activate device.lflicense --accept-terms-version 1.0 --confirm-age-18
lab-factory telemetry enable
lab-factory feedback-export --output lab-factory-feedback.json
lab-factory verify-update 新安装包 --sha256 <你公布的SHA-256>
```

## 开发与测试

```bash
python3 -m pip install -r mcp/lab-skill-factory/runtime-requirements.txt
python3 mcp/lab-skill-factory/scripts/run_beta_smoke_tests.py
python3 mcp/lab-skill-factory/scripts/run_v2_tests.py
python3 mcp/lab-skill-factory/scripts/run_autopilot_tests.py
python3 mcp/lab-skill-factory/scripts/test_install_and_activation.py
python3 mcp/lab-skill-factory/scripts/test_commercial_flow.py
```

源码开发可临时设置 `LAB_FACTORY_DEV_ALLOW=1`；冻结发行包忽略该变量。

详细说明见 [离线授权与人工商业闭环](docs/OFFLINE_LICENSING.md)、[用户指南](USER_GUIDE.md) 和 [跨平台说明](docs/WINDOWS_MAC_USAGE.md)。
