# Windows 安装

安装后运行：

```powershell
lab-factory install --target both --purchase-url "微信联系销售者" --support-email support@example.com --feedback-email feedback@example.com
lab-factory license-request --output device.lfreq
lab-factory activate device.lflicense --accept-terms-version 1.0 --confirm-age-18
```

将 `.lfreq` 发给销售者，只导入销售者发回的 `.lflicense`。
