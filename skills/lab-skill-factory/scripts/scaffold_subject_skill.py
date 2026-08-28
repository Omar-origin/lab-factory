#!/usr/bin/env python3
"""Scaffold a subject-specific lab report skill from a confirmed skill spec."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FACTORY_ROOT = Path(__file__).resolve().parent.parent


FILL_MAP_SCHEMA = {
    "type": "object",
    "required": ["version", "source_fill", "target_document", "copy_mode", "format_strategy", "items"],
    "properties": {
        "version": {"type": "string"},
        "source_fill": {"type": "string"},
        "target_document": {"type": "string"},
        "copy_mode": {"type": "string", "enum": ["byte_for_byte_first"]},
        "format_strategy": {"type": "string", "enum": ["inherit_target_anchor"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "source",
                    "target_anchor",
                    "operation",
                    "preserve_original",
                    "format_strategy",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "source": {"type": "string"},
                    "target_anchor": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": ["insert_after", "replace_placeholder", "fill_table_cell"],
                    },
                    "preserve_original": {"type": "boolean"},
                    "format_strategy": {"type": "string", "enum": ["inherit_target_anchor"]},
                    "requires_user_confirmation": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
            },
        },
    },
}


DEFAULT_WRITING_PARAMETERS_MD = """# Default Writing Parameters

## 使用原则

先完整浏览实验报告模板、任务书、评分标准和文末提交说明，再询问用户是否有格式规范和内容粒度要求。用户选择默认时，使用本文件默认值，并把默认值当成本次用户明确要求执行。

优先级：任务书/模板/评分标准 > 用户确认 > 专属 skill 已沉淀规则 > 用户确认采用的本文件默认值 > 参考案例格式倾向。

## 默认标题格式

### 一级标题

- 字号：三号。
- 中文字体：宋体。
- 英文字体：Times New Roman。
- 对齐：居中。
- 序号和文字之间：一个半角空格。
- 行距：单倍行距。
- 段前：3 行。
- 段后：2 行。

### 二级标题

- 序号缩进：不缩进。
- 对齐：左对齐。
- 字号：小三号。
- 中文字体：宋体。
- 英文字体：Times New Roman。
- 序号和文字之间：一个半角空格。
- 行距：1.5 倍行距。
- 段前：1 行。
- 段后：0.5 行。

### 三级标题

- 序号缩进：缩进两个字符。
- 字号：四号。
- 中文字体：宋体。
- 英文字体：Times New Roman。
- 序号和文字之间：一个半角空格。
- 行距：1.5 倍行距。
- 段前：0.5 行。
- 段后：0 行。

## 默认正文格式

- 字号：小四。
- 中文字体：宋体。
- 英文字体：Times New Roman。
- 颜色：黑色。
- 首行缩进：默认度量值 2。
- 不使用其他字体或颜色，除非任务书、模板、评分标准或用户明确要求覆盖。

## 默认内容填补粒度

- 正文中每一个解释说明性质的小点尽量控制在 150-200 字左右。
- 截图、表格、步骤说明等普通说明点默认按 150-200 字左右处理。
- 任务书或模板有明确字数、点数、表格长度要求时，优先按任务书或模板执行。
- 依赖真实截图、数据、运行结果的内容留占位和待办，不编造。

## 默认实验小结结构

如果模板或任务书包含“实验小结”，但没有给出更具体写法，默认分点填写。

- “问题和解决办法”写 3 个问题，每个问题使用 `问题1：xxx。解决办法：xxx。` 的形式。
- “心得体会”写 3 个小点。
- “意见与建议”写 3 个小点。
- 实验小结里的每个小点尽量控制在 100 字左右。

如果实验报告要求的小结栏目不是这三项，应根据实际栏目调整，但仍保持“分点、每点约 100 字”的默认粒度。

## 执行要求

- 生成 fill.md 前必须把本次采用的写作规范和内容粒度列为确认摘要。
- 用户采用默认时，不得只写“默认”，必须展开为具体字体、字号、颜色、首行缩进、行距、标题样式、正文点字数、小结点数和每点字数。
- 若模板包含“问题和解决办法、心得体会、意见与建议”，且用户采用默认，必须生成 3 个问题、3 个心得点、3 个建议点。
"""


USER_GUIDANCE_POLICY_MD = """# User Guidance Policy

## 先要资料

开始处理前，先完整浏览用户已经提供的模板、任务书和文末提交说明。然后请用户补充课程要求、老师要求、评分标准、参考成品报告、课件、源码、数据、截图或运行环境说明。有多少给多少，没有也可以继续。

参考成品报告只能学习格式、栏目、图文关系和详略程度，不复制正文。

## 提问方式

用口语化问题，不直接抛术语：

- “这个 skill 是以后这门课都能用，还是只做这一次？”
- “每个小点大概写多长？没有要求的话，我默认正文说明点 150-200 字左右，小结每点 100 字左右。”
- “第一版我只填空白，不删模板提示。等你插完图后，我再问你哪些提示要删，可以吗？”
- “文档里如果要求 Jupyter、源码、系统地址或压缩包，我先按文档理解，再问你确认。”
- “最后要交哪些文件？只交报告，还是还要交 Notebook、源码、数据和压缩包？”

每轮只问 1-3 个强相关问题。

## 每步都请用户检查

每完成一个阶段，都要说：

```text
请查看，是否存在什么问题？有哪些需要修改的地方？
```

必须检查的阶段：材料清点、文末提交要求摘要、工具/源码/截图/提交清单确认、需求摘要、fill.md、fill-map.json、草稿、finalize 前、最终版、skill 迭代摘要。

## 引导修正

主动提醒用户可以直接修改 AI 的理解，例如：这个部分不要写、这里要更详细、实验小结少一点、截图先留空、按老师模板格式来。
"""


TOOL_ARTIFACT_POLICY_MD = """# Tool And Artifact Policy

