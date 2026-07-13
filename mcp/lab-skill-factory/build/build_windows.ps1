param(
  [string]$RootDir = "",
  [string]$DistDir = "",
  [string]$AppName = "lab-factory"
)

$ErrorActionPreference = "Stop"

if ($RootDir -eq "") {
  $RootDir = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
}
if ($DistDir -eq "") {
  $DistDir = Join-Path $RootDir "mcp\lab-skill-factory\dist\windows"
}

$McpDir = Join-Path $RootDir "mcp\lab-skill-factory"
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

python -m pip install pyinstaller -r (Join-Path $McpDir "runtime-requirements.txt")

pyinstaller `
  --clean `
  --onefile `
  --name $AppName `
  --distpath $DistDir `
  --workpath (Join-Path $McpDir "build\pyinstaller-work") `
  --specpath (Join-Path $McpDir "build") `
  --hidden-import docx `
  --hidden-import lxml `
  --collect-data docx `
  --add-data "$RootDir\skills\lab-skill-factory;skills\lab-skill-factory" `
  --add-data "$McpDir\scripts;scripts" `
  --add-data "$McpDir\evals;evals" `
  --add-data "$McpDir\install.py;." `
  "$McpDir\cli.py"

Write-Host "Built: $(Join-Path $DistDir ($AppName + '.exe'))"
Write-Host "Optional signing: signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a <exe>"
