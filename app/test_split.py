"""Split-sigma filter-bypass test: the first K steps run a neutral guider
(unconditional model, zeroed conditioning) so the baked-in refusal cannot
form; the remaining steps run the full dual-model prompt guidance."""

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

SPLIT_AT = int(sys.argv[2]) if len(sys.argv) > 2 else 4

params = {
    "mode": "image",
    "prompt": sys.argv[1] if len(sys.argv) > 1 else
        "a ginger cat wearing a tiny wizard hat reading a spellbook",
    "negative": "",
    "aspect": "1:1",
    "img_size": "std",
    "width": 1024,
    "height": 1024,
    "seed": 123456,
    "steps": 20,
}

graph = builder.build_image(params, "splittest")

# carve the single-sampler graph into a two-stage split
graph["50"] = {  # split the schedule
    "class_type": "SplitSigmas",
    "inputs": {"sigmas": ["13", 0], "step": SPLIT_AT},
}
graph["51"] = {  # neutral guidance: unconditional model, zeroed conditioning
    "class_type": "BasicGuider",
    "inputs": {"model": ["16", 0], "conditioning": ["18", 0]},
}
graph["52"] = {  # stage 1: neutral composition forming
    "class_type": "SamplerCustomAdvanced",
    "inputs": {
        "noise": ["11", 0],
        "guider": ["51", 0],
        "sampler": ["12", 0],
        "sigmas": ["50", 0],
        "latent_image": ["8", 0],
    },
}
graph["53"] = {"class_type": "DisableNoise", "inputs": {}}
# stage 2: the original sampler continues from the neutral latent
graph["15"]["inputs"]["noise"] = ["53", 0]
graph["15"]["inputs"]["sigmas"] = ["50", 1]
graph["15"]["inputs"]["latent_image"] = ["52", 0]

job = client.submit(graph, params)
print(f"submitted split@{SPLIT_AT} job={job['id']}", flush=True)
while True:
    time.sleep(5)
    j = client.jobs[job["id"]]
    if j["status"] in ("done", "error", "cancelled"):
        print(f"FINAL: {j['status']} output={j.get('output')} error={j.get('error')}", flush=True)
        break