## 完整浏览

生成 fill.md 前必须完整浏览模板、任务书、评分标准和文末提交说明，重点检查提交要求、命名规则、压缩包、源码、Notebook、截图、标红提醒和老师备注。

如果文档要求 Jupyter Notebook、源码、指定软件、系统地址、GitHub 仓库或压缩包，必须先复述文档要求，再让用户确认。

## 必须确认

- 必用工具/平台：例如 Jupyter Notebook、Python、MATLAB、Logisim、Packet Tracer、DOSBox、浏览器、本地系统或 GitHub。
- 运行环境：本机、Anaconda、VS Code、浏览器地址、线上地址或仓库地址。
- 源码/Notebook 产物：文件名、是否需要 agent 帮写/补代码、依赖和数据。
- 截图来源：真实运行、用户已有截图或可复现代码输出。
- 提交清单：报告、源码、Notebook、数据集、压缩包。
- 命名规则：压缩包格式和姓名、学号、班级、序号等占位字段。

## 禁止

- 不用生图伪造 Notebook、软件界面、浏览器、设备或实验现场截图。
- 不把参考案例截图当成用户截图。
- 不在 skill 中保存完整源码、用户隐私、截图或原始数据。

## 缺失时

如果当前环境无法运行工具或用户未提供截图/数据，保留可执行步骤和截图占位，不编造运行结果。
"""


QUALITY_PROFILE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Lab Factory Skill Quality Profile v2",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "version",
        "skill_name",
        "scope_level",
        "quality_priority",
        "quality_axes",
        "variation_controls",
        "user_adjustment_points",
        "quality_gates",
        "privacy",
    ],
    "properties": {
        "version": {"const": "2.0"},
        "skill_name": {"type": "string", "minLength": 1},
        "scope_level": {"type": "string", "enum": ["subject", "template", "experiment"]},
        "quality_priority": {"const": "generation_quality_first"},
        "quality_axes": {
            "type": "array",
            "minItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "name", "target", "evidence", "gate"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "target": {"type": "string"},
                    "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                    "gate": {"type": "string", "enum": ["warn", "block", "ask_user"]},
                },
            },
        },
        "variation_controls": {
            "type": "object",
            "additionalProperties": False,
            "required": ["variation_seed", "dimensions", "protected_facts"],
            "properties": {
                "variation_seed": {"type": "string", "minLength": 1},
                "dimensions": {"type": "array", "minItems": 4, "items": {"type": "string"}},
                "protected_facts": {"type": "array", "minItems": 3, "items": {"type": "string"}},
            },
        },
        "user_adjustment_points": {
            "type": "array",
            "minItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "question", "when", "default_allowed"],
                "properties": {
                    "id": {"type": "string"},
                    "question": {"type": "string"},
                    "when": {"type": "string"},
                    "default_allowed": {"type": "boolean"},
                },
            },
        },
        "quality_gates": {
            "type": "array",
            "minItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "check", "action"],
                "properties": {
                    "id": {"type": "string"},
                    "check": {"type": "string"},
                    "action": {"type": "string", "enum": ["warn", "block", "ask_user"]},
                },
            },
        },
        "privacy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["style_card_only", "forbidden_persistence"],
            "properties": {
                "style_card_only": {"const": True},
                "forbidden_persistence": {"type": "array", "minItems": 4, "items": {"type": "string"}},
            },
        },
    },
}


SKILL_QUALITY_CONTRACT_MD = """# Skill Quality Contract

## 目标

本 Skill 的第一目标是生成高质量、可复用、可调整的执行规则；这是“生成质量优先”，而不是把所有定位自动化。定位不确定时允许让用户选择或微调；生成内容不确定时必须追问、留占位或停止，不能靠编造补齐。

## 六个质量轴

1. **任务落地**：每个章节、工具、提交物和格式规则都能追溯到任务书、模板、用户确认或明确的默认值。
2. **结构完整**：先建立任务地图、填写区域、不可触碰区域、证据要求和提交清单，再生成内容；不能只生成一篇看起来完整的正文。
3. **写作质量**：复用课程写作画像和参考样本的结构化风格卡，控制详略、语气、术语密度和反思方式；不保存或复制参考正文。
4. **差异化**：每份报告使用会话 `variation_seed`，允许用户调整写作水平、内容详略、反思取向、语言语气和句式节奏；变化不得覆盖事实、真实数据、格式和用户确认规则。
5. **可检查与可微调**：输出应让用户能看懂、能纠正、能继续完成；正常任务只保留 preflight 和最终 DOCX 两个常规确认点，例外按风险提问。
6. **格式与隐私安全**：源文件和非目标区域保持不变；个人信息、样本正文、一次性异常和未确认规则不进入专属 Skill。

## 生成前

- 先读取 `references/subject-contract.md`，把其中的来源和限制当作本 Skill 的可复用边界。
- 先生成结构化需求摘要，再补写作画像、风格卡和变化种子；没有证据的结果、截图和数据只生成占位与操作提示。
- 只询问缺失项、冲突项和会改变输出质量的选择；不要重复询问模板已经明确的规则。需求确认与微调面板尽量合并在同一轮，每轮最多 1–3 个强相关问题。

## 生成中

- 用任务事实、模板结构和用户确认内容约束正文，用写作画像和风格卡控制表达，不用参考样本正文作为范文复制。
- 每个内容块标明语义目的、事实来源、目标位置、内容粒度和证据依赖；无法确定时把问题暴露给用户。
- 同一报告修改沿用原 `variation_seed`；新报告使用新种子。临时风格调整只作用于当前报告，不自动沉淀。

## 用户微调面板

首次建档收集 8 项稳定偏好；后续只询问缺失、冲突或会显著改变结果的强相关问题：

