---
name: user-subject-<slug>
description: |
  <课程/科目/模板> 实验报告专属 skill。当用户要求完成该课程、该模板或同类实验报告时使用。
  这个 skill 不直接修改源文件；它使用 Lab Factory v2 的结构化需求摘要、模板配置、内容包和持久化会话，在低置信度位置经用户确认后写入副本。
---

# <课程/科目/模板> 实验报告专属 Skill

## 适配范围

- 默认层级：科目级/模板系列级
- 课程/科目：
- 实验类型：
- 模板：
- 当前样例实验：
- 不适用场景：

## 平台兼容性

- 本 skill 使用普通 `SKILL.md + references/ + assets/ + evals/` 结构。
- 不依赖 Codex-only 指令。
- Claude Code、Codex 或其他支持本地 skill/Markdown 指令的 agent 均可读取执行。
- 如果客户端不能自动发现 skill，用户可以把本 skill 路径提供给 agent，让 agent 先读取 `SKILL.md`。

## 最高优先级规则

- 新任务必须使用 v2；v1 `fill-map.json` 只允许迁移后重新定位。
- 先创建会话、确认需求、解析 OOXML inventory、解决定位，再生成内容包和草稿。
- 第一次只填补，不删除、不改写、不重排原文，不改变原结构、字体、字号、内容、格式和排版。
- 生成 `fill.md` 前必须先从头到尾完整阅读实验报告、任务书和文末提交说明，充分理解后复述任务要求，并等待用户确认；然后再根据模板多轮确认写作规范、内容粒度、实验小结结构、必用工具、运行环境、源码/Notebook、截图来源、提交清单和 finalize 边界。
- 用户选择默认时，必须把 `references/default-writing-parameters.md` 的默认值当成本次用户要求执行，并在 `fill.md` 中展开列出。
- 每个阶段都要请用户检查并鼓励修正：`请查看，是否存在什么问题？有哪些需要修改的地方？`
- 复制原文件必须是字节级副本，新增内容必须继承目标锚点样式，不能整篇重建 DOCX。
- 截图和绘图只能来自真实运行、用户材料或可复现代码输出；缺失时只留占位和操作提示，不使用生图伪造截图。
- 参考案例只生成 style card，不保存或复制正文；Finalize 前执行严格相似性门禁。
- 草稿输出后必须询问用户是否满意或有问题；有问题先修正，没问题则等待用户补齐截图/绘图/数据后再二次修改。
- Finalize 前必须确认删除项、封面信息和文件命名方式，并在最终版末尾添加免责声明。
- 不保存姓名、学号、账号、完整报告正文、原始数据或截图到 skill。

## 工作流

1. 读取用户材料。
2. 从头到尾完整阅读模板、任务书和文末提交说明。
3. 复述任务要求：实验目标、任务步骤、填写范围、不可触碰区域、工具环境、源码/Notebook、截图来源、提交清单、命名规则和缺失材料。
4. 等待用户确认理解无误；有误先修正复述。
5. 根据模板多轮确认填写范围、不可触碰范围、写作规范、内容粒度、实验小结点数、必用工具、运行环境、源码/Notebook、截图来源、提交清单和 finalize 边界；用户选默认时展开默认值。
6. 生成并确认 requirements-summary；只追问缺失和冲突项。
7. 解析 OOXML inventory；首次确认节点并编译 template-profile，后续复用并对低置信度候选确认。
8. 读取课程 writing-profile 和可选 style-card，沿用本报告 variation seed 生成 content-package。
9. 状态到达 content_ready 后调用 v2 安全写入工具生成草稿。
10. 输出草稿后，请用户在 WPS 检查位置、表格、分页和图片；记录 review_id 和反馈。
11. 有问题回到内容阶段；没问题但需要截图/数据时等待用户补齐。
12. Finalize 前执行参考样本相似性门禁，通过后生成终稿。
13. 提供继续修改、审阅并更新 Skill、完成但不更新三个出口。

## References

- `references/workflow.md`
- `references/document-understanding-policy.md`
- `references/docx-tooling-policy.md`
- `references/fill-policy.md`
- `references/finalize-policy.md`
- `references/formatting-notes.md`
- `references/tool-artifact-policy.md`
- `references/user-guidance-policy.md`
- `references/default-writing-parameters.md`
- `references/compliance.md`
- `references/iteration-log.md`
- `references/v2-workflow.md`
