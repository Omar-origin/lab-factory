# Lab Factory Windows Beta

Lab Factory is installed per user by default:

```text
%LOCALAPPDATA%\Programs\Lab Factory
```

The installer does not automatically modify Claude Code, Codex, or your system PATH.

If you want Claude Code or Codex to deploy this package for you, give it this folder or zip path and tell it to read `INSTALL_FOR_AGENT.md` first.

Use the Start Menu shortcuts:

- `Lab Factory CLI`
- `Install Codex MCP Config (Free Beta)`
- `Install Claude Code MCP Config (Free Beta)`
- `Lab Factory README`
- `Lab Factory Agent Quick Install`
- `Lab Factory User Guide`

Or run commands from PowerShell:

```powershell
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" status
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" check-runtime
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" mcp-smoke
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" install --target codex --dev-allow
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" install --target claude --dev-allow
```

For remote beta activation:

```powershell
& "$env:LOCALAPPDATA\Programs\Lab Factory\lab-factory.exe" activate <activation-code> --auth-url "https://your-auth-service.example"
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
