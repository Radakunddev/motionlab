"""Validates the ultra path's tiled VAE decode on a small, safe render."""

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
    "prompt": "A paper boat drifts across a puddle in gentle rain, ripples spread, soft rain sound",
    "negative": "",
    "aspect": "16:9",
    "quality": "ultra",  # forces VAEDecodeTiled; dims stay small and safe
    "width": 768,
    "height": 448,
    "seconds": 2.0,
    "fps": 25.0,
    "seed": 424242,
}

graph, frames, real_seconds = builder.build(params, "tiledtest")
assert graph["24"]["class_type"] == "VAEDecodeTiled", graph["24"]["class_type"]
print(f"graph ok, decoder={graph['24']['class_type']} frames={frames}", flush=True)

job = client.submit(graph, params)
print(f"submitted job={job['id']}", flush=True)

last = None
started = time.time()
while True:
    time.sleep(5)
    j = client.jobs[job["id"]]
    key = (j["status"], j["stage"], j["step"])
    if key != last:
        last = key
        print(f"[{int(time.time()-started):4d}s] {j['status']} | {j['stage']} | step={j['step']}/{j['steps']}", flush=True)
    if j["status"] in ("done", "error", "cancelled"):
        print(f"FINAL: {j['status']} output={j.get('output')} error={j.get('error')}", flush=True)
        break
    if time.time() - started > 2400:
        print("FINAL: timeout", flush=True)
        break
