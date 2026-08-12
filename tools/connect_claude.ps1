# Connects MotionLab to Claude Desktop (adds the MCP server to its config).
# Safe to re-run; keeps every other configured server and makes a backup.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$cfgDir = Join-Path $env:APPDATA "Claude"
$cfgPath = Join-Path $cfgDir "claude_desktop_config.json"

if (-not (Test-Path $cfgDir)) {
  Write-Host "Claude Desktop does not appear to be installed (no $cfgDir)." -ForegroundColor Yellow
  Write-Host "Install it from https://claude.ai/download, run it once, then re-run this script."
  exit 1
}

$cfg = @{}
if (Test-Path $cfgPath) {
  Copy-Item $cfgPath "$cfgPath.bak" -Force
  try { $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json } catch { $cfg = @{} }
}

# PSCustomObject -> ensure mcpServers exists
if (-not $cfg.PSObject.Properties["mcpServers"]) {
  $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{}) -Force
}

$server = [pscustomobject]@{
  command = (Join-Path $Root "engine\venv\Scripts\python.exe")
  args    = @((Join-Path $Root "app\mcp_server.py"))
}
$cfg.mcpServers | Add-Member -NotePropertyName motionlab -NotePropertyValue $server -Force

$cfg | ConvertTo-Json -Depth 8 | Set-Content -Path $cfgPath -Encoding utf8
Write-Host "MotionLab connected. Restart Claude Desktop, then look for the 'motionlab' tools." -ForegroundColor Green
