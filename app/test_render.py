"""Headless end-to-end test: submits a small render through the app's own
engine client and prints progress lines until it finishes."""

import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

from engine import ComfyClient, WorkflowBuilder  # noqa: E402

ROOT = APP.parent
client = ComfyClient("127.0.0.1", 8199, ROOT / "outputs" / "_render", ROOT / "outputs")
builder = WorkflowBuilder(APP / "workflow_t2v.json", ROOT / "engine" / "ComfyUI" / "input")

image_path = sys.argv[1] if len(sys.argv) > 1 else None

params = {
    "prompt": (
        "The sun sets over a calm ocean, gentle waves roll toward the shore, "
        "the camera slowly pushes in, warm light shimmers on the water, "
        "soft wave sounds"
    ) if image_path else (
        "A fluffy orange cat wearing tiny sunglasses rides a skateboard down a "
        "sunny suburban street, smooth tracking shot, upbeat whistling and "
        "skateboard wheel sounds"
    ),
    "negative": "",
    "aspect": "16:9",
    "quality": "fast",
    "width": 768,
    "height": 448,
    "seconds": 2.0,
    "fps": 25.0,
    "seed": 20260807,
    "image_path": image_path,
}

graph, frames, real_seconds = builder.build(params, "testrun")
print(f"frames={frames} real_seconds={real_seconds:.2f}", flush=True)

job = client.submit(graph, params)
print(f"submitted job={job['id']} prompt_id={job['prompt_id']}", flush=True)

last = None
started = time.time()
while True:
    time.sleep(5)
    j = client.jobs[job["id"]]
    key = (j["status"], j["stage"], j["step"])
    if key != last:
        last = key
        el = int(time.time() - started)
        print(f"[{el:4d}s] {j['status']} | {j['stage']} | step={j['step']}/{j['steps']}", flush=True)
    if j["status"] in ("done", "error", "cancelled"):
        print(f"FINAL: {j['status']} output={j.get('output')} error={j.get('error')}", flush=True)
        break
    if time.time() - started > 3600:
        print("FINAL: timeout after 1h", flush=True)
        break
