---
name: user-subject-<slug>
description: |
  <课程/科目/模板> 实验报告专属 skill。当用户要求完成该课程、该模板或同类实验报告时使用。
  这个 skill 不直接修改源文件；它先生成 fill.md + fill-map.json，用户确认后由 MCP 复制原文件并按锚点填入副本。
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

- 先生成 `fill.md + fill-map.json`，不要直接改文档。
- 用户确认 `fill.md` 后，才允许复制源文件并填入副本。
- 第一次只填补，不删除、不改写、不重排原文，不改变原结构、字体、字号、内容、格式和排版。
- 生成 `fill.md` 前必须先从头到尾完整阅读实验报告、任务书和文末提交说明，充分理解后复述任务要求，并等待用户确认；然后再根据模板多轮确认写作规范、内容粒度、实验小结结构、必用工具、运行环境、源码/Notebook、截图来源、提交清单和 finalize 边界。
- 用户选择默认时，必须把 `references/default-writing-parameters.md` 的默认值当成本次用户要求执行，并在 `fill.md` 中展开列出。
- 每个阶段都要请用户检查并鼓励修正：`请查看，是否存在什么问题？有哪些需要修改的地方？`
- 复制原文件必须是字节级副本，新增内容必须继承目标锚点样式，不能整篇重建 DOCX。
- 截图和绘图只能来自真实运行、用户材料或可复现代码输出；缺失时只留占位和操作提示，不使用生图伪造截图。
- 参考案例只学格式，不复制内容。
- 草稿输出后必须询问用户是否满意或有问题；有问题先修正，没问题则等待用户补齐截图/绘图/数据后再二次修改。
- Finalize 前必须确认删除项、封面信息和文件命名方式，并在最终版末尾添加免责声明。
- 不保存姓名、学号、账号、完整报告正文、原始数据或截图到 skill。

## 工作流

1. 读取用户材料。
2. 从头到尾完整阅读模板、任务书和文末提交说明。
3. 复述任务要求：实验目标、任务步骤、填写范围、不可触碰区域、工具环境、源码/Notebook、截图来源、提交清单、命名规则和缺失材料。
4. 等待用户确认理解无误；有误先修正复述。
5. 根据模板多轮确认填写范围、不可触碰范围、写作规范、内容粒度、实验小结点数、必用工具、运行环境、源码/Notebook、截图来源、提交清单和 finalize 边界；用户选默认时展开默认值。
6. 生成 `fill.md`。
7. 生成带格式保全策略的 `fill-map.json`。
8. 等待用户确认。
9. 用户确认后，调用 MCP 文件处理能力复制并填入副本。
10. 输出草稿后，请用户检查草稿是否可以、是否有问题、有哪些地方要改。
11. 有问题先修正；没问题但需要图片/截图/数据时，等待用户补齐并提醒用户回来进行第二次修改。
12. Finalize：调整排版，删除用户确认可删内容，添加文末免责声明，询问文件命名方式并输出最终版。
13. 用户确认最终版后，询问用户是否要更新迭代 skill；先说明拟优化方向，用户确认后才写入。

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
