---
name: lab-skill-factory
description: |
  实验报告 DOCX 自动驾驶与专属 skill 定制工厂。用户提供实验报告模板、任务书、参考案例或课程材料，希望生成格式受控的报告草稿，或定制某门课/某类模板的实验报告 skill 时必须使用。
  新报告默认使用 v2.1 自动驾驶：先确认个性化与格式摘要，再自动推进低风险步骤，交付 DOCX 后才在后台提议更新专属 skill。用户明确只想制作 skill 时，仍可走 skill-spec 与脚手架流程。v1 fill-map 只允许迁移。
---

# Lab Skill Factory

## 定位

这是本地 MCP 工具的内置 skill。它的默认产品入口是根据课程材料和模板尽快生成格式受控、可核验的 DOCX 草稿；专属 Skill 是后台复用用户稳定偏好和模板规则的产物，不要求用户先理解或制作 Skill。

MCP 工具后续负责文件复制、DOCX/MD 解析、模板保全、占位检查、校验、版本管理和 skill 安装；本 skill 负责定义专属 skill 的生成流程和质量门禁。

## 当前质量重点

优先提升“材料与模板 → 个性化确认 → 可用 DOCX → 后台学习摘要”的结果质量。正常 `balanced` 流程只保留 preflight 和最终 DOCX 两个常规确认点；定位不可靠、结构变化或硬门禁失败时才额外请求确认或阻断。

## 最高优先级规则

