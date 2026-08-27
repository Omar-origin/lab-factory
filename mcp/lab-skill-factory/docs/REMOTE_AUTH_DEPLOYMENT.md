# 在线密钥中控与 24 小时租约

当前商业主线使用“一个密钥绑定一个安装 + 24 小时签名租约”。报告正文、模板、文件路径、截图和课程材料仍完全留在用户本地。

## 能力边界

- 中控生成高熵激活密钥，明文只在创建响应中出现一次；SQLite 只保存带服务端 Pepper 的 HMAC。
- 首次激活通过 `BEGIN IMMEDIATE` 原子绑定安装 ID 和安装 Ed25519 公钥；第二个安装收到 `409 KEY_ALREADY_USED`。
- 客户端每次 MCP 进程启动尝试刷新，此后按租约中的 `refresh_after`（6 小时）刷新。
- 租约最长 24 小时。中控不可达时，只能继续使用尚未过期的本地租约。
- 异常退款经人工确认、退款完成或违规封禁后不再签发租约，最迟在现有租约到期时停用。
- 不承诺识别共享电脑或完整克隆环境；准确表述是“绑定一个安装”。

## 初始化

在线租约密钥与正式离线许可证密钥必须分开。先创建可轮换的租约密钥：

```bash
python3 mcp/lab-skill-factory/auth/license_control_admin.py init-lease-issuer \
  --private-key ~/.lab-factory-control/lease-private.json \
  --public-key mcp/lab-skill-factory/lease_public_key.json
```

重新构建客户端，使公钥进入发行包。`lease-private.json` 只能放在中控 Secret 或受限文件中；现有正式许可证私钥仍不得上传。

生成三个至少 32 字符的独立随机 Secret：

- `LAB_CONTROL_ADMIN_TOKEN`：卖家管理 API。
- `LAB_CONTROL_KEY_PEPPER`：激活密钥 HMAC。
- `LAB_CONTROL_TOKEN_SECRET`：确定性安装 Token。

购买页还需要配置价格、异常售后参考期、售后QQ群，以及支付宝经营码图片的服务器私有路径。完整变量见 [购买页、人工核款与退款运营](COMMERCIAL_PURCHASE.md)。经营码图片不得提交到公开仓库。

不要复用三个值，也不要提交 Git。

也可以使用卖家 CLI 一次性创建权限为 `600` 的本地配置文件；命令不会把 Secret 输出到终端：

```bash
python3 mcp/lab-skill-factory/auth/license_control_admin.py init-control-config \
  --output ~/.lab-factory-control/control.env \
  --lease-private-key ~/.lab-factory-control/lease-private.json \
  --db ~/.lab-factory-control/license-control.sqlite3 \
  --alipay-qr mcp/lab-skill-factory/private/payment/alipay-business-code.png \
  --support-contact "售后QQ群：923937311"
```

## 启动中控

```bash
source ~/.lab-factory-control/control.env
python3 mcp/lab-skill-factory/auth/license_control_service.py
```

不使用配置文件时，才需要逐一设置前述环境变量和启动参数。

生产环境必须放在 HTTPS 反向代理后面，并为激活、刷新和管理接口配置限流。不要直接把 stdlib HTTP 端口暴露到公网。

卖家网页中控位于 `https://lab.elyther.top/admin`。页面要求手动输入管理员 Token，Token 只保存在当前页面内存，刷新后清除。

公开购买页位于 `https://lab.elyther.top/plans`。生产环境应分别为订单创建、查询和付款提交设置限流；旧版退款接口继续限流并统一拒绝自助申请。订单 Token 只通过 `X-Order-Token` 请求头传递。

## 卖家操作

```bash
export LAB_CONTROL_API_URL="https://lab.elyther.top"
export LAB_CONTROL_ADMIN_TOKEN="<管理员Token>"

python3 mcp/lab-skill-factory/auth/license_control_admin.py keys create \
  --refund-days 7 --label "首批体验" --customer-ref "order-001"
python3 mcp/lab-skill-factory/auth/license_control_admin.py keys list
python3 mcp/lab-skill-factory/auth/license_control_admin.py keys mark-sent lfkey_xxx
python3 mcp/lab-skill-factory/auth/license_control_admin.py keys refund lfkey_xxx --reason "退款已完成"
python3 mcp/lab-skill-factory/auth/license_control_admin.py keys ban lfkey_xxx --reason "违规原因"
python3 mcp/lab-skill-factory/auth/license_control_admin.py keys restore lfkey_xxx --reason "确认误封"
python3 mcp/lab-skill-factory/auth/license_control_admin.py keys reset-binding lfkey_xxx --reason "人工换机"
```

网页和 CLI 都只显示密钥后四位。创建后丢失明文时应创建新密钥，不要尝试从数据库恢复。

## 用户激活与售后

```bash
lab-factory install --target both \
  --control-url "https://lab.elyther.top" \
  --purchase-url "https://lab.elyther.top/plans" \
  --support-email "QQ群923937311"

lab-factory activate-key 'LF-XXXX-...' \
  --accept-terms-version 1.0 --confirm-age-18
lab-factory request-refund
```

`request-refund` 只显示售后 QQ 群与适用情形，不自动提交退款或停止续租。数字化密钥交付后原则上不接受无理由退款；重复付款、无法激活且无法修复、重大功能缺陷或法律另有规定时，由售后人工核实。卖家实际退回款项后再执行 `keys refund`；误操作时可执行 `keys restore`。

## 状态与审计

```text
unused → active → refund_requested → refunded
           └──────────────→ banned
banned / refund_requested → active    （管理员恢复）
active / banned → unused               （换机重置）
```

创建、发送、激活、刷新、管理员退款、封禁、恢复和换机重置都会写入 `audit_events`。中控不保存报告内容或用户机器信息，只保存随机安装 ID、安装公钥、订单引用和授权时间。

## 备份与轮换

- 每日备份 SQLite 数据库和在线租约私钥，备份必须加密。
- 管理 Token、Pepper 或 Token Secret 泄露时立即轮换；Pepper/Token Secret 轮换会影响现有记录，需要迁移方案，不能直接替换。
- 租约签名私钥轮换后，客户端必须先发布同时信任新公钥的构建；当前格式首版只嵌入一个公钥，因此不能无停机直接轮换。
- 若授权服务永久停止，所有客户端会在最长 24 小时后停用；商业承诺必须明确这一服务依赖。
