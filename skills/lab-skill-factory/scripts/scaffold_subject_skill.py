#!/usr/bin/env python3
"""Scaffold a subject-specific lab report skill from a confirmed skill spec."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


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
                "expected_output": "要求字节级复制原文件，默认用 python-docx + lxml 按 fill-map.json 最小范围填入副本并继承目标锚点样式；不能整篇重建 DOCX，不能用 Mammoth 写回覆盖模板，草稿阶段不得改变原结构、字体、字号、内容、格式和排版。",
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
                "expected_output": "先询问草稿是否可以或有问题；没问题时等待用户补齐截图/数据，用户回来后再二次修改、调整排版、删除确认可删内容、添加文末免责声明、询问文件命名方式并输出最终版；最终版确认后才提出受控迭代。",
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
    scope_level = args.scope_level or ("experiment" if wants_experiment_level(spec) else "subject")
    title, source_title = derive_skill_title(spec, scope_level)
    slug_prefix = "user-experiment" if scope_level == "experiment" else "user-subject"
    slug = args.slug or f"{slug_prefix}-{slugify(title)}"
    skill_dir = output_root / slug

    skill_md = f"""---
name: {slug}
description: |
  {title} 专属实验报告 skill。当用户要求完成该科目、该模板系列或同类实验报告时使用。
  先生成 fill.md + fill-map.json，用户确认后再由 MCP 复制原文件并按锚点填入副本。
---

# {title} 专属实验报告 Skill

## 来源

本 skill 由 Lab Skill Factory 根据已确认的 skill-spec.md 生成。后续修改必须通过用户确认后的受控迭代完成。

来源 spec 标题：{source_title}

默认适配层级：{"实验级" if scope_level == "experiment" else "科目级/模板系列级"}

## 平台兼容性

- 本 skill 使用普通 `SKILL.md + references/ + assets/ + evals/` 结构。
- 不依赖 Codex-only 指令。
- Claude Code、Codex 或其他支持本地 skill/Markdown 指令的 agent 均可读取执行。
- 如果客户端不能自动发现 skill，用户可以把本 skill 路径提供给 agent，让 agent 先读取 `SKILL.md`。

## 最高优先级规则

- 先生成 `fill.md + fill-map.json`，不要直接改文档。
- 用户确认 `fill.md` 后，才允许复制源文件并填入副本。
- 第一次只填补，不删除、不改写、不重排原文，不改变原结构、字体、字号、内容、格式和排版。
- 当前实验编号只能作为样例，不要把它当成唯一适配范围，除非本 skill 明确是实验级。
- 生成 `fill.md` 前必须先从头到尾完整阅读实验报告、任务书和文末提交说明，充分理解后复述任务要求，并等待用户确认；然后再根据模板多轮确认写作规范、内容粒度、实验小结结构、必用工具、运行环境、源码/Notebook、截图来源、提交清单和 finalize 边界。
- 用户选择默认时，必须把 `references/default-writing-parameters.md` 的默认值当成本次用户要求执行，并在 `fill.md` 中展开列出。
- 每个阶段都要请用户检查并鼓励修正：`请查看，是否存在什么问题？有哪些需要修改的地方？`
- 复制原文件必须是字节级副本；新增内容继承目标锚点样式，不能整篇重建 DOCX。
- DOCX 默认使用 `python-docx + lxml` 做副本内最小范围填补；`docxtpl` 只用于受控占位符模板，`Mammoth` 只用于辅助抽取，`pywin32 COM` 只作为 Windows + Word 可选增强。
- 截图和绘图只能来自真实运行、用户材料或可复现代码输出；缺失时只留占位和操作提示，不使用生图伪造截图。
- 参考案例只学格式，不复制内容。
- 草稿输出后必须询问用户是否满意或有问题；有问题先修正，没问题则等待用户补齐截图/绘图/数据后再二次修改。
- Finalize 前必须确认删除项、封面信息和文件命名方式，并在最终版末尾添加免责声明。
- 不保存姓名、学号、账号、完整报告正文、原始数据或截图到 skill。

## Workflow

读取 `references/document-understanding-policy.md`、`references/docx-tooling-policy.md` 和 `references/workflow.md` 执行。
"""

    workflow = f"""# Workflow

