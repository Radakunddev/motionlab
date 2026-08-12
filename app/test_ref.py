"""A/B proof that reference images reach the model: same prompt + seed,
run A with a reference image, run B without. Different-and-ref-like output
in A proves the vision-token path carries the image."""

import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

from engine import ComfyClient, WorkflowBuilder  # noqa: E402

ROOT = APP.parent
client = ComfyClient("127.0.0.1", 8199, ROOT / "outputs" / "_render", ROOT / "outputs")
builder = WorkflowBuilder(
    APP / "workflow_image.json", ROOT / "engine" / "ComfyUI" / "input"
)

REF = sys.argv[1] if len(sys.argv) > 1 else ""
PROMPT = (
    "the same character sitting in a small diner booth eating breakfast, "
    "black and white ink comic panel, dramatic hatching"
)

base = {
    "mode": "image",
    "prompt": PROMPT,
    "negative": "",
    "aspect": "1:1",
    "img_size": "std",
    "width": 1024,
    "height": 1024,
    "seed": 5150,
    "steps": 20,
}

runs = [("A-with-ref", {**base, "ref_images": [REF]}), ("B-no-ref", base)]

for label, params in runs:
    graph = builder.build_image(params, f"ref{label[0]}")
    cls = None
    for node in graph.values():
        if (node.get("_meta") or {}).get("title") == "@PROMPT":
            cls = node["class_type"]
    print(f"{label}: prompt-node={cls}", flush=True)
    job = client.submit(graph, params)
    while True:
        time.sleep(5)
        j = client.jobs[job["id"]]
        if j["status"] in ("done", "error", "cancelled"):
            print(f"{label} FINAL: {j['status']} output={j.get('output')} error={j.get('error')}", flush=True)
            break
