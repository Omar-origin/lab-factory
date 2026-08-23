# Cloudflare 商业中控部署

正式入口：

- 购买页：`https://lab.alan.elyther.top/buy`
- 卖家中控：`https://lab.alan.elyther.top/admin`
- 客户端中控：`https://lab.alan.elyther.top`
- 应急 Worker 地址：`https://lab-factory-commercial.elyther-top.workers.dev`

Cloudflare 项目位于 `mcp/lab-skill-factory/cloudflare/`，采用 Workers Static Assets + D1 + Workers Secrets。线上 D1 数据库为 `lab-factory-commercial`，ID 为 `4c794e72-7514-487b-b143-dc42f1c3fccf`。

## 安全边界

- `ADMIN_TOKEN`、`KEY_PEPPER`、`TOKEN_SECRET` 和 `LEASE_PRIVATE_KEY_B64` 只保存为 Workers Secrets。
- 在线租约私钥允许放入 Workers Secret；它与离线正式许可证私钥是不同密钥。
- 支付宝经营码原图位于被 Git 忽略的 `private/payment/`，部署前由 `scripts/sync_assets.py` 复制到 Worker 静态资产；不得提交到公开仓库。
- D1 不保存报告正文、模板、课程材料、截图或本地文件路径。
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

npm run deploy
```

`predeploy` 会自动同步共享 UI 和支付宝经营码并执行 TypeScript 检查。部署后必须只读检查 `/health`、购买配置、经营码 SHA-256 和管理员鉴权；不要为了验收而在线上伪造付款记录。

## 真实首单验收

由可信测试者完成一笔真实 9.9 元交易：创建订单、扫码付款、提交交易信息、卖家核款、签发、交付、客户端激活、申请退款、支付宝原路退款、卖家确认退款。完成后确认客户端最迟在已有 24 小时租约到期时停用。