- 写作水平：基础、自然本科、较成熟。
- 内容详略：精简、均衡、详细。
- 句段风格：短、混合、长。
- 术语密度：低、中、高。
- 反思取向：问题解决、学习过程、工程实践、批判改进。
- 语言语气：朴素、规范、技术型、个人化。
- 分析顺序：原理优先、步骤优先、结果优先。
- 个性化强度：低、中、高。

用户可以直接说“按默认”或在草稿后指出具体段落怎么改。临时选择不能自动更新课程 Skill。

## 生成后自检

在交付 `fill.md` 或草稿前检查：

- 是否完整覆盖任务要求、填写区域、提交物和不可触碰区域。
- 是否所有事实、工具、数据和截图都有来源；缺失内容是否明确标出。
- 是否执行了写作画像、风格卡和 `variation_seed`，且没有连续复制参考样本表达。
- 是否符合已确认的格式和粒度；是否存在同质化段落、空泛套话或不必要的重复。
- 是否给用户留下可检查、可修改的明确入口，并记录本阶段反馈。

失败处理：事实/证据缺失则询问或留占位；规则冲突则列出冲突来源并让用户选择；复杂 DOCX 对象或定位不可靠则阻断自动写入并给人工处理说明。

## 迭代边界

报告完成后只提出“拟更新摘要”：只沉淀跨报告稳定、可复用且已被用户确认的规则；姓名、学号、样本正文、当前报告正文、一次性异常、个人文件路径和临时措辞不得写入。用户确认 diff 后才生成新版本，并保留回滚记录。
"""


CONTRACT_SECTIONS = [
    "适配范围",
    "触发词",
    "输入材料",
    "文档理解与任务复述",
    "需求确认清单",
    "需要填写的区域",
    "不可触碰的区域",
    "写作规范",
    "内容粒度要求",
    "工具环境与提交要求",
    "参考案例使用边界",
    "截图和绘图占位规则",
    "验收测试",
    "版本与迭代",
]


def sanitize_contract_text(text: str) -> str:
    """Keep reusable rules while stripping paths, identifiers, and secret-like values."""
    text = re.sub(r"https?://[^\s)]+", "<运行时地址>", text)
    text = re.sub(r"(?:/Users/|/home/|[A-Za-z]:\\)[^\s)]+", "<本地路径>", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<邮箱>", text)
    text = re.sub(r"\b\d{10,18}\b", "<编号>", text)
    text = re.sub(
        r"(?i)(姓名|学号|班级|序号|账号|密码|token|secret|api[_ -]?key)\s*[:：=]\s*[^\s，。；;]+",
        lambda match: f"{match.group(1)}：<运行时提供>",
        text,
    )
    return text.strip()


def render_subject_contract(spec: str, title: str, scope_level: str) -> str:
    lines = [
        "# Subject Contract",
        "",
        "> 这是从用户确认的 `skill-spec.md` 提炼出的可复用规则摘要。原始 spec 不写入专属 Skill；任何未列出的规则都不能被 agent 自行补全。",
        "",
        f"- 适配主题：{sanitize_contract_text(title)}",
        f"- 适配层级：{scope_level}",
        "- 规则来源：用户确认、模板/任务书、或已展开的默认参数；每条规则保留来源语义。",
        "",
    ]
    for section in CONTRACT_SECTIONS:
        body = sanitize_contract_text(extract_section(spec, section))
        if not body:
            continue
        lines.extend([f"## {section}", "", body[:8000], ""])
    lines.extend(
        [
            "## 使用边界",
            "",
            "- 这份摘要用于生成质量和提问引导，不替代每次任务的完整材料阅读。",
            "- 每次报告仍需重新读取任务书、模板、提交说明和本次用户材料，并生成 requirements-summary。",
            "- 个人信息、原始截图、完整报告正文和一次性文件路径不属于可复用规则。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_quality_profile(slug: str, scope_level: str) -> dict:
    return {
        "version": "2.0",
        "skill_name": slug,
        "scope_level": scope_level,
        "quality_priority": "generation_quality_first",
        "quality_axes": [
            {
                "id": "grounding",
                "name": "任务与事实可追溯",
                "target": "每个关键要求、事实和证据都有来源；缺失时不编造",
                "evidence": ["subject-contract", "requirements-summary.json", "用户本次材料"],
                "gate": "block",
            },
            {
                "id": "coverage",
                "name": "结构与提交完整",
                "target": "覆盖任务、填写区域、不可触碰区域、证据和提交清单",
                "evidence": ["subject-contract", "template-profile.json", "content-package.json"],
                "gate": "block",
            },
            {
                "id": "writing",
                "name": "写作画像与表达质量",
                "target": "按课程画像和本次调整生成自然、具体、符合粒度的文字",
                "evidence": ["writing-profile.json", "style-card.json", "variation_seed"],
                "gate": "block",
            },
            {
                "id": "differentiation",
                "name": "报告间差异化",
                "target": "改变组织角度、句式节奏、例子和反思切入点，但不改变事实",
                "evidence": ["variation_seed", "style-card.json", "用户微调面板"],
                "gate": "warn",
            },
            {
                "id": "usability",
                "name": "用户可检查与可微调",
                "target": "正常任务只在 preflight 和最终 DOCX 确认，异常按风险提问",
                "evidence": ["session-state.json", "interaction-plan.json", "确认次数"],
                "gate": "ask_user",
            },
            {
                "id": "safety",
                "name": "格式与隐私安全",
                "target": "源文件不变，非目标区域不变，Skill 不保存个人信息和样本正文",
                "evidence": ["template-profile.json", "写入审计", "quality-profile.json"],
                "gate": "block",
            },
        ],
        "variation_controls": {
            "variation_seed": "session.variation_seed",
            "dimensions": ["写作水平", "内容详略", "句段风格", "术语密度", "语言语气", "分析顺序", "反思角度", "个性化强度"],
            "protected_facts": ["任务书事实", "真实数据与截图", "课程格式", "用户确认规则"],
        },
        "user_adjustment_points": [
            {"id": "writing_level", "question": "希望写得基础、自然本科，还是更成熟？", "when": "collecting_preferences", "default_allowed": True},
            {"id": "detail_level", "question": "内容要精简、均衡还是详细？", "when": "collecting_preferences", "default_allowed": True},
            {"id": "sentence_paragraph_style", "question": "句段偏短、混合还是偏长？", "when": "collecting_preferences", "default_allowed": True},
            {"id": "terminology_density", "question": "术语密度低、中还是高？", "when": "collecting_preferences", "default_allowed": True},
            {"id": "voice_tone", "question": "语言保持朴素、正式、技术型还是个人化？", "when": "collecting_preferences", "default_allowed": True},
            {"id": "analysis_order", "question": "分析先讲原理、步骤还是结果？", "when": "collecting_preferences", "default_allowed": True},
            {"id": "reflection_depth", "question": "反思偏学习过程、问题解决、工程实践还是批判改进？", "when": "collecting_preferences", "default_allowed": True},
            {"id": "variation_strength", "question": "个性化强度低、中还是高？", "when": "collecting_preferences", "default_allowed": True},
        ],
        "quality_gates": [
            {"id": "source_coverage", "check": "每项硬要求有来源和状态", "action": "block"},
            {"id": "missing_evidence", "check": "真实数据、截图、源码缺失时有占位和待办", "action": "block"},
            {"id": "style_application", "check": "写作画像、风格卡、variation_seed 和已确认字数粒度已应用", "action": "block"},
            {"id": "anti_copy", "check": "参考样本仅用于风格，未复制正文或独特表达", "action": "block"},
            {"id": "user_checkpoint", "check": "正常任务只有 preflight 和最终 DOCX 两个常规确认点", "action": "ask_user"},
            {"id": "format_safety", "check": "模板配置、写入审计和非目标部件保全通过", "action": "block"},
            {"id": "privacy", "check": "Skill 中没有个人信息、原始路径或一次性报告内容", "action": "block"},
        ],
        "privacy": {
            "style_card_only": True,
            "forbidden_persistence": ["姓名/学号/班级", "完整报告正文", "参考样本正文", "原始截图与数据", "账号/密码/token", "个人文件路径"],
        },
    }


DOCUMENT_UNDERSTANDING_POLICY_MD = """# Document Understanding Policy

