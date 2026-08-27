# Windows 安装

安装后运行：

```powershell
lab-factory install --target both --purchase-url "https://lab.elyther.top/plans" --support-email "QQ群923937311" --feedback-email "QQ群923937311" --control-url https://lab.elyther.top
lab-factory license-request --output device.lfreq
lab-factory activate device.lflicense --accept-terms-version 1.0 --confirm-age-18
```

将 `.lfreq` 发给销售者，只导入销售者发回的 `.lflicense`。
