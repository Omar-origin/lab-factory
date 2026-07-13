# Lab Factory v2 Workflow

## 1. 建立会话与确认需求

1. 调用 `lab_factory_v2_create_session`。
2. 完整阅读材料，生成符合 `requirements-summary-v2.schema.json` 的需求摘要。
3. 先展示系统已识别内容和来源，只询问缺失项或冲突项。
4. 用户确认后调用 `lab_factory_v2_confirm_requirements`。不得直接跳到写入。

## 2. 理解标题树并按需扩展

1. 调用 `lab_factory_v2_inventory_docx`，检查 paragraph、table cell、header/footer 和 unsupported 节点。
2. 将完整材料所需章节与 inventory 的 `heading_tree` 比较。模板二级/三级标题不足时，宿主 AI 必须根据任务要求和用户具体要求生成结构提案，调用 `lab_factory_v2_propose_section_plan`；提案必须列出材料来源、任务摘要、用户要求、父标题、插入位置、同级样式来源和编号策略。
3. 一次性向用户展示新增标题差异；只有用户明确确认后才调用 `lab_factory_v2_apply_section_plan`。该工具只写入模板副本；写入后必须对副本重新 inventory，并在最终 WPS 审阅时更新目录。无需扩展时跳过本步骤，不额外提问。

## 3. 编译和复用模板

1. 首次模板让用户确认正确节点，再调用 `lab_factory_v2_create_template_profile`。
2. 后续同系列模板调用 `lab_factory_v2_propose_placements`：
   - 先检查 `family_signature` 的标签、页眉页脚、表格形状和容器分布兼容分数；局部内容增长不要求完整结构哈希一致。
   - `AlternateContent` 同时包含 Choice/Fallback 时只采用 Choice，避免把同一个文本框重复列为两个候选。
   - `auto`：可采用。
   - `confirm`：展示最多五个候选的文本、上下文和表格坐标，让用户选择。
   - `blocked`：停止，不得用字符串首个命中回退。
3. 调用 `lab_factory_v2_resolve_placements` 记录确认。

## 4. 生成差异化内容

1. 读取课程 `writing-profile.json`；首次没有时调用 `lab_factory_v2_create_writing_profile`。
2. 有参考样本时只生成并校验 `style-card.json`，不得把完整样本正文写入 Skill。
3. 沿用会话中的 `variation_seed` 生成本报告内容；局部修改不得更换 seed。
4. 输出符合 `content-package-v2.schema.json` 的内容包。低置信度字段写入用户确认的 `selected_node_id`。

## 5. 安全写入和审阅

1. 调用 `lab_factory_v2_mark_content_ready`。
2. 调用 `lab_factory_v2_apply_draft`。该工具只修改被审计的 OOXML part，并返回实际节点、容器、坐标和样式来源。
3. 让用户在 WPS 检查写入位置、标题层级和编号、目录、表格边框和合并、分页行距、图片公式。
4. 使用返回的 `review_id` 调用 `lab_factory_v2_review_draft`；用户要求修改时回到内容阶段。

## 6. Finalize 与 Skill 迭代

1. 调用 `lab_factory_v2_finalize`，传入参考样本路径和固定术语白名单。
2. 相似性门禁失败时展示命中位置并重写，不能绕过。
3. 通过后提供三个出口：继续修改、审阅更新 diff 后更新 Skill、完成且不更新。
4. 更新 Skill 时排除个人信息、样本正文、本次报告正文和一次性异常。

v1 `fill-map.json` 只能通过 `lab_factory_v2_migrate_v1` 生成重新定位草案，旧字符串锚点永远不能直接升级为高置信度位置。
