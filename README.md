# MotionLab

Local desktop studio for open-weight video models. v1 runs Lightricks LTX-2.3 (22B distilled, Q4_K_M GGUF) fully offline on your own GPU, with synchronized audio. No accounts, no API keys, no per-render cost.

## Run

Double-click `MotionLab.bat` (or the MotionLab desktop shortcut). The window opens immediately; the engine (headless ComfyUI) warms up in the background, the status pill in the top bar turns lime when ready. First render after a cold start loads the 22B model and takes extra minutes.

## Layout

- `app\` desktop app: pywebview window, UI, engine client, workflow template
- `engine\ComfyUI\` headless render engine (git clone) + `engine\venv\` Python 3.12 env (torch cu128)
- `engine\ComfyUI\models\` model weights (see below)
- `LTX-2\` official Lightricks repo clone, reference for pipelines and training
- `outputs\` finished clips (`.mp4` + `.jpg` poster + `.json` metadata sidecar)
- `logs\` `app.log` and `engine.log`

## Models on disk

| File | Where | Size |
| --- | --- | --- |
| LTX-2.3-22B-distilled-1.1-Q4_K_M.gguf | `engine\ComfyUI\models\unet` | 17.8 GB |
| gemma-3-12b-it-qat-Q4_0.gguf | `engine\ComfyUI\models\text_encoders` | 6.9 GB |
| ltx-2.3_text_projection_bf16.safetensors | `engine\ComfyUI\models\text_encoders` | 2.3 GB |
| LTX23_video_vae_bf16.safetensors | `engine\ComfyUI\models\vae` | 1.5 GB |
| LTX23_audio_vae_bf16.safetensors | `engine\ComfyUI\models\checkpoints` | 0.4 GB |
| ltx-2.3-spatial-upscaler-x2-1.1.safetensors | `engine\ComfyUI\models\latent_upscale_models` | 1.0 GB |
| ideogram4_fp8_scaled.safetensors (Image mode) | `engine\ComfyUI\models\diffusion_models` | 9.3 GB |
| qwen3vl_8b_fp8_scaled.safetensors (Image mode) | `engine\ComfyUI\models\text_encoders` | 10.6 GB |
| flux2-vae.safetensors (Image mode) | `engine\ComfyUI\models\vae` | 0.3 GB |

Image mode runs Ideogram 4 (9.3B, fp8) for text-to-image; it shares the same engine. Note: Ideogram 4 weights are under a non-commercial license, unlike the LTX-2 video side.

Hardware this was set up for: RTX 4060 Laptop 8 GB VRAM + 31 GB RAM. The 22B model does not fit in VRAM; ComfyUI streams it from system RAM, so renders are slow but stable. Balanced 576p, 4 s is the sweet spot; Fast 448p for drafts.

## Memory stability

The app reads the Windows commit limit (RAM + pagefile) at startup and adapts. Below 55 GB the engine runs with `--cache-none` (models drop out of RAM between stages, ~2 extra minutes per render) and the heavy combos are locked: Ultra 1080p entirely, High at 8 s. At 55 GB or more (after the pagefile fix below) models stay warm between renders and everything unlocks; Ultra stays capped at 4 s on this GPU. Ultra uses tiled VAE decode and matches the official template's 1920x1088 two-stage path. Expect roughly 25 to 45 minutes per Ultra clip.

Strongly recommended once: set a fixed 32 to 48 GB pagefile. Admin PowerShell, paste the whole block, check the printed result, then reboot:

```powershell
Get-CimInstance Win32_ComputerSystem | Set-CimInstance -Property @{AutomaticManagedPagefile=$false}
$pf = Get-CimInstance Win32_PageFileSetting | Where-Object { $_.Name -eq 'C:\pagefile.sys' }
if ($pf) { $pf | Set-CimInstance -Property @{InitialSize=32768; MaximumSize=49152} }
else { New-CimInstance -ClassName Win32_PageFileSetting -Property @{Name='C:\pagefile.sys'; InitialSize=32768; MaximumSize=49152} | Out-Null }
Get-CimInstance Win32_PageFileSetting | Format-List Name, InitialSize, MaximumSize
Write-Host "OK - restart Windows now"
```

GUI alternative: Win+R, `sysdm.cpl`, Advanced, Performance Settings, Advanced, Virtual memory Change: untick "Automatically manage", select C:, Custom size 32768 / 49152, Set, OK, reboot.

After that, removing `--cache-none` from `app\main.py` makes back-to-back renders much faster (models stay warm).

## Notes

- Everything is free and local: ComfyUI (GPL), ComfyUI-GGUF (Apache-2.0), LTX-2 weights (LTX-2 Community License), Gemma 3 encoder (Gemma Terms of Use).
- The engine listens on `127.0.0.1:8199` only.
- To reclaim disk, delete clips from the app or the `outputs\` folder.
