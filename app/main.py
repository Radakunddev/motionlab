"""MotionLab: local desktop studio for open-weight video models (LTX-2).

Boots a headless ComfyUI engine, serves the UI over localhost, and opens a
native window (pywebview / WebView2). All state lives in plain files under
the motionlab folder.
"""

import json
import logging
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
UI_DIR = APP_DIR / "ui"
ENGINE_DIR = ROOT / "engine"
COMFY_DIR = ENGINE_DIR / "ComfyUI"
VENV_PY = ENGINE_DIR / "venv" / "Scripts" / "python.exe"
OUTPUTS = ROOT / "outputs"           # library (final clips + sidecars)
COMFY_OUT = OUTPUTS / "_render"      # comfy writes here, finalize moves up
LOGS = ROOT / "logs"
ENGINE_HOST = "127.0.0.1"
ENGINE_PORT = 8199

for d in (OUTPUTS, COMFY_OUT, LOGS):
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOGS / "app.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("motionlab.app")

sys.path.insert(0, str(APP_DIR))
import updater  # noqa: E402
from engine import ComfyClient, WorkflowBuilder  # noqa: E402

try:
    APP_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
except Exception:
    APP_VERSION = "dev"

client = ComfyClient(ENGINE_HOST, ENGINE_PORT, COMFY_OUT, OUTPUTS)
builder = WorkflowBuilder(APP_DIR / "workflow_t2v.json", COMFY_DIR / "input")
builder_img = WorkflowBuilder(APP_DIR / "workflow_image.json", COMFY_DIR / "input")
builder_edit = WorkflowBuilder(APP_DIR / "workflow_edit.json", COMFY_DIR / "input")
window = None  # set in main()

# Ideogram 4 output sizes, every edge on the 16 px Flux2 latent grid, max 2048.
# Aspect set mirrors the official ResolutionSelector presets.
IMG_SIZES = {
    "std": {
        "1:1": (1024, 1024), "16:9": (1344, 768), "9:16": (768, 1344),
        "4:3": (1152, 864), "3:4": (864, 1152), "3:2": (1248, 832),
        "2:3": (832, 1248), "21:9": (1536, 656),
    },
    "large": {
        "1:1": (1280, 1280), "16:9": (1664, 944), "9:16": (944, 1664),
        "4:3": (1440, 1088), "3:4": (1088, 1440), "3:2": (1568, 1040),
        "2:3": (1040, 1568), "21:9": (1920, 816),
    },
    "xl": {
        "1:1": (2048, 2048), "16:9": (2048, 1152), "9:16": (1152, 2048),
        "4:3": (2048, 1536), "3:4": (1536, 2048), "3:2": (2048, 1360),
        "2:3": (1360, 2048), "21:9": (2048, 880),
    },
}

# Final output sizes; all divisible by 64 so the half-res base pass stays on
# the 32px latent grid of EmptyLTXVLatentVideo. "ultra" matches the official
# LTX-2.3 template default (1920x1088 via 960x544 base + x2 upsample).
QUALITY = {
    "fast":     {"16:9": (768, 448),  "9:16": (448, 768),  "1:1": (640, 640)},
    "balanced": {"16:9": (1024, 576), "9:16": (576, 1024), "1:1": (768, 768)},
    "high":     {"16:9": (1216, 704), "9:16": (704, 1216), "1:1": (960, 960)},
    "ultra":    {"16:9": (1920, 1088), "9:16": (1088, 1920), "1:1": (1088, 1088)},
}

# Commit limit (RAM + pagefile) that makes the heavy paths safe. The box has
# 31 GB RAM; a fixed 32-48 GB pagefile pushes the limit past this threshold.
SAFE_COMMIT_GB = 55


