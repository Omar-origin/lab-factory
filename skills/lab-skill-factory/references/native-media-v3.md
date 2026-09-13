# 原生图表与本地审计（v3）

适用于包含 `lab_factory_v3_*` 工具的新客户端。旧内容包 v2 仍能写文本；最终审阅不再接受宿主自行声明的通过结果。

1. 先调用 `lab_factory_v3_capabilities`。`local_files` 是实际探测；模型视觉、桌面截图、Office 渲染若为 `not_probed`，不能擅自声明支持。宿主无法截图时请用户提供真实 PNG/JPEG。
2. 将任务说明整理到 requirements-summary。明确要求的构件用 `required_artifacts: [{"id":"classes","kind":"class_diagram","source":"任务书第3项"}]` 登记。完成原有 prepare → preflight 确认。不得因为缺少实验材料而编造结果。
3. 调用 `lab_factory_v3_import_asset`，传 workspace、source_path、可选 source_description。返回 asset_id 与 asset（relative_path、sha256）。来源说明只是用户声明，不是独立真实性证明。
4. 内容包设 `version: "3.0"`。每个 item 仍对应模板 field_id，可包含 paragraph、figure、table。将返回 asset 放入 `assets[asset_id]`。正文用 `segments: [{"text":"结果见"},{"ref":"result"},{"text":"。"}]` 引用 figure/table 的 caption_id。图表分别按 chapter 编号。所有图表必须有正文引用。
5. 表格传 columns 字符串数组、rows 矩形数组。生成器写原生 Word 表格：顶底 1.5pt，表头底 0.5pt，无竖线、无内部横线，跨页重复表头。图片等比限制在写入容器宽度内。固定高度行、无法确定宽度的单元格、多栏、非主文档故事等复杂位置会阻止自动写入，不能绕过。
6. 如任务明确要求类图，figure 需声明 `artifact_kind: "class_diagram"` 并用 `requirement_coverage: {"classes":"对应block的id"}` 映射。这里只能机械校验构件类型；图中是否真是类图仍需具备视觉能力的宿主或用户检查，不把声明当视觉验收。
7. balanced 用 `lab_factory_v3_apply_draft`；strict 继续用 `lab_factory_v2_apply_draft`。输出和 v3 资产必须在 workspace 内，原模板不能覆盖。
8. 事实清单单独存本地 JSON：`{"facts":[{"source":"用户提供的实验记录第2步","status":"provided"}]}`。status 可为 provided、observed、unknown。unknown 事实不能写为已完成。清单是来源登记，仍需人工核实内容真伪。
9. 两种模式都调用 `lab_factory_v3_verify_draft`（workspace、document_path、fact_ledger_path、可选 comparison_paths）。比较报告先复制到工作区，便于哈希绑定和重现。它运行本机结构、去模板腔、跨报告审计，检查真实对象及未补证据，再返回登记的 draft。失败时修复原会话；禁止自己拼“pass”。
10. balanced 将返回 draft 交给 advance；strict review → finalize。最终确认绑定实际文件 SHA。改动报告、事实清单、已登记的生成材料或对照报告之后必须重新生成/审计/确认。展示 DOCX 给用户检查分页、图片和表格。普通段落结构相近只提示，文本碰撞仍会阻止。

## 不依赖 MCP 的入口

在能执行本地命令的宿主中，将参数写入 UTF-8 JSON 文件：

```sh
lab-factory tool lab_factory_v3_capabilities --args-file capabilities.json
lab-factory tool lab_factory_v3_import_asset --args-file import.json
lab-factory tool lab_factory_v3_apply_draft --args-file apply.json
lab-factory tool lab_factory_v3_verify_draft --args-file verify.json
```

命令只允许已登记工具名，参数与 MCP 相同，不允许模型构造任意 shell 工具。网页模型没有本地执行器时只能准备 JSON 与文字，不能声称本地 DOCX 已生成。不要把授权密钥交给模型。

WorkBuddy/Kimi 配置导出：`lab-factory export-config --client workbuddy` 或 `--client kimi`。导出的是 stdio mcpServers 配置，导入后需实际检查工具发现；这不证明特定模型具备图片理解能力。DeepSeek 等通过宿主的 MCP/CLI 桥接使用，不绑定固定模型名称，也不在生成器内存储供应商密钥。

## 恢复和证据边界

有效会话先保存，额度确认再按稳定 report_id 执行；本地 usage 记录 pending/retry_required/acknowledged。超时可重试同一会话，服务端仍是扣次幂等的权威。同一报告跨 prepare/apply 使用同一个编号。未实现服务端 reservation/refund：本版保持“创建报告会话计次”的现有口径。

本地登记防止工具协议中的虚构 ID 和过期文件；不承诺抵抗能任意修改整个本地进程、源代码与登记目录的攻击者。不能用自动校验取代事实与目标编辑器的人工审查。没有历史基线时会明确标注未证明跨报告差异。
