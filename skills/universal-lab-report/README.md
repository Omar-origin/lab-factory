# Universal Lab Report Skill

这是通用实验报告辅助 skill 的 MVP 包。它先作为 skill 使用，不包含 MCP 包装。

## 目录

```text
skills/universal-lab-report/
  SKILL.md
  references/
  scripts/
```

## 使用方式

把整个 `skills/universal-lab-report` 目录复制到支持 skills 的环境中，或在 agent 中指定这个 skill 路径。

示例提示词：

```text
使用 universal-lab-report skill，根据这些材料生成实验报告草稿：
<任务书路径>
<报告模板路径>
<实验数据或源码路径>
```

最简调用也可以：

```text
请使用这个 skill：
<skill 路径>

帮我完成这个实验报告：
<实验报告或材料路径>
```

skill 不会拿到路径就直接填内容。它会先查看文档，确认实验要求、需要填写的部分、不可触碰范围、写作排版要求、实验环境和工具，以及是否有同科目参考案例。确认过程应一问一答进行；个人信息和详细环境版本可以先不回答，后续必须用到时再问。

Finalize 示例：

```text
我已经补齐截图和个人信息，请使用 universal-lab-report skill 生成最终版。
```

最终整理时，skill 会根据封面字段询问个人信息，并确认文件命名方式，再填写最终版副本。

专属科目 skill 示例：

```text
这次结果满意，请根据这次流程生成一个我的计网实验报告专属 skill。先给我拟沉淀规则摘要，等我确认后再写入。
```

## 合规边界

默认不伪造真实实验数据。缺少截图、实测数据、个人操作或不可复现环境时，先保留占位并给用户补齐步骤。
