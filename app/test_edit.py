"""End-to-end Qwen-Image-Edit test through the app builder."""

import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

from engine import ComfyClient, WorkflowBuilder  # noqa: E402

ROOT = APP.parent
client = ComfyClient("127.0.0.1", 8199, ROOT / "outputs" / "_render", ROOT / "outputs")
builder = WorkflowBuilder(APP / "workflow_edit.json", ROOT / "engine" / "ComfyUI" / "input")

params = {
    "mode": "edit",
    "prompt": sys.argv[2] if len(sys.argv) > 2 else
        "Add a tall red top hat on the man's head. Keep everything else identical, "
        "same black and white ink comic style.",
    "image_path": sys.argv[1],
    "ref_images": sys.argv[3].split(";") if len(sys.argv) > 3 else [],
    "seed": 4242,
    "steps": 4,
}

graph = builder.build_edit(params, "edittest")
print(f"graph ok, nodes={len(graph)}", flush=True)
job = client.submit(graph, params)
print(f"submitted job={job['id']}", flush=True)
started = time.time()
last = None
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
