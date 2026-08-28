# Windows / macOS 使用说明

macOS Apple Silicon 与 Windows x64 使用同一在线密钥流程：密钥首次激活后绑定一个安装，客户端使用最长 24 小时的签名租约。

```bash
lab-factory install --target both --purchase-url "https://lab.elyther.top/plans" --support-email "QQ群923937311" --feedback-email "QQ群923937311" --control-url https://lab.elyther.top
lab-factory activate-key '销售者提供的密钥' --accept-terms-version 1.0 --confirm-age-18
```

本地开发包可能使用临时签名；任何面向用户收费分发的版本必须使用 Developer ID/Authenticode 正式签名，macOS 还应完成公证，并同时公布安装包 SHA-256。构建脚本的发布模式会在缺少签名身份时直接失败。
