# Lab Factory 远程授权部署方案

当前 `auth/remote_auth_service.py` 是免费内测用的最小验证服务，不应直接视为商业级授权平台。

## 推荐架构

1. 客户端安装 Lab Factory 本地二进制，并在 MCP 配置中保存公开的授权服务 URL。
2. 用户输入激活码后，客户端向 HTTPS `/activate` 发送激活码、产品 ID 和匿名设备 ID。
3. 服务端校验激活码、有效期和设备数量，返回随机授权 token。
4. 客户端只在本地保存 token，不保存明文激活码。
5. 每次启动或按缓存周期调用 `/verify`，服务端可返回有效、过期、撤销或设备不匹配。

## 推荐技术

- API：FastAPI、Node.js/NestJS 或 Go 均可。
- 数据库：PostgreSQL；早期内测也可使用当前 SQLite 服务。
- 部署：Fly.io、Railway、Render、Cloud Run、VPS + Caddy，或 Supabase Edge Functions/Postgres。
- HTTPS：必须启用，不能通过明文 HTTP 传输激活码或 token。
- 激活码：使用密码学安全随机数生成，建议至少 128 bit 随机性。
- 激活码存储：高熵随机码可使用带服务端密钥的 HMAC-SHA-256；不要存明文。
- 授权 token：至少 256 bit 随机性，数据库只保存 token 哈希。
- 管理密钥：放在托管平台 Secret Manager 或环境变量中，不写进仓库和安装包。

## 最少数据表

- `products`：产品和版本策略。
- `activation_codes`：激活码哈希、状态、过期时间、最大设备数。
- `devices`：匿名设备 ID、首次激活和最后验证时间。
- `licenses`：客户、产品、授权状态和期限。
- `license_tokens`：token 哈希、设备、撤销状态和轮换时间。
- `audit_logs`：创建、激活、验证、解绑和撤销事件。

## 必需接口

- `POST /activate`
- `POST /verify`
- `POST /deactivate`
- `POST /admin/codes`
- `POST /admin/licenses/{id}/revoke`
- `POST /admin/devices/{id}/unbind`
- `GET /health`

管理接口必须单独鉴权，并增加限流、审计日志和操作权限控制。

## 从当前版本迁移

1. 先把 `remote_auth_service.py` 部署到只供内测的 HTTPS 地址。
2. 创建测试激活码，验证激活、重复激活、设备上限、过期和撤销。
3. 在发行配置中固定 `LAB_FACTORY_AUTH_URL`，安装器只需要写产品 ID。
4. 将 SQLite 换成 PostgreSQL，token 改为仅保存哈希。
5. 增加管理后台、设备解绑、撤销、限流、日志和备份。
6. 商业发布前做代码签名、公证、隐私政策和授权服务安全审计。
