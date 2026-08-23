# Windows / macOS 使用说明

macOS Apple Silicon 与 Windows x64 使用同一在线密钥流程：密钥首次激活后绑定一个安装，客户端使用最长 24 小时的签名租约。

```bash
lab-factory install --target both --purchase-url "https://lab.alan.elyther.top/buy" --support-email "QQ群923937311" --feedback-email "QQ群923937311" --control-url https://lab.alan.elyther.top
lab-factory activate-key '销售者提供的密钥' --accept-terms-version 1.0 --confirm-age-18
```

macOS 未签名包可能被 Gatekeeper 阻止，Windows 未签名包可能出现 SmartScreen 提示。付款前应告知用户，并同时公布安装包 SHA-256。扩大销售前再完成平台签名和 macOS 公证。
