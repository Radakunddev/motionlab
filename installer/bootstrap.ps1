# MotionLab first-run bootstrap.
# Downloads and wires every heavy component that the tiny installer does not
# ship: uv + Python venv, PyTorch CUDA, ComfyUI engine, and the model weights.
# Idempotent: safe to re-run, it skips whatever is already in place.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Engine = Join-Path $Root "engine"
$Comfy = Join-Path $Engine "ComfyUI"
$Venv = Join-Path $Engine "venv"
$Models = Join-Path $Comfy "models"
$Dl = Join-Path $Root "models_dl"

function Step($msg) { Write-Host ""; Write-Host ("==> " + $msg) -ForegroundColor Green }

Step "MotionLab setup starting (this downloads roughly 30-60 GB, grab a coffee)"

# --- disk space guard -------------------------------------------------------
$free = (Get-PSDrive -Name ($Root.Substring(0,1))).Free / 1GB
if ($free -lt 45) {
  Write-Host ("Not enough free disk space: {0:N0} GB free, 45 GB needed." -f $free) -ForegroundColor Red
  exit 1
}

# --- git --------------------------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Step "Installing Git (winget)"
  winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

# --- uv (python manager) ----------------------------------------------------
$uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
if (-not (Test-Path $uv)) {
  Step "Installing uv (python manager)"
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
}
$env:Path = (Join-Path $env:USERPROFILE ".local\bin") + ";" + $env:Path

# --- engine clone -----------------------------------------------------------
if (-not (Test-Path (Join-Path $Comfy "main.py"))) {
  Step "Cloning ComfyUI engine"
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git $Comfy
}
$gguf = Join-Path $Comfy "custom_nodes\ComfyUI-GGUF"
if (-not (Test-Path $gguf)) {
  Step "Cloning GGUF loader node"
  git clone --depth 1 https://github.com/city96/ComfyUI-GGUF.git $gguf
}
$mlnode = Join-Path $Comfy "custom_nodes\motionlab_nodes.py"
$mlnodeSrc = Join-Path $PSScriptRoot "assets\motionlab_nodes.py"
if ((Test-Path $mlnodeSrc) -and -not (Test-Path $mlnode)) {
  Copy-Item $mlnodeSrc $mlnode
}

# --- python env -------------------------------------------------------------
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
  Step "Creating Python 3.12 environment"
  & $uv venv $Venv --python 3.12
}
$py = Join-Path $Venv "Scripts\python.exe"
Step "Installing PyTorch CUDA (about 3 GB)"
& $uv pip install --python $py torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
Step "Installing engine dependencies"
& $uv pip install --python $py -r (Join-Path $Comfy "requirements.txt") -r (Join-Path $gguf "requirements.txt") pywebview websocket-client huggingface_hub

# --- models -----------------------------------------------------------------
function Fetch($repo, $file, $dest) {
  $name = Split-Path $file -Leaf
  $target = Join-Path $dest $name
  if (Test-Path $target) { Write-Host ("   already here: " + $name); return }
  New-Item -ItemType Directory -Force $dest | Out-Null
  Step ("Downloading " + $name)
  & $uv tool run --from "huggingface_hub[hf_xet]" hf download $repo $file --local-dir $Dl
  $src = Join-Path $Dl $file
  if (-not (Test-Path $src)) { throw ("download failed: " + $file) }
  Move-Item -Force $src $target
}

Fetch "QuantStack/LTX-2.3-GGUF" "LTX-2.3-distilled-1.1/LTX-2.3-22B-distilled-1.1-Q4_K_M.gguf" (Join-Path $Models "unet")
Fetch "unsloth/gemma-3-12b-it-qat-GGUF" "gemma-3-12b-it-qat-Q4_0.gguf" (Join-Path $Models "text_encoders")
Fetch "Kijai/LTX2.3_comfy" "text_encoders/ltx-2.3_text_projection_bf16.safetensors" (Join-Path $Models "text_encoders")
Fetch "Kijai/LTX2.3_comfy" "vae/LTX23_video_vae_bf16.safetensors" (Join-Path $Models "vae")
Fetch "Kijai/LTX2.3_comfy" "vae/LTX23_audio_vae_bf16.safetensors" (Join-Path $Models "checkpoints")
Fetch "Lightricks/LTX-2.3" "ltx-2.3-spatial-upscaler-x2-1.1.safetensors" (Join-Path $Models "latent_upscale_models")

$img = Read-Host "Also set up the image model, Ideogram 4? Adds about 29 GB, non-commercial license [y/N]"
if ($img -match '^[yY]') {
  Fetch "Comfy-Org/ideogram-4" "diffusion_models/ideogram4_fp8_scaled.safetensors" (Join-Path $Models "diffusion_models")
  Fetch "Comfy-Org/ideogram-4" "diffusion_models/ideogram4_unconditional_fp8_scaled.safetensors" (Join-Path $Models "diffusion_models")
  Fetch "Comfy-Org/ideogram-4" "text_encoders/qwen3vl_8b_fp8_scaled.safetensors" (Join-Path $Models "text_encoders")
  Fetch "Comfy-Org/ideogram-4" "vae/flux2-vae.safetensors" (Join-Path $Models "vae")
}

if (Test-Path $Dl) { Remove-Item -Recurse -Force $Dl -ErrorAction SilentlyContinue }

Step "MotionLab setup finished. Starting the app..."
exit 0
