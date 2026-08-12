"""First Ideogram 4 image render through the app pipeline."""

import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

from engine import ComfyClient, WorkflowBuilder  # noqa: E402

ROOT = APP.parent
client = ComfyClient("127.0.0.1", 8199, ROOT / "outputs" / "_render", ROOT / "outputs")
builder = WorkflowBuilder(APP / "workflow_image.json")

import sys as _sys

params = {
    "mode": "image",
    "prompt": _sys.argv[1] if len(_sys.argv) > 1 else (
        "a ginger cat wearing a tiny wizard hat reading a spellbook"
    ),
    "negative": "",
    "aspect": "1:1",
    "img_size": "std",
    "width": 1024,
    "height": 1024,
    "seed": int(_sys.argv[2]) if len(_sys.argv) > 2 else 77007,
    "steps": int(_sys.argv[3]) if len(_sys.argv) > 3 else 20,
}
if len(_sys.argv) > 5:
    params["mu"] = float(_sys.argv[4])
    params["std"] = float(_sys.argv[5])

graph = builder.build_image(params, "imgtest")
print(f"graph ok, nodes={len(graph)}", flush=True)

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
    if time.time() - started > 4500:
        print("FINAL: timeout", flush=True)
        break
