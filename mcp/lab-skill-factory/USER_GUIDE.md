# Lab Factory 用户指南

## 生成报告

新任务默认使用“报告自动驾驶”：

1. 提供任务材料和 DOCX 模板。
2. 首次确认写作水平、详略、句段风格、术语密度、语气、分析顺序、反思角度和个性化强度。
3. 查看生成前摘要。系统会明确列出字体、字号、行距、编号、表格等要求，以及它们来自用户、任务书、模板还是内置默认。
4. 确认后，明确且低风险的中间步骤会自动执行；只有结构变化、定位不确定或安全检查失败时才会追加提问。
5. 在 WPS 或实际编辑器中检查最终 DOCX，这是正常流程的第二个确认点。
6. 最后可接受、修改或拒绝 Skill 学习摘要；报告正文不会进入个人偏好。

没有参考报告也可以继续。系统会使用个人偏好生成可解释的变化策略；偏好不明确时才会给出两个短样例供选择。

## 激活

```bash
lab-factory license-request --output device.lfreq
```

将 `device.lfreq` 发给销售者。收到 `device.lflicense` 后：

```bash
lab-factory activate device.lflicense --accept-terms-version 1.0 --confirm-age-18
lab-factory status
```

许可证只适用于生成请求的这次安装。换机或应用数据丢失时重新生成请求并联系销售者。

## 反馈

数据记录默认关闭。开启后也只保存在本机，不会自动上传：

```bash
lab-factory telemetry enable
lab-factory feedback review-001 --rating 4 --edit-time 15_30m --issue format
lab-factory feedback-export --output lab-factory-feedback.json
```

你可以先打开 JSON 检查，再主动发送到产品提示的反馈邮箱。`telemetry disable` 停止记录；`telemetry clear` 删除本地记录。

## 更新

更新由销售者人工发送。安装前校验其公布的 SHA-256：

```bash
lab-factory verify-update <安装包路径> --sha256 <64位校验值>
```

校验失败时不要安装。
