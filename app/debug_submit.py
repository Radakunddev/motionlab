"""Prints the engine's full validation error for the built graph."""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
from engine import WorkflowBuilder  # noqa: E402

builder = WorkflowBuilder(APP / "workflow_t2v.json")
params = {
    "prompt": "test", "negative": "", "width": 768, "height": 448,
    "seconds": 2.0, "fps": 25.0, "seed": 1,
}
graph, _, _ = builder.build(params, "dbg")
req = urllib.request.Request(
    "http://127.0.0.1:8199/prompt",
    data=json.dumps({"prompt": graph, "client_id": "debug"}).encode(),
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print("OK", r.read().decode()[:500])
except urllib.error.HTTPError as e:
    body = e.read().decode(errors="replace")
    print("HTTP", e.code)
    try:
        err = json.loads(body)
        print(json.dumps(err, indent=1)[:4000])
    except Exception:
        print(body[:4000])
