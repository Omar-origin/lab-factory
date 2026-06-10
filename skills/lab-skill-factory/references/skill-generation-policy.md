# Skill Generation Policy

## skill-creator 使用策略

生成或更新专属科目 skill 时，开发环境优先使用 `skill-creator` 的流程做质量参考。

但是正式分发给用户的 MCP 不能假设用户电脑里也有 `skill-creator`。如果当前环境没有 `skill-creator`，必须使用 MCP 内置的模板、校验器和脚手架生成器生成专属 skill，并明确按 `skill-creator` 的结构规范执行。

这意味着 `skill-creator` 是开发期/增强期依赖，不是用户侧硬依赖。

## 平台兼容性

MCP 必须按标准 stdio MCP 暴露工具，不绑定 Codex-only 能力。Claude Code、Codex 和其他支持 stdio MCP 的客户端应使用同一个 MCP server，只通过客户端配置格式适配。

专属 skill 必须保持平台中立：

- 使用普通 `SKILL.md + references/ + assets/ + evals/` 结构。
- 不写 Codex 专用指令。
- 不要求用户必须安装 `skill-creator`。
- 如果某个客户端不支持自动发现本地 skill，允许用户把专属 skill 路径提供给 agent，让 agent 读取 `SKILL.md` 后执行。

## 无 skill-creator 时的质量门禁

没有 `skill-creator` 时，不能降级成随便拼一个提示词。必须执行这些门禁：

1. `skill-spec.md` 已由用户确认，且通过 `validate_skill_spec.py`。
2. 使用版本化模板或 `scaffold_subject_skill.py` 生成完整 skill 包。
3. 生成后运行 `validate_scaffolded_skill.py`。
4. evals 至少覆盖 fill.md、完整阅读、原文保全、写作规范、截图占位、finalize 和受控迭代。
5. 输出给用户检查，用户确认后才安装或使用。

质量的关键不是用户电脑有没有 `skill-creator`，而是 spec 是否具体、默认参数是否展开、生成后校验是否通过、用户是否完成确认和反馈闭环。

最低要求：

- 明确 skill 目标。
- 明确触发条件。
- 明确输出格式。
- 生成 `SKILL.md`。
- 拆分必要 references。
- 准备 evals。
- 用户确认后再写入。

如果当前环境不能直接运行 skill-creator 的评测流程，也要在输出中明确说明：已按 skill-creator 的结构规范生成，评测待后续执行。

MCP 内置兜底能力至少包括：

- 读取已确认的 `skill-spec.md`。
- 校验必要章节、适配层级和默认参数是否展开。
- 生成 `SKILL.md`、`references/`、`assets/` 和 `evals/`。
- 默认生成科目级/模板系列级 skill，不把单次实验编号固化为唯一范围。
- 保留后续受控迭代入口和回滚记录。

## 专属 skill 命名

命名使用稳定 slug：

```text
user-subject-<course-or-template-slug>
```

默认用课程名或模板系列名生成 slug，不要用“实验八”“实验 8”“第 N 次实验”等一次性编号生成 slug。

如果材料只暴露了实验编号，先从封面、文件夹路径、任务书或用户回答中提取课程名。无法提取时必须询问用户课程/科目名称。

只有用户明确确认“只适配这一次实验”时，才允许使用：

```text
user-experiment-<course-or-experiment-slug>
```

不要在目录名里包含姓名、学号、班级等隐私。

## 专属 skill 必须包含

```text
SKILL.md
references/workflow.md
references/document-understanding-policy.md
references/docx-tooling-policy.md
references/fill-policy.md
references/finalize-policy.md
references/formatting-notes.md
references/tool-artifact-policy.md
references/user-guidance-policy.md
references/default-writing-parameters.md
references/compliance.md
references/iteration-log.md
assets/fill-template.md
assets/fill-map.schema.json
evals/evals.json
```

## SKILL.md 要求

`SKILL.md` 保持短小，只写：

- 触发条件。
- 适配范围。
- 适配层级。
- 写作规范和内容粒度确认策略；用户选择默认时，必须展开默认值并作为本次执行规则。
- 最高优先级规则。
- 固定工作流。
- 需要读取的 references。

不要把完整报告范文、用户隐私、一次性数据写入 `SKILL.md`。

## references 要求

references 保存可复用规则：

- 模板锚点。
- 文档理解门禁：完整阅读、任务复述、用户确认。
- DOCX 工具策略：默认 python-docx + lxml，docxtpl/Mammoth/pywin32 仅作条件增强。
- 图文关系。
- 截图占位。
- 必用工具、运行环境、源码/Notebook、系统地址、截图来源、提交清单和压缩包命名规则。
- 小结结构。
- finalize 清理规则。
- 格式偏好。
- 内置默认写作参数，包括标题格式、正文小四黑色、中文宋体/英文 Times New Roman、首行缩进默认度量值 2、正文说明点约 150-200 字、实验小结每点约 100 字、实验小结分点规则。
- 用户引导规则：先要参考资料，提问口语化，每个阶段都请用户检查并鼓励修正 AI。
- 需求确认清单，包括每项规则的来源：`confirmed_by_user`、`default_confirmed` 或 `derived_from_template`。
- 用户选择默认后的展开规则：不能只写“使用默认”，必须写明字体、字号、行距、标题样式、实验小结点数和每点字数。
- 格式保全策略：字节级复制、继承锚点样式、不整篇重建，不修改原文结构、字体、字号、内容、格式和排版。

## evals 要求

每个专属 skill 至少有 3 个 eval：

- 生成 `fill.md + fill-map.json`。
- 生成 fill.md 前完整阅读文档、复述任务要求并等待用户确认。
- 草稿填补不删除原文。
- 不把单个实验编号圈死为唯一范围。
- 写作规范和内容粒度已确认；用户选择默认时已展开为具体执行规则。
- 每个阶段都引导用户检查和修正。
- 生成前完整浏览模板/任务书，包括文末提交说明、命名规则和源码/Notebook 提交要求。
- 必用工具、运行环境、源码/Notebook、系统地址、截图来源和提交产物已确认。
- DOCX 样式继承和排版保真。
- DOCX 工具选择合理，不把未知老师模板强行改成 docxtpl，不用 Mammoth 写回，不把 pywin32 作为 Mac 默认依赖。
- 原文结构、字体、字号、内容、格式和排版默认不被修改。
- 完成一次报告后提出受控迭代摘要，用户确认后才能更新专属 skill。
- 草稿输出后询问用户是否满意或有问题，没问题时等待用户补齐图片/截图/数据后再进入二次修改。
- finalize 前确认删除项、封面命名和文件命名方式，并在报告末尾添加免责声明。