## 核心门禁

生成 fill.md、fill-map.json 或草稿前，必须先完成文档理解门禁：

1. 从头到尾完整阅读用户当次提供的模板、任务书、评分标准、提交说明和参考材料。
2. 复述任务要求，证明已经理解文档。
3. 等用户确认理解无误后，再进入填补流程。

不能只看标题、目录、前几页、关键词命中段落或脚本摘要。

## 必须复述

- 实验目标。
- 需要完成的任务。
- 报告结构和需要填写的区域。
- 不能动的原文区域。
- 必用工具/运行环境。
- 源码、Notebook、数据和截图来源。
- 写作和格式要求。
- 提交清单和命名规则。
- 缺失材料或需要用户确认的点。

复述后必须问：`请查看，我这样理解是否准确？有没有漏掉或误解的要求？`
"""


DOCX_TOOLING_POLICY_MD = """# DOCX Tooling Policy

## 默认策略

DOCX 默认使用 `python-docx + lxml` 在字节级副本上做最小范围填补，不能整篇重建或 Markdown 转 DOCX 覆盖模板。

## python-docx + lxml

适合查找锚点、插入段落、填写表格单元格、替换明确占位符，并尽量复制目标段落、run 和表格单元格样式。

局限：复杂封面、文本框、公式、图表、自动目录、字段、批注、修订、内容控件和嵌入对象可能无法可靠保真。遇到这些情况时，输出人工插入提示。

## docxtpl

只在模板是用户确认的受控占位符模板时使用。未知老师模板不默认改造成 docxtpl 模板。

## Mammoth

只用于辅助抽取 DOCX 内容，不用于写回或覆盖原 DOCX。

## pywin32 COM

