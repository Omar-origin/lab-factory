# Lab Factory MCP

Lab Factory 1.x 是面向课程实验报告工作流的本地 MCP 工具。当前商业主线采用轻量密钥中控：一个密钥绑定一个安装，通过 24 小时签名租约支持退款和违规封禁；报告处理仍完全在本地。

## v2.1 报告自动驾驶

新报告以可用 DOCX 为产品入口。首次使用可选提供 1–3 份本人旧实验报告做本地写作校准；没有时按安装身份分配稳定 writer capsule。系统在 preflight 完整披露写作身份、报告级变化、身份化去模板腔策略和模板/默认格式，之后自动推进低风险步骤，只在结构变化、低置信度定位、事实或差异化硬门禁和最终 DOCX 处暂停。专属 Skill 在报告完成后以学习摘要形式受控更新，旧报告和本次报告正文都不写入画像或 Skill。

主要 MCP 工具：

- `lab_factory_v2_analyze_writing_samples`（可选；首次校准，任意科目 1–3 份）
- `lab_factory_v2_prepare_autopilot`
- `lab_factory_v2_answer_questions`
- `lab_factory_v2_confirm_checkpoint`
- `lab_factory_v2_advance_autopilot`
- `lab_factory_v2_autopilot_status`
- `lab_factory_v2_humanization_audit`
- `lab_factory_v2_document_structure_audit`
- `lab_factory_v2_cohort_similarity`

每份报告在正文生成前都会选定结构原型并建立图表登记表。图片、截图、绘图和表格按单项占位，预先给出编号、名称和正文引用；存在真实行列数据时会保留表格或编号表格占位。跨报告比较同时检查文字与结构流，因此仅替换题目、类名和数据库名而复用同一排版骨架会被阻止。

默认使用 `balanced`，正常任务只有 preflight 和最终 DOCX 两个常规确认点。旧 v2.0 会话继续使用 strict 流程；`fast` 暂未开放。

## 当前商业授权

- 同一个 Windows/macOS 安装包支持两种密钥：9.9 元体验版可创建 3 个报告会话且不能凝练/更新 Skill；49.9 元永久版不限报告次数并解锁 Skill 凝练。
- 体验版额度按服务端的稳定报告 ID 幂等记账，重试不重复扣次，重装不会恢复额度；因此创建新的体验版报告时必须能连接授权中控。
- 用户从独立 `/buy` 页面创建订单，通过支付宝经营码付款；GitHub 只提供购买链接和发行说明。
- 首发暂只开放支付宝经营码，售后与激活协助QQ群为 `923937311`。
- 用户提交交易号/备注和付款时间，你在商户记录中人工核款，不接收付款截图。
- 你在中控核对到账后点击一次“确认到账并自动发货”；系统原子生成密钥，用户凭订单 Token 在订单页直接领取。
- 用户运行 `activate-key`，中控原子绑定随机安装 ID 和安装公钥，列表立即显示“已使用”。
- 客户端每次启动尝试刷新，之后每 6 小时刷新；签名租约最长 24 小时。
- 异常退款经人工确认、完成退款或违规封禁后不再续租，最迟 24 小时后停止使用；用户侧不提供自助无理由退款。
- 授权准确表述为“绑定一个安装”，不读取用户名、机器名或硬件指纹，也不处理共享电脑和完整克隆。
- 使用数据默认不记录；用户同意后仅在本机记录白名单字段，主动导出后自行发邮件。
- 更新包由你人工发送，用户先核对 SHA-256，再按说明安装。
- 草稿/终稿固定追加一次 AI 辅助生成声明，无法安全追加时阻止 Finalize。

原有 `.lfreq` / `.lflicense` 离线流程保留为兼容入口，但无法远程封禁，不再作为新商业密钥的默认流程。

## 密钥中控快速开始

完整部署见 [在线密钥中控与 24 小时租约](docs/REMOTE_AUTH_DEPLOYMENT.md) 和 [Cloudflare 商业中控部署](docs/CLOUDFLARE_COMMERCIAL_DEPLOYMENT.md)。正式购买页为 `https://lab.alan.elyther.top/buy`，卖家中控为 `https://lab.alan.elyther.top/admin`。支付配置与运营步骤见 [购买页、人工核款与退款运营](docs/COMMERCIAL_PURCHASE.md)。

```bash
python3 mcp/lab-skill-factory/auth/license_control_admin.py keys create \
  --refund-days 7 --label "首批体验" --customer-ref order-001
python3 mcp/lab-skill-factory/auth/license_control_admin.py keys list
python3 mcp/lab-skill-factory/auth/license_control_admin.py keys ban lfkey_xxx --reason "违规原因"
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders list --status payment_submitted
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders confirm-payment lforder_xxx
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders issue lforder_xxx
```

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
lab-factory install --target both --purchase-url "https://lab.alan.elyther.top/buy" \
  --support-email "QQ群923937311" --feedback-email "QQ群923937311" \
  --control-url https://lab.alan.elyther.top
lab-factory activate-key 'LF-XXXX-...' --accept-terms-version 1.0 --confirm-age-18
lab-factory request-refund
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
python3 mcp/lab-skill-factory/scripts/test_online_license_control.py
```

源码开发可临时设置 `LAB_FACTORY_DEV_ALLOW=1`；冻结发行包忽略该变量。

详细说明见 [在线密钥中控](docs/REMOTE_AUTH_DEPLOYMENT.md)、[离线兼容授权](docs/OFFLINE_LICENSING.md)、[用户指南](USER_GUIDE.md) 和 [跨平台说明](docs/WINDOWS_MAC_USAGE.md)。
