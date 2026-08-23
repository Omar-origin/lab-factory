# 购买页、人工核款与退款运营

公开购买页与密钥中控由同一个服务承载：

- `/buy`：购买、付款信息提交、订单查询和退款申请。
- `/admin`：人工核款、一次性签发密钥、交付、原路退款和封禁。
- GitHub README 只应链接到 `/buy`，不要使用 GitHub Issues、Discussions 或 Pages 处理付款、联系方式和退款。

## 首发支付配置

只配置支付宝经营码/商家服务和微信经营收款/收款商业版的官方链接或操作说明。不要填写普通个人静态收款码、亲友代收账号或用于绕过平台规则的链接。

```bash
export LAB_CONTROL_PRICE_CENTS=990
export LAB_CONTROL_REFUND_DAYS=7
export LAB_CONTROL_SUPPORT_CONTACT="售后QQ群：923937311"

export LAB_CONTROL_ALIPAY_QR_PATH="/服务器私有目录/alipay-business-code.png"
export LAB_CONTROL_ALIPAY_INSTRUCTIONS="使用支付宝扫描经营码并支付 9.9 元"
```

经营码图片和运营联系方式属于部署配置；图片不写入源码、GitHub Actions 或公开仓库。当前私有副本位于 `mcp/lab-skill-factory/private/payment/alipay-business-code.png`，整个 `private/` 目录已被 Git 忽略。部署时单独上传图片并配置绝对路径。未配置 URL、二维码或说明的支付方式不会显示；因此不配置微信变量时，购买页只显示支付宝。Paddle 适配器同样保持关闭；只有完成卖家/域名审核并实现签名 webhook 验证后才能开放。

## 订单流程

```text
payment_pending → payment_submitted → paid → key_issued → delivered
        ↑                └→ payment_rejected
        └───────────────────────┘（用户修正后重新提交）

paid / key_issued / delivered → refund_requested → refunded
```

操作顺序：

1. 用户创建订单，浏览器获得 256-bit 随机查询 Token；数据库只保存 Token 的 SHA-256。
2. 用户通过经营收款渠道付款，只提交交易号/备注和付款时间，不上传截图。
3. 卖家在支付平台的商户记录中核对金额、时间和交易信息。
4. 确认到账后签发密钥。明文只返回一次，复制后通过订单联系方式发送。
5. 发送成功后标记交付。不要在尚未发送时提前标记。
6. 退款时先在原支付交易中完成原路退款，再在中控确认退款；关联密钥随即停止续租，现有租约最长 24 小时后失效。

网页中控提供所有操作。也可以使用 CLI：

```bash
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders list --status payment_submitted
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders confirm-payment lforder_xxx --reason "商户记录已核对"
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders issue lforder_xxx
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders deliver lforder_xxx
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders refund lforder_xxx --reason "原路退款已完成"
```

重复确认付款、签发、交付和退款是幂等操作。重复执行 `issue` 不会生成第二把密钥，也不会再次返回明文。

## Token、隐私和清理

- 订单查询 Token 只放在浏览器 URL fragment、会话存储和 `X-Order-Token` 请求头中，不放在查询字符串。
- 中控保存联系方式、支付渠道、核验字段、订单状态、密钥 ID 和审计记录，不保存支付密码、付款截图或报告材料。
- 交付或退款满 90 天后清理联系方式、交易核验字段和付款申报时间：

```bash
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders purge-personal-data --retention-days 90
```

建议每日定时执行一次。金额、渠道、订单状态、许可证 ID、退款状态和非个人化审计记录继续保留用于对账。

## 部署边界

- 生产服务必须放在 HTTPS 反向代理后，为创建订单、查询、付款提交、激活、刷新和管理员接口配置独立限流。
- `/admin` 应增加网络访问控制；管理员 Token 不能交给购买者。
- 付款链接必须先在手机和桌面端人工验证收款主体、金额和退款入口。
- 购买页不能宣传代写、伪造材料、绕过学校规定或“完全人工完成”。
- Paddle 后续接入必须验证 webhook 签名、按事件 ID 去重，并只在 `transaction.completed` 后确认付款。