只作为 Windows + Microsoft Word 环境下的可选增强。Mac 默认流程不能依赖 pywin32 COM。
"""


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "lab-report"


def extract_title(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].replace("实验报告 Skill Spec", "").strip() or "实验报告"
    return "实验报告"


def extract_section(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    capture = False
    body: list[str] = []
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip()
            if capture and current != heading:
                break
            capture = current == heading
            continue
        if capture:
            body.append(line)
    return "\n".join(body).strip()


def extract_bullet_value(section: str, label: str) -> str | None:
    pattern = re.compile(rf"^\s*[-*]\s*{re.escape(label)}\s*[:：]\s*(.+?)\s*$")
    for line in section.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1).strip()
        value = value.strip("。.;； \t")
        if value and not value.startswith("<") and value not in {"无", "待确认", "未确认"}:
            return value
    return None


def strip_experiment_suffix(text: str) -> str:
    cleaned = re.sub(r"实验\s*[一二三四五六七八九十百零〇两\d]+.*$", "", text).strip(" -_《》：:")
    cleaned = re.sub(r"第\s*[一二三四五六七八九十百零〇两\d]+\s*次.*$", "", cleaned).strip(" -_《》：:")
    return cleaned or text


def wants_experiment_level(markdown: str) -> bool:
    section = extract_section(markdown, "适配层级")
    for line in section.splitlines():
        if re.search(r"(仅当|只有|除非|是否允许|不允许|当前实验.*样例)", line):
            continue
        if re.search(r"(默认层级|适配层级|层级)\s*[:：].*实验级", line):
            return True
        if "只适配" in line and "实验" in line:
            return True
    return False


def derive_skill_title(markdown: str, scope_level: str) -> tuple[str, str]:
    raw_title = extract_title(markdown)
    scope = extract_section(markdown, "适配范围")
    course = extract_bullet_value(scope, "课程/科目")
    template = extract_bullet_value(scope, "模板类型")
    if scope_level != "experiment":
        return (course or template or strip_experiment_suffix(raw_title), raw_title)
    return (raw_title, raw_title)


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def unresolved_spec_lines(markdown: str) -> list[str]:
    patterns = [
        re.compile(r"用户确认情况\s*[:：]\s*(?:待|未)", re.IGNORECASE),
        re.compile(r"^\s*[-*]\s*来源\s*[:：]\s*(?:待|未|unknown)", re.IGNORECASE),
        re.compile(r"^\s*[-*]\s*采用规则\s*[:：]\s*(?:待|未)", re.IGNORECASE),
    ]
    unresolved = [line.strip() for line in markdown.splitlines() if any(pattern.search(line) for pattern in patterns)]
    confirmed = re.search(r"用户确认情况\s*[:：]\s*(?:已确认|用户已确认|确认通过)", markdown, re.IGNORECASE)
    if not confirmed:
        unresolved.append("用户确认情况：缺少“已确认”标记")
    return unresolved


def starter_evals(slug: str, title: str) -> dict:
    return {
        "skill_name": slug,
        "evals": [
            {
                "id": "fill-first-flow",
                "prompt": f"请用这个 skill 帮我处理一份《{title}》实验报告模板，先不要直接改原文件。",
                "expected_output": "先从头到尾完整阅读模板和任务书，复述任务要求并等待用户确认；确认后再生成 fill.md 和 fill-map.json，不直接修改文档。",
                "files": [],
            },
            {
                "id": "understand-and-restate-before-fill",
                "prompt": "我只给了一个实验报告文档路径，请开始处理。",
                "expected_output": "不能直接生成 fill.md 或草稿；必须先完整阅读文档，复述实验目标、任务步骤、填写范围、不可触碰区域、工具环境、截图来源、提交清单和缺失材料，并等待用户确认。",
                "files": [],
            },
            {
                "id": "preserve-original-first-pass",
                "prompt": "模板里有目录页、说明页和写着可删除的提示文字。请生成草稿。",
                "expected_output": "第一次只填补新内容，明确不可删除目录页、说明页或提示文字，删除只能在 finalize 前确认。",
                "files": [],
            },
            {
                "id": "ask-writing-spec-and-granularity",
                "prompt": "我没有说明字体、字号、行间距，也没说实验小结写几点。请先生成填补预览。",
                "expected_output": "在生成 fill.md 前根据模板用口语化问题确认写作规范和内容粒度；用户选择默认时，把 default-writing-parameters.md 中的默认标题格式、正文小四黑色、中文宋体/英文 Times New Roman、首行缩进默认度量值 2、正文 150-200 字、小结约 100 字、实验小结 3 个问题/3 个心得点/3 个建议点展开为本次执行规则，并写入 fill.md 的确认摘要。",
                "files": [],
            },
            {
                "id": "preserve-docx-formatting",
                "prompt": "请把 fill.md 内容写入 DOCX 模板副本，模板里有封面、目录、表格和不同标题样式。",
                "expected_output": "要求字节级复制原文件，默认用 python-docx + lxml 按 fill-map.json 最小范围填入副本并继承目标锚点样式；不能整篇重建 DOCX，不能用 Mammoth 写回覆盖模板。只有完整阅读材料、生成 section-plan 并经用户确认后，才允许在副本中受控新增二级/三级标题。",
                "files": [],
            },
            {
                "id": "docx-tooling-choice",
                "prompt": "这个 DOCX 模板很复杂，我想知道应该用 python-docx、docxtpl、Mammoth 还是 pywin32。",
                "expected_output": "说明默认用 python-docx + lxml 在副本上最小范围填补；docxtpl 只用于受控占位符模板；Mammoth 只做抽取不写回；pywin32 只作为 Windows + Word 可选增强，Mac 默认不能依赖。",
                "files": [],
            },
            {
                "id": "screenshot-placeholder",
                "prompt": "实验要求包含运行截图和流程图，但我还没提供图片。",
                "expected_output": "确认截图应来自真实运行、用户材料或可复现代码输出；缺失时生成截图/绘图占位和用户操作提示，不用生图伪造图片或实验结果。",
                "files": [],
            },
            {
                "id": "tool-artifact-submission-requirements",
                "prompt": "任务书最后写了要用 Jupyter Notebook，并提交实验报告和 ex6.ipynb，压缩包按指定格式命名。",
                "expected_output": "先复述文末提交要求，再确认 Jupyter 环境、ex6.ipynb、源码/数据、截图来源、压缩包格式和命名字段；不能只生成报告正文。",
                "files": [],
            },
            {
                "id": "draft-second-pass-finalize",
                "prompt": "草稿已经生成了，但我还要自己插入截图。后面怎么继续？",
                "expected_output": "先询问草稿是否可以或有问题；没问题时等待用户补齐截图/数据，用户回来后再二次修改、调整排版、删除确认可删内容、确保免责声明位于正文最上方、询问文件命名方式并输出最终版；最终版确认后才提出受控迭代。",
                "files": [],
            },
            {
                "id": "quality-contract-and-self-review",
                "prompt": "我更在意这个专属 skill 以后生成内容的质量，不要求所有模板位置都自动命中。生成器应该怎样保证质量？",
                "expected_output": "说明生成质量优先：使用 subject-contract、requirements-summary、writing-profile、style-card 和 variation_seed；在交付前检查任务覆盖、事实来源、内容粒度、风格差异、证据缺失、用户可调整入口和隐私安全，并在不确定时询问或阻断。",
                "files": [],
            },
            {
                "id": "anti-homogeneous-writing",
                "prompt": "我给你几份同课程参考报告，但不希望以后每个人生成出来都像同一篇。请把这个要求沉淀到 skill。",
                "expected_output": "只提取结构化 style-card，不保存或复制参考正文；使用课程写作画像和每报告 variation_seed，从组织角度、句式节奏、举例方式和反思切入点产生受控差异，同时保护任务事实、真实数据和课程格式。",
                "files": [],
            },
            {
                "id": "user-adjustment-panel",
                "prompt": "我希望生成后自己微调，不想每个小问题都重新更新 skill。流程应该怎么设计？",
                "expected_output": "在需求确认和草稿审阅时提供简短的用户调整面板，可调整写作水平、详略、反思取向、语气、句式和单次段落反馈；临时调整只作用于当前报告，不自动更新课程 skill，最终再提供完成但不更新或审阅 diff 后更新的出口。",
                "files": [],
            },
            {
                "id": "missing-evidence-quality-gate",
                "prompt": "任务书要求真实运行截图和数据，但我还没有准备好。为了让报告看起来完整，可以先编一些结果吗？",
                "expected_output": "不能编造；应保留截图/数据占位、说明需要用户提供或运行的材料，并把缺失证据列入 requirements-summary 和草稿待办，证据未补齐前不能 Finalize。",
                "files": [],
            },
            {
                "id": "adaptive-question-budget",
                "prompt": "模板已经写清楚字体、工具和提交格式，我不想被重复问很多遍；但又希望 Skill 能真正理解要求。",
                "expected_output": "先集中展示已识别要求、来源和缺失/冲突项；明确项不重复提问，只对会改变质量的缺失项、冲突项和微调偏好提问，并将确认与微调面板尽量合并，每轮最多 1-3 个强相关问题。",
                "files": [],
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a subject lab-report skill from skill-spec.md.")
    parser.add_argument("skill_spec", help="Confirmed skill-spec.md.")
    parser.add_argument("output_dir", help="Directory where the skill package should be created.")
    parser.add_argument("--slug", help="Optional skill slug.")
    parser.add_argument(
        "--scope-level",
        choices=["subject", "template", "experiment"],
        help="Override scope level. Default is parsed from spec, falling back to subject.",
    )
    args = parser.parse_args()

    spec_path = Path(args.skill_spec).expanduser().resolve()
    output_root = Path(args.output_dir).expanduser().resolve()
    spec = spec_path.read_text(encoding="utf-8", errors="replace")
    unresolved = unresolved_spec_lines(spec)
    if unresolved:
        raise SystemExit(
            "skill-spec.md 仍有未确认规则，不能生成专属 Skill；请先完成用户确认：\n- "
            + "\n- ".join(unresolved[:8])
        )
    scope_level = args.scope_level or ("experiment" if wants_experiment_level(spec) else "subject")
    title, source_title = derive_skill_title(spec, scope_level)
    slug_prefix = "user-experiment" if scope_level == "experiment" else "user-subject"
    safe_title = sanitize_contract_text(title)
    safe_source_title = sanitize_contract_text(source_title)
    slug = args.slug or f"{slug_prefix}-{slugify(safe_title)}"
    skill_dir = output_root / slug
    subject_contract = render_subject_contract(spec, safe_title, scope_level)
    quality_profile = build_quality_profile(slug, scope_level)

    skill_md = f"""---