def commit_limit_gb():
    """Current Windows commit limit in GB (physical RAM + pagefile)."""
    try:
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        st = MemoryStatusEx()
        st.dwLength = ctypes.sizeof(MemoryStatusEx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        return st.ullTotalPageFile / 1e9
    except Exception:
        return 0.0

SAMPLE_PROMPTS = [
    "A woman in a yellow raincoat walks through neon-lit rain at night, "
    "reflections shimmer on the wet street, cinematic tracking shot, soft rain sound",
    "Close-up of an espresso pouring into a glass cup in warm morning light, "
    "steam rising, rich crema swirling, gentle cafe ambience",
    "A small sailboat glides across a glassy alpine lake at dawn, mist over the water, "
    "mountains mirrored, calm wind and water sounds",
    "Macro shot of a matchstick igniting in slow motion, sparks and smoke curling "
    "in dark space, sharp striking sound",
]


# ----------------------------------------------------------------- engine boot

engine_proc = None
engine_state = {"phase": "offline"}  # offline -> starting -> ready / failed
_engine_lock = threading.Lock()


def spawn_engine():
    global engine_proc
    engine_log = open(LOGS / "engine.log", "a", encoding="utf-8", errors="replace")
    engine_log.write(f"\n----- engine start {time.ctime()} -----\n")
    engine_log.flush()
    cmd = [
        str(VENV_PY), "-u", "main.py",
        "--listen", ENGINE_HOST,
        "--port", str(ENGINE_PORT),
        "--disable-auto-launch",
        "--output-directory", str(COMFY_OUT),
        # Async weight offload + pinned memory hard-crash (access violation) on
        # this Windows box while loading the GGUF text encoder; disable both.
        "--disable-async-offload",
        "--disable-pinned-memory",
        # Leave headroom for the display / other apps on the 8 GB card.
        "--reserve-vram", "0.8",
    ]
    limit = commit_limit_gb()
    if limit < SAFE_COMMIT_GB:
        # 31 GB RAM + a small pagefile cannot hold Gemma AND the 22B DiT cached
        # at once (machine-crashing commit spike). Drop models between stages;
        # costs ~2 min reload per render, keeps the OS alive. With an enlarged
        # pagefile this is skipped and models stay warm between renders.
        cmd.append("--cache-none")
    log.info("commit limit %.1f GB -> cache-none=%s", limit, limit < SAFE_COMMIT_GB)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    engine_proc = subprocess.Popen(
        cmd, cwd=str(COMFY_DIR),
        stdout=engine_log, stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    log.info("engine spawned, pid %s", engine_proc.pid)


def ensure_engine_async():
    def run():
        with _engine_lock:
            if engine_state["phase"] in ("starting", "ready"):
                return
            engine_state["phase"] = "starting"
        try:
            if client.is_up():
                engine_state["phase"] = "ready"
                client.ensure_ws()
                return
            spawn_engine()
            deadline = time.time() + 300  # first boot imports torch, be patient
            while time.time() < deadline:
                if engine_proc is not None and engine_proc.poll() is not None:
                    engine_state["phase"] = "failed"
                    log.error("engine exited with code %s", engine_proc.returncode)
                    return
                if client.is_up():
                    engine_state["phase"] = "ready"
                    client.ensure_ws()
                    log.info("engine ready")
                    return
                time.sleep(1.5)
            engine_state["phase"] = "failed"
            log.error("engine did not come up in time")
        except Exception:
            engine_state["phase"] = "failed"
            log.exception("engine boot failed")

    threading.Thread(target=run, name="engine-boot", daemon=True).start()


# -------------------------------------------------------------------- ui http

class UiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlsplit_path(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._json({"ok": False, "error": "invalid JSON body"}, 400)
            return
        if path == "/api/generate":
            self._json(api.generate(payload))
        elif path == "/api/cancel":
            self._json(api.cancel(payload.get("job_id", "")))
        else:
            self._json({"ok": False, "error": "unknown endpoint"}, 404)

    def _resolve(self):
        path = urlsplit_path(self.path)
        if path.startswith("/media/"):
            base, rel = OUTPUTS, path[len("/media/"):]
        else:
            base, rel = UI_DIR, path.lstrip("/") or "index.html"
        target = (base / rel).resolve()
        if not str(target).startswith(str(base.resolve())):
            return None
        return target if target.is_file() else None

    def do_HEAD(self):
        self._serve(head=True)

    def do_GET(self):
        path = urlsplit_path(self.path)
        if path == "/api/state":
            self._json(api.get_state())
            return
        if path == "/api/library":
            self._json({"ok": True, "items": api.library()[:40]})
            return
        self._serve(head=False)

    def _serve(self, head):
        target = self._resolve()
        if target is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        size = target.stat().st_size
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                else:  # suffix range
                    start = max(0, size - int(m.group(2)))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head:
            return
        try:
            with open(target, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (ConnectionAbortedError, BrokenPipeError):
            pass


def urlsplit_path(raw):
    from urllib.parse import unquote, urlsplit
    return unquote(urlsplit(raw).path)


def start_ui_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), UiHandler)
    threading.Thread(target=srv.serve_forever, name="ui-http", daemon=True).start()
    return srv.server_address[1]


# ------------------------------------------------------------------ JS bridge

class Api:
    def get_state(self):
        running, pending = (0, 0)
        phase = engine_state["phase"]
        if phase == "ready":
            if not client.is_up():
                phase = "starting" if (engine_proc and engine_proc.poll() is None) else "failed"
                engine_state["phase"] = phase
                with client.lock:  # engine died: fail any job still in flight
                    for j in client.jobs.values():
                        if j["status"] in ("queued", "running"):
                            j["status"] = "error"
                            j["error"] = "The engine stopped unexpectedly. Check logs\\engine.log."
                            j["finished"] = int(time.time() * 1000)
            else:
                running, pending = client.queue_counts()
        return {
            "engine": phase,
            "queue_running": running,
            "queue_pending": pending,
            "jobs": client.active_jobs()[:8],
            "headroom": commit_limit_gb() >= SAFE_COMMIT_GB,
            "version": APP_VERSION,
            "update": {"version": updater.state["available"], "notes": updater.state["notes"]}
                      if updater.state["available"] else None,
            "mcp_url": f"http://127.0.0.1:{mcp_state['port']}/mcp" if mcp_state.get("port") else None,
            "now": int(time.time() * 1000),
        }

    def get_defaults(self):
        return {
            "samples": SAMPLE_PROMPTS,
            "quality": {k: v["16:9"] for k, v in QUALITY.items()},
            "model": "LTX-2.3 22B distilled Q4_K_M",
        }

    def generate(self, params):
        try:
            phase = engine_state["phase"]
            if phase != "ready":
                ensure_engine_async()
                return {"ok": False, "error": "Engine is not ready yet. It keeps warming up in the background, try again in a moment."}
            prompt = (params.get("prompt") or "").strip()
            if not prompt:
                return {"ok": False, "error": "Write a prompt first."}
            aspect = params.get("aspect", "16:9")
            quality = params.get("quality", "balanced")
            seconds = float(params.get("seconds", 4))
            headroom = commit_limit_gb() >= SAFE_COMMIT_GB

            if params.get("mode") == "edit":
                image_path = params.get("image_path")
                if not image_path or not Path(image_path).is_file():
                    return {"ok": False, "error": "Pick the image to edit first."}
                seed = params.get("seed")
                if seed in (None, "", "random"):
                    seed = int.from_bytes(os.urandom(4), "big")
                refs = [str(p) for p in (params.get("ref_images") or []) if p and Path(p).is_file()][:2]
                job_params = {
                    "mode": "edit",
                    "prompt": prompt,
                    "image_path": str(image_path),
                    "ref_images": refs,
                    "seed": int(seed),
                    "steps": 4,
                }
                tag = f"mlab_{int(time.time())}"
                graph = builder_edit.build_edit(job_params, tag)
                job = client.submit(graph, job_params)
                return {"ok": True, "job": job["id"], "seed": int(seed)}

            if params.get("mode") == "image":
                size_key = params.get("img_size", "std")
                sizes = IMG_SIZES.get(size_key, IMG_SIZES["std"])
                width, height = sizes.get(aspect, sizes["1:1"])
                seed = params.get("seed")
                if seed in (None, "", "random"):
                    seed = int.from_bytes(os.urandom(4), "big")
                refs = [str(p) for p in (params.get("ref_images") or []) if p and Path(p).is_file()][:3]
                job_params = {
                    "mode": "image",
                    "prompt": prompt,
                    "negative": params.get("negative", ""),
                    "aspect": aspect,
                    "img_size": size_key,
                    "width": width,
                    "height": height,
                    "seed": int(seed),
                    "steps": 20,
                    "ref_images": refs,
                }
                tag = f"mlab_{int(time.time())}"
                graph = builder_img.build_image(job_params, tag)
                job = client.submit(graph, job_params)
                return {"ok": True, "job": job["id"], "seed": int(seed)}

            if quality == "ultra":
                if not headroom:
                    return {"ok": False, "error": "Ultra 1080p needs the bigger Windows pagefile first (32 to 48 GB fixed, command in the README). Set it, reboot, restart MotionLab."}
                if seconds > 4:
                    return {"ok": False, "error": "Ultra 1080p is capped at 4 s on this machine. Pick 2 s or 4 s."}
            if seconds > 8 and not headroom:
                return {"ok": False, "error": "10 and 12 s need the bigger Windows pagefile first (command in the README). Until then the max is 8 s, or 6 s on High."}
            if quality == "high" and seconds >= 8 and not headroom:
                return {"ok": False, "error": "High with 8 s or longer needs the bigger pagefile (README). Right now High works up to 6 s; for 8 s pick Balanced."}
            width, height = QUALITY.get(quality, QUALITY["balanced"]).get(aspect, QUALITY["balanced"]["16:9"])
            image_path = (params.get("image_path") or "").strip() or None
            if image_path and not Path(image_path).is_file():
                return {"ok": False, "error": "The attached image no longer exists."}
            seed = params.get("seed")
            if seed in (None, "", "random"):
                seed = int.from_bytes(os.urandom(4), "big")
            job_params = {
                "prompt": prompt,
                "negative": params.get("negative", ""),
                "aspect": aspect,
                "quality": quality,
                "width": width,
                "height": height,
                "seconds": seconds,
                "fps": 25.0,
                "seed": int(seed),
                "image_path": image_path,
                "mode": "i2v" if image_path else "t2v",
            }
            tag = f"mlab_{int(time.time())}"
            graph, frames, real_seconds = builder.build(job_params, tag)
            job_params["frames"] = frames
            job_params["real_seconds"] = round(real_seconds, 2)
            job = client.submit(graph, job_params)
            return {"ok": True, "job": job["id"], "seed": int(seed)}
        except Exception as exc:
            log.exception("generate failed")
            return {"ok": False, "error": str(exc)}

    def cancel(self, job_id):
        return {"ok": client.cancel(job_id)}

    @staticmethod
    def _img_preview(path):
        try:
            import base64
            import io as _io

            from PIL import Image

            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail((120, 120))
                buf = _io.BytesIO()
                img.save(buf, "JPEG", quality=80)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:
            return None

    def pick_image(self, multiple=False):
        """Native file dialog; returns chosen path(s) plus small previews."""
        try:
            import webview

            if window is None:
                return {"ok": False, "error": "Window not ready."}
            picked = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=bool(multiple),
                file_types=("Images (*.png;*.jpg;*.jpeg;*.webp;*.bmp)",),
            )
            if not picked:
                return {"ok": False, "cancelled": True}
            paths = list(picked) if isinstance(picked, (list, tuple)) else [picked]
            items = [
                {"path": str(p), "name": Path(p).name, "preview": self._img_preview(p)}
                for p in paths[:3]
            ]
            if not multiple:
                return {"ok": True, **items[0]}
            return {"ok": True, "items": items}
        except Exception as exc:
            log.exception("pick_image failed")
            return {"ok": False, "error": str(exc)}

    def library(self):
        items = []
        for sidecar in sorted(OUTPUTS.glob("*.json"), reverse=True):
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                continue
            video = OUTPUTS / (meta.get("file") or "")
            if not video.is_file():
                continue
            meta["url"] = f"/media/{video.name}"
            meta["poster_url"] = f"/media/{meta['poster']}" if meta.get("poster") else None
            meta["size_mb"] = round(video.stat().st_size / 1e6, 1)
            items.append(meta)
        return items

    def delete_item(self, file_name):
        try:
            base = (OUTPUTS / file_name).resolve()
            if not str(base).startswith(str(OUTPUTS.resolve())) or not base.is_file():
                return {"ok": False, "error": "File not found."}
            for p in (base, base.with_suffix(".json"), base.with_suffix(".jpg")):
                if p.exists():
                    p.unlink()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def reveal(self, file_name):
        target = OUTPUTS / file_name
        if target.exists():
            subprocess.Popen(["explorer", "/select,", str(target)])
            return {"ok": True}
        return {"ok": False}

    def open_outputs(self):
        os.startfile(str(OUTPUTS))  # noqa: S606
        return {"ok": True}

    def engine_log_tail(self):
        try:
            text = (LOGS / "engine.log").read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "lines": text.splitlines()[-120:]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def retry_engine(self):
        engine_state["phase"] = "offline"
        ensure_engine_async()
        return {"ok": True}

    # ----------------------------------------------------- Claude Desktop

    @staticmethod
    def _claude_cfg_path():
        candidates = []
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Claude")
        candidates.append(Path.home() / "AppData" / "Roaming" / "Claude")
        # Store/MSIX-packaged Claude Desktop virtualizes %APPDATA%\Claude into
        # its package store; the junction may not be traversable from an
        # unelevated process, but the real folder is.
        local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        try:
            for pkg in sorted((local / "Packages").glob("Claude_*")):
                candidates.append(pkg / "LocalCache" / "Roaming" / "Claude")
        except OSError:
            pass
        for claude_dir in candidates:
            try:
                if claude_dir.is_dir():
                    return claude_dir / "claude_desktop_config.json"
            except OSError:
                continue
        log.warning("claude detect: no Claude dir under %s", [str(c) for c in candidates])
        return None

    def claude_link(self):
        """Connection status of the Claude Desktop MCP integration."""
        p = self._claude_cfg_path()
        if p is None or not p.parent.is_dir():
            return {"installed": False, "connected": False}
        try:
            cfg = json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
        except Exception:
            cfg = {}
        entry = ((cfg.get("mcpServers") or {}).get("motionlab") or {})
        want_cmd = str(VENV_PY)
        return {
            "installed": True,
            "connected": entry.get("command") == want_cmd,
        }

    def build_plugin(self):
        """Builds motionlab.plugin (Claude Desktop local plugin bundle) with
        this machine's paths and returns its path."""
        import zipfile

        manifest = {
            "name": "motionlab",
            "version": APP_VERSION,
            "description": "Drive MotionLab from Claude: generate videos, images and edits on the local GPU, queue batches, check render status, browse the library.",
            "author": {"name": "Radakund Nemeth"},
        }
        mcp = {
            "mcpServers": {
                "motionlab": {
                    "command": str(VENV_PY),
                    "args": [str(APP_DIR / "mcp_server.py")],
                }
            }
        }
        readme = (
            "# MotionLab plugin\n\n"
            "Lets Claude drive the MotionLab app on this machine: generate videos "
            "(LTX-2), images (Ideogram 4) and edits (Qwen-Image-Edit), queue "
            "batches, poll status and list outputs.\n"
        )
        skill = f"""---
name: motionlab
description: Drive the MotionLab app on this machine to generate videos (LTX-2 with audio), images (Ideogram 4) and identity-preserving image edits (Qwen-Image-Edit) on the local GPU. Use whenever the user mentions MotionLab, or asks to generate/queue video, image or edit locally, check render status, or list generated files.
---

# Driving MotionLab

MotionLab is a local generative studio at `{ROOT}`. It exposes a small HTTP
API while running. Everything renders on this machine's GPU; renders take
minutes, so queue jobs and poll rather than wait synchronously.

## 1. Ensure the app is running

Read `{ROOT}\\logs\\runtime.json` -> `ui_port` (and `pid`). Verify with
`GET http://127.0.0.1:<ui_port>/api/state`. If unreachable, start the app:

```
cmd /c start "" "{ROOT}\\MotionLab.bat"
```

then re-read runtime.json (it is rewritten on boot) and wait for
`/api/state` to answer. `engine` cycles offline -> starting -> ready; first
boot takes 1-2 minutes. Generation requires `engine: "ready"`.

## 2. Generate

`POST http://127.0.0.1:<ui_port>/api/generate` with JSON. Three shapes:

Video (LTX-2, audio included): `{{"prompt": "...", "seconds": 4, "aspect": "16:9", "quality": "fast", "seed": "random", "image_path": ""}}`
- seconds: 2-12 (over 8 needs the machine's big pagefile; the API refuses with a clear error if not allowed)
- aspect: 16:9 | 9:16 | 1:1; quality: fast | balanced | high | ultra (ultra caps at 4 s)
- image_path: absolute path of a start image -> image-to-video

Image (Ideogram 4, good at posters/text): `{{"mode": "image", "prompt": "...", "aspect": "1:1", "img_size": "std", "seed": "random", "ref_images": []}}`
- aspect: 1:1 | 16:9 | 9:16 | 4:3 | 3:4 | 3:2 | 2:3 | 21:9; img_size: std | large | xl

Edit (Qwen-Image-Edit, keeps identity): `{{"mode": "edit", "prompt": "what changes", "image_path": "abs path of image to edit", "ref_images": ["up to 2 abs paths carrying identity"], "seed": "random"}}`

Response: `{{"ok": true, "job": "<id>", "seed": N}}` or `{{"ok": false, "error": "..."}}`.
Queue several by POSTing repeatedly; jobs render strictly one at a time and
all appear in the app window's queue.

## 3. Poll and deliver

`GET /api/state` -> `jobs[]` with `id, status (queued|running|done|error),
stage, step, steps, output`. Poll every 20-30 s; do not block the
conversation. When `done`, the file is `{ROOT}\\outputs\\<output>` (mp4 for
video, png for images) with a same-name .json sidecar and .jpg poster for
videos. Tell the user the absolute path. `GET /api/library` lists recent
outputs. Cancel with `POST /api/cancel` body `{{"job_id": "..."}}`.

PowerShell example:

```
$s = irm http://127.0.0.1:PORT/api/state
irm http://127.0.0.1:PORT/api/generate -Method Post -ContentType 'application/json' -Body '{{"prompt":"...","seconds":4,"quality":"fast","aspect":"16:9","seed":"random","image_path":""}}'
```
"""
        target = ROOT / "motionlab.plugin"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(".claude-plugin/plugin.json", json.dumps(manifest, indent=2))
            zf.writestr(".mcp.json", json.dumps(mcp, indent=2))
            zf.writestr("skills/motionlab/SKILL.md", skill)
            zf.writestr("README.md", readme)
        return target

    def install_extension(self):
        """Generates the plugin bundle and reveals it for drag-into-chat install."""
        try:
            target = self.build_plugin()
            subprocess.Popen(["explorer", "/select,", str(target)])
            return {"ok": True, "path": str(target)}
        except Exception as exc:
            log.exception("install_extension failed")
            return {"ok": False, "error": str(exc)}

    def connect_claude(self):
        """Adds (or repairs) the motionlab MCP server in Claude Desktop's config."""
        p = self._claude_cfg_path()
        if p is None or not p.parent.is_dir():
            return {"ok": False, "error": "Claude Desktop is not installed. Get it from claude.ai/download, run it once, then connect again."}
        try:
            cfg = {}
            if p.is_file():
                Path(str(p) + ".bak").write_bytes(p.read_bytes())
                try:
                    cfg = json.loads(p.read_text(encoding="utf-8-sig"))
                except Exception:
                    cfg = {}
            servers = cfg.setdefault("mcpServers", {})
            servers["motionlab"] = {
                "command": str(VENV_PY),
                "args": [str(APP_DIR / "mcp_server.py")],
            }
            p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"ok": True}
        except Exception as exc:
            log.exception("connect_claude failed")
            return {"ok": False, "error": str(exc)}

    def disconnect_claude(self):
        p = self._claude_cfg_path()
        try:
            if p and p.is_file():
                cfg = json.loads(p.read_text(encoding="utf-8"))
                if (cfg.get("mcpServers") or {}).pop("motionlab", None) is not None:
                    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------- main

