param(
  [string]$RootDir = "",
  [string]$DistDir = "",
  [string]$AppName = "lab-factory",
  [switch]$ReleaseBuild,
  [string]$CodeSigningThumbprint = ""
)

$ErrorActionPreference = "Stop"

if ($ReleaseBuild -and $CodeSigningThumbprint -eq "") {
  throw "ReleaseBuild requires CodeSigningThumbprint; refusing to create an unsigned release artifact."
}

if ($RootDir -eq "") {
  $RootDir = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
}
if ($DistDir -eq "") {
  $DistDir = Join-Path $RootDir "mcp\lab-skill-factory\dist\windows"
}

$McpDir = Join-Path $RootDir "mcp\lab-skill-factory"
$RuntimeSkillRoot = Join-Path $RootDir "skills\lab-skill-factory"
$StagedRuntimeRoot = Join-Path $McpDir "build\release-runtime\lab-skill-factory"
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
python (Join-Path $McpDir "scripts\stage_release_runtime.py") --source $RuntimeSkillRoot --output $StagedRuntimeRoot

python -m pip install pyinstaller -r (Join-Path $McpDir "runtime-requirements.txt")

pyinstaller `
  --clean `
  --optimize 2 `
  --onefile `
  --name $AppName `
  --distpath $DistDir `
  --workpath (Join-Path $McpDir "build\pyinstaller-work") `
  --specpath (Join-Path $McpDir "build") `
  --hidden-import docx `
  --hidden-import lxml `
  --hidden-import cryptography `
  --hidden-import keyring.backends.Windows `
  --collect-data docx `
  --add-data "$StagedRuntimeRoot;skills\lab-skill-factory" `
  --add-data "$McpDir\license_public_key.json;." `
  --add-data "$McpDir\lease_public_key.json;." `
  "$McpDir\cli.py"

$ExePath = Join-Path $DistDir ($AppName + ".exe")
if ($CodeSigningThumbprint -ne "") {
  $SignTool = Get-Command "signtool.exe" -ErrorAction Stop
  & $SignTool.Source sign /sha1 $CodeSigningThumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $ExePath
  if ($LASTEXITCODE -ne 0) { throw "signtool failed for $ExePath" }
}
if ($ReleaseBuild -and (Get-AuthenticodeSignature $ExePath).Status -ne "Valid") {
  throw "Release binary does not have a valid Authenticode signature: $ExePath"
}

python (Join-Path $McpDir "scripts\test_release_security.py") --binary $ExePath

Write-Host "Built: $(Join-Path $DistDir ($AppName + '.exe'))"
Write-Host "Optional signing: signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a <exe>"
