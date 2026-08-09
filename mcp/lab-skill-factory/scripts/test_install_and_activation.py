#!/usr/bin/env python3
"""Regression tests for installer env merging and the offline CLI activation flow."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MCP_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(MCP_DIR))
import install


def install_args(**overrides):
    values = {"skill_root": None, "workspace_root": None, "product_id": "lab-factory-1",
              "purchase_url": "微信联系销售者", "support_email": "support@example.test",
              "feedback_email": "feedback@example.test", "codex_config": None,
              "claude_scope": "user", "dry_run": False}
    values.update(overrides)
    return argparse.Namespace(**values)


class InstallerTests(unittest.TestCase):
    def test_codex_env_is_merged_without_bypass(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.toml"
            config.write_text('[mcp_servers.lab-skill-factory]\ncommand="old"\n[mcp_servers.lab-skill-factory.env]\nLAB_FACTORY_DEV_ALLOW="1"\nEXISTING_VALUE="keep"\n', encoding="utf-8")
            args = install_args(codex_config=str(config))
            effective = install.effective_codex_env(args, {"LAB_FACTORY_PRODUCT_ID": "new-product"})
            self.assertNotIn("LAB_FACTORY_DEV_ALLOW", effective)
            self.assertEqual(effective["EXISTING_VALUE"], "keep")

    def test_windows_paths_are_escaped(self):
        snippet = install.codex_config_snippet(r"C:\Program Files\Lab Factory\lab-factory.exe", ["serve-mcp"], {"LAB_FACTORY_WORKSPACE_ROOT": r"C:\Users\Tester\实验"})
        self.assertEqual(tomllib.loads(snippet)["mcp_servers"]["lab-skill-factory"]["command"], r"C:\Program Files\Lab Factory\lab-factory.exe")

    def test_offline_configuration_has_no_server_or_private_key(self):
        env = install.env_map(install_args())
        self.assertEqual(env["LAB_FACTORY_FEEDBACK_EMAIL"], "feedback@example.test")
        self.assertNotIn("LAB_FACTORY_AUTH_URL", env)
        self.assertNotIn("LAB_FACTORY_LEASE_PRIVATE_KEY", env)
        self.assertNotIn("LAB_FACTORY_DEV_ALLOW", env)


class ActivationTests(unittest.TestCase):
    def test_cli_request_issue_activate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private, public = root / "private.json", root / "public.json"
            request, license_file = root / "device.lfreq", root / "device.lflicense"
            env = os.environ.copy()
            env.update({"LAB_FACTORY_APP_DIR": str(root / "app"), "LAB_FACTORY_CREDENTIAL_BACKEND": "file",
                        "LAB_FACTORY_LICENSE_PUBLIC_KEY_FILE": str(public), "LAB_FACTORY_INSTALL_ID": "test-device"})
            commands = [
                [sys.executable, str(MCP_DIR / "auth" / "commercial_admin.py"), "init-issuer", "--private-key", str(private), "--public-key", str(public)],
                [sys.executable, str(MCP_DIR / "cli.py"), "license-request", "--output", str(request)],
                [sys.executable, str(MCP_DIR / "auth" / "commercial_admin.py"), "issue-license", "--private-key", str(private), "--request", str(request), "--output", str(license_file), "--channel-id", "test"],
                [sys.executable, str(MCP_DIR / "cli.py"), "activate", str(license_file), "--accept-terms-version", "1.0", "--confirm-age-18"],
            ]
            for command in commands:
                proc = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15, check=False)
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertEqual(json.loads(proc.stdout)["mode"], "offline_permanent_license")
            self.assertTrue((root / "app" / "license.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
