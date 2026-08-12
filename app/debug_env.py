"""Writes what a pythonw process (launched like the app) sees for the Claude config."""
import json
import os
from pathlib import Path

out = {}
appdata = os.environ.get("APPDATA", "")
out["APPDATA"] = appdata
p = Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
out["path"] = str(p) if p else None
out["parent_is_dir"] = bool(p and p.parent.is_dir())
out["file_exists"] = bool(p and p.is_file())
try:
    cfg = json.loads(p.read_text(encoding="utf-8-sig"))
    out["motionlab_entry"] = (cfg.get("mcpServers") or {}).get("motionlab")
except Exception as exc:
    out["read_error"] = str(exc)

Path(__file__).with_name("debug_env_out.json").write_text(
    json.dumps(out, indent=2), encoding="utf-8"
)
