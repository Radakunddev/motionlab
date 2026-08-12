"""MotionLab MCP server: lets Claude (Desktop or Code) drive generations.

Thin stdio bridge to the running MotionLab app's local HTTP API. The app
writes its port to logs\runtime.json on startup; if the app is not running,
tools return a friendly hint instead of failing.

Claude Desktop config (claude_desktop_config.json):
  "motionlab": {
    "command": "<motionlab>\\engine\\venv\\Scripts\\python.exe",
    "args": ["<motionlab>\\app\\mcp_server.py"]
  }
"""

import json
import time
import urllib.request
from pathlib import Path

from fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "logs" / "runtime.json"

mcp = FastMCP("motionlab")

NOT_RUNNING = (
    "MotionLab is not running. Start it first (desktop shortcut or MotionLab.bat), "
    "then try again."
)


def _port():
    try:
        info = json.loads(RUNTIME.read_text(encoding="utf-8"))
        return int(info["ui_port"])
    except Exception:
        return None


def _call(method, path, payload=None):
    port = _port()
    if port is None:
        return {"ok": False, "error": NOT_RUNNING}
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"ok": False, "error": NOT_RUNNING}


def _wait_or_status(job_id, wait_minutes):
    deadline = time.time() + wait_minutes * 60
    last = None
    while time.time() < deadline:
        state = _call("GET", "/api/state")
        jobs = state.get("jobs") or []
        job = next((j for j in jobs if j["id"] == job_id), None)
        if job is None:
            return {"ok": False, "error": "job not found (app restarted?)"}
        last = job
        if job["status"] in ("done", "error", "cancelled"):
            out = {"ok": job["status"] == "done", "status": job["status"], "job_id": job_id}
            if job.get("output"):
                out["output_file"] = str(ROOT / "outputs" / job["output"])
            if job.get("error"):
                out["error"] = job["error"]
            return out
        time.sleep(5)
    return {
        "ok": True, "status": last["status"] if last else "unknown", "job_id": job_id,
        "stage": (last or {}).get("stage"), "step": (last or {}).get("step"),
        "steps": (last or {}).get("steps"),
        "note": "still rendering, call job_status again later",
    }


@mcp.tool()
def generate_video(prompt: str, seconds: float = 4, aspect: str = "16:9",
                   quality: str = "fast", seed: int = -1,
                   start_image_path: str = "", wait_minutes: float = 0) -> dict:
    """Generate a video (with audio) locally via LTX-2. aspect: 16:9|9:16|1:1;
    quality: fast|balanced|high|ultra; seconds: 2-12. Optional start_image_path
    turns it into image-to-video. Renders take minutes: by default returns a
    job_id immediately (poll with job_status); set wait_minutes>0 to block."""
    params = {
        "prompt": prompt, "seconds": seconds, "aspect": aspect,
        "quality": quality, "image_path": start_image_path,
        "seed": "random" if seed < 0 else seed,
    }
    res = _call("POST", "/api/generate", params)
    if not res.get("ok"):
        return res
    if wait_minutes > 0:
        return _wait_or_status(res["job"], wait_minutes)
    return {"ok": True, "job_id": res["job"], "seed": res.get("seed"),
            "note": "rendering started, poll with job_status"}


@mcp.tool()
def generate_image(prompt: str, aspect: str = "1:1", size: str = "std",
                   seed: int = -1, ref_image_paths: list[str] = [],
                   wait_minutes: float = 5) -> dict:
    """Generate an image locally via Ideogram 4 (strong at posters and text).
    aspect: 1:1|16:9|9:16|4:3|3:4|3:2|2:3|21:9; size: std|large|xl.
    ref_image_paths (up to 3, absolute paths) add style/content references."""
    params = {
        "mode": "image", "prompt": prompt, "aspect": aspect, "img_size": size,
        "ref_images": list(ref_image_paths)[:3],
        "seed": "random" if seed < 0 else seed,
    }
    res = _call("POST", "/api/generate", params)
    if not res.get("ok"):
        return res
    if wait_minutes > 0:
        return _wait_or_status(res["job"], wait_minutes)
    return {"ok": True, "job_id": res["job"], "seed": res.get("seed")}


@mcp.tool()
def edit_image(prompt: str, image_path: str, ref_image_paths: list[str] = [],
               seed: int = -1, wait_minutes: float = 5) -> dict:
    """Edit an existing image locally via Qwen-Image-Edit 2511 (4-step).
    image_path (absolute) is the image to change; ref_image_paths (up to 2)
    carry identity, e.g. a character to insert. The prompt describes the edit."""
    params = {
        "mode": "edit", "prompt": prompt, "image_path": image_path,
        "ref_images": list(ref_image_paths)[:2],
        "seed": "random" if seed < 0 else seed,
    }
    res = _call("POST", "/api/generate", params)
    if not res.get("ok"):
        return res
    if wait_minutes > 0:
        return _wait_or_status(res["job"], wait_minutes)
    return {"ok": True, "job_id": res["job"], "seed": res.get("seed")}


@mcp.tool()
def job_status(job_id: str) -> dict:
    """Status of a render job: stage, step progress, and the output file path
    once done."""
    return _wait_or_status(job_id, 0)


@mcp.tool()
def app_status() -> dict:
    """Is MotionLab running, is the engine ready, what is rendering right now."""
    state = _call("GET", "/api/state")
    if not isinstance(state, dict) or state.get("ok") is False:
        return state
    jobs = state.get("jobs") or []
    active = [
        {"id": j["id"], "status": j["status"], "stage": j.get("stage"),
         "step": j.get("step"), "steps": j.get("steps"),
         "prompt": (j.get("prompt") or "")[:80]}
        for j in jobs if j["status"] in ("queued", "running")
    ]
    return {"ok": True, "engine": state.get("engine"),
            "version": state.get("version"), "active_jobs": active}


@mcp.tool()
def list_library(query: str = "", type: str = "all", limit: int = 10) -> dict:
    """Recent generated files (newest first) with absolute paths.
    type: all|video|image|edit; query filters prompts."""
    res = _call("GET", "/api/library")
    if not res.get("ok"):
        return res
    items = []
    q = query.strip().lower()
    for it in res.get("items", []):
        itype = it.get("type") or "video"
        if type != "all" and itype != type:
            continue
        if q and q not in (it.get("prompt") or "").lower():
            continue
        items.append({
            "file": str(ROOT / "outputs" / it["file"]),
            "type": itype,
            "prompt": it.get("prompt"),
            "params": {k: it.get("params", {}).get(k) for k in ("width", "height", "seconds", "seed", "quality")},
        })
        if len(items) >= max(1, min(50, limit)):
            break
    return {"ok": True, "items": items}


def run_http(port=8765):
    """Serve MCP over streamable HTTP on 127.0.0.1 (for Claude Desktop's
    Settings -> Connectors -> Add custom connector)."""
    mcp.run(transport="http", host="127.0.0.1", port=port, show_banner=False)


if __name__ == "__main__":
    mcp.run()  # stdio (claude_desktop_config.json style)