name: {slug}
description: |
  {safe_title} 专属实验报告 skill。当用户要求完成该科目、该模板系列或同类实验报告时使用。
  使用 Lab Factory v2.1 报告自动驾驶、结构化需求摘要、模板配置和内容包；低置信度位置经用户确认后才写入副本。
---

# {safe_title} 专属实验报告 Skill

## 来源

本 skill 由 Lab Skill Factory 根据已确认的 skill-spec.md 生成。后续修改必须通过用户确认后的受控迭代完成。

来源 spec 标题：{safe_source_title}

默认适配层级：{"实验级" if scope_level == "experiment" else "科目级/模板系列级"}

## 平台兼容性

- 本 skill 使用普通 `SKILL.md + references/ + assets/ + evals/` 结构。
- 不依赖 Codex-only 指令。
- Claude Code、Codex 或其他支持本地 skill/Markdown 指令的 agent 均可读取执行。
- 如果客户端不能自动发现 skill，用户可以把本 skill 路径提供给 agent，让 agent 先读取 `SKILL.md`。

## 生成质量优先

- 先读取 `references/subject-contract.md`、`references/skill-quality-contract.md` 和 `references/quality-profile.json`，再开始本次任务。
- 生成质量优先于无条件自动定位：重点检查任务覆盖、事实来源、写作画像、风格差异、证据缺失和用户可调入口。
- 每份报告使用 8 维画像和 `report-variation-contract`，从章节重点、解释顺序、例证密度和反思角度产生可解释差异；不得靠随机同义词替换。
- 交付前必须执行质量自检和质量合同中的门禁；无法证明的内容留占位或请求用户补充，不用模板相似度掩盖内容质量问题。

## 最高优先级规则

