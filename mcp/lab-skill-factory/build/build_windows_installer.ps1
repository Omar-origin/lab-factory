param(
  [string]$RootDir = "",
  [string]$DistDir = "",
  [string]$AppName = "lab-factory",
  [string]$Version = "1.0.0-beta.1",
  [string]$Publisher = "Lab Factory",
  [switch]$SkipBinaryBuild,
  [switch]$ReleaseBuild,
  [string]$CodeSigningThumbprint = ""
)

$ErrorActionPreference = "Stop"

if ($RootDir -eq "") {
  $RootDir = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
} else {
  $RootDir = Resolve-Path $RootDir
}

$McpDir = Join-Path $RootDir "mcp\lab-skill-factory"
if ($DistDir -eq "") {
  $DistDir = Join-Path $McpDir "dist\windows"
}
$InstallerDir = Join-Path $DistDir "installer"
$ExePath = Join-Path $DistDir ($AppName + ".exe")
$InnoScript = Join-Path $McpDir "build\windows\lab-factory.iss"

New-Item -ItemType Directory -Force -Path $InstallerDir | Out-Null

if (-not $SkipBinaryBuild) {
  & (Join-Path $McpDir "build\build_windows.ps1") -RootDir $RootDir -DistDir $DistDir -AppName $AppName -ReleaseBuild:$ReleaseBuild -CodeSigningThumbprint $CodeSigningThumbprint
}

if (-not (Test-Path $ExePath)) {
  throw "Windows binary not found: $ExePath. Run build_windows.ps1 first or omit -SkipBinaryBuild."
}
if ($ReleaseBuild -and (Get-AuthenticodeSignature $ExePath).Status -ne "Valid") {
  throw "Release installer cannot include an unsigned or invalid binary: $ExePath"
}

$Iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($null -eq $Iscc) {
  $CommonIscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
  if (Test-Path $CommonIscc) {
    $IsccPath = $CommonIscc
  } else {
    throw "ISCC.exe not found. Install Inno Setup 6 first, for example: choco install innosetup -y"
  }
} else {
  $IsccPath = $Iscc.Source
}

& $IsccPath `
  "/DAppVersion=$Version" `
  "/DAppPublisher=$Publisher" `
  "/DSourceDir=$DistDir" `
  "/DMcpDir=$McpDir" `
  "/DOutputDir=$InstallerDir" `
  "/DAppExeName=$($AppName).exe" `
  $InnoScript

$Installer = Join-Path $InstallerDir ("LabFactory-$Version-Setup.exe")
if (-not (Test-Path $Installer)) {
  throw "Installer build finished but expected output was not found: $Installer"
}

if ($CodeSigningThumbprint -ne "") {
  $SignTool = Get-Command "signtool.exe" -ErrorAction Stop
  & $SignTool.Source sign /sha1 $CodeSigningThumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $Installer
  if ($LASTEXITCODE -ne 0) { throw "signtool failed for $Installer" }
}
if ($ReleaseBuild -and (Get-AuthenticodeSignature $Installer).Status -ne "Valid") {
  throw "Release installer does not have a valid Authenticode signature: $Installer"
}

Write-Host "Built Windows installer: $Installer"
Write-Host "For distributable artifacts use -ReleaseBuild -CodeSigningThumbprint <thumbprint>."
