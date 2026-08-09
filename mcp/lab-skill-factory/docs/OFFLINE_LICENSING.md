# 离线授权与人工商业闭环

## 数据流

1. 用户生成 `.lfreq`。文件只含随机安装 ID、平台、架构、请求 ID 和时间。
2. 销售者本地签发 `.lflicense`。私钥只在销售者设备上；公钥随客户端分发。
3. 用户导入许可证。客户端校验签名和安装 ID，全程不联网。
4. 用户可选择在本机记录结构化使用数据，检查导出 JSON 后自行发到反馈邮箱。
5. 销售者人工发送更新安装包和 SHA-256；客户端只负责校验文件。

## 安全边界

- 私钥文件不得提交 Git、上传网盘或发送给用户；至少保留一份断网备份。
- `license_public_key.json` 是公钥，可以进入发行包；初始化或轮换公钥后必须重新构建。
- `.lfreq` 不是秘密，但不要公开散播；签发前核对订单与渠道。
- 客户端不会上传正文、标题、文件名、路径、源码、截图或自然语言摘要。
- 离线永久许可证无法远程吊销。`add-note` 仅记录处理结果，不会让旧文件失效。

## 管理命令

```bash
python3 auth/commercial_admin.py summary --ledger ~/.lab-factory-issuer/license-ledger.jsonl
python3 auth/commercial_admin.py add-note --ledger ~/.lab-factory-issuer/license-ledger.jsonl \
  --license-id lflic_xxx --kind replacement --note "设备丢失，已补发"
```

## 发布门禁

仓库中的默认公钥是 `NOT_INITIALIZED`，仅用于明确阻止误激活。正式发包前必须初始化真实签发者密钥、重新构建，并在干净设备完整测试“请求—签发—导入”。