- 新报告默认调用 `lab_factory_v2_prepare_autopilot`，按返回的 `next_action` 执行；只有用户明确要求“先制作专属 Skill”时，才先生成 `skill-spec.md`。
- 默认生成“科目级/模板系列级”专属 skill，不要把一次实验编号固化成唯一适配范围；只有用户明确要求一次性实验 skill 时才允许生成实验级 skill。
- 生成或更新专属 skill 时，开发环境优先调用 `skill-creator` 工作流做质量参考；商业分发环境不能依赖用户电脑已有 `skill-creator`，必须使用 MCP 内置模板、校验器和脚手架生成器兜底，并明确按 `skill-creator` 的结构规范执行。
- 生成的 MCP 必须是标准 stdio MCP，不得绑定 Codex-only 能力；Claude Code、Codex 和其他支持 stdio MCP 的客户端应能使用同一个 server，只通过客户端配置适配。
- 生成出来的专属 skill 必须保持平台中立：普通 `SKILL.md + references/ + assets/ + evals/`，不写 Codex 专用指令，也不要求用户必须安装 `skill-creator`。
- 没有 `skill-creator` 时，必须执行内置质量门禁：校验 `skill-spec.md`，使用固定模板生成，校验专属 skill 包，准备 evals，并让用户确认后再安装或使用。
- 如果用户已经提供模板、任务书或材料路径，第一步必须完整只读浏览这些材料，包括文档末尾、附录、提交说明、命名规则、标红提醒、压缩包要求和源码提交要求；不能只看开头、标题或前几页。
- 完整浏览后必须形成结构化需求摘要，至少覆盖实验目标、具体任务、报告结构、填写范围、不可触碰区域、工具环境、源码/Notebook、截图来源、提交清单、命名规则和缺失材料；自动驾驶会把它与格式、偏好合并到 preflight 中一次确认。
- 生成出来的专属 skill 也必须遵循同一规则：每次处理新报告时先从头到尾读完整文档，输出结构化需求摘要并交给 v2.1 自动驾驶决定是否需要提问。
- 浏览已有材料后，再用通俗话请用户补充缺失材料：课程要求、实验任务书、老师要求、评分标准、同科目成品报告、模板、课件或往期要求；没有也可以继续，但必须记录缺失材料。
- 生成 `skill-spec.md` 前必须根据模板逐项、多轮确认需求；仍不清晰时继续追问，不允许带着未确认规则生成专属 skill。
- 提问必须口语化、具体化，避免直接抛出“适配层级、内容粒度、finalize 边界”这类术语；必须把专业词翻译成用户能理解的问题。
- 始终引导用户修正 AI，但不要机械地逐阶段询问。正常任务只在 preflight 和最终 DOCX 主动确认；歧义、结构修改、低置信度定位、格式冲突和硬门禁失败按需提问。
- 必须确认的需求至少包括：适配层级、填写区域、不可触碰区域、写作规范、内容粒度、实验小结结构、必用工具/运行环境、源码或 Notebook 产物、截图/绘图/真实数据、提交文件清单、压缩包或命名规则、草稿与 finalize 边界。
- 用户可以对某一项选择“默认”。一旦用户选择默认，就把 `references/default-writing-parameters.md` 中对应默认值当成用户本次明确提供的要求，逐项写入 `skill-spec.md`，不得只写“使用默认值”。
- 内置默认写作参数见 `references/default-writing-parameters.md`；只有任务书、模板、用户确认和专属规则都没有覆盖要求，且用户选择默认时才使用。
- 默认正文格式必须包含：小四、中文宋体、英文 Times New Roman、黑色、首行缩进默认度量值 2；正文说明点默认 150-200 字，实验小结每个小点默认 100 字左右。
- 参考案例只能学习格式、栏目、图文关系、详略程度和截图位置，不复制正文、数据、截图、个人信息或独特表达。
- 生成质量优先：必须使用课程写作画像、参考样本结构化 style card 和每报告 `variation_seed`，控制详略、语气、反思取向、句式节奏和举例角度，避免所有报告同质化。
- 首次生成收集并展示 8 个稳定偏好：写作水平、内容详略、句段风格、术语密度、语气、分析顺序、反思角度、个性化强度。偏好冲突或置信度低时，按需提供两个短样例进行风格校准；正常情况不增加此步骤。
- 没有参考样式时必须生成 `report-variation-contract.json`，控制章节重点、解释顺序、例证密度和反思角度；不得用随机同义词替换伪造差异。
- preflight 必须具体展示正文/标题样式、字体、字号、颜色、对齐、缩进、行距、段距、编号、表格、页眉页脚和图片关系，并标明 `user`、`task`、`template` 或 `default` 来源；即使采用内置默认也必须展开说明。
- 自适应提问：先展示已识别要求、来源和缺失/冲突项，只问会改变质量的内容；确认与微调尽量合并，每轮最多 1–3 个强相关问题，不重复询问模板已明确的规则。
- 生成后执行质量自检：任务覆盖、事实来源、证据缺失、写作画像应用、差异化、可操作性和隐私安全任一硬门禁失败时，必须询问、留占位或阻断。
- 专属 skill 的报告流程必须是“模板编译式”：先生成 OOXML inventory，用户确认写入节点后编译 `template-profile.json`；后续生成 `content-package.json`，高置信度位置自动使用，低置信度位置必须展示候选并等待确认。
- 不得把“第一个包含锚点文字的段落”当作 v2 定位回退。`auto` 定位要求分数至少 0.90 且领先第二候选至少 0.15；`confirm` 必须用户选择；`blocked` 禁止写入。
- 第一次写入副本只填补，不删除、不改写、不重排原文；不得修改文档原本结构、字体、字号、内容、格式、分页、目录、表格布局或排版。
- 复制文件必须先做字节级副本；填入内容时默认继承目标锚点附近的段落、字体、字号、行距、表格和编号样式，不能通过整篇重建或 Markdown 转 DOCX 覆盖原格式。
- DOCX 默认使用 `python-docx + lxml` 做副本内最小范围填补；`docxtpl` 只用于受控占位符模板，`Mammoth` 只用于辅助抽取，`pywin32 COM` 只作为 Windows + Microsoft Word 的可选增强，不作为 Mac MVP 默认依赖。
- 如果实验要求必须使用 Jupyter Notebook、指定软件、指定系统、网站、GitHub 仓库、本地地址或其他工具，必须先确认工具、环境、输入数据、源码文件和真实截图来源；不能跳过工具直接编造结果。
- 绘图、截图、实操环境、设备照片等证据内容只能来自真实运行、用户提供材料或可复现代码输出；不能调用生图能力伪造截图、界面、代码运行结果或实验现场图片。
- 新报告必须使用 v2.1 编排状态机执行 `collecting_preferences → preflight_pending → running → final_review_pending → finalized → iteration_decided`；例外进入 `exception_pending`。旧 v2.0 会话继续使用原 strict 状态机。
- `balanced` 模式下草稿安全写回后自动进入最终 DOCX 验收，不增加独立草稿确认；最终摘要必须提醒用户在 WPS 或实际编辑器中检查位置、表格、分页和图片。
- 删除模板说明、占位文字、命令提示或草稿提示，只能发生在第二次 finalize，且必须由用户确认删除范围。
- Finalize 必须做排版调整、清理用户确认可删除内容、添加文末免责声明并输出最终版；最终版经用户确认后，展示 Skill 学习摘要，用户可接受、修改或拒绝。
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
- 生成的 `subject-contract.md`、`skill-quality-contract.md`、`quality-profile.json` 和质量自检摘要。