## Skill Spec

本 skill 按以下 spec 执行：

```markdown
{spec}
```

## Fixed Flow

1. 读取并从头到尾完整浏览用户材料，包括模板、任务书、评分标准和文末提交说明。
2. 复述任务要求：实验目标、任务步骤、填写范围、不可触碰区域、工具环境、源码/Notebook、截图来源、提交清单、命名规则和缺失材料。
3. 等待用户确认理解无误；如果用户指出误解，先修正复述。
4. 结合模板和任务书，多轮确认填写范围、不可触碰范围、写作规范、内容粒度、实验小结结构、必用工具、运行环境、源码/Notebook、截图来源、提交清单和 finalize 边界；用户选择默认时展开 `references/default-writing-parameters.md` 的具体默认值，并把它们当成本次用户要求。
5. 生成 `fill.md`。
6. 生成带 `copy_mode: byte_for_byte_first` 和 `format_strategy: inherit_target_anchor` 的 `fill-map.json`。
7. 等待用户确认。
8. 用户确认后，调用 MCP 文件处理能力字节级复制并填入副本。
9. 输出草稿后，询问用户：`请查看，草稿是否可以？是否存在什么问题？有哪些需要修改的地方？`
10. 用户指出问题时，先修正新增内容、占位、`fill.md` 或 `fill-map.json`，再请用户检查。
11. 用户确认草稿没问题但仍需插入图片/截图/数据时，暂停等待用户完成，并提醒用户回来进行第二次修改。
12. Finalize：调整排版，删除用户确认可删内容，添加文末免责声明，询问文件命名方式并输出最终版。
13. 用户确认最终版后，询问用户是否要更新迭代 skill；先说明拟优化方向，用户确认后才写入。
"""

    write_file(skill_dir / "SKILL.md", skill_md)
    write_file(skill_dir / "references" / "workflow.md", workflow)
    write_file(
        skill_dir / "references" / "fill-policy.md",
        "# Fill Policy\n\n先生成 fill.md 和 fill-map.json，用户确认后再填入副本。生成 fill.md 前必须先完成文档理解门禁：从头到尾完整阅读模板、任务书和文末提交说明，复述实验目标、任务步骤、填写范围、不可触碰区域、工具环境、源码/Notebook、截图来源、提交清单、命名规则和缺失材料，并等待用户确认理解无误。之后再根据模板多轮确认写作规范、内容粒度、实验小结结构、必用工具、运行环境、源码/Notebook、截图来源、提交清单和 finalize 边界；用户选择默认时，必须展开 references/default-writing-parameters.md 的具体值，并把默认值当成本次用户要求执行。fill.md 必须包含文档理解与任务复述、写作规范确认摘要、内容粒度确认摘要、工具环境与提交确认摘要。默认正文为小四、中文宋体、英文 Times New Roman、黑色、首行缩进默认度量值 2；正文说明点约 150-200 字；若模板包含“问题和解决办法、心得体会、意见与建议”，且用户采用默认，实验小结必须生成 3 个问题、3 个心得点、3 个建议点，每点约 100 字。每个阶段都要请用户检查并鼓励修正。DOCX 默认用 python-docx + lxml 在字节级副本上最小范围填补；docxtpl 只用于受控占位符模板；Mammoth 只用于辅助抽取，不写回；pywin32 COM 只作为 Windows + Word 可选增强。fill-map 顶层必须包含 copy_mode: byte_for_byte_first 和 format_strategy: inherit_target_anchor；每个 item 必须 preserve_original: true 并继承目标锚点样式。第一次草稿不得改变原结构、字体、字号、内容、格式和排版。\n",
    )
    write_file(
        skill_dir / "references" / "finalize-policy.md",
        "# Finalize Policy\n\n草稿输出后必须询问用户是否可以、是否存在问题、有哪些需要修改。用户指出问题时先修正新增内容、占位、fill.md 或 fill-map.json；用户确认草稿没问题但仍需图片、截图、绘图或真实数据时，暂停等待用户完成，并提醒用户回来进行第二次修改。\n\nFinalize 前必须确认：截图/绘图/数据是否补齐，哪些模板提示、占位和草稿提示可以删除，哪些原文必须保留，封面个人信息，文件命名方式，以及是否还有排版问题。个人信息和文件命名只用于本次最终版，不写入 skill。\n\nFinalize 必须调整排版、删除用户确认可删内容、在报告最后添加免责声明，并按用户确认的命名方式输出最终版。免责声明：本文档中的 AI 辅助生成内容仅供学习参考，使用者应结合个人真实实验过程自行核验，并遵守课程要求和学术规范。\n\n最终版输出后必须请用户检查；用户确认满意后，才询问是否要更新迭代 skill。更新前先说明拟优化方向，用户确认后才写入。\n",
    )
    write_file(
        skill_dir / "references" / "formatting-notes.md",
        "# Formatting Notes\n\n从 skill-spec.md、references/default-writing-parameters.md 和用户确认中沉淀格式规则。DOCX 处理必须先字节级复制原文件，新增内容继承目标段落、表格单元格、标题、图题和表题样式；无法可靠继承时停止并提示用户手动处理。第一次草稿不得改变原文结构、字体、字号、颜色、分页、目录、表格布局或已有内容。\n",
    )
    write_file(skill_dir / "references" / "tool-artifact-policy.md", TOOL_ARTIFACT_POLICY_MD)
    write_file(skill_dir / "references" / "document-understanding-policy.md", DOCUMENT_UNDERSTANDING_POLICY_MD)
    write_file(skill_dir / "references" / "docx-tooling-policy.md", DOCX_TOOLING_POLICY_MD)
    write_file(skill_dir / "references" / "default-writing-parameters.md", DEFAULT_WRITING_PARAMETERS_MD)
    write_file(skill_dir / "references" / "user-guidance-policy.md", USER_GUIDANCE_POLICY_MD)
    write_file(skill_dir / "references" / "compliance.md", "# Compliance\n\n不伪造数据，不复制参考案例，不保存隐私。\n")
    write_file(skill_dir / "references" / "iteration-log.md", "# Iteration Log\n\n## 0.1.0\n\n- Initial scaffold generated from confirmed skill spec.\n")
    write_file(
        skill_dir / "assets" / "fill-template.md",
        "# 填补内容预览\n\n## 文档理解与任务复述\n\n- 实验目标：\n- 需要完成的任务：\n- 关键要求：\n- 仍需用户确认或补充：\n\n## 填写范围\n\n## 不可触碰范围\n\n## 写作规范确认\n\n- 正文字体/字号/颜色：默认小四，中文宋体，英文 Times New Roman，黑色；除非明确覆盖，不使用其他字体或颜色。\n- 正文首行缩进：默认度量值 2，除非任务书、模板或用户明确覆盖。\n- 标题格式：\n- 行间距/段前段后：\n- 表格/图题/截图占位样式：\n- 来源：confirmed_by_user / default_confirmed / derived_from_template\n\n## 内容粒度确认\n\n- 正文小点：默认每点约 150-200 字，除非任务书/用户另有要求。\n- 实验小结结构：按模板栏目分点；常见“问题和解决办法、心得体会、意见与建议”三栏按每栏 3 小点，每点约 100 字。\n- 截图/表格说明：普通说明点默认约 150-200 字；只依赖真实截图或数据时保留占位。\n- 来源：confirmed_by_user / default_confirmed / derived_from_template\n\n## 工具环境与提交确认\n\n- 必用工具/运行环境：\n- 源码或 Notebook：\n- 截图来源：\n- 提交清单：\n- 压缩包和命名规则：\n- 来源：confirmed_by_user / default_confirmed / derived_from_template\n\n## 正文内容\n\n## 实验小结\n\n## 截图/绘图占位\n\n请查看，是否存在什么问题？有哪些需要修改的地方？\n",
    )
    write_file(
        skill_dir / "assets" / "fill-map.schema.json",
        json.dumps(FILL_MAP_SCHEMA, ensure_ascii=False, indent=2) + "\n",
    )
    write_file(
        skill_dir / "evals" / "evals.json",
        json.dumps(starter_evals(slug, title), ensure_ascii=False, indent=2) + "\n",
    )
    print(skill_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
