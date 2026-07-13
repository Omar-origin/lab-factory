---
name: lab-skill-factory
description: |
  实验报告专属 skill 定制工厂。用户想做一个本地 MCP 工具的内置 skill，或提供实验报告模板、任务书、参考案例、课程材料，希望定制某门课/某类模板的实验报告 skill 时必须使用。
  这个 skill 不直接代写实验报告，而是分析材料、生成 skill-spec.md，并通过 MCP 内置生成器或开发环境 skill-creator 结构规范生成/更新专属科目 skill。新任务使用 v2 的 requirements-summary、template-profile、content-package 和持久化会话；v1 fill-map 只允许迁移。
---

# Lab Skill Factory

## 定位

这是本地 MCP 工具的内置 skill。它的目标不是直接写实验报告，而是根据用户的课程材料、模板、参考案例和确认需求，定制一个“指定科目/指定模板”的实验报告专属 skill。

MCP 工具后续负责文件复制、DOCX/MD 解析、模板保全、占位检查、校验、版本管理和 skill 安装；本 skill 负责定义专属 skill 的生成流程和质量门禁。

## 最高优先级规则

- 不要直接生成可提交实验报告正文。先分析材料并生成 `skill-spec.md`，用户确认后再生成专属 skill。
- 默认生成“科目级/模板系列级”专属 skill，不要把一次实验编号固化成唯一适配范围；只有用户明确要求一次性实验 skill 时才允许生成实验级 skill。
- 生成或更新专属 skill 时，开发环境优先调用 `skill-creator` 工作流做质量参考；商业分发环境不能依赖用户电脑已有 `skill-creator`，必须使用 MCP 内置模板、校验器和脚手架生成器兜底，并明确按 `skill-creator` 的结构规范执行。
- 生成的 MCP 必须是标准 stdio MCP，不得绑定 Codex-only 能力；Claude Code、Codex 和其他支持 stdio MCP 的客户端应能使用同一个 server，只通过客户端配置适配。
- 生成出来的专属 skill 必须保持平台中立：普通 `SKILL.md + references/ + assets/ + evals/`，不写 Codex 专用指令，也不要求用户必须安装 `skill-creator`。
- 没有 `skill-creator` 时，必须执行内置质量门禁：校验 `skill-spec.md`，使用固定模板生成，校验专属 skill 包，准备 evals，并让用户确认后再安装或使用。
- 如果用户已经提供模板、任务书或材料路径，第一步必须完整只读浏览这些材料，包括文档末尾、附录、提交说明、命名规则、标红提醒、压缩包要求和源码提交要求；不能只看开头、标题或前几页。
- 完整浏览后必须充分理解并复述任务要求，至少覆盖实验目标、具体任务、报告结构、填写范围、不可触碰区域、工具环境、源码/Notebook、截图来源、提交清单、命名规则和缺失材料；用户确认理解无误后，才允许生成 `skill-spec.md` 或专属 skill。
- 生成出来的专属 skill 也必须遵循同一规则：每次处理新报告时先从头到尾读完整文档，输出结构化需求摘要并等待用户确认，再生成 v2 内容包。
- 浏览已有材料后，再用通俗话请用户补充缺失材料：课程要求、实验任务书、老师要求、评分标准、同科目成品报告、模板、课件或往期要求；没有也可以继续，但必须记录缺失材料。
- 生成 `skill-spec.md` 前必须根据模板逐项、多轮确认需求；仍不清晰时继续追问，不允许带着未确认规则生成专属 skill。
- 提问必须口语化、具体化，避免直接抛出“适配层级、内容粒度、finalize 边界”这类术语；必须把专业词翻译成用户能理解的问题。
- 始终引导用户修正 AI：每一个阶段结束后，都要主动问“请查看，我这样理解有没有问题？有哪些需要修改的地方？”不要让用户一味让 agent 自己执行。
- 必须确认的需求至少包括：适配层级、填写区域、不可触碰区域、写作规范、内容粒度、实验小结结构、必用工具/运行环境、源码或 Notebook 产物、截图/绘图/真实数据、提交文件清单、压缩包或命名规则、草稿与 finalize 边界。
- 用户可以对某一项选择“默认”。一旦用户选择默认，就把 `references/default-writing-parameters.md` 中对应默认值当成用户本次明确提供的要求，逐项写入 `skill-spec.md`，不得只写“使用默认值”。
- 内置默认写作参数见 `references/default-writing-parameters.md`；只有任务书、模板、用户确认和专属规则都没有覆盖要求，且用户选择默认时才使用。
- 默认正文格式必须包含：小四、中文宋体、英文 Times New Roman、黑色、首行缩进默认度量值 2；正文说明点默认 150-200 字，实验小结每个小点默认 100 字左右。
- 参考案例只能学习格式、栏目、图文关系、详略程度和截图位置，不复制正文、数据、截图、个人信息或独特表达。
- 专属 skill 的报告流程必须是“模板编译式”：先生成 OOXML inventory，用户确认写入节点后编译 `template-profile.json`；后续生成 `content-package.json`，高置信度位置自动使用，低置信度位置必须展示候选并等待确认。
- 不得把“第一个包含锚点文字的段落”当作 v2 定位回退。`auto` 定位要求分数至少 0.90 且领先第二候选至少 0.15；`confirm` 必须用户选择；`blocked` 禁止写入。
- 第一次写入副本只填补，不删除、不改写、不重排原文；不得修改文档原本结构、字体、字号、内容、格式、分页、目录、表格布局或排版。
- 复制文件必须先做字节级副本；填入内容时默认继承目标锚点附近的段落、字体、字号、行距、表格和编号样式，不能通过整篇重建或 Markdown 转 DOCX 覆盖原格式。
- DOCX 默认使用 `python-docx + lxml` 做副本内最小范围填补；`docxtpl` 只用于受控占位符模板，`Mammoth` 只用于辅助抽取，`pywin32 COM` 只作为 Windows + Microsoft Word 的可选增强，不作为 Mac MVP 默认依赖。
- 如果实验要求必须使用 Jupyter Notebook、指定软件、指定系统、网站、GitHub 仓库、本地地址或其他工具，必须先确认工具、环境、输入数据、源码文件和真实截图来源；不能跳过工具直接编造结果。
- 绘图、截图、实操环境、设备照片等证据内容只能来自真实运行、用户提供材料或可复现代码输出；不能调用生图能力伪造截图、界面、代码运行结果或实验现场图片。
- 专属 skill 必须使用持久化状态机执行 `materials_scanned → requirements_confirmed → placements_resolved → content_ready → draft_generated → draft_reviewed → finalized → iteration_decided`，不能只靠提示词声明门禁。
- 专属 skill 输出草稿后必须让用户在 WPS 或其实际编辑器中检查位置、表格、分页和图片；有问题先按反馈修正，没问题则等待用户补齐截图/绘图/数据，并提醒用户完成后回来进行二次修改。
- 删除模板说明、占位文字、命令提示或草稿提示，只能发生在第二次 finalize，且必须由用户确认删除范围。
- 第二次 finalize 必须做排版调整、清理用户确认可删除内容、添加文末免责声明、询问文件命名方式并输出最终版；最终版经用户确认后，才询问是否受控迭代专属 skill。
- 个人信息、完整报告正文、原始数据、截图、私有源码、账号密码、token 不得写入专属 skill。
- 最终稿后必须提供三个出口：继续修改、审阅 Skill 更新 diff 后确认迭代、完成但不更新；不得强迫用户更新 Skill。
- 专属 skill 不允许自动自改。只能在用户确认满意后生成“拟更新摘要”，经用户确认后受控迭代到新版本，并保留回滚信息。
- 每门课程保存一份写作画像；参考成品只提取结构化 style card，不保存正文。每份报告保存 variation seed。Finalize 前必须通过连续 40 字、句子相似度和字符 5-gram 三类相似性门禁。

