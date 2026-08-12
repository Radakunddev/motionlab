# Builds a MotionLab release: app-layer zip + manifest.json (+ installer exe).
# Usage:  powershell -File tools\make_release.ps1 [-Version 1.1.0] [-Notes "what changed"]
# Then: create a GitHub release for the tag, upload the zip from dist\,
# and commit the updated manifest.json to the repo root (main branch).

param(
  [string]$Version = "",
  [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Dist = Join-Path $Root "dist"
New-Item -ItemType Directory -Force $Dist | Out-Null

if ($Version) {
  Set-Content -Path (Join-Path $Root "VERSION") -Value $Version -Encoding ascii -NoNewline
} else {
  $Version = (Get-Content (Join-Path $Root "VERSION") -Raw).Trim()
}

Write-Host "Building MotionLab app release $Version"

# --- stage the app layer (never the engine, models or the launcher bat:
# --- the bat applies updates and must not overwrite itself mid-run)
$Stage = Join-Path $env:TEMP ("mlrel_" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force (Join-Path $Stage "app") | Out-Null
robocopy (Join-Path $Root "app") (Join-Path $Stage "app") /E /NFL /NDL /NJH /NJS /XD __pycache__ /XF "test_*.py" "debug_*.py" | Out-Null
Copy-Item (Join-Path $Root "VERSION") $Stage
Copy-Item (Join-Path $Root "README.md") $Stage

$ZipName = "motionlab-app-$Version.zip"
$ZipPath = Join-Path $Dist $ZipName
if (Test-Path $ZipPath) { Remove-Item $ZipPath }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath
Remove-Item -Recurse -Force $Stage

$Sha = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLower()

# --- manifest: commit this file to the repo root; installed apps poll it.
# --- Fill OWNER/REPO once (also in app\update_config.json manifest_url).
$manifest = [ordered]@{
  version = $Version
  zip_url = "https://github.com/Radakunddev/motionlab/releases/download/v$Version/$ZipName"
  sha256  = $Sha
  notes   = $Notes
}
$manifest | ConvertTo-Json | Set-Content -Path (Join-Path $Dist "manifest.json") -Encoding utf8
Copy-Item (Join-Path $Dist "manifest.json") (Join-Path $Root "manifest.json") -Force

Write-Host ""
Write-Host "dist\$ZipName  (sha256 $($Sha.Substring(0,12))...)"
Write-Host "manifest.json written to repo root and dist\"
Write-Host ""
Write-Host "Publish steps:"
Write-Host "  git add -A; git commit -m `"release $Version`"; git tag v$Version; git push; git push --tags"
Write-Host "  gh release create v$Version dist\$ZipName --title `"MotionLab $Version`" --notes `"$Notes`""

# --- installer (optional, needs Inno Setup 6)
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe" }
if (Test-Path $iscc) {
  Write-Host ""
  Write-Host "Compiling installer..."
  & $iscc (Join-Path $Root "installer\motionlab.iss") /Q
  Write-Host "installer\dist\MotionLab-Setup-$Version.exe"
} else {
  Write-Host "Inno Setup not found, installer exe skipped (winget install -e --id JRSoftware.InnoSetup)"
}
