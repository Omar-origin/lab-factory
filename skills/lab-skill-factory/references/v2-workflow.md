# Lab Factory v2 Workflow

## 0. 默认使用 v2.1 报告自动驾驶

新报告默认走结果优先流程；旧 v2.0 会话继续按下方 strict 流程恢复。

1. 首次使用时提供一次可选写作校准：用户可上传 1–3 份自己以前完成的任意科目实验报告。提供时调用 `lab_factory_v2_analyze_writing_samples` 生成不含正文、路径和个人信息的画像；没有时直接跳过。
2. 准备 `requirements-summary` 和 `template-profile`，调用 `lab_factory_v2_prepare_autopilot`。有旧报告画像时传入 `personal_writing_profile_path`；没有时工具按安装身份分配稳定 writer capsule。
3. 严格执行返回的 `next_action`：
   - `ask_user`：一次展示当前强相关问题；系统 capsule 或旧报告画像已经覆盖稳定偏好时，不再强迫用户填写 8 项配置表。
   - `deliver_preview`：展示 preflight 或最终 DOCX 摘要。
   - `await_host_artifact`：宿主生成或读取所需结构化产物，不询问用户。
   - `auto_advance`：继续调用 `lab_factory_v2_advance_autopilot`。
   - `blocked`：展示具体安全门禁，不得绕过。
   - `done`：结束会话。
4. preflight 必须展示 8 维偏好、writer capsule 来源和置信度、12 个稳定写作轴、报告变化契约、身份化去模板腔规则、格式具体值及其来源。使用 `lab_factory_v2_confirm_checkpoint` 获取一次性 token，再调用 `lab_factory_v2_advance_autopilot`。
5. `await_host_artifact` 返回 `required_object_ids` 后，宿主必须先读取 preferences、writer genome、variation contract 和 generation contract，然后按其中的 `host_generation_sequence` 生成；不得只根据模型默认文风直接写正文。
6. 高置信度定位和低风险写入自动推进；只有结构变化、定位分数低于自动阈值、格式冲突或硬门禁失败时额外提问。
7. 正常 `balanced` 流程的第二个、也是最后一个常规确认点是最终 DOCX。进入该确认点前必须提交事实账本、humanization audit、layout audit、diversity report 和十项门禁证据。确认后展示 Skill 学习摘要，报告正文不得写入画像或 Skill。
8. `fast` 目前只保留接口并返回 `MODE_NOT_ENABLED`；`strict` 映射下方旧流程。

以下章节是 strict 模式和旧会话的兼容流程。

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

1. 读取个人基础写作画像、课程 `writing-profile.json` 和 writer genome；个人画像缺失时使用系统分配 capsule。
2. 有参考样本时只生成并校验 `style-card.json`，不得把完整样本正文写入 Skill。
3. 先建立不含虚构内容的事实账本，再按 `variation-v3` 和当前 `variation_seed` 选定本报告结构原型：图先讲、文先讲、图文穿插、表格先行或混合证据。结构计划必须同时记录视觉密度、表格角色、问题证据位置和小结形态；局部修改不得更换 seed 或 capsule。
4. 在写正文前建立图表登记表。每个图、截图、绘图或表格独占一条，预先确定 `图/表编号 + 名称 + 占位要求 + 正文引用句 + 相对位置`；图表分别编号，禁止多图合并占位。存在类职责、字段、测试用例、配置项、输入输出、异常或对比数据时必须明确记录“用表/不用表”的原因。
5. 输出符合 `content-package-v2.schema.json` 的内容包。低置信度字段写入用户确认的 `selected_node_id`。不得把所有报告固定为相同三级标题序列、相同五段长文、相同 3/3/3 小结。
6. 草稿完成后按 `generation-contract-v3` 做身份化去模板腔编辑。删除成组 AI 痕迹，但不添加事实、经历、数据、报错或引用，不故意制造学生式错误。

## 5. 安全写入和审阅

1. 调用 `lab_factory_v2_mark_content_ready`。
2. 调用 `lab_factory_v2_apply_draft`。该工具只修改被审计的 OOXML part，并返回实际节点、容器、坐标和样式来源。
3. 让用户在 WPS 检查写入位置、标题层级和编号、目录、表格边框和合并、分页行距、图片公式。
4. 使用返回的 `review_id` 调用 `lab_factory_v2_review_draft`；用户要求修改时回到内容阶段。

## 6. Finalize 与 Skill 迭代

1. 调用 `lab_factory_v2_humanization_audit`；成组 AI 模板腔或聊天机器人痕迹命中时按 writer genome 重写，不能把所有人统一改成同一种“干净文风”。
2. 调用 `lab_factory_v2_document_structure_audit`；未编号/未命名占位、缺失正文交叉引用、多图合并占位、适合表格但未记录表格、必要的问题证据缺失、目录或正文残留 `XXX` 均需修复。
3. 调用 `lab_factory_v2_cohort_similarity`。有本机历史或经同意的脱敏批次报告时进行实际比较，固定模板、题目、课程术语、代码、公式和引用先进入白名单；文字相似性门禁或结构流碰撞门禁失败时改变内容组织后重写，不能绕过。首次使用没有对照时允许空数组，但报告必须明确写出 `baseline_unavailable` 和比较数 0，不能声称已经证明跨用户差异。
4. 向自动驾驶提交事实账本、humanization audit、layout audit、diversity report，以及十项 `passed_gate_ids`。AI 检测器分数不得加入门禁。
5. 调用 `lab_factory_v2_finalize`，传入参考样本路径和固定术语白名单；Finalize 会再次执行文档结构门禁，失败时不得写入完成状态。
6. 通过后提供三个出口：继续修改、审阅更新 diff 后更新 Skill、完成且不更新。
7. 更新 Skill 时排除个人信息、样本正文、本次报告正文和一次性异常。

v1 `fill-map.json` 只能通过 `lab_factory_v2_migrate_v1` 生成重新定位草案，旧字符串锚点永远不能直接升级为高置信度位置。