def apply_window_icon(w):
    """Set the MotionLab icon on the native WinForms window (title bar + taskbar)."""
    try:
        import clr

        clr.AddReference("System.Drawing")
        from System.Drawing import Icon

        ico = APP_DIR / "assets" / "motionlab.ico"
        if ico.exists() and getattr(w, "native", None) is not None:
            w.native.Icon = Icon(str(ico))
            log.info("window icon applied")
    except Exception:
        log.exception("window icon failed")


api = Api()  # shared by the webview bridge and the local HTTP API

MCP_PORT = 8765
mcp_state = {"port": None}


def start_mcp_server():
    """Runs the MCP server (HTTP transport) in a background thread so Claude
    Desktop can connect via Settings -> Connectors with a plain URL."""
    def run():
        try:
            import mcp_server

            mcp_server.run_http(MCP_PORT)
        except Exception:
            log.exception("mcp http server failed")
            mcp_state["port"] = None

    mcp_state["port"] = MCP_PORT
    threading.Thread(target=run, name="mcp-http", daemon=True).start()
    return MCP_PORT


def main():
    global window
    import webview

    try:  # own taskbar identity instead of pythonw's
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NRMedia.MotionLab")
    except Exception:
        pass

    ensure_engine_async()
    updater.start_background_checks()
    port = start_ui_server()
    log.info("ui server on 127.0.0.1:%s (MotionLab %s)", port, APP_VERSION)
    mcp_port = start_mcp_server()
    try:  # discovery file for the MCP bridge (Claude Desktop integration)
        (LOGS / "runtime.json").write_text(
            json.dumps({"ui_port": port, "mcp_port": mcp_port, "pid": os.getpid(), "version": APP_VERSION}),
            encoding="utf-8",
        )
    except Exception:
        log.exception("runtime.json write failed")

    window = webview.create_window(
        "MotionLab",
        url=f"http://127.0.0.1:{port}/index.html",
        js_api=api,
        width=1280, height=880,
        min_size=(1080, 720),
        background_color="#131410",
    )

    def on_closed():
        if engine_proc is not None and engine_proc.poll() is None:
            log.info("stopping engine (pid %s)", engine_proc.pid)
            engine_proc.terminate()

    window.events.closed += on_closed
    window.events.shown += lambda: apply_window_icon(window)
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