## 需求澄清门禁

生成 `skill-spec.md` 之前，必须完成一份模板驱动的需求清单。

每一项只能处于三种状态之一：

- `confirmed_by_user`：用户明确给出要求。
- `default_confirmed`：用户选择默认，已把内置默认值展开为本次要求。
- `derived_from_template`：模板、任务书或评分标准已有明确要求，并记录来源。

不得出现 `unknown`、`待确认`、`使用默认值但未展开` 这类状态。存在未清晰项时，继续一问一答确认；一次最多问 1-3 个强相关问题。

## 何时读取哪些 reference

- 开始任何定制任务：读取 `references/workflow.md`。
- 需要完整阅读、理解并复述文档任务要求：读取 `references/document-understanding-policy.md`。
- 需要提问、收集资料、引导用户检查和修正：读取 `references/user-guidance-policy.md`。
- 生成 `skill-spec.md`：读取 `references/skill-spec-policy.md`。
- 需要写作规范、标题格式、字数和实验小结默认值：读取 `references/default-writing-parameters.md`。
- 需要选择 DOCX 编辑工具、判断是否安装 python-docx/docxtpl/Mammoth/pywin32：读取 `references/docx-tooling-policy.md`。
- 需要确认 Jupyter、源码、工具环境、截图来源、提交文件和压缩包命名：读取 `references/tool-artifact-policy.md`。
- 生成或更新专属 skill：读取 `references/skill-generation-policy.md`；开发环境可调用 `skill-creator`，用户侧商业分发必须使用 MCP 内置生成器兜底。
- 规定专属 skill 的报告执行流程：读取 `references/fill-workflow-policy.md`。
- 使用 v2 inventory、模板配置、状态机、写作画像和相似性门禁：读取 `references/v2-workflow.md`。
- 规定草稿后、二次修改、终版和免责声明流程：读取 `references/finalize-policy.md`。
- 处理合规、参考案例、证据来源：读取 `references/compliance-policy.md`。
- 设计更新、回滚和版本记录：读取 `references/versioning-policy.md`。

