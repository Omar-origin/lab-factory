#!/usr/bin/env python3
"""Stdio MCP wrapper for the Lab Skill Factory skill.

This server intentionally keeps the MCP layer thin: it exposes activation,
material inspection, DOCX outline extraction, spec validation, fill-map
validation, and subject-skill scaffolding. The actual lab-skill-factory rules
remain in the skill package and its helper scripts.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import runpy
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
import commercial_client
import autopilot


SERVER_NAME = "lab-factory-mcp"
SERVER_VERSION = "1.0.0-beta.1"
PROTOCOL_VERSION = "2024-11-05"

FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).resolve()
SERVER_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
REPO_ROOT = SERVER_DIR.parents[1] if not FROZEN else SERVER_DIR
DEFAULT_SKILL_ROOT = (BUNDLE_ROOT / "skills" / "lab-skill-factory") if FROZEN else (REPO_ROOT / "skills" / "lab-skill-factory")
DEFAULT_VENDOR_DIR = SERVER_DIR / "vendor"


def configure_stdio() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")


configure_stdio()


def vendor_dir() -> Path:
    return Path(os.environ.get("LAB_FACTORY_VENDOR_DIR", DEFAULT_VENDOR_DIR)).expanduser().resolve()


if vendor_dir().exists():
    sys.path.insert(0, str(vendor_dir()))


class ToolError(Exception):
    """A user-actionable MCP tool error."""

    def __init__(self, message: str, code: str = "TOOL_ERROR", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def skill_root() -> Path:
    return Path(os.environ.get("LAB_FACTORY_SKILL_ROOT", DEFAULT_SKILL_ROOT)).expanduser().resolve()


def product_id() -> str:
    return os.environ.get("LAB_FACTORY_PRODUCT_ID", commercial_client.PRODUCT_ID)


def python_executable() -> str:
    return os.environ.get("LAB_FACTORY_PYTHON", sys.executable)


def workspace_root() -> Path:
    return Path(os.environ.get("LAB_FACTORY_WORKSPACE_ROOT", Path.cwd())).expanduser().resolve()


def resolve_user_path(path_string: str) -> str:
    path = Path(path_string).expanduser()
    if not path.is_absolute():
        path = workspace_root() / path
    return str(path.resolve())


def activation_status() -> dict[str, Any]:
    return commercial_client.activation_status()


def require_activation(enforce_minimum_version: bool = True) -> None:
    status = activation_status()
    if status.get("activated"):
        return
    raise ToolError(
        f"{status.get('message', '工具尚未激活。')} "
        f"购买说明：{commercial_client.PURCHASE_URL}；支持：{commercial_client.SUPPORT_EMAIL}；"
        "在线密钥用户调用 lab_factory_activate_key；离线许可证用户调用 lab_factory_activate。"
    )


def run_skill_script(
    script_name: str,
    args: list[str],
    *,
    timeout: int = 90,
    ok_return_codes: tuple[int, ...] = (0,),
) -> dict[str, Any]:
    root = skill_root()
    script = root / "scripts" / script_name
    if not root.exists():
        raise ToolError(f"找不到 lab-skill-factory skill 根目录：{root}")
    if not script.exists():
        raise ToolError(f"找不到辅助脚本：{script}")

    env = os.environ.copy()
    vendor = vendor_dir()
    if vendor.exists():
        pythonpath_parts = [str(vendor)]
        if env.get("PYTHONPATH"):
            pythonpath_parts.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

    command = [sys.executable, "--run-skill-script", str(script), *args] if FROZEN else [python_executable(), str(script), *args]
    proc = subprocess.run(
        command,
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    if proc.returncode not in ok_return_codes:
        message = f"{script_name} 执行失败，退出码 {proc.returncode}。"
        if stderr:
            message += f" stderr: {stderr[-1200:]}"
        if stdout:
            message += f" stdout: {stdout[-1200:]}"
        raise ToolError(message)

    parsed: Any
    try:
        parsed = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        parsed = {"stdout": stdout}
    if stderr:
        parsed = {"result": parsed, "stderr": stderr}
    if isinstance(parsed, dict):
        parsed.setdefault("exit_code", proc.returncode)
    return parsed if isinstance(parsed, dict) else {"result": parsed, "exit_code": proc.returncode}


def tool_status(_: dict[str, Any]) -> dict[str, Any]:
    root = skill_root()
    status = activation_status()
    return {
        "ok": True,
        "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "activation": status,
        "telemetry": commercial_client.telemetry_status(),
        "telemetry_first_run_question": "是否允许在本机记录不含文档内容的匿名质量数据？数据仅在你主动导出并发送后才会离开设备。" if commercial_client.telemetry_status().get("telemetry") == "unset" else None,
        "skill_root": str(root),
        "skill_root_exists": root.exists(),
        "vendor_dir": str(vendor_dir()),
        "vendor_dir_exists": vendor_dir().exists(),
        "client_compatibility": {
            "transport": "stdio",
            "clients": ["Claude Code", "Codex", "any MCP client that supports stdio servers"],
            "note": "This server is not Codex-specific. Client differences are handled by config snippets.",
        },
        "available_scripts": sorted(p.name for p in (root / "scripts").glob("*.py")) if root.exists() else [],
        "distribution_note": "Lab Factory 1.x 商业授权：一个密钥绑定一个安装，在线租约最长 24 小时；报告内容始终只在本地处理。",
        "custom_skill_visibility_recommendation": (
            "建议让定制出来的专属 skill 可见、可编辑，因为它是用户自己的规则沉淀；"
            "不要把核心工厂逻辑、激活逻辑、完整报告正文或隐私材料写进专属 skill。"
        ),
    }


def module_available(import_name: str) -> bool:
    return importlib.util.find_spec(import_name) is not None


def tool_check_runtime(_: dict[str, Any]) -> dict[str, Any]:
    checks = [
        {
            "package": "python-docx",
            "import_name": "docx",
            "required_for": "DOCX 最小范围读取/写入和样式继承",
            "required_level": "recommended_for_docx_write",
        },
        {
            "package": "lxml",
            "import_name": "lxml",
            "required_for": "底层 OOXML 检查和复杂 DOCX 辅助处理",
            "required_level": "recommended_for_docx_write",
        },
        {
            "package": "docxtpl",
            "import_name": "docxtpl",
            "required_for": "受控占位符模板增强，不用于未知老师模板默认写回",
            "required_level": "optional",
        },
        {
            "package": "mammoth",
            "import_name": "mammoth",
            "required_for": "DOCX 到 HTML/Markdown 的只读抽取增强",
            "required_level": "optional",
        },
        {
            "package": "pywin32",
            "import_name": "win32com",
            "required_for": "Windows + Microsoft Word 自动化增强",
            "required_level": "windows_optional",
        },
    ]
    results = []
    for check in checks:
        results.append({**check, "available": module_available(check["import_name"])})

    missing_recommended = [
        item["package"]
        for item in results
        if item["required_level"] == "recommended_for_docx_write" and not item["available"]
    ]
    packaging_command = (
        "Rebuild the release binary with build/build_macos.sh or build/build_windows.ps1; "
        "runtime dependencies must be bundled during build."
        if FROZEN
        else (
            f"{sys.executable} -m pip install --target {vendor_dir()} "
            f"-r {SERVER_DIR / 'runtime-requirements.txt'}"
        )
    )
    return {
        "ok": not missing_recommended,
        "python": sys.executable,
        "vendor_dir": str(vendor_dir()),
        "vendor_dir_exists": vendor_dir().exists(),
        "checks": results,
        "packaging_command": packaging_command,
        "note": (
            "当前 MCP 核心工具只依赖 Python 标准库。真正写 DOCX 时建议随产品打包 "
            "python-docx 和 lxml 到 vendor/；docxtpl、mammoth、pywin32 保持条件增强。"
        ),
    }


def client_command_args() -> tuple[str, list[str]]:
    command = os.environ.get("LAB_FACTORY_SERVER_COMMAND", str(sys.executable) if FROZEN else "python3")
    args = ["serve-mcp"] if FROZEN else [str(SERVER_DIR / "cli.py"), "serve-mcp"]
    return command, args


def build_client_config(client: str) -> dict[str, Any]:
    command, args = client_command_args()
    env = {}
    if not FROZEN or os.environ.get("LAB_FACTORY_SKILL_ROOT"):
        env["LAB_FACTORY_SKILL_ROOT"] = str(skill_root())
    env["LAB_FACTORY_PRODUCT_ID"] = product_id()
    for key in ("LAB_FACTORY_PURCHASE_URL", "LAB_FACTORY_SUPPORT_EMAIL", "LAB_FACTORY_FEEDBACK_EMAIL"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    if os.environ.get("LAB_FACTORY_WORKSPACE_ROOT"):
        env["LAB_FACTORY_WORKSPACE_ROOT"] = str(workspace_root())
    if os.environ.get("LAB_FACTORY_VENDOR_DIR"):
        env["LAB_FACTORY_VENDOR_DIR"] = str(vendor_dir())

    if client == "claude_code":
        return {
            "format": "json",
            "config": {
                "mcpServers": {
                    "lab-skill-factory": {
                        "command": command,
                        "args": args,
                        "env": env,
                    }
                }
            },
            "note": "Use this as a Claude Code MCP server snippet or translate it through Claude Code's MCP add command.",
        }
    if client == "codex":
        env_lines = "\n".join(f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in env.items())
        toml = (
            "[mcp_servers.lab-skill-factory]\n"
            f"command = {json.dumps(command, ensure_ascii=False)}\n"
            f"args = {json.dumps(args, ensure_ascii=False)}\n\n"
            "[mcp_servers.lab-skill-factory.env]\n"
            f"{env_lines}\n"
        )
        return {
            "format": "toml",
            "config": toml,
            "note": "Use this in Codex's MCP server configuration.",
        }
    if client == "generic_stdio":
        return {
            "format": "json",
            "config": {
                "name": "lab-skill-factory",
                "transport": "stdio",
                "command": command,
                "args": args,
                "env": env,
            },
            "note": "Generic stdio MCP shape for clients that do not use mcpServers JSON.",
        }
    raise ToolError("client 只能是 claude_code、codex 或 generic_stdio。")


def tool_export_client_config(args: dict[str, Any]) -> dict[str, Any]:
    client = args.get("client", "generic_stdio")
    if not isinstance(client, str):
        raise ToolError("client 必须是字符串。")
    data = build_client_config(client)
    command, command_args = client_command_args()
    data.update(
        {
            "ok": True,
            "client": client,
            "entrypoint": " ".join([command, *command_args]),
            "source_entrypoint": str(SERVER_DIR / "cli.py"),
            "compatibility": "standard stdio MCP; not tied to Codex-only APIs",
        }
    )
    return data


def tool_create_license_request(args: dict[str, Any]) -> dict[str, Any]:
    output = args.get("output_path")
    if not isinstance(output, str) or not output.strip():
        raise ToolError("output_path 必须是 .lfreq 文件路径。")
    path = Path(resolve_user_path(output))
    if path.suffix.lower() != ".lfreq":
        raise ToolError("授权请求文件必须使用 .lfreq 扩展名。")
    try:
        return commercial_client.create_license_request(path)
    except Exception as exc:
        raise ToolError(f"生成授权请求失败：{exc}") from exc


def tool_activate(args: dict[str, Any]) -> dict[str, Any]:
    license_path = args.get("license_path")
    if not isinstance(license_path, str) or not license_path.strip():
        raise ToolError("license_path 必须是销售者发回的 .lflicense 文件路径。")
    if args.get("adult_confirmed") is not True:
        raise ToolError("激活前必须确认使用者已满18岁。")
    terms_version = args.get("terms_version")
    if terms_version != commercial_client.TERMS_VERSION:
        raise ToolError(f"必须明确接受当前协议版本 {commercial_client.TERMS_VERSION}。")
    try:
        result = commercial_client.activate(Path(resolve_user_path(license_path)), True, terms_version)
    except Exception as exc:
        raise ToolError(f"激活失败：{exc}") from exc
    if not result.get("ok"):
        raise ToolError(f"激活失败：{result.get('error') or result}")
    return {"ok": True, "message": "Lab Factory 1.x 创始内测永久离线授权导入成功。", **result}


def tool_activate_key(args: dict[str, Any]) -> dict[str, Any]:
    activation_key = args.get("activation_key")
    if not isinstance(activation_key, str) or not activation_key.strip():
        raise ToolError("activation_key 必须是中控生成的非空密钥。")
    if args.get("adult_confirmed") is not True:
        raise ToolError("激活前必须确认使用者已满18岁。")
    terms_version = args.get("terms_version")
    if terms_version != commercial_client.TERMS_VERSION:
        raise ToolError(f"必须明确接受当前协议版本 {commercial_client.TERMS_VERSION}。")
    control_url = args.get("control_url")
    if control_url is not None and not isinstance(control_url, str):
        raise ToolError("control_url 必须是字符串。")
    try:
        return commercial_client.activate_key(activation_key, True, terms_version, control_url or "")
    except Exception as exc:
        raise ToolError(f"在线密钥激活失败：{exc}") from exc


def tool_deactivate(_: dict[str, Any]) -> dict[str, Any]:
    result = commercial_client.deactivate()
    if not result.get("ok"):
        raise ToolError(str(result.get("error") or "解绑失败"))
    return result


def tool_request_refund(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("confirm_refund_request") is not True:
        raise ToolError("退款申请会立即停止签发新租约，必须明确设置 confirm_refund_request=true。")
    try:
        return commercial_client.request_refund()
    except Exception as exc:
        raise ToolError(f"退款申请失败：{exc}") from exc


def tool_telemetry_settings(args: dict[str, Any]) -> dict[str, Any]:
    action = args.get("action", "status")
    if action == "enable":
        return commercial_client.set_telemetry(True)
    if action == "disable":
        return commercial_client.set_telemetry(False)
    if action == "status":
        return commercial_client.telemetry_status()
    if action == "clear":
        return commercial_client.clear_telemetry()
    raise ToolError("action 只能是 enable、disable、status 或 clear。")


def tool_submit_draft_feedback(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    rating = args.get("rating")
    edit_time = args.get("edit_time_bucket")
    categories = args.get("issue_categories", [])
    if not isinstance(rating, int) or rating < 1 or rating > 5:
        raise ToolError("rating 必须是 1-5 的整数。")
    if edit_time not in {"under_15m", "15_30m", "30_60m", "over_60m"}:
        raise ToolError("edit_time_bucket 不合法。")
    if not isinstance(categories, list) or not all(isinstance(item, str) for item in categories):
        raise ToolError("issue_categories 必须是字符串数组。")
    status = activation_status()
    feedback = {
        "review_id": require_string(args, "review_id"), "rating": rating,
        "issue_categories": categories[:10], "edit_time_bucket": edit_time,
        "channel_id": status.get("channel_id"),
    }
    try:
        result = commercial_client.record_feedback(feedback)
    except Exception as exc:
        raise ToolError(f"反馈记录失败：{exc}") from exc
    if not result.get("ok"):
        raise ToolError(str(result.get("error") or "反馈记录失败"))
    return result


def tool_export_feedback(args: dict[str, Any]) -> dict[str, Any]:
    output = args.get("output_path")
    if not isinstance(output, str) or not output.strip():
        raise ToolError("output_path 必须是导出文件路径。")
    try:
        return commercial_client.export_feedback(Path(resolve_user_path(output)))
    except Exception as exc:
        raise ToolError(f"反馈导出失败：{exc}") from exc


def tool_verify_update(args: dict[str, Any]) -> dict[str, Any]:
    path, sha256 = args.get("path"), args.get("sha256")
    if not isinstance(path, str) or not isinstance(sha256, str) or len(sha256) != 64:
        raise ToolError("path 和 64 位 SHA-256 必须提供。")
    return commercial_client.verify_update_file(Path(resolve_user_path(path)), sha256)


def tool_inspect_materials(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    paths = args.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        raise ToolError("paths 必须是非空字符串数组。")
    max_files = args.get("max_files", 300)
    if not isinstance(max_files, int) or max_files <= 0:
        raise ToolError("max_files 必须是正整数。")
    result = run_skill_script(
        "inspect_lab_materials.py",
        [*(resolve_user_path(path) for path in paths), "--max-files", str(max_files)],
        timeout=60,
    )
    result["mcp_next_step"] = (
        "不要直接定制 skill。先完整阅读任务书/模板/文末提交说明，复述要求，"
        "再用口语化问题确认写作规范、填写范围、工具环境、截图来源、提交清单和命名规则。"
    )
    return result


def tool_extract_docx_outline(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    docx_path = args.get("docx_path")
    if not isinstance(docx_path, str) or not docx_path.strip():
        raise ToolError("docx_path 必须是非空字符串。")
    result = run_skill_script("extract_docx_outline.py", [resolve_user_path(docx_path)], timeout=90)
    result["mcp_next_step"] = (
        "请从 paragraphs 第一段读到最后一段，特别检查 paragraphs_tail 和 requirement_paragraphs，"
        "然后向用户复述完整任务要求并等待确认。"
    )
    return result


def tool_validate_skill_spec(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    path = args.get("skill_spec_path")
    if not isinstance(path, str) or not path.strip():
        raise ToolError("skill_spec_path 必须是非空字符串。")
    result = run_skill_script("validate_skill_spec.py", [resolve_user_path(path)], timeout=30, ok_return_codes=(0, 1, 2))
    result["mcp_next_step"] = "ok=false 时，先补齐缺失章节和未确认项，再生成专属 skill。"
    return result


def tool_validate_fill_map(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    path = args.get("fill_map_path")
    if not isinstance(path, str) or not path.strip():
        raise ToolError("fill_map_path 必须是非空字符串。")
    result = run_skill_script("validate_fill_map.py", [resolve_user_path(path)], timeout=30, ok_return_codes=(0, 1, 2))
    result["mcp_next_step"] = (
        "ok=false 时，修正 copy_mode、format_strategy、preserve_original 和锚点操作后再写入 DOCX 副本。"
    )
    return result


def tool_apply_fill_map(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    fill_map_path = args.get("fill_map_path")
    if not isinstance(fill_map_path, str) or not fill_map_path.strip():
        raise ToolError("fill_map_path 必须是非空字符串。")
    command_args = [resolve_user_path(fill_map_path)]
    output_path = args.get("output_path")
    if isinstance(output_path, str) and output_path.strip():
        command_args.extend(["--output", resolve_user_path(output_path)])
    if args.get("overwrite", False) is True:
        command_args.append("--overwrite")

    validation = run_skill_script(
        "validate_fill_map.py",
        [resolve_user_path(fill_map_path)],
        timeout=30,
        ok_return_codes=(0, 1, 2),
    )
    if not validation.get("ok"):
        raise ToolError(f"fill-map 校验失败，不能写入副本：{validation.get('errors') or validation.get('error')}")

    result = run_skill_script("apply_fill_map.py", command_args, timeout=120, ok_return_codes=(0, 1))
    if not result.get("ok"):
        raise ToolError(f"写入副本失败：{result.get('error')}")
    result["mcp_next_step"] = (
        "请让用户检查草稿副本。若截图/绘图/真实数据未补齐，暂停等待用户补齐；"
        "不要在第一次草稿阶段删除模板原文或提示。"
    )
    return result


def run_v2(args: list[str], *, timeout: int = 120, allow_validation_failure: bool = False) -> dict[str, Any]:
    codes = (0, 1) if allow_validation_failure else (0,)
    return run_skill_script("v2_engine.py", args, timeout=timeout, ok_return_codes=codes)


def require_string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{key} 必须是非空字符串。")
    return value.strip()


def require_integer(args: dict[str, Any], key: str) -> int:
    value = args.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolError(f"{key} 必须是整数。")
    return value


def run_autopilot(function: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return function(*args, **kwargs)
    except autopilot.AutopilotError as exc:
        raise ToolError(str(exc), code=exc.code, details=exc.details) from exc


def tool_v2_prepare_autopilot(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    mode = args.get("mode", "balanced")
    if mode == "strict":
        workspace = require_string(args, "workspace")
        raw_key = require_string(args, "idempotency_key")
        try:
            strict_report_id = "strict_" + uuid.UUID(raw_key).hex[:12]
        except ValueError as exc:
            raise ToolError("idempotency_key 必须是 UUID。", code="IDEMPOTENCY_KEY_INVALID") from exc
        legacy_state_path = Path(resolve_user_path(workspace)) / "lab-factory" / "session-state.json"
        if legacy_state_path.exists():
            existing = v2_session_status(workspace)
            session = existing.get("session") or {}
            if session.get("version") != "2.0" or session.get("report_id") != strict_report_id:
                raise ToolError("workspace 已存在其他会话。", code="SESSION_EXISTS")
            legacy = existing
        else:
            legacy = run_v2([
                "create-session", resolve_user_path(workspace),
                "--subject", require_string(args, "subject"), "--report-id", strict_report_id,
            ])
        return {
            "ok": True, "mode": "strict", "legacy_session": legacy.get("session"),
            "next_action": "ask_user", "reason_code": "STRICT_REQUIREMENTS_CONFIRMATION",
            "required_tool": "lab_factory_v2_confirm_requirements",
            "note": "strict 模式映射现有 v2.0 逐阶段确认流程；后续继续使用旧 v2 工具。",
        }
    writing_profile = args.get("writing_profile_path")
    style_card = args.get("style_card_path")
    return run_autopilot(
        autopilot.prepare,
        Path(resolve_user_path(require_string(args, "workspace"))),
        require_string(args, "idempotency_key"),
        require_string(args, "subject"),
        mode,
        Path(resolve_user_path(require_string(args, "requirements_path"))),
        Path(resolve_user_path(require_string(args, "template_profile_path"))),
        Path(resolve_user_path(writing_profile)) if isinstance(writing_profile, str) and writing_profile.strip() else None,
        Path(resolve_user_path(style_card)) if isinstance(style_card, str) and style_card.strip() else None,
    )


def tool_v2_answer_questions(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    answers = args.get("answers")
    if not isinstance(answers, list):
        raise ToolError("answers 必须是数组。")
    return run_autopilot(
        autopilot.answer_questions,
        Path(resolve_user_path(require_string(args, "workspace"))),
        require_integer(args, "state_version"),
        require_string(args, "idempotency_key"),
        require_string(args, "plan_id"),
        answers,
    )


def tool_v2_confirm_checkpoint(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    return run_autopilot(
        autopilot.confirm_checkpoint,
        Path(resolve_user_path(require_string(args, "workspace"))),
        require_integer(args, "state_version"),
        require_string(args, "idempotency_key"),
        require_string(args, "checkpoint_id"),
        require_string(args, "summary_sha256"),
    )


def tool_v2_advance_autopilot(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    artifacts = args.get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise ToolError("artifacts 必须是对象。")
    token = args.get("confirmation_token")
    return run_autopilot(
        autopilot.advance,
        Path(resolve_user_path(require_string(args, "workspace"))),
        require_integer(args, "state_version"),
        require_string(args, "idempotency_key"),
        token if isinstance(token, str) and token else None,
        artifacts,
    )


def tool_v2_autopilot_status(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    return run_autopilot(
        autopilot.status,
        Path(resolve_user_path(require_string(args, "workspace"))),
    )


def v2_session_status(workspace: str) -> dict[str, Any]:
    return run_v2(["session-status", resolve_user_path(workspace)])


def require_v2_state(workspace: str, expected: set[str]) -> dict[str, Any]:
    result = v2_session_status(workspace)
    state = ((result.get("session") or {}).get("state"))
    if state not in expected:
        raise ToolError(f"当前 v2 会话状态为 {state}，此操作要求状态为：{', '.join(sorted(expected))}。")
    return result


def tool_v2_inventory(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    command = ["inventory", resolve_user_path(require_string(args, "docx_path"))]
    output = args.get("output_path")
    if isinstance(output, str) and output.strip():
        command.extend(["--output", resolve_user_path(output)])
    result = run_v2(command)
    result["mcp_next_step"] = "让用户检查可写节点；文本框、公式、域和修订节点不得自动写入。"
    return result


def tool_v2_create_template_profile(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    fields = args.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ToolError("fields 必须是非空数组，每项至少包含 id、node_id 和 operation。")
    return run_v2(
        [
            "create-profile", resolve_user_path(require_string(args, "inventory_path")),
            "--fields-json", json.dumps(fields, ensure_ascii=False),
            "--subject", require_string(args, "subject"),
            "--output", resolve_user_path(require_string(args, "output_path")),
        ]
    )


def tool_v2_validate_template_profile(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    return run_v2(
        ["validate-profile", resolve_user_path(require_string(args, "profile_path"))],
        allow_validation_failure=True,
    )


def tool_v2_propose_placements(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    command = [
        "propose", resolve_user_path(require_string(args, "profile_path")),
        resolve_user_path(require_string(args, "docx_path")),
    ]
    output = args.get("output_path")
    if isinstance(output, str) and output.strip():
        command.extend(["--output", resolve_user_path(output)])
    result = run_v2(command)
    result["mcp_next_step"] = (
        "auto 项可直接采用；confirm 项必须把候选上下文展示给用户并调用 resolve_placements；"
        "blocked 项不得写入。"
    )
    return result


def tool_v2_propose_section_plan(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    proposal = args.get("proposal")
    if not isinstance(proposal, dict):
        raise ToolError("proposal 必须是对象，包含材料来源、任务要求摘要、用户要求摘要和待新增标题。")
    result = run_v2(
        [
            "create-section-plan", resolve_user_path(require_string(args, "inventory_path")),
            "--proposal-json", json.dumps(proposal, ensure_ascii=False),
            "--output", resolve_user_path(require_string(args, "output_path")),
        ]
    )
    result["mcp_next_step"] = "把 section plan 的标题差异预览一次性展示给用户；未得到明确确认不得调用 apply_section_plan。"
    return result


def tool_v2_apply_section_plan(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    workspace = require_string(args, "workspace")
    require_v2_state(workspace, {"requirements_confirmed"})
    confirmation = require_string(args, "user_confirmation_summary")
    command = [
        "apply-section-plan", resolve_user_path(require_string(args, "section_plan_path")),
        resolve_user_path(require_string(args, "docx_path")),
        "--confirmation", confirmation,
        "--output", resolve_user_path(require_string(args, "output_path")),
    ]
    if args.get("overwrite") is True:
        command.append("--overwrite")
    result = run_v2(command, timeout=180)
    transition = run_v2(
        ["advance-session", resolve_user_path(workspace), "--event", "resolve_sections", "--feedback", confirmation]
    )
    result["session"] = transition.get("session")
    result["mcp_next_step"] = "对扩展后的 DOCX 重新执行 inventory，再创建模板配置和定位计划；最终在 WPS 更新目录。"
    return result


def tool_v2_create_session(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    command = [
        "create-session", resolve_user_path(require_string(args, "workspace")),
        "--subject", require_string(args, "subject"),
    ]
    report_id = args.get("report_id")
    if isinstance(report_id, str) and report_id.strip():
        command.extend(["--report-id", report_id.strip()])
    return run_v2(command)


def tool_v2_session_status(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    return v2_session_status(require_string(args, "workspace"))


def tool_v2_confirm_requirements(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    workspace = require_string(args, "workspace")
    require_v2_state(workspace, {"materials_scanned"})
    validation = run_v2(
        ["validate-requirements", resolve_user_path(require_string(args, "requirements_path"))],
        allow_validation_failure=True,
    )
    if not validation.get("ok"):
        raise ToolError(f"需求摘要未通过校验：{validation.get('errors')}")
    feedback = require_string(args, "user_confirmation_summary")
    return run_v2(
        ["advance-session", resolve_user_path(workspace), "--event", "confirm_requirements", "--feedback", feedback]
    )


def tool_v2_resolve_placements(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    workspace = require_string(args, "workspace")
    require_v2_state(workspace, {"requirements_confirmed", "sections_resolved"})
    plan_path = Path(resolve_user_path(require_string(args, "placement_plan_path")))
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError(f"无法读取 placement plan：{exc}") from exc
    selections = args.get("selections")
    if not isinstance(selections, list):
        raise ToolError("selections 必须是数组。")
    selected = {item.get("field_id"): item.get("node_id") for item in selections if isinstance(item, dict)}
    errors = []
    for proposal in plan.get("proposals", []):
        if proposal.get("decision") == "blocked":
            errors.append(f"{proposal.get('field_id')} 没有可靠候选，不能继续")
        if proposal.get("decision") == "confirm":
            allowed = {item.get("node_id") for item in proposal.get("candidates", [])}
            if selected.get(proposal.get("field_id")) not in allowed:
                errors.append(f"{proposal.get('field_id')} 尚未选择有效候选")
    if errors:
        raise ToolError("；".join(errors))
    feedback = require_string(args, "user_confirmation_summary")
    profile_result = run_v2(
        [
            "confirm-profile", resolve_user_path(require_string(args, "profile_path")),
            resolve_user_path(require_string(args, "docx_path")), str(plan_path),
            "--selections-json", json.dumps(selections, ensure_ascii=False),
            "--summary", feedback,
            "--output", resolve_user_path(require_string(args, "updated_profile_path")),
        ]
    )
    audit_summary = json.dumps({"confirmation": feedback, "selections": selected}, ensure_ascii=False)
    transition = run_v2(
        ["advance-session", resolve_user_path(workspace), "--event", "resolve_placements", "--feedback", audit_summary]
    )
    return {"ok": True, "profile": profile_result, "session": transition.get("session")}


def tool_v2_mark_content_ready(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    workspace = require_string(args, "workspace")
    require_v2_state(workspace, {"placements_resolved", "draft_reviewed"})
    return run_v2(
        ["advance-session", resolve_user_path(workspace), "--event", "mark_content_ready", "--feedback", require_string(args, "content_summary")]
    )


def tool_v2_apply_draft(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    workspace = require_string(args, "workspace")
    require_v2_state(workspace, {"content_ready"})
    command = [
        "apply", resolve_user_path(require_string(args, "profile_path")),
        resolve_user_path(require_string(args, "docx_path")),
        resolve_user_path(require_string(args, "content_package_path")),
        "--output", resolve_user_path(require_string(args, "output_path")),
    ]
    if args.get("overwrite") is True:
        command.append("--overwrite")
    result = run_v2(command, timeout=180)
    transition = run_v2(["advance-session", resolve_user_path(workspace), "--event", "record_draft"])
    result["session"] = transition.get("session")
    result["mcp_next_step"] = "必须让用户在 WPS 中检查草稿；未提交 draft review 前不得 finalize。"
    return result


def tool_v2_review_draft(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    workspace = require_string(args, "workspace")
    require_v2_state(workspace, {"draft_generated"})
    decision = require_string(args, "decision")
    if decision not in {"approve", "revise"}:
        raise ToolError("decision 只能是 approve 或 revise。")
    event = "approve_draft" if decision == "approve" else "revise_draft"
    return run_v2(
        [
            "advance-session", resolve_user_path(workspace), "--event", event,
            "--review-id", require_string(args, "review_id"),
            "--feedback", require_string(args, "user_feedback_summary"),
        ]
    )


def tool_v2_finalize(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    workspace = require_string(args, "workspace")
    require_v2_state(workspace, {"draft_reviewed"})
    command = ["similarity", resolve_user_path(require_string(args, "generated_path"))]
    references = args.get("reference_paths", [])
    if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
        raise ToolError("reference_paths 必须是字符串数组。")
    command.extend(resolve_user_path(item) for item in references)
    if not references:
        # argparse requires one reference; no reference means the anti-copy gate has no comparison surface.
        similarity = {"ok": True, "gate": "pass", "findings": [], "note": "No reference samples supplied."}
    else:
        whitelist = args.get("whitelist", [])
        if not isinstance(whitelist, list) or not all(isinstance(item, str) for item in whitelist):
            raise ToolError("whitelist 必须是字符串数组。")
        command.extend(["--whitelist-json", json.dumps(whitelist, ensure_ascii=False)])
        similarity = run_v2(command, allow_validation_failure=True)
    if not similarity.get("ok"):
        raise ToolError(f"相似性门禁阻止 finalize：{similarity.get('findings')}")
    disclaimer = run_v2(["ensure-disclaimer", resolve_user_path(require_string(args, "generated_path"))])
    if disclaimer.get("disclaimer_count") != 1:
        raise ToolError("AI 辅助生成声明无法安全写入，Finalize 已阻止。")
    transition = run_v2(
        [
            "advance-session", resolve_user_path(workspace), "--event", "finalize",
            "--review-id", require_string(args, "review_id"),
            "--feedback", require_string(args, "user_confirmation_summary"),
        ]
    )
    return {"ok": True, "similarity_gate": similarity, "disclaimer": disclaimer, "session": transition.get("session"), "next_actions": ["continue_revision", "review_skill_update", "finish_without_update"]}


def tool_v2_decide_iteration(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    workspace = require_string(args, "workspace")
    require_v2_state(workspace, {"finalized"})
    decision = require_string(args, "decision")
    if decision == "continue_revision":
        event = "revise_draft"
    elif decision == "finish_without_update":
        event = "finish_without_update"
    else:
        raise ToolError("decision 只能是 continue_revision 或 finish_without_update；更新 Skill 请先 propose diff，再调用 apply_skill_update。")
    return run_v2(
        [
            "advance-session", resolve_user_path(workspace), "--event", event,
            "--review-id", require_string(args, "review_id"),
            "--feedback", require_string(args, "user_feedback_summary"),
        ]
    )


def tool_v2_create_writing_profile(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    overrides = args.get("overrides", {})
    if not isinstance(overrides, dict):
        raise ToolError("overrides 必须是对象。")
    return run_v2(
        [
            "create-writing-profile", "--subject", require_string(args, "subject"),
            "--preset", str(args.get("preset", "balanced")),
            "--overrides-json", json.dumps(overrides, ensure_ascii=False),
            "--output", resolve_user_path(require_string(args, "output_path")),
        ]
    )


def tool_v2_validate_style_card(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    return run_v2(
        ["validate-style-card", resolve_user_path(require_string(args, "style_card_path"))],
        allow_validation_failure=True,
    )


def tool_v2_migrate_v1(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    return run_v2(
        [
            "migrate-v1", resolve_user_path(require_string(args, "fill_map_path")),
            "--output", resolve_user_path(require_string(args, "output_path")),
        ]
    )


def tool_v2_propose_skill_update(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    workspace = require_string(args, "workspace")
    require_v2_state(workspace, {"finalized"})
    updates = args.get("updates")
    if not isinstance(updates, list) or not updates:
        raise ToolError("updates 必须是非空数组。")
    return run_v2(
        [
            "propose-skill-update", resolve_user_path(require_string(args, "skill_dir")),
            "--updates-json", json.dumps(updates, ensure_ascii=False),
            "--output", resolve_user_path(require_string(args, "output_path")),
        ]
    )


def tool_v2_apply_skill_update(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    workspace = require_string(args, "workspace")
    require_v2_state(workspace, {"finalized"})
    proposal_path = Path(resolve_user_path(require_string(args, "proposal_path")))
    try:
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError(f"无法读取 Skill 更新提案：{exc}") from exc
    if proposal.get("update_id") != require_string(args, "update_id"):
        raise ToolError("update_id 与用户审阅的提案不一致。")
    result = run_v2(["apply-skill-update", str(proposal_path)])
    transition = run_v2(
        [
            "advance-session", resolve_user_path(workspace), "--event", "update_skill",
            "--review-id", require_string(args, "review_id"),
            "--feedback", require_string(args, "user_confirmation_summary"),
        ]
    )
    return {"ok": True, "update": result, "session": transition.get("session")}


def validate_scaffolded_skill_dir(skill_path: str) -> dict[str, Any]:
    return run_skill_script(
        "validate_scaffolded_skill.py",
        [resolve_user_path(skill_path)],
        timeout=30,
        ok_return_codes=(0, 1, 2),
    )


def tool_scaffold_subject_skill(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    skill_spec_path = args.get("skill_spec_path")
    output_dir = args.get("output_dir")
    if not isinstance(skill_spec_path, str) or not skill_spec_path.strip():
        raise ToolError("skill_spec_path 必须是非空字符串。")
    if not isinstance(output_dir, str) or not output_dir.strip():
        raise ToolError("output_dir 必须是非空字符串。")

    if not args.get("skip_validation", False):
        validation = run_skill_script(
            "validate_skill_spec.py",
            [resolve_user_path(skill_spec_path)],
            timeout=30,
            ok_return_codes=(0, 1, 2),
        )
        if not validation.get("ok"):
            raise ToolError(
                "skill-spec.md 还没有通过校验，不能生成专属 skill。"
                f"缺失章节：{validation.get('missing_headings') or validation.get('error')}"
            )
        if not validation.get("confirmed", False):
            unresolved = validation.get("unresolved_confirmation") or ["存在未确认的规则"]
            raise ToolError(
                "skill-spec.md 仍有未确认规则，不能生成专属 skill；请先让用户确认："
                + "；".join(unresolved[:8])
            )

    command_args = [resolve_user_path(skill_spec_path), resolve_user_path(output_dir)]
    slug = args.get("slug")
    if isinstance(slug, str) and slug.strip():
        command_args.extend(["--slug", slug.strip()])
    scope_level = args.get("scope_level")
    if isinstance(scope_level, str) and scope_level.strip():
        if scope_level not in {"subject", "template", "experiment"}:
            raise ToolError("scope_level 只能是 subject、template 或 experiment。")
        command_args.extend(["--scope-level", scope_level])

    result = run_skill_script("scaffold_subject_skill.py", command_args, timeout=90)
    skill_path = result.get("stdout") or result.get("result")
    validation = validate_scaffolded_skill_dir(str(skill_path)) if skill_path else {"ok": False, "error": "missing skill_path"}
    return {
        "ok": bool(validation.get("ok")),
        "skill_path": skill_path,
        "quality_validation": validation,
        "message": (
            "专属 skill 骨架已生成并完成内置质量校验。下一步请让用户检查 skill 的触发范围、写作规范、"
            "填补区域、不可触碰区域、工具环境和 finalize 流程；同时检查质量画像、用户微调入口和质量自检合同；"
            "确认后再安装或使用。"
            if validation.get("ok")
            else "专属 skill 已生成，但内置质量校验未通过。请先修正 quality_validation.errors，再安装或使用。"
        ),
    }


def tool_validate_scaffolded_skill(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    path = args.get("skill_dir")
    if not isinstance(path, str) or not path.strip():
        raise ToolError("skill_dir 必须是非空字符串。")
    result = validate_scaffolded_skill_dir(path)
    result["mcp_next_step"] = (
        "ok=false 时不要交付给用户；先修正缺失文件、核心规则、默认参数和 evals。"
        "ok=true 后仍需要用户检查，因为校验器只能检查结构和关键规则，不能替代用户确认。"
    )
    return result


def tool_get_factory_guidance(args: dict[str, Any]) -> dict[str, Any]:
    require_activation()
    topic = args.get("topic", "workflow")
    guidance = {
        "workflow": [
            "先清点并完整阅读用户材料，包括文档末尾和提交说明。",
            "复述实验目标、任务、填写区域、不可触碰区域、工具环境、截图来源、提交清单和命名规则。",
            "一轮一轮用通俗问题确认缺失需求，用户可选择默认，但默认值必须展开。",
            "生成 skill-spec.md 并校验，通过后再生成科目级或模板系列级专属 skill。",
            "专属 skill 后续先生成 fill.md + fill-map.json，用户确认后再复制原文件并填补副本。",
        ],
        "licensing": [
            "MVP 使用本地 hash allowlist 激活，适合测试，不适合强保护商业分发。",
            "正式售卖建议使用远程授权服务，或使用公钥签名离线许可证，私钥不能随客户端分发。",
            "本地二进制只能提高修改门槛，不能保证绝对不可逆向。",
        ],
        "custom_skill_visibility": [
            "建议让定制出来的专属 skill 可见、可编辑，因为它是用户自己的课程规则和迭代记录。",
            "核心工厂逻辑、授权逻辑、完整报告正文、隐私信息、截图和原始数据不要写入专属 skill。",
            "可以采用“核心 MCP 受保护 + 用户专属 skill 可编辑”的混合模式。",
        ],
        "client_compatibility": [
            "MCP server 使用标准 stdio JSON-RPC，不依赖 Codex-only API。",
            "Claude Code、Codex 和其他支持 stdio MCP 的客户端可以使用同一个 CLI 入口：lab-factory serve-mcp。",
            "差异只在客户端配置格式：Claude Code 通常使用 mcpServers JSON，Codex 通常使用 mcp_servers TOML。",
            "生成出来的专属 skill 应保持普通 SKILL.md + references/assets/evals 结构，不写 Codex 专用指令。",
        ],
        "quality_without_skill_creator": [
            "没有 skill-creator 不应直接导致质量很差，但必须有质量门禁。",
            "质量主要来自：完整材料理解、逐项确认后的 skill-spec.md、内置模板、结构校验、evals 和用户确认闭环。",
            "skill-creator 在这里是开发期质量参考，不是用户侧硬依赖。",
            "如果 skill-spec.md 很粗糙，任何生成器都会变差；所以 spec 校验和用户确认是更关键的质量来源。",
        ],
    }
    if topic not in guidance:
        raise ToolError(
            "topic 只能是 workflow、licensing、custom_skill_visibility、client_compatibility "
            "或 quality_without_skill_creator。"
        )
    return {"ok": True, "topic": topic, "guidance": guidance[topic]}


TOOLS: dict[str, dict[str, Any]] = {
    "lab_factory_status": {
        "description": "查看 Lab Skill Factory MCP 的激活状态、skill 根目录和商业化保护提示。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": tool_status,
    },
    "lab_factory_activate": {
        "description": "导入销售者针对本机请求签发的 .lflicense 永久离线许可证。",
        "inputSchema": {
            "type": "object",
            "required": ["license_path", "terms_version", "adult_confirmed"],
            "properties": {
                "license_path": {"type": "string", "description": "销售者发回的 .lflicense 文件路径。"},
                "terms_version": {"type": "string", "const": "1.0"},
                "adult_confirmed": {"type": "boolean", "const": True},
            },
            "additionalProperties": False,
        },
        "handler": tool_activate,
    },
    "lab_factory_activate_key": {
        "description": "把中控生成的在线密钥绑定到当前安装，并取得最长 24 小时的签名租约。",
        "inputSchema": {
            "type": "object",
            "required": ["activation_key", "terms_version", "adult_confirmed"],
            "properties": {
                "activation_key": {"type": "string", "minLength": 16},
                "control_url": {"type": "string"},
                "terms_version": {"type": "string", "const": "1.0"},
                "adult_confirmed": {"type": "boolean", "const": True},
            },
            "additionalProperties": False,
        },
        "handler": tool_activate_key,
    },
    "lab_factory_create_license_request": {
        "description": "为当前安装生成 .lfreq 请求文件；用户将它发给销售者以取得离线许可证。",
        "inputSchema": {"type": "object", "required": ["output_path"], "properties": {"output_path": {"type": "string"}}, "additionalProperties": False},
        "handler": tool_create_license_request,
    },
    "lab_factory_deactivate": {
        "description": "从本机移除授权凭据。在线密钥仍保持安装绑定，换机需由销售者在中控重置。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": tool_deactivate,
    },
    "lab_factory_request_refund": {
        "description": "在密钥配置的 3 天或 7 天无理由退款期限内提交退款申请；提交后停止签发新租约。",
        "inputSchema": {
            "type": "object",
            "required": ["confirm_refund_request"],
            "properties": {"confirm_refund_request": {"type": "boolean", "const": True}},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True},
        "handler": tool_request_refund,
    },
    "lab_factory_telemetry_settings": {
        "description": "开启、关闭、清除或查看仅保存在本机的结构化使用记录；不会自动上传。",
        "inputSchema": {"type": "object", "required": ["action"], "properties": {"action": {"type": "string", "enum": ["enable", "disable", "status", "clear"]}}, "additionalProperties": False},
        "handler": tool_telemetry_settings,
    },
    "lab_factory_submit_draft_feedback": {
        "description": "草稿审阅后在本机记录一次不含正文的结构化质量反馈。",
        "inputSchema": {"type": "object", "required": ["review_id", "rating", "issue_categories", "edit_time_bucket"], "properties": {"review_id": {"type": "string"}, "rating": {"type": "integer", "minimum": 1, "maximum": 5}, "issue_categories": {"type": "array", "items": {"type": "string"}, "maxItems": 10}, "edit_time_bucket": {"type": "string", "enum": ["under_15m", "15_30m", "30_60m", "over_60m"]}}, "additionalProperties": False},
        "handler": tool_submit_draft_feedback,
    },
    "lab_factory_export_feedback": {
        "description": "导出本地白名单遥测和结构化反馈；用户自行检查并发送到反馈邮箱。",
        "inputSchema": {"type": "object", "required": ["output_path"], "properties": {"output_path": {"type": "string"}}, "additionalProperties": False},
        "handler": tool_export_feedback,
    },
    "lab_factory_verify_update": {
        "description": "校验人工收到的更新安装包 SHA-256；不会下载或安装。",
        "inputSchema": {"type": "object", "required": ["path", "sha256"], "properties": {"path": {"type": "string"}, "sha256": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"}}, "additionalProperties": False},
        "handler": tool_verify_update,
    },
    "lab_factory_check_runtime": {
        "description": "检查随 MCP 打包的 Python 运行时依赖是否可用，尤其是 DOCX 处理相关库。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": tool_check_runtime,
    },
    "lab_factory_export_client_config": {
        "description": "导出 Claude Code、Codex 或通用 stdio MCP 客户端配置片段。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "client": {
                    "type": "string",
                    "enum": ["claude_code", "codex", "generic_stdio"],
                    "default": "generic_stdio",
                }
            },
            "additionalProperties": False,
        },
        "handler": tool_export_client_config,
    },
    "lab_factory_inspect_materials": {
        "description": "清点实验报告材料路径，推测任务书、模板、参考案例、源码、截图等角色。",
        "inputSchema": {
            "type": "object",
            "required": ["paths"],
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "max_files": {"type": "integer", "minimum": 1, "default": 300},
            },
            "additionalProperties": False,
        },
        "handler": tool_inspect_materials,
    },
    "lab_factory_extract_docx_outline": {
        "description": "抽取 DOCX 全文段落、表格摘要、可能锚点和提交要求段落，帮助 agent 完整理解模板。",
        "inputSchema": {
            "type": "object",
            "required": ["docx_path"],
            "properties": {"docx_path": {"type": "string"}},
            "additionalProperties": False,
        },
        "handler": tool_extract_docx_outline,
    },
    "lab_factory_validate_skill_spec": {
        "description": "校验 skill-spec.md 是否包含生成专属实验报告 skill 所需章节。",
        "inputSchema": {
            "type": "object",
            "required": ["skill_spec_path"],
            "properties": {"skill_spec_path": {"type": "string"}},
            "additionalProperties": False,
        },
        "handler": tool_validate_skill_spec,
    },
    "lab_factory_scaffold_subject_skill": {
        "description": "根据已确认并通过校验的 skill-spec.md 生成科目级/模板级专属实验报告 skill 骨架。",
        "inputSchema": {
            "type": "object",
            "required": ["skill_spec_path", "output_dir"],
            "properties": {
                "skill_spec_path": {"type": "string"},
                "output_dir": {"type": "string"},
                "slug": {"type": "string"},
                "scope_level": {"type": "string", "enum": ["subject", "template", "experiment"]},
                "skip_validation": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        "handler": tool_scaffold_subject_skill,
    },
    "lab_factory_validate_fill_map": {
        "description": "校验专属 skill 生成的 fill-map.json，确保第一次草稿只填补并保留原文格式。",
        "inputSchema": {
            "type": "object",
            "required": ["fill_map_path"],
            "properties": {"fill_map_path": {"type": "string"}},
            "additionalProperties": False,
        },
        "handler": tool_validate_fill_map,
    },
    "lab_factory_apply_fill_map": {
        "description": "按 fill-map.json 复制 DOCX/MD 原文件并把 fill.md 内容填入副本，源文件保持只读不变。",
        "inputSchema": {
            "type": "object",
            "required": ["fill_map_path"],
            "properties": {
                "fill_map_path": {"type": "string"},
                "output_path": {"type": "string"},
                "overwrite": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        "handler": tool_apply_fill_map,
    },
    "lab_factory_validate_scaffolded_skill": {
        "description": "校验已生成的专属实验报告 skill 包，确保无 skill-creator 时也满足内置质量门禁。",
        "inputSchema": {
            "type": "object",
            "required": ["skill_dir"],
            "properties": {"skill_dir": {"type": "string"}},
            "additionalProperties": False,
        },
        "handler": tool_validate_scaffolded_skill,
    },
    "lab_factory_get_factory_guidance": {
        "description": "获取工厂流程、授权保护或专属 skill 可见性的简要指导。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": [
                        "workflow",
                        "licensing",
                        "custom_skill_visibility",
                        "client_compatibility",
                        "quality_without_skill_creator",
                    ],
                    "default": "workflow",
                }
            },
            "additionalProperties": False,
        },
        "handler": tool_get_factory_guidance,
    },
    "lab_factory_v2_inventory_docx": {
        "description": "解析 DOCX OOXML 结构，为正文、表格单元格、页眉页脚生成稳定节点 ID，并标记不可安全自动写入的复杂对象。",
        "inputSchema": {
            "type": "object", "required": ["docx_path"],
            "properties": {"docx_path": {"type": "string"}, "output_path": {"type": "string"}},
            "additionalProperties": False,
        },
        "handler": tool_v2_inventory,
    },
    "lab_factory_v2_create_template_profile": {
        "description": "根据用户确认的 inventory 节点编译可复用的 v2 模板配置。",
        "inputSchema": {
            "type": "object", "required": ["inventory_path", "subject", "fields", "output_path"],
            "properties": {
                "inventory_path": {"type": "string"}, "subject": {"type": "string"},
                "output_path": {"type": "string"},
                "fields": {"type": "array", "minItems": 1, "items": {"type": "object"}},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_create_template_profile,
    },
    "lab_factory_v2_validate_template_profile": {
        "description": "校验用户可见、可编辑的 template-profile.json；未通过校验的配置不能生效。",
        "inputSchema": {"type": "object", "required": ["profile_path"], "properties": {"profile_path": {"type": "string"}}, "additionalProperties": False},
        "handler": tool_v2_validate_template_profile,
    },
    "lab_factory_v2_propose_placements": {
        "description": "用模板配置为新 DOCX 评分并提出 auto/confirm/blocked 定位候选；不使用第一个字符串匹配作为回退。",
        "inputSchema": {
            "type": "object", "required": ["profile_path", "docx_path"],
            "properties": {"profile_path": {"type": "string"}, "docx_path": {"type": "string"}, "output_path": {"type": "string"}},
            "additionalProperties": False,
        },
        "handler": tool_v2_propose_placements,
    },
    "lab_factory_v2_propose_section_plan": {
        "description": "宿主 AI 完整阅读材料并理解用户要求后，把模板标题树与所需结构编译为可审阅的二/三级标题扩展方案；本工具只提出方案，不修改 DOCX。",
        "inputSchema": {
            "type": "object", "required": ["inventory_path", "proposal", "output_path"],
            "properties": {
                "inventory_path": {"type": "string"},
                "output_path": {"type": "string"},
                "proposal": {
                    "type": "object",
                    "required": ["requirements_summary", "user_request_summary", "material_sources", "sections"],
                    "properties": {
                        "requirements_summary": {"type": "string", "minLength": 1},
                        "user_request_summary": {"type": "string", "minLength": 1},
                        "material_sources": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                        "sections": {"type": "array", "minItems": 1, "items": {"type": "object"}},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_propose_section_plan,
    },
    "lab_factory_v2_apply_section_plan": {
        "description": "仅在用户确认标题差异方案后，把新增二/三级标题安全写入模板副本并记录审计；源文件不变，写入后必须重新 inventory。",
        "inputSchema": {
            "type": "object",
            "required": ["workspace", "section_plan_path", "docx_path", "output_path", "user_confirmation_summary"],
            "properties": {
                "workspace": {"type": "string"},
                "section_plan_path": {"type": "string"},
                "docx_path": {"type": "string"},
                "output_path": {"type": "string"},
                "user_confirmation_summary": {"type": "string", "minLength": 1},
                "overwrite": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_apply_section_plan,
    },
    "lab_factory_v2_prepare_autopilot": {
        "description": "创建结果优先的 v2.1 报告自动驾驶会话，汇总 8 维偏好、格式来源和首个 preflight 确认点；不生成正文。",
        "inputSchema": {
            "type": "object",
            "required": ["workspace", "idempotency_key", "subject", "mode", "requirements_path", "template_profile_path"],
            "properties": {
                "workspace": {"type": "string"}, "idempotency_key": {"type": "string", "format": "uuid"},
                "subject": {"type": "string"},
                "mode": {"type": "string", "enum": ["balanced", "strict", "fast"], "default": "balanced"},
                "requirements_path": {"type": "string"}, "template_profile_path": {"type": "string"},
                "writing_profile_path": {"type": "string"}, "style_card_path": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_prepare_autopilot,
    },
    "lab_factory_v2_answer_questions": {
        "description": "一次回答当前 interaction plan 的阻断问题；稳定偏好会进入草稿画像，完成后生成 preflight 摘要。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "state_version", "idempotency_key", "plan_id", "answers"],
            "properties": {
                "workspace": {"type": "string"}, "state_version": {"type": "integer", "minimum": 1},
                "idempotency_key": {"type": "string", "format": "uuid"}, "plan_id": {"type": "string"},
                "answers": {"type": "array", "minItems": 1, "items": {
                    "type": "object", "required": ["question_id", "value"],
                    "properties": {"question_id": {"type": "string"}, "value": {}}, "additionalProperties": False,
                }},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_answer_questions,
    },
    "lab_factory_v2_confirm_checkpoint": {
        "description": "确认已展示的 preflight 或最终 DOCX 摘要，并签发绑定摘要哈希和状态版本的一次性 token。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "state_version", "idempotency_key", "checkpoint_id", "summary_sha256"],
            "properties": {
                "workspace": {"type": "string"}, "state_version": {"type": "integer", "minimum": 1},
                "idempotency_key": {"type": "string", "format": "uuid"},
                "checkpoint_id": {"type": "string", "enum": ["preflight", "final_review"]},
                "summary_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_confirm_checkpoint,
    },
    "lab_factory_v2_advance_autopilot": {
        "description": "按风险策略批量推进连续低风险步骤，直到需要宿主产物、例外提问、最终验收或完成。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "state_version", "idempotency_key", "artifacts"],
            "properties": {
                "workspace": {"type": "string"}, "state_version": {"type": "integer", "minimum": 1},
                "idempotency_key": {"type": "string", "format": "uuid"},
                "confirmation_token": {"type": "string"}, "artifacts": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_advance_autopilot,
    },
    "lab_factory_v2_autopilot_status": {
        "description": "只读恢复 v2.1 自动驾驶状态和当前 interaction plan，不改变 state_version。",
        "inputSchema": {
            "type": "object", "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}}, "additionalProperties": False,
        },
        "handler": tool_v2_autopilot_status,
    },
    "lab_factory_v2_create_session": {
        "description": "创建可跨客户端重启恢复的 v2 报告会话，保存 variation seed、状态和审计日志。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "subject"],
            "properties": {"workspace": {"type": "string"}, "subject": {"type": "string"}, "report_id": {"type": "string"}},
            "additionalProperties": False,
        },
        "handler": tool_v2_create_session,
    },
    "lab_factory_v2_session_status": {
        "description": "恢复并查看 v2 报告会话状态。",
        "inputSchema": {"type": "object", "required": ["workspace"], "properties": {"workspace": {"type": "string"}}, "additionalProperties": False},
        "handler": tool_v2_session_status,
    },
    "lab_factory_v2_confirm_requirements": {
        "description": "校验结构化需求摘要并记录用户确认；存在冲突或缺失章节时不能进入定位阶段。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "requirements_path", "user_confirmation_summary"],
            "properties": {"workspace": {"type": "string"}, "requirements_path": {"type": "string"}, "user_confirmation_summary": {"type": "string"}},
            "additionalProperties": False,
        },
        "handler": tool_v2_confirm_requirements,
    },
    "lab_factory_v2_resolve_placements": {
        "description": "记录用户对低置信度候选的选择；存在 blocked 项或未确认 confirm 项时拒绝继续。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "profile_path", "docx_path", "placement_plan_path", "updated_profile_path", "selections", "user_confirmation_summary"],
            "properties": {
                "workspace": {"type": "string"}, "placement_plan_path": {"type": "string"},
                "profile_path": {"type": "string"}, "docx_path": {"type": "string"},
                "updated_profile_path": {"type": "string"},
                "selections": {"type": "array", "items": {"type": "object", "required": ["field_id", "node_id"], "properties": {"field_id": {"type": "string"}, "node_id": {"type": "string"}}, "additionalProperties": False}},
                "user_confirmation_summary": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_resolve_placements,
    },
    "lab_factory_v2_mark_content_ready": {
        "description": "在需求和定位均确认后记录结构化内容包已就绪。",
        "inputSchema": {"type": "object", "required": ["workspace", "content_summary"], "properties": {"workspace": {"type": "string"}, "content_summary": {"type": "string"}}, "additionalProperties": False},
        "handler": tool_v2_mark_content_ready,
    },
    "lab_factory_v2_apply_draft": {
        "description": "仅在 content_ready 状态执行安全 OOXML 写回，保留非目标 DOCX 部件并自动进入草稿审阅状态。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "profile_path", "docx_path", "content_package_path", "output_path"],
            "properties": {
                "workspace": {"type": "string"}, "profile_path": {"type": "string"},
                "docx_path": {"type": "string"}, "content_package_path": {"type": "string"},
                "output_path": {"type": "string"}, "overwrite": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_apply_draft,
    },
    "lab_factory_v2_review_draft": {
        "description": "记录用户在 WPS 中对草稿的 approve/revise 决定、review_id 和反馈摘要。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "review_id", "decision", "user_feedback_summary"],
            "properties": {
                "workspace": {"type": "string"}, "review_id": {"type": "string"},
                "decision": {"type": "string", "enum": ["approve", "revise"]},
                "user_feedback_summary": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_review_draft,
    },
    "lab_factory_v2_finalize": {
        "description": "在草稿批准后执行参考样本防照抄门禁；通过后记录 finalize，并返回三个后续出口。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "review_id", "generated_path", "user_confirmation_summary"],
            "properties": {
                "workspace": {"type": "string"}, "review_id": {"type": "string"},
                "generated_path": {"type": "string"}, "reference_paths": {"type": "array", "items": {"type": "string"}},
                "whitelist": {"type": "array", "items": {"type": "string"}},
                "user_confirmation_summary": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_finalize,
    },
    "lab_factory_v2_decide_iteration": {
        "description": "最终稿后记录继续修改、确认更新 Skill 或完成但不更新三个出口之一。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "review_id", "decision", "user_feedback_summary"],
            "properties": {
                "workspace": {"type": "string"}, "review_id": {"type": "string"},
                "decision": {"type": "string", "enum": ["continue_revision", "finish_without_update"]},
                "user_feedback_summary": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_decide_iteration,
    },
    "lab_factory_v2_create_writing_profile": {
        "description": "为一门课程创建可复用写作画像，支持预设和写作水平、详略、反思、语气四维覆盖。",
        "inputSchema": {
            "type": "object", "required": ["subject", "output_path"],
            "properties": {
                "subject": {"type": "string"}, "output_path": {"type": "string"},
                "preset": {"type": "string", "enum": ["balanced", "concise", "technical", "personal"], "default": "balanced"},
                "overrides": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_create_writing_profile,
    },
    "lab_factory_v2_validate_style_card": {
        "description": "校验参考报告风格卡并禁止把完整样本正文存入专属 Skill。",
        "inputSchema": {"type": "object", "required": ["style_card_path"], "properties": {"style_card_path": {"type": "string"}}, "additionalProperties": False},
        "handler": tool_v2_validate_style_card,
    },
    "lab_factory_v2_migrate_v1": {
        "description": "把 v1 fill-map 转成必须重新 inventory、重新定位和用户确认的 v2 迁移草案。",
        "inputSchema": {
            "type": "object", "required": ["fill_map_path", "output_path"],
            "properties": {"fill_map_path": {"type": "string"}, "output_path": {"type": "string"}},
            "additionalProperties": False,
        },
        "handler": tool_v2_migrate_v1,
    },
    "lab_factory_v2_propose_skill_update": {
        "description": "在 finalized 状态生成受限 Skill 更新 diff；只允许稳定课程/模板规则，并拒绝个人信息、样本正文和报告正文。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "skill_dir", "updates", "output_path"],
            "properties": {
                "workspace": {"type": "string"}, "skill_dir": {"type": "string"}, "output_path": {"type": "string"},
                "updates": {"type": "array", "minItems": 1, "items": {"type": "object"}},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_propose_skill_update,
    },
    "lab_factory_v2_apply_skill_update": {
        "description": "用户审阅 diff 后，用 update_id、review_id 和确认摘要原子应用 Skill 更新并结束迭代状态。",
        "inputSchema": {
            "type": "object", "required": ["workspace", "proposal_path", "update_id", "review_id", "user_confirmation_summary"],
            "properties": {
                "workspace": {"type": "string"}, "proposal_path": {"type": "string"},
                "update_id": {"type": "string"}, "review_id": {"type": "string"},
                "user_confirmation_summary": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": tool_v2_apply_skill_update,
    },
}


def public_tool_specs() -> list[dict[str, Any]]:
    specs = []
    for name, spec in TOOLS.items():
        public = {
            "name": name,
            "description": spec["description"],
            "inputSchema": spec["inputSchema"],
        }
        if isinstance(spec.get("annotations"), dict):
            public["annotations"] = spec["annotations"]
        specs.append(public)
    return specs


def json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    spec = TOOLS.get(name)
    if not spec:
        raise ToolError(f"未知工具：{name}")
    handler = spec["handler"]
    started = time.monotonic()
    try:
        data = handler(args)
        event = {
            "event": "tool_call", "version": SERVER_VERSION, "platform": sys.platform,
            "architecture": commercial_client.client_platform()[1], "tool": name,
            "ok": data.get("ok", True) is not False, "error_code": "",
            "duration_ms": int((time.monotonic() - started) * 1000),
            "channel_id": commercial_client.read_json(commercial_client.LICENSE_METADATA_FILE).get("channel_id"),
        }
        if isinstance(data.get("remaining_template_cues"), list):
            event["placeholder_count"] = len(data["remaining_template_cues"])
        if isinstance(data.get("gate"), str):
            event["quality_gate"] = data["gate"]
        if name not in {"lab_factory_status", "lab_factory_telemetry_settings", "lab_factory_activate"}:
            commercial_client.record_telemetry(event)
        return {
            "content": [{"type": "text", "text": json_text(data)}],
            "structuredContent": data,
        }
    except ToolError as exc:
        data = {"ok": False, "error": str(exc), "error_code": exc.code}
        if exc.details:
            data["details"] = exc.details
        event = {
            "event": "tool_call", "version": SERVER_VERSION, "platform": sys.platform,
            "architecture": commercial_client.client_platform()[1], "tool": name,
            "ok": False, "error_code": exc.code.lower(),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "channel_id": commercial_client.read_json(commercial_client.LICENSE_METADATA_FILE).get("channel_id"),
        }
        if name not in {"lab_factory_status", "lab_factory_telemetry_settings", "lab_factory_activate"}:
            commercial_client.record_telemetry(event)
        return {
            "content": [{"type": "text", "text": json_text(data)}],
            "structuredContent": data,
            "isError": True,
        }


def make_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    try:
        if method == "initialize":
            client_protocol = params.get("protocolVersion") if isinstance(params, dict) else None
            return make_response(
                request_id,
                {
                    "protocolVersion": client_protocol or PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": (
                        "If given an online activation key, use lab_factory_activate_key. Offline license files remain supported through lab_factory_activate. "
                        "New reports should start with lab_factory_v2_prepare_autopilot and obey its next_action. "
                        "Balanced mode normally asks only for stable preferences, preflight confirmation, exceptions that materially affect quality or safety, and final DOCX review. "
                        "Legacy v2.0 sessions continue with the strict lab_factory_v2_create_session workflow."
                    ),
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return make_response(request_id, {})
        if method == "tools/list":
            return make_response(request_id, {"tools": public_tool_specs()})
        if method == "tools/call":
            if not isinstance(params, dict):
                return make_error(request_id, -32602, "tools/call params must be an object")
            name = params.get("name")
            args = params.get("arguments") or {}
            if not isinstance(name, str):
                return make_error(request_id, -32602, "tools/call requires string name")
            if not isinstance(args, dict):
                return make_error(request_id, -32602, "tools/call arguments must be an object")
            return make_response(request_id, call_tool(name, args))
        if method == "resources/list":
            return make_response(request_id, {"resources": []})
        if method == "prompts/list":
            return make_response(request_id, {"prompts": []})
        if method == "logging/setLevel":
            return make_response(request_id, {})
        return make_error(request_id, -32601, f"Method not found: {method}")
    except Exception as exc:  # Protocol-level guard; tool errors are handled in call_tool.
        return make_error(request_id, -32000, str(exc))


def read_content_length_message(first_line: bytes) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    decoded_first = first_line.decode("ascii", errors="replace").strip()
    if ":" in decoded_first:
        key, value = decoded_first.split(":", 1)
        headers[key.lower()] = value.strip()
    while True:
        line = sys.stdin.buffer.readline()
        if line == b"":
            return None
        if line in {b"\r\n", b"\n"}:
            break
        decoded = line.decode("ascii", errors="replace").strip()
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.lower()] = value.strip()

    length_value = headers.get("content-length")
    if not length_value:
        raise RuntimeError("Missing Content-Length header")
    length = int(length_value)
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def read_line_message(first_line: bytes) -> dict[str, Any]:
    return json.loads(first_line.decode("utf-8").strip())


def read_message() -> dict[str, Any] | None:
    while True:
        line = sys.stdin.buffer.readline()
        if line == b"":
            return None
        if line in {b"\r\n", b"\n"}:
            continue
        if line.lower().startswith(b"content-length:"):
            return read_content_length_message(line)
        return read_line_message(line)


def send_message(message: dict[str, Any]) -> None:
    body = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def serve_stdio() -> int:
    while True:
        try:
            message = read_message()
        except Exception as exc:
            print(f"{SERVER_NAME}: failed to read message: {exc}", file=sys.stderr)
            return 1
        if message is None:
            return 0
        response = handle_request(message)
        if response is not None:
            send_message(response)


def self_test() -> int:
    result = tool_status({})
    print(json_text(result))
    missing = []
    root = skill_root()
    for script in [
        "inspect_lab_materials.py",
        "extract_docx_outline.py",
        "validate_skill_spec.py",
        "validate_fill_map.py",
        "apply_fill_map.py",
        "validate_scaffolded_skill.py",
        "scaffold_subject_skill.py",
        "v2_engine.py",
    ]:
        if not (root / "scripts" / script).exists():
            missing.append(script)
    if missing:
        print(f"Missing scripts: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Lab Skill Factory MCP server.")
    parser.add_argument("--self-test", action="store_true", help="Check local paths and print status without MCP framing.")
    parser.add_argument("--run-skill-script", help=argparse.SUPPRESS)
    parser.add_argument("script_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.run_skill_script:
        script = Path(args.run_skill_script).expanduser().resolve()
        sys.argv = [str(script), *args.script_args]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    if args.self_test:
        return self_test()
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