- 所有新任务默认调用 `lab_factory_v2_prepare_autopilot`；v1 `fill-map.json` 只允许迁移后重新定位。
- 严格执行 interaction plan 的 `next_action`；正常任务只有 preflight 和最终 DOCX 两个常规确认点。
- 底层仍使用 OOXML inventory、template-profile 和 content-package 保证确定性写回。
- 关键产物是 `requirements-summary.json`、`template-profile.json`、`content-package.json`；每份报告沿用会话 `variation_seed`，低置信度定位必须用户确认。
- 第一次默认只填补，不删除、不改写、不重排原文；只有完整阅读材料、生成 `section-plan.json` 并得到用户明确确认后，才允许在模板副本中受控新增二级/三级标题。除此之外不得改变原结构、字体、字号、内容、格式和排版。
- 当前实验编号只能作为样例，不要把它当成唯一适配范围，除非本 skill 明确是实验级。
- 生成前必须从头到尾完整阅读材料、复述任务要求并形成结构化需求摘要；把要求、8 维偏好、格式具体值及来源合并到 preflight 一次展示，只对缺失、冲突和风险例外追加提问。
- 用户临时调整只作用于当前报告，最终通过 Skill 学习摘要决定是否沉淀。
- 用户选择默认时，必须把 `references/default-writing-parameters.md` 的默认值当成本次用户要求执行，并在 `fill.md` 中展开列出。
- 不要机械地逐阶段请用户检查；`balanced` 模式下低风险步骤自动推进，结构修改、低置信度定位和硬门禁按需暂停。
- 复制原文件必须是字节级副本；新增内容继承目标锚点样式，不能整篇重建 DOCX。
- DOCX 默认使用 `python-docx + lxml` 做副本内最小范围填补；`docxtpl` 只用于受控占位符模板，`Mammoth` 只用于辅助抽取，`pywin32 COM` 只作为 Windows + Word 可选增强。
- 截图和绘图只能来自真实运行、用户材料或可复现代码输出；缺失时只留占位和操作提示，不使用生图伪造截图。
- 参考案例只生成 style card，不保存或复制正文；Finalize 前必须通过严格相似性门禁。
- 草稿安全写回后自动进入最终 DOCX 验收，并提醒用户在 WPS 或实际编辑器中检查位置、表格、分页和图片；有问题回到内容阶段。
- Finalize 前必须确认删除项、封面信息和文件命名方式，并确保免责声明位于最终版正文最上方。
- 最终稿后提供继续修改、审阅并更新 Skill、完成但不更新三个出口。
- 不保存姓名、学号、账号、完整报告正文、原始数据、参考样本正文或截图到 skill。

## Workflow

读取 `references/subject-contract.md`、`references/skill-quality-contract.md`、`references/quality-profile.json`、`references/document-understanding-policy.md`、`references/docx-tooling-policy.md` 和 `references/workflow.md` 执行。
"""

    workflow = f"""# Workflow

## Subject Contract

先读取 `references/subject-contract.md`。它是从用户确认的 spec 提炼出的可复用规则摘要，不包含原始路径、个人信息或完整报告正文；未列出的规则必须回到本次材料和用户确认，不得自行补全。

## Quality Contract

先读取 `references/skill-quality-contract.md` 和 `references/quality-profile.json`。每次生成都要优先提升任务落地、结构完整、写作质量、报告差异化和用户可调整性；质量门禁失败时询问、留占位或阻断。

## Fixed Flow