## 推荐脚本

- `scripts/inspect_lab_materials.py <paths...>`：清点材料并推测角色。
- `scripts/extract_docx_outline.py <docx>`：提取 DOCX 段落、表格、锚点和占位摘要。
- `scripts/validate_skill_spec.py <skill-spec.md>`：检查 skill spec 是否包含必要章节。
- `scripts/validate_fill_map.py <fill-map.json>`：检查 fill-map 基本结构。
- `scripts/apply_fill_map.py <fill-map.json>`：按 fill-map 复制 DOCX/MD 原文件并填入副本，源文件保持只读不变。
- `scripts/v2_engine.py inventory|create-profile|propose|apply|create-session|advance-session|similarity|migrate-v1 ...`：v2 确定性模板编译、写回和流程门禁；所有新任务优先使用。
- `scripts/scaffold_subject_skill.py <skill-spec.md> <output-dir>`：根据已确认的 spec 生成专属 skill 骨架。
- `scripts/validate_scaffolded_skill.py <skill-dir>`：校验生成出来的专属 skill 包是否满足内置质量门禁。

脚本都是辅助工具，不能替代用户确认。商业分发环境中，脚本和内置模板是 `skill-creator` 缺失时的兜底生成器；开发环境仍可用 `skill-creator` 做质量参考。

## 输出约定

每次定制任务至少输出：

- 材料清点摘要。
- 实验目的和模板结构摘要。
- 需要填写区域和不可触碰区域。
- 必用工具、运行环境、源码/Notebook、截图来源、提交清单和命名规则。
- 参考案例使用边界。
- `skill-spec.md` 路径或完整草案。
- 用户确认后的专属 skill 路径。
- 专属 skill 的版本号、更新日志和回滚说明。
