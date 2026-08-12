"""MotionLab self-updater.

Checks a manifest URL (GitHub raw/release) for a newer app-layer version,
downloads and verifies the release zip, and stages it. The launcher
(MotionLab.bat) applies the staged payload on the next start, before Python
boots, so no running file is ever overwritten.

Manifest format (JSON):
{
  "version": "1.1.0",
  "zip_url": "https://github.com/<user>/motionlab/releases/download/v1.1.0/motionlab-app-1.1.0.zip",
  "sha256": "<hex digest of the zip>",
  "notes": "short changelog line shown in the app"
}

The zip contains the app layer only, rooted like the install dir
(app/..., VERSION, README.md). Engine and models are never auto-updated.
"""

import hashlib
import json
import logging
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("motionlab.updater")

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
STAGING = ROOT / "update_staging"

state = {
    "available": None,   # version string when an update is staged
    "notes": "",
    "error": None,
    "checked": 0,
}


def _local_version():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


def _ver_tuple(v):
    parts = []
    for piece in str(v).strip().lstrip("v").split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _config():
    try:
        cfg = json.loads((APP_DIR / "update_config.json").read_text(encoding="utf-8"))
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "MotionLab-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check_once():
    """One update check. Quiet on any failure (offline is normal)."""
    cfg = _config()
    url = (cfg.get("manifest_url") or "").strip()
    state["checked"] = int(time.time())
    if not url:
        return
    try:
        manifest = json.loads(_fetch(url).decode("utf-8-sig"))
        remote = str(manifest.get("version", ""))
        if _ver_tuple(remote) <= _ver_tuple(_local_version()):
            return
        ready = STAGING / "READY"
        if ready.is_file() and ready.read_text(encoding="utf-8").strip() == remote:
            state["available"] = remote
            state["notes"] = str(manifest.get("notes", ""))
            return  # already staged

        zip_url = manifest["zip_url"]
        want_sha = str(manifest.get("sha256", "")).lower()
        log.info("update %s found, downloading %s", remote, zip_url)
        blob = _fetch(zip_url, timeout=300)
        if want_sha:
            got = hashlib.sha256(blob).hexdigest().lower()
            if got != want_sha:
                raise ValueError(f"sha256 mismatch: expected {want_sha[:12]}.., got {got[:12]}..")

        STAGING.mkdir(parents=True, exist_ok=True)
        zpath = STAGING / "update.zip"
        zpath.write_bytes(blob)
        payload = STAGING / "payload"
        if payload.exists():
            import shutil

            shutil.rmtree(payload)
        payload.mkdir(parents=True)
        with zipfile.ZipFile(zpath) as zf:
            base = payload.resolve()
            for member in zf.namelist():
                target = (payload / member).resolve()
                if not str(target).startswith(str(base)):
                    raise ValueError(f"unsafe path in update zip: {member}")
            zf.extractall(payload)
        ready.write_text(remote, encoding="utf-8")
        state["available"] = remote
        state["notes"] = str(manifest.get("notes", ""))
        state["error"] = None
        log.info("update %s staged", remote)
    except Exception as exc:
        state["error"] = str(exc)
        log.warning("update check failed: %s", exc)


def start_background_checks():
    cfg = _config()
    hours = float(cfg.get("check_interval_hours", 6) or 6)

    def loop():
        time.sleep(8)  # let the app settle first
        while True:
            check_once()
            time.sleep(max(1.0, hours) * 3600)

    threading.Thread(target=loop, name="updater", daemon=True).start()
