#!/usr/bin/env python3
"""Stdio MCP wrapper for the Lab Skill Factory skill.

This server intentionally keeps the MCP layer thin: it exposes activation,
material inspection, DOCX outline extraction, spec validation, fill-map
validation, and subject-skill scaffolding. The actual lab-skill-factory rules
remain in the skill package and its helper scripts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import runpy
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SERVER_NAME = "lab-factory-mcp"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).resolve()
SERVER_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
REPO_ROOT = SERVER_DIR.parents[1] if not FROZEN else SERVER_DIR
DEFAULT_SKILL_ROOT = (BUNDLE_ROOT / "skills" / "lab-skill-factory") if FROZEN else (REPO_ROOT / "skills" / "lab-skill-factory")
DEFAULT_LICENSE_DB = SERVER_DIR / "activation_codes.json"
DEFAULT_LICENSE_FILE = Path.home() / ".lab-factory" / "license.json"
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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def skill_root() -> Path:
    return Path(os.environ.get("LAB_FACTORY_SKILL_ROOT", DEFAULT_SKILL_ROOT)).expanduser().resolve()


def license_db_path() -> Path:
    return Path(os.environ.get("LAB_FACTORY_LICENSE_DB", DEFAULT_LICENSE_DB)).expanduser().resolve()


def license_file_path() -> Path:
    return Path(os.environ.get("LAB_FACTORY_LICENSE_FILE", DEFAULT_LICENSE_FILE)).expanduser().resolve()


def auth_url() -> str | None:
    value = os.environ.get("LAB_FACTORY_AUTH_URL", "").strip().rstrip("/")
    return value or None


def product_id() -> str:
    return os.environ.get("LAB_FACTORY_PRODUCT_ID", "lab-skill-factory-beta")


def device_id() -> str:
    configured = os.environ.get("LAB_FACTORY_DEVICE_ID", "").strip()
    if configured:
        return configured
    raw = f"{uuid.getnode()}:{os.environ.get('USER') or os.environ.get('USERNAME') or ''}:{os.uname().nodename if hasattr(os, 'uname') else ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def python_executable() -> str:
    return os.environ.get("LAB_FACTORY_PYTHON", sys.executable)


def workspace_root() -> Path:
    return Path(os.environ.get("LAB_FACTORY_WORKSPACE_ROOT", Path.cwd())).expanduser().resolve()


def resolve_user_path(path_string: str) -> str:
    path = Path(path_string).expanduser()
    if not path.is_absolute():
        path = workspace_root() / path
    return str(path.resolve())


def activation_hash(code: str) -> str:
    normalized = code.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_activation_db() -> dict[str, Any]:
    path = license_db_path()
    if not path.exists():
        return {"version": 1, "codes": [], "path": str(path), "exists": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(f"激活码库不是合法 JSON：{path}，错误：{exc}") from exc
    if not isinstance(data, dict):
        raise ToolError(f"激活码库顶层必须是对象：{path}")
    data["path"] = str(path)
    data["exists"] = True
    return data


def iter_code_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_codes = data.get("codes", [])
    if not isinstance(raw_codes, list):
        raise ToolError("激活码库中的 codes 必须是数组。")
    entries: list[dict[str, Any]] = []
    for raw in raw_codes:
        if isinstance(raw, str):
            entries.append({"sha256": raw})
        elif isinstance(raw, dict):
            entries.append(raw)
        else:
            raise ToolError("激活码库中的每个 code 必须是字符串 hash 或对象。")
    return entries


def parse_expiry(value: Any) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        raise ToolError("expires_at 必须是 ISO 日期字符串，例如 2026-12-31。")
    if len(value) == 10:
        value = f"{value}T23:59:59+00:00"
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(f"无法解析 expires_at：{value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def find_activation_entry(code_hash: str) -> dict[str, Any] | None:
    data = load_activation_db()
    now = datetime.now(timezone.utc)
    for entry in iter_code_entries(data):
        if entry.get("sha256") != code_hash:
            continue
        expires_at = parse_expiry(entry.get("expires_at"))
        if expires_at is not None and expires_at < now:
            raise ToolError("这个激活码已经过期，请换一个新的激活码。")
        return entry
    return None


def read_license_file() -> dict[str, Any] | None:
    path = license_file_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def post_json(url: str, payload: dict[str, Any], timeout: int = 8) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8")
            parsed = json.loads(data) if data else {}
            if not isinstance(parsed, dict):
                raise ToolError("远程授权服务返回值不是 JSON 对象。")
            return parsed
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ToolError(f"远程授权服务 HTTP {exc.code}: {detail[:800]}") from exc
    except urllib.error.URLError as exc:
        raise ToolError(f"无法连接远程授权服务：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise ToolError(f"远程授权服务返回的 JSON 无法解析：{exc}") from exc


def remote_activation_status(license_data: dict[str, Any] | None) -> dict[str, Any]:
    url = auth_url()
    if not url:
        return {"activated": False, "mode": "remote_unconfigured"}
    if not license_data or not isinstance(license_data.get("token"), str):
        return {
            "activated": False,
            "mode": "remote_token",
            "auth_url": url,
            "license_file": str(license_file_path()),
            "message": "尚未远程激活。请先调用 lab_factory_activate 并输入激活码。",
        }
    result = post_json(
        f"{url}/verify",
        {
            "token": license_data["token"],
            "device_id": license_data.get("device_id") or device_id(),
            "product_id": license_data.get("product_id") or product_id(),
        },
    )
    if not result.get("ok"):
        return {
            "activated": False,
            "mode": "remote_token",
            "auth_url": url,
            "license_file": str(license_file_path()),
            "message": result.get("error") or "远程授权校验失败。",
        }
    return {
        "activated": True,
        "mode": "remote_token",
        "auth_url": url,
        "license_file": str(license_file_path()),
        "customer_id": license_data.get("customer_id"),
        "device_id": license_data.get("device_id"),
        "activated_at": license_data.get("activated_at"),
        "server_status": result,
    }


def activation_status() -> dict[str, Any]:
    if os.environ.get("LAB_FACTORY_DEV_ALLOW") == "1":
        return {
            "activated": True,
            "mode": "development_override",
            "message": "LAB_FACTORY_DEV_ALLOW=1 已开启，仅适合本地开发测试，正式分发必须移除。",
        }

    license_data = read_license_file()
    if auth_url():
        return remote_activation_status(license_data)

    db = load_activation_db()
    if not license_data:
        if not db.get("exists", False):
            return {
                "activated": False,
                "mode": "authorization_unconfigured",
                "license_file": str(license_file_path()),
                "activation_db": db.get("path"),
                "activation_db_exists": False,
                "message": (
                    "当前没有可用的授权方式：未设置 LAB_FACTORY_AUTH_URL，"
                    "并且本地 activation_codes.json 不存在。"
                ),
                "next_steps": [
                    "免费内测：重新运行 install 并加上 --dev-allow。",
                    "激活码模式：重新运行 install --auth-url <授权服务地址>，再执行 activate <激活码> --auth-url <授权服务地址>。",
                ],
            }
        return {
            "activated": False,
            "mode": "local_hash_allowlist",
            "license_file": str(license_file_path()),
            "activation_db": db.get("path"),
            "activation_db_exists": db.get("exists", False),
            "message": "尚未激活。请先调用 lab_factory_activate 并输入激活码。",
        }

    code_hash = license_data.get("code_hash")
    if not isinstance(code_hash, str):
        return {
            "activated": False,
            "mode": "local_hash_allowlist",
            "license_file": str(license_file_path()),
            "message": "本地 license 文件缺少 code_hash，请重新激活。",
        }

    entry = find_activation_entry(code_hash)
    if not entry:
        return {
            "activated": False,
            "mode": "local_hash_allowlist",
            "license_file": str(license_file_path()),
            "activation_db": db.get("path"),
            "message": "本地 license 存在，但激活码不在当前激活码库中，请重新激活。",
        }

    return {
        "activated": True,
        "mode": "local_hash_allowlist",
        "license_file": str(license_file_path()),
        "activation_db": db.get("path"),
        "label": entry.get("label"),
        "activated_at": license_data.get("activated_at"),
        "customer_id": license_data.get("customer_id"),
    }


def require_activation() -> None:
    status = activation_status()
    if status.get("activated"):
        return
    next_steps = status.get("next_steps")
    guidance = "；".join(str(item) for item in next_steps) if isinstance(next_steps, list) else (
        "先调用 lab_factory_activate；开发测试可使用 install --dev-allow。"
    )
    raise ToolError(f"{status.get('message', '工具尚未激活。')} 下一步：{guidance}")


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
        "distribution_note": (
            "当前 MVP 是本地 MCP 包装。源码级隐藏和防修改不能靠本地脚本绝对保证；"
            "正式售卖建议使用远程授权/远程核心服务，或至少编译成签名二进制。"
        ),
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
    if auth_url():
        env["LAB_FACTORY_AUTH_URL"] = str(auth_url())
    else:
        env["LAB_FACTORY_LICENSE_DB"] = str(license_db_path())
    env["LAB_FACTORY_PRODUCT_ID"] = product_id()
    if os.environ.get("LAB_FACTORY_DEV_ALLOW") == "1":
        env["LAB_FACTORY_DEV_ALLOW"] = "1"
    if os.environ.get("LAB_FACTORY_WORKSPACE_ROOT"):
        env["LAB_FACTORY_WORKSPACE_ROOT"] = str(workspace_root())
    if os.environ.get("LAB_FACTORY_LICENSE_FILE"):
        env["LAB_FACTORY_LICENSE_FILE"] = str(license_file_path())
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


def tool_activate(args: dict[str, Any]) -> dict[str, Any]:
    code = args.get("activation_code")
    if not isinstance(code, str) or not code.strip():
        raise ToolError("activation_code 必须是非空字符串。")

    if auth_url():
        result = post_json(
            f"{auth_url()}/activate",
            {
                "activation_code": code.strip(),
                "customer_id": args.get("customer_id"),
                "device_id": device_id(),
                "product_id": product_id(),
            },
        )
        if not result.get("ok") or not result.get("token"):
            raise ToolError(f"远程激活失败：{result.get('error') or result}")
        license_data = {
            "status": "ACTIVE",
            "license_mode": "remote_token",
            "token": result["token"],
            "customer_id": args.get("customer_id"),
            "device_id": device_id(),
            "product_id": product_id(),
            "auth_url": auth_url(),
            "activated_at": utc_now(),
            "server": SERVER_NAME,
        }
        path = license_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(license_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "ok": True,
            "message": "远程激活成功。",
            "license_file": str(path),
            "auth_url": auth_url(),
            "device_id": device_id(),
            "expires_at": result.get("expires_at"),
        }

    code_hash = activation_hash(code)
    db = load_activation_db()
    if not db.get("exists", False):
        raise ToolError(
            "激活失败：当前未设置远程授权地址，且本地 activation_codes.json 不存在。"
            "请使用 activate <激活码> --auth-url <授权服务地址>，"
            "或在免费内测模式下重新执行 install --dev-allow。"
        )
    entry = find_activation_entry(code_hash)
    if not entry:
        raise ToolError(
            "激活失败：激活码不在本地激活码库中。"
            f"当前激活码库：{db.get('path')}，exists={db.get('exists', False)}。"
        )

    license_data = {
        "status": "ACTIVE",
        "code_hash": code_hash,
        "label": entry.get("label"),
        "customer_id": args.get("customer_id"),
        "activated_at": utc_now(),
        "server": SERVER_NAME,
        "license_mode": "local_hash_allowlist_mvp",
    }
    path = license_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(license_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "message": "激活成功。",
        "license_file": str(path),
        "label": entry.get("label"),
        "expires_at": entry.get("expires_at"),
    }


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
            "填补区域、不可触碰区域、工具环境和 finalize 流程；确认后再安装或使用。"
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
        "description": "输入激活码，激活本地 Lab Skill Factory MCP。MVP 使用本地 hash allowlist。",
        "inputSchema": {
            "type": "object",
            "required": ["activation_code"],
            "properties": {
                "activation_code": {"type": "string", "description": "你发给用户的激活码。"},
                "customer_id": {"type": "string", "description": "可选，客户标识；不要填姓名、学号等敏感信息。"},
            },
            "additionalProperties": False,
        },
        "handler": tool_activate,
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
}


def public_tool_specs() -> list[dict[str, Any]]:
    specs = []
    for name, spec in TOOLS.items():
        specs.append(
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
            }
        )
    return specs


def json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    spec = TOOLS.get(name)
    if not spec:
        raise ToolError(f"未知工具：{name}")
    handler = spec["handler"]
    try:
        data = handler(args)
        return {
            "content": [{"type": "text", "text": json_text(data)}],
            "structuredContent": data,
        }
    except ToolError as exc:
        data = {"ok": False, "error": str(exc)}
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
                    "instructions": "Use lab_factory_activate before calling protected factory tools.",
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
