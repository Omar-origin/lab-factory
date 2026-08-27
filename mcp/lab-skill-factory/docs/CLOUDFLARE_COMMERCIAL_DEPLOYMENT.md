# Cloudflare 商业中控部署

正式入口：

- 购买页：`https://lab.elyther.top/plans`
- 账号中控：`https://lab.elyther.top/control/overview`
- 应急 Token 中控：`https://lab.elyther.top/admin`
- 客户端中控：`https://lab.elyther.top`
- 应急 Worker 地址：`https://lab-factory-commercial.elyther-top.workers.dev`

2026-08-27 已完成远程 D1 `0003`–`0007` 迁移与正式 Worker 发布；Brevo 发件人 `no-reply@mail.elyther.top` 和 Turnstile 生产 Widget 已启用。注册与登录已拆分，密码先经服务端 HMAC pepper，再使用账号独立随机盐和 100,000 次 PBKDF2-SHA256 保存。账号中控采用 `owner`、`distributor_admin` 和 `user` 三层角色，管理员邀请、角色变更、密钥与订单操作均有服务端权限边界。当前线上版本 ID 为 `627d9af2-ec81-4e97-997d-220b376dbdd2`。`0008_new_user_upgrade_discount.sql` 及对应 Worker 代码已完成本地验证，正式环境仍需先应用该迁移再部署新版 Worker。

Cloudflare 项目位于 `mcp/lab-skill-factory/cloudflare/`，采用 Workers Static Assets + D1 + Workers Secrets。线上 D1 数据库为 `lab-factory-commercial`，ID 为 `4c794e72-7514-487b-b143-dc42f1c3fccf`。

账号系统使用 Brevo 已验证发信域名与 `BREVO_SENDER_EMAIL`，并使用允许域名为 `lab.elyther.top` 的 Cloudflare Turnstile Widget。公开 Site Key 写入 `wrangler.jsonc` 的 `TURNSTILE_SITE_KEY`，Secret Key 只通过下面的 Workers Secret 命令设置；轮换时沿用同一边界。

## 安全边界

- `ADMIN_TOKEN`、`KEY_PEPPER`、`TOKEN_SECRET`、`LEASE_PRIVATE_KEY_B64`、`BREVO_API_KEY` 和 `TURNSTILE_SECRET` 只保存为 Workers Secrets。
- 在线租约私钥允许放入 Workers Secret；它与离线正式许可证私钥是不同密钥。
- 支付宝经营码原图位于被 Git 忽略的 `private/payment/`，部署前由 `scripts/sync_assets.py` 复制到 Worker 静态资产；不得提交到公开仓库。
- D1 不保存报告正文、模板、课程材料、截图或本地文件路径。
- 访问统计只保存按日、按路由的计数和每日轮换的 HMAC 访客摘要，不保存原始 IP；页面访问数据从 `0007` 上线后开始积累。
- `0008` 增加订单促销字段和一次性优惠预留表；必须先迁移再发布 Worker，否则创建订单会因字段缺失失败。
- 本机 Python 中控和 SQLite 仅作为开发/应急备份；线上 Worker 使用独立 D1 数据，不自动双写。

## 本地开发

```bash
cd mcp/lab-skill-factory/cloudflare
npm install
source ~/.lab-factory-control/control.env
python3 scripts/export_secrets.py \
  --output .dev.vars --format dev-vars \
  --lease-private-key ~/.lab-factory-control/lease-private.json
npm run db:local
npm run dev
```

完整本地 Worker 回归：

```bash
source ~/.lab-factory-control/control.env
python3 scripts/test_worker_flow.py
python3 scripts/test_portal_flow.py
```

## 正式部署

```bash
cd mcp/lab-skill-factory/cloudflare
npm run db:remote

source ~/.lab-factory-control/control.env
python3 scripts/export_secrets.py \
  --output /tmp/lab-factory-worker-secrets.json --format json \
  --lease-private-key ~/.lab-factory-control/lease-private.json --force
npx wrangler secret bulk /tmp/lab-factory-worker-secrets.json
rm -f /tmp/lab-factory-worker-secrets.json

# 账号系统额外 Secret；按提示粘贴，不写入 shell 历史或仓库
npx wrangler secret put BREVO_API_KEY
npx wrangler secret put TURNSTILE_SECRET

npm run deploy
```

`predeploy` 会自动同步共享 UI 和支付宝经营码并执行 TypeScript 检查。部署后必须只读检查 `/health`、购买配置、经营码 SHA-256 和管理员鉴权；不要为了验收而在线上伪造付款记录。

## 真实首单验收

由可信测试者分别完成一笔 9.9 元体验版、49.9 元永久版和 199 元五人共享版交易：创建订单、扫码付款、提交交易信息、卖家核款、一键确认并自动发货、用户订单页领取密钥并激活。体验版还要验证前三个不同报告 ID 成功、重复 ID 不重复扣次、第四个 ID 被拒绝且 Skill 凝练入口被拒绝；永久版要验证不限次数并可凝练 Skill；五人版必须得到 5 把彼此独立的密钥。再用被邀请账号付款，核对邀请人佣金等于实际支付额的 20%，并分别验收划转余额、人工提现和退款冲销。
