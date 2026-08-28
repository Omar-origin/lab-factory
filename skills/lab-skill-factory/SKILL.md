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
- 生成质量优先：必须使用课程写作画像、参考样本结构化 style card 和每报告 `variation_seed`，同时控制内容写法与可观察结构。结构至少覆盖图先讲/文先讲/图文穿插/表格先行/混合证据、视觉密度、表格角色、问题证据位置和小结形态；不得只更换题目与正文名词后复用同一骨架。
- 首次使用时先用自然语言提供一次可选校准：用户可以上传 1–3 份自己以前完成的任意科目实验报告；有样本时调用 `lab_factory_v2_analyze_writing_samples`，只在本地提取稳定写作特征，禁止保存正文、源路径、姓名、学号、截图、数据和源码；没有样本时直接跳过，不得阻断任务。
- 旧报告画像只提取句段节奏、解释顺序、术语处理、人称、连接词、列表和反思方式。模板原文、报告答案和疑似公式化 AI 表达必须标记为 `do_not_learn`；旧报告同时进入本地防照抄比较面，不能复用原句。
- 没有旧报告、参考样式或用户偏好时，不得让所有用户使用同一组默认文风。必须按不含个人信息的安装身份分配稳定 `writer capsule`，再叠加课程修正和每报告 `variation_seed`；preflight 展示 capsule 来源、置信度和可调整摘要。
- 写作身份必须拆成稳定 `writer-genome-v3` 与单报告 `variation-v3`。至少控制思考入口、解释形状、句段节奏、段落推进、术语引入、证据习惯、人称、反思、保留意见、连接词、列表和修订重点；不得用随机同义词替换伪造差异。
- 每个需要后补的图片、截图、绘图或表格必须独占一个占位，并在生成正文前确定类型、编号、名称和插入关系。推荐格式为 `【图 2-1：名称；待补：具体操作和画面要求】` 或 `【表 2-1：名称；待补：字段或数据来源】`。图与表分别连续编号，正文必须使用“如图 2-1 所示”“见表 2-1”等交叉引用；禁止一条占位同时要求类图、活动图和状态图。
- 行列数据确实存在但尚无真实值时，应生成有编号、有名称、有字段说明的表格占位；类职责、数据库字段、测试用例、配置项、输入输出、异常处理和结果对比优先接受表格 gate，不能把所有内容都挤成长段落，也不能为追求变化滥造表格。
- “问题和解决办法”不得永久固定为 3 问题 + 3 心得 + 3 建议。应按本次 `summary_shape` 在不破坏老师固定栏目语义的前提下选择成对问题/解决、过程复盘、紧凑问题表或叙述加要点。报错提示、异常界面、配置状态和前后对比若用截图更直观，应在问题后、问题与解决之间或解决后预留独立编号图片，并在文字中引用。
- 偏好冲突或画像置信度低时，按需提供两个短样例进行风格校准；正常情况不增加此步骤。系统分配或旧报告画像已经覆盖稳定偏好时，不再强迫用户填写 8 项配置表。
- preflight 必须具体展示正文/标题样式、字体、字号、颜色、对齐、缩进、行距、段距、编号、表格、页眉页脚和图片关系，并标明 `user`、`task`、`template` 或 `default` 来源；即使采用内置默认也必须展开说明。
- 自适应提问：先展示已识别要求、来源和缺失/冲突项，只问会改变质量的内容；确认与微调尽量合并，每轮最多 1–3 个强相关问题，不重复询问模板已明确的规则。
- 生成后执行质量自检：任务覆盖、事实来源、证据缺失、写作画像应用、差异化、可操作性和隐私安全任一硬门禁失败时，必须询问、留占位或阻断。
- 宿主生成正文前必须读取 `generation-contract-v3` 引用的 preferences、writer genome 和 variation contract，按“事实账本 → 结构与图表登记计划 → 内容规划 → 草稿 → 身份化去模板腔编辑 → 结构/编号/差异确定性门禁”执行。只说“写得像大学生”或“换一种排版”不算应用写作身份。
- 去 AI 化的目标是减少公式化机器腔，不是规避检测器。必须删除成组出现的意义拔高、宣传腔、模糊归因、否定式排比、机械连接词、万能结论和聊天机器人痕迹，同时保留课程术语、代码、公式、引用、老师固定标题和必要技术表达；禁止故意加入错别字、病句、虚构经历或无依据的不确定性。
- Final review 前必须提供事实账本、`humanization-audit`、`document-structure-audit`、本机历史或脱敏批次 `diversity-report`，并通过 source coverage、fact integrity、student identity、style application、humanization、anti-copy、cross-report collision、structure diversity、caption cross-reference 和 evidence placeholder balance 十项门禁。没有可用对照时 `diversity-report` 必须如实标记 `baseline_unavailable` 和比较数 0，不能把“未发现碰撞”表述成“已证明差异”。AI 检测器分数永远不能作为通过条件。
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
- Finalize 必须做排版调整、清理用户确认可删除内容，并确保免责声明位于文档正文最上方后输出最终版；最终版经用户确认后，展示 Skill 学习摘要，用户可接受、修改或拒绝。
- 个人信息、完整报告正文、原始数据、截图、私有源码、账号密码、token 不得写入专属 skill。
- 最终稿后必须提供三个出口：继续修改、审阅 Skill 更新 diff 后确认迭代、完成但不更新；不得强迫用户更新 Skill。
- 专属 skill 不允许自动自改。只能在用户确认满意后生成“拟更新摘要”，经用户确认后受控迭代到新版本，并保留回滚信息。
- 每位用户可保存一份不含正文的个人基础写作画像，每门课程保存课程修正；参考成品只提取结构化 style card，不保存正文。每份报告保存 variation seed。Finalize 前必须通过参考样本防照抄以及本机历史/脱敏批次的连续 40 字、句子相似度、字符 5-gram 和结构流碰撞门禁；风格指纹距离只作差异提醒，结构流与构件数量同时达到阈值时直接阻止，阈值仍需持续用批量评测校准。

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
