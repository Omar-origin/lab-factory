#!/usr/bin/env python3
"""Regression tests for installer env merging and activation flows."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import tomllib
import unittest
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
MCP_DIR = SCRIPT_DIR.parent
AUTH_DIR = MCP_DIR / "auth"
sys.path.insert(0, str(MCP_DIR))
sys.path.insert(0, str(AUTH_DIR))

import install  # noqa: E402
import remote_auth_service  # noqa: E402
import server  # noqa: E402


@contextmanager
def patched_env(updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def install_args(**overrides):
    values = {
        "skill_root": None,
        "workspace_root": None,
        "auth_url": None,
        "license_db": str(MCP_DIR / "activation_codes.json"),
        "product_id": "lab-skill-factory-beta",
        "dev_allow": False,
        "codex_config": None,
        "claude_scope": "user",
        "dry_run": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class InstallerTests(unittest.TestCase):
    def test_codex_env_is_merged_instead_of_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text(
                """
[mcp_servers.lab-skill-factory]
command = "old"
args = ["serve-mcp"]

[mcp_servers.lab-skill-factory.env]
LAB_FACTORY_DEV_ALLOW = "1"
EXISTING_VALUE = "keep"

[mcp_servers.other]
command = "other"
""".lstrip(),
                encoding="utf-8",
            )
            args = install_args(codex_config=str(config))
            requested = {"LAB_FACTORY_PRODUCT_ID": "new-product"}
            effective = install.effective_codex_env(args, requested)
            self.assertEqual(effective["LAB_FACTORY_DEV_ALLOW"], "1")
            self.assertEqual(effective["EXISTING_VALUE"], "keep")
            self.assertEqual(effective["LAB_FACTORY_PRODUCT_ID"], "new-product")

            install.install_codex(args, "/tmp/lab-factory", ["serve-mcp"], effective)
            written = config.read_text(encoding="utf-8")
            self.assertIn('LAB_FACTORY_DEV_ALLOW = "1"', written)
            self.assertIn('EXISTING_VALUE = "keep"', written)
            self.assertIn("[mcp_servers.other]", written)

    def test_codex_snippet_escapes_windows_paths(self) -> None:
        snippet = install.codex_config_snippet(
            r"C:\Program Files\Lab Factory\lab-factory.exe",
            ["serve-mcp"],
            {
                "LAB_FACTORY_WORKSPACE_ROOT": r"C:\Users\Tester\Documents\实验报告",
                "LAB_FACTORY_DEV_ALLOW": "1",
            },
        )
        parsed = tomllib.loads(snippet)
        server_config = parsed["mcp_servers"]["lab-skill-factory"]
        self.assertEqual(server_config["command"], r"C:\Program Files\Lab Factory\lab-factory.exe")
        self.assertEqual(
            server_config["env"]["LAB_FACTORY_WORKSPACE_ROOT"],
            r"C:\Users\Tester\Documents\实验报告",
        )

    def test_claude_local_scope_merges_user_and_current_project_env(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as project_dir:
            home = Path(home_dir)
            project = Path(project_dir).resolve()
            config = {
                "mcpServers": {
                    "lab-skill-factory": {
                        "env": {"LAB_FACTORY_DEV_ALLOW": "1", "USER_VALUE": "global"}
                    }
                },
                "projects": {
                    str(project): {
                        "mcpServers": {
                            "lab-skill-factory": {
                                "env": {"PROJECT_VALUE": "local"}
                            }
                        }
                    }
                },
            }
            (home / ".claude.json").write_text(json.dumps(config), encoding="utf-8")
            existing = install.read_claude_env("local", cwd=project, home=home)
            effective = install.merge_env(existing, {"LAB_FACTORY_PRODUCT_ID": "new-product"})
            self.assertEqual(effective["LAB_FACTORY_DEV_ALLOW"], "1")
            self.assertEqual(effective["USER_VALUE"], "global")
            self.assertEqual(effective["PROJECT_VALUE"], "local")
            self.assertEqual(effective["LAB_FACTORY_PRODUCT_ID"], "new-product")

    def test_dev_allow_flag_is_written_to_requested_env(self) -> None:
        env = install.env_map(install_args(dev_allow=True))
        self.assertEqual(env["LAB_FACTORY_DEV_ALLOW"], "1")


class ActivationTests(unittest.TestCase):
    def test_missing_auth_backend_has_actionable_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patched_env(
                {
                    "LAB_FACTORY_DEV_ALLOW": None,
                    "LAB_FACTORY_AUTH_URL": None,
                    "LAB_FACTORY_LICENSE_DB": str(root / "missing-codes.json"),
                    "LAB_FACTORY_LICENSE_FILE": str(root / "missing-license.json"),
                }
            ):
                status = server.activation_status()
            self.assertFalse(status["activated"])
            self.assertEqual(status["mode"], "authorization_unconfigured")
            self.assertIn("--dev-allow", " ".join(status["next_steps"]))
            self.assertIn("--auth-url", " ".join(status["next_steps"]))

    def test_remote_activation_cli_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = remote_auth_service.AuthStore(root / "auth.sqlite3")
            code = "BETA-TEST-REMOTE-123456"
            store.create_code(code, "test", None, 1)
            remote_auth_service.Handler.store = store
            remote_auth_service.Handler.admin_token = "test-admin"
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), remote_auth_service.Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            auth_url = f"http://127.0.0.1:{httpd.server_port}"
            license_file = root / "license.json"
            env = os.environ.copy()
            env["LAB_FACTORY_DEVICE_ID"] = "test-device"
            try:
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(MCP_DIR / "cli.py"),
                        "activate",
                        code,
                        "--auth-url",
                        auth_url,
                        "--license-file",
                        str(license_file),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    check=False,
                    timeout=15,
                )
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=5)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(license_file.exists())
            license_data = json.loads(license_file.read_text(encoding="utf-8"))
            self.assertEqual(license_data["license_mode"], "remote_token")


if __name__ == "__main__":
    unittest.main(verbosity=2)
