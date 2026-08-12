"""Validates long-clip support: 10 s, 249 frames, tiled decode, long audio."""

import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

from engine import ComfyClient, WorkflowBuilder  # noqa: E402

ROOT = APP.parent
client = ComfyClient("127.0.0.1", 8199, ROOT / "outputs" / "_render", ROOT / "outputs")
builder = WorkflowBuilder(
    APP / "workflow_t2v.json", ROOT / "engine" / "ComfyUI" / "input"
)

params = {
    "prompt": (
        "A tiny robot waters a sunflower on a balcony at golden hour, the flower "
        "slowly turns toward the sun, birds chirp and a soft breeze rustles leaves"
    ),
    "negative": "",
    "aspect": "16:9",
    "quality": "fast",
    "width": 768,
    "height": 448,
    "seconds": 10.0,
    "fps": 25.0,
    "seed": 101010,
}

graph, frames, real_seconds = builder.build(params, "longtest")
assert graph["24"]["class_type"] == "VAEDecodeTiled", graph["24"]["class_type"]
print(f"graph ok, decoder={graph['24']['class_type']} frames={frames} ({real_seconds:.1f}s)", flush=True)

job = client.submit(graph, params)
print(f"submitted job={job['id']}", flush=True)

last = None
started = time.time()
while True:
    time.sleep(6)
    j = client.jobs[job["id"]]
    key = (j["status"], j["stage"], j["step"])
    if key != last:
        last = key
        print(f"[{int(time.time()-started):4d}s] {j['status']} | {j['stage']} | step={j['step']}/{j['steps']}", flush=True)
    if j["status"] in ("done", "error", "cancelled"):
        print(f"FINAL: {j['status']} output={j.get('output')} error={j.get('error')}", flush=True)
        break
    if time.time() - started > 3000:
        print("FINAL: timeout", flush=True)
        break
