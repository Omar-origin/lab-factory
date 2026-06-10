# Lab Factory Windows Beta

Lab Factory is installed per user by default:

```text
%LOCALAPPDATA%\Programs\Lab Factory
```

The installer does not automatically modify Claude Code, Codex, or your system PATH.

Use the Start Menu shortcuts:

- `Lab Factory CLI`
- `Install Codex MCP Config`
- `Install Claude Code MCP Config`
- `Lab Factory README`

Or run commands from PowerShell:

```powershell
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" status
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" check-runtime
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" mcp-smoke
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" install --target codex
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" install --target claude
```

For remote beta activation:

```powershell
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" activate <activation-code>
```

For MCP clients, the server command is:

```text
%LOCALAPPDATA%\Programs\Lab Factory\lab-factory.exe
```

with args:

```text
serve-mcp
```

Generated user subject skills are intentionally visible and editable.
