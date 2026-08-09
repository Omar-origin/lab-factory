# Windows / macOS 使用说明

macOS Apple Silicon 与 Windows x64 使用同一离线授权流程：安装后生成 `.lfreq`，销售者签发 `.lflicense`，用户本地导入。

```bash
lab-factory install --target both --purchase-url "微信联系销售者" --support-email support@example.com --feedback-email feedback@example.com
lab-factory license-request --output device.lfreq
lab-factory activate device.lflicense --accept-terms-version 1.0 --confirm-age-18
```

macOS 未签名包可能被 Gatekeeper 阻止，Windows 未签名包可能出现 SmartScreen 提示。付款前应告知用户，并同时公布安装包 SHA-256。扩大销售前再完成平台签名和 macOS 公证。
