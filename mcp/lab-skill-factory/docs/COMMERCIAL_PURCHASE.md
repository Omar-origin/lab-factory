# 购买页、人工核款与退款运营

公开购买页与密钥中控由同一个服务承载：

- `/register`：设置密码并通过邮箱验证码确认注册；注册时可绑定邀请码。
- `/login`：使用邮箱和密码登录，连续失败会触发临时锁定。
- `/dashboard`：套餐、密钥、绑定设备、通知和快捷入口。
- `/plans`：三个套餐的购买、付款信息提交与余额抵扣。
- `/referrals`：邀请码、20% 佣金、余额划转和人工提现申请。
- `/orders`：用订单 Token 查询状态及领取一把或五把密钥。
- `/admin`：人工核款、一键自动发货、原路退款和封禁；保留拆分签发/交付作为异常恢复入口。
- GitHub README 只应链接到 `/plans`，不要使用 GitHub Issues、Discussions 或 Pages 处理付款、联系方式和退款。

## 首发支付配置

只配置支付宝经营码/商家服务和微信经营收款/收款商业版的官方链接或操作说明。不要填写普通个人静态收款码、亲友代收账号或用于绕过平台规则的链接。

```bash
export LAB_CONTROL_PRICE_CENTS=990
export LAB_CONTROL_PERMANENT_PRICE_CENTS=4990
export LAB_CONTROL_REFUND_DAYS=7
export LAB_CONTROL_SUPPORT_CONTACT="售后QQ群：923937311"

export LAB_CONTROL_ALIPAY_QR_PATH="/服务器私有目录/alipay-business-code.png"
export LAB_CONTROL_ALIPAY_INSTRUCTIONS="使用支付宝扫描经营码，并按订单金额付款"
```

经营码图片和运营联系方式属于部署配置；图片不写入源码、GitHub Actions 或公开仓库。当前私有副本位于 `mcp/lab-skill-factory/private/payment/alipay-business-code.png`，整个 `private/` 目录已被 Git 忽略。部署时单独上传图片并配置绝对路径。未配置 URL、二维码或说明的支付方式不会显示；因此不配置微信变量时，购买页只显示支付宝。Paddle 适配器同样保持关闭；只有完成卖家/域名审核并实现签名 webhook 验证后才能开放。

## 订单流程

```text
payment_pending → payment_submitted ──确认到账并自动发货──→ delivered
        ↑                └→ payment_rejected
        └───────────────────────┘（用户修正后重新提交）

delivered ──异常售后人工确认──→ refunded
```

操作顺序：

1. 用户创建订单，浏览器获得 256-bit 随机查询 Token；数据库只保存 Token 的 SHA-256。
   下单时必须选择 9.9 元体验版、49.9 元当前大版本永久版或 199 元五人共享版；订单金额和最终签发密钥的 `plan` 必须一致。
2. 用户通过经营收款渠道付款，只提交交易号/备注和付款时间，不上传截图。
3. 卖家在支付平台的商户记录中核对金额、时间和交易信息。
4. 点击“确认到账并自动发货”。系统在同一事务中确认付款，单人套餐创建 1 把密钥，五人共享版创建 5 把独立密钥并标记交付。
5. 只有持有该订单 256-bit Token 的用户能看到完整密钥。D1 不保存自动交付密钥明文，Worker 按订单与席位从卖家 Secret 确定性派生。
6. 被邀请账号每笔实际支付金额都会生成 20% 佣金；售后参考期结束后可划转为站内余额或提交人工提现。退款时未结算佣金自动冲销。
7. 数字化密钥交付后原则上不接受无理由退款。重复付款、无法激活且无法修复、重大功能缺陷或法律另有规定时，用户通过售后 QQ 群提交订单号与问题描述。
8. 异常退款审核通过后，先在原支付交易中完成原路退款，再在中控确认退款；关联密钥随即停止续租，现有租约最长 24 小时后失效。

### 新用户升级优惠

账号有效购买并交付一次体验版后，永久版与五人共享版都减 990 分，但只能在其中一档使用一次。创建高阶套餐订单时服务端会预留优惠，取消未付款订单会释放预留；管理员确认任一高阶套餐付款后，优惠标记为已使用。订单保存 `promotion_code` 与 `promotion_discount_cents`，返佣按扣除优惠与余额后的实际支付金额计算。不能依赖前端显示判断优惠，最终金额必须由 Worker 重算。

完全管理员也可在 `/control/keys` 直接生成套餐密钥。体验版和永久版每次生成 1 把，五人共享版每次生成 5 把；该入口不创建订单、不产生佣金，只适用于已经在线下完成归因和收款的特殊交付。

网页中控提供所有操作。也可以使用 CLI：

```bash
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders list --status payment_submitted
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders confirm-and-deliver lforder_xxx --reason "商户记录已核对"
python3 mcp/lab-skill-factory/auth/license_control_admin.py orders refund lforder_xxx --reason "原路退款已完成"
```

重复执行 `confirm-and-deliver` 和管理员退款是幂等操作，不会生成第二把密钥。旧的 `confirm-payment`、`issue`、`deliver` 命令只用于异常恢复，不作为日常订单流程。旧客户端调用用户退款接口时会收到 `SELF_SERVICE_REFUND_UNAVAILABLE`，且不会改变订单或密钥状态。

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
