# 生产部署记录 · 2026-09-14

正式站点：https://lab.elyther.top

- 新 Worker 版本：`f5b5fb5d-4f48-48df-9a1a-1a10e01d2eda`。
- 上一版本：`627d9af2-ec81-4e97-997d-220b376dbdd2`。
- 已应用 `0008_new_user_upgrade_discount.sql`：新增优惠字段和预留表；复核无待应用迁移。
- 同步资产、TypeScript 检查、套餐选择回归、Wrangler dry-run 通过；部署上传 14 个新增/修改静态资产。
- 上线后 12 项只读检查全部通过，详见 `live-checks.json`。页面、脚本、样稿与经营码均核对内容哈希；未创建真实订单或付款。
- 官网与示例文件已上线；客户端仍按原人工交付流程更新，未将未正式签名的预览可执行文件公开发布。
- 源码仍在本地工作区，未提交或推送。资产摘要记录于 `release.json`，便于对照本次发布。

新首页进入 `/showcase`；教程 `/docs`；样稿 `/examples/native-report.docx`。

本机 Python 的证书信任库不完整，初次 HTTP 验收失败；最终使用系统 curl 并保持 TLS 校验，通过全部检查。
