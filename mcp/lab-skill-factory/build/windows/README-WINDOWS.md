# Windows 安装

安装后运行：

```powershell
lab-factory install --target both --purchase-url "https://lab.elyther.top/plans" --support-email "QQ群923937311" --feedback-email "QQ群923937311" --control-url https://lab.elyther.top
lab-factory license-request --output device.lfreq
lab-factory activate device.lflicense --accept-terms-version 1.0 --confirm-age-18
```

将 `.lfreq` 发给销售者，只导入销售者发回的 `.lflicense`。

开发构建可以不签名；面向用户分发必须执行：

```powershell
.\mcp\lab-skill-factory\build\build_windows_installer.ps1 -ReleaseBuild -CodeSigningThumbprint "证书指纹"
```

发布模式会同时验证主程序与安装器的 Authenticode 签名；缺少签名证书时直接失败。构建过程还会检查运行时文件白名单，并验证正式包不能执行外部 Python 脚本或接受外部 Skill/vendor 路径。