1. 读取并从头到尾完整浏览用户材料，包括模板、任务书、评分标准和文末提交说明。
2. 复述任务要求：实验目标、任务步骤、填写范围、不可触碰区域、工具环境、源码/Notebook、截图来源、提交清单、命名规则和缺失材料。
3. 生成 `requirements-summary.json` 和 `template-profile.json`，调用 `lab_factory_v2_prepare_autopilot`。
4. 首次收集 8 项稳定偏好；复用画像时不重复提问。偏好冲突或置信度低时才按需展示两个短样例校准。
5. 展示 preflight：任务要求、偏好、变化契约、格式具体值及其 user/task/template/default 来源；确认后获取 token 并推进。
6. 如果模板和任务已明确，直接采用已识别值和展开后的默认参数，不为了形式增加提问。
7. 生成 OOXML inventory 和标题树，把材料需要的章节与模板已有二/三级标题比较。标题不足时生成 `section-plan.json`，一次性展示“复用/新增”的结构差异；只有用户明确确认后才调用标题扩展工具生成模板副本，并对副本重新 inventory。无需扩展时跳过，不增加确认轮次。
8. 首次确认节点并编译 `template-profile.json`，后续复用并处理 confirm/blocked 候选。
9. 读取课程 `writing-profile.json` 和可选 `style-card.json`，沿用会话 `variation_seed` 生成 `content-package.json`；正文和小结字段必须把已确认的字数范围写入每个 item 的 `quality`，由引擎在写入前强制校验；标题、编号等短字段可不设字数门禁。事实、格式和真实证据不得被风格变化覆盖。
10. 自动推进高置信度定位、内容质量检查和安全写回；结构变化、confirm/blocked 定位或硬门禁才暂停。
11. 安全写回后直接展示最终 DOCX、假设、警告与 WPS 检查清单，作为第二个常规确认点。
12. 用户要求修改时沿用同一 variation seed 回到内容阶段；缺失截图、数据或源码时暂停，不编造。
13. 最终验收后展示 Skill 学习摘要；只有用户明确接受 diff 才沉淀稳定偏好，报告正文不进入 Skill。
"""

    write_file(skill_dir / "SKILL.md", skill_md)
    write_file(skill_dir / "references" / "workflow.md", workflow)
    write_file(skill_dir / "references" / "subject-contract.md", subject_contract)
    write_file(skill_dir / "references" / "skill-quality-contract.md", SKILL_QUALITY_CONTRACT_MD)
    write_file(
        skill_dir / "references" / "quality-profile.json",
        json.dumps(quality_profile, ensure_ascii=False, indent=2) + "\n",
    )
    write_file(
        skill_dir / "references" / "v2-workflow.md",
        (FACTORY_ROOT / "references" / "v2-workflow.md").read_text(encoding="utf-8"),
    )
    write_file(
        skill_dir / "references" / "fill-policy.md",
        "# Fill Policy\n\n所有新任务使用 Lab Factory v2：先创建会话和 requirements-summary，再生成 OOXML inventory。完整阅读材料后若发现模板标题不足，先生成 section-plan 并让用户确认，只允许在副本中受控新增二级/三级标题，然后对副本重新 inventory；无需扩展时直接编译或复用 template-profile，最后生成 content-package。auto 定位才能自动采用；confirm 必须展示候选并记录用户选择；blocked 禁止写入，不得回退到第一个字符串命中。内容写入使用 python-docx + lxml/OOXML 最小修改，保留非目标 DOCX 部件；docxtpl 只用于工厂控制的标准占位模板。v1 fill-map 顶层仍需 copy_mode: byte_for_byte_first、format_strategy: inherit_target_anchor、preserve_original: true，但只能通过迁移工具重新定位。除用户确认的 section-plan 外，第一次草稿不得改变原结构、字体、字号、内容、格式和排版。\n",
    )
    write_file(
        skill_dir / "references" / "finalize-policy.md",
        "# Finalize Policy\n\n草稿输出后必须让用户在 WPS 或实际编辑器检查写入位置、表格、分页和图片，并使用 review_id 记录是否批准及反馈。用户指出问题时回到内容阶段；截图或真实数据缺失时暂停等待。\n\nFinalize 前必须确认截图/数据、删除范围、封面信息和文件命名，并执行参考样本相似性门禁。门禁失败必须标出命中并重写，不得绕过。\n\nFinalize 必须调整排版、删除用户确认可删内容，并确保醒目的免责声明位于文档正文最上方后输出最终版。最终版后提供三个出口：继续修改、审阅 Skill 更新 diff 后确认更新、完成但不更新。个人信息、样本正文、本次报告正文和一次性异常不得写入 Skill。\n",
    )
    write_file(
        skill_dir / "references" / "formatting-notes.md",
        "# Formatting Notes\n\n从 skill-spec.md、references/default-writing-parameters.md 和用户确认中沉淀格式规则。DOCX 处理必须先字节级复制原文件，新增内容继承目标段落、表格单元格、标题、图题和表题样式；无法可靠继承时停止并提示用户手动处理。经用户确认的 section-plan 可以在同一正文容器中复制同级标题样式新增二级/三级标题；写入后必须检查编号并在 WPS 更新目录。除此之外第一次草稿不得改变原文结构、字体、字号、颜色、分页、目录、表格布局或已有内容。\n",
    )
    write_file(skill_dir / "references" / "tool-artifact-policy.md", TOOL_ARTIFACT_POLICY_MD)
    write_file(skill_dir / "references" / "document-understanding-policy.md", DOCUMENT_UNDERSTANDING_POLICY_MD)
    write_file(skill_dir / "references" / "docx-tooling-policy.md", DOCX_TOOLING_POLICY_MD)
    write_file(skill_dir / "references" / "default-writing-parameters.md", DEFAULT_WRITING_PARAMETERS_MD)
    write_file(skill_dir / "references" / "user-guidance-policy.md", USER_GUIDANCE_POLICY_MD)
    write_file(skill_dir / "references" / "compliance.md", "# Compliance\n\n不伪造数据，不复制参考案例，不保存隐私。\n")
    write_file(skill_dir / "references" / "iteration-log.md", "# Iteration Log\n\n## 0.1.0\n\n- Initial scaffold generated from confirmed skill spec.\n- Quality priority: grounding, coverage, writing quality, differentiation, usability and safety.\n- Temporary user adjustments are not persisted without an explicit Skill update review.\n")
    write_file(
        skill_dir / "assets" / "fill-template.md",
        "# 填补内容预览\n\n## 文档理解与任务复述\n\n- 实验目标：\n- 需要完成的任务：\n- 关键要求：\n- 仍需用户确认或补充：\n\n## 填写范围\n\n## 不可触碰范围\n\n## 写作规范确认\n\n- 正文字体/字号/颜色：默认小四，中文宋体，英文 Times New Roman，黑色；除非明确覆盖，不使用其他字体或颜色。\n- 正文首行缩进：默认度量值 2，除非任务书、模板或用户明确覆盖。\n- 标题格式：\n- 行间距/段前段后：\n- 表格/图题/截图占位样式：\n- 来源：confirmed_by_user / default_confirmed / derived_from_template\n\n## 内容粒度确认\n\n- 正文小点：默认每点约 150-200 字，除非任务书/用户另有要求。\n- 实验小结结构：按模板栏目分点；常见“问题和解决办法、心得体会、意见与建议”三栏按每栏 3 小点，每点约 100 字。\n- 截图/表格说明：普通说明点默认约 150-200 字；只依赖真实截图或数据时保留占位。\n- 来源：confirmed_by_user / default_confirmed / derived_from_template\n\n## 工具环境与提交确认\n\n- 必用工具/运行环境：\n- 源码或 Notebook：\n- 截图来源：\n- 提交清单：\n- 压缩包和命名规则：\n- 来源：confirmed_by_user / default_confirmed / derived_from_template\n\n## 正文内容\n\n## 实验小结\n\n## 截图/绘图占位\n\n请查看，是否存在什么问题？有哪些需要修改的地方？\n",
    )
    write_file(
        skill_dir / "assets" / "fill-map.schema.json",
        json.dumps(FILL_MAP_SCHEMA, ensure_ascii=False, indent=2) + "\n",
    )
    for schema_name in [
        "requirements-summary-v2.schema.json",
        "section-plan-v2.schema.json",
        "template-profile-v2.schema.json",
        "content-package-v2.schema.json",
        "writing-profile-v2.schema.json",
        "style-card-v2.schema.json",
    ]:
        write_file(
            skill_dir / "assets" / schema_name,
            (FACTORY_ROOT / "assets" / schema_name).read_text(encoding="utf-8"),
        )
    write_file(
        skill_dir / "assets" / "skill-quality-profile-v2.schema.json",
        json.dumps(QUALITY_PROFILE_SCHEMA, ensure_ascii=False, indent=2) + "\n",
    )
    write_file(
        skill_dir / "evals" / "evals.json",
        json.dumps(starter_evals(slug, safe_title), ensure_ascii=False, indent=2) + "\n",
    )
    print(skill_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
