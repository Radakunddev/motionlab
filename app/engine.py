"""MotionLab engine client.

Talks to a headless ComfyUI instance over HTTP + WebSocket, tracks render jobs,
and finalizes output files (move to library, poster frame, metadata sidecar).
"""

import copy
import json
import logging
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

log = logging.getLogger("motionlab.engine")

STAGE_BY_CLASS = {
    "UnetLoaderGGUF": "Loading video model",
    "UNETLoader": "Loading image model",
    "DualCLIPLoaderGGUF": "Loading text encoder",
    "CLIPLoaderGGUF": "Loading text encoder",
    "CLIPLoader": "Loading text encoder",
    "SaveImage": "Saving image",
    "VAELoader": "Loading VAE",
    "LTXVAudioVAELoader": "Loading audio VAE",
    "LatentUpscaleModelLoader": "Loading upscaler",
    "CLIPTextEncode": "Encoding prompt",
    "SamplerCustomAdvanced": "Rendering",
    "SamplerCustom": "Rendering",
    "KSampler": "Rendering",
    "LTXVLatentUpsampler": "Upscaling",
    "VAEDecode": "Decoding frames",
    "VAEDecodeTiled": "Decoding frames",
    "LTXVAudioVAEDecode": "Decoding audio",
    "CreateVideo": "Writing video",
    "SaveVideo": "Writing video",
}

STAGE_BY_TITLE = {
    "@SAMPLE_BASE": "Rendering pass 1/2",
    "@SAMPLE_REFINE": "Rendering pass 2/2",
    "@SAMPLE_IMG": "Rendering",
}

SAMPLER_CLASSES = {"SamplerCustomAdvanced", "SamplerCustom", "KSampler"}


def _now_ms():
    return int(time.time() * 1000)


class ComfyClient:
    def __init__(self, host, port, comfy_output_dir, library_dir):
        self.base = f"http://{host}:{port}"
        self.ws_url = f"ws://{host}:{port}/ws"
        self.client_id = uuid.uuid4().hex
        self.comfy_output_dir = Path(comfy_output_dir)
        self.library_dir = Path(library_dir)
        self.library_dir.mkdir(parents=True, exist_ok=True)

        self.lock = threading.RLock()
        self.jobs = {}            # job_id -> job dict (shared with UI via get_state)
        self.order = []           # job ids, submit order
        self.by_prompt = {}       # comfy prompt_id -> job_id
        self._graphs = {}         # job_id -> submitted graph (for stage lookup)
        self._ws_started = False

    # ----------------------------------------------------------------- HTTP

    def _http(self, method, path, payload=None, timeout=20):
        url = self.base + path
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:800]
            raise RuntimeError(f"Engine HTTP {exc.code} on {path}: {detail}") from exc
        if not body:
            return None
        try:
            return json.loads(body)
        except ValueError:
            return None

    def is_up(self):
        try:
            self._http("GET", "/system_stats", timeout=4)
            return True
        except Exception:
            return False

    def system_stats(self):
        try:
            return self._http("GET", "/system_stats", timeout=4)
        except Exception:
            return None

    def queue_counts(self):
        try:
            q = self._http("GET", "/queue", timeout=4) or {}
            return len(q.get("queue_running", [])), len(q.get("queue_pending", []))
        except Exception:
            return 0, 0

    # ------------------------------------------------------------------- WS

    def ensure_ws(self):
        with self.lock:
            if self._ws_started:
                return
            self._ws_started = True
        t = threading.Thread(target=self._ws_loop, name="comfy-ws", daemon=True)
        t.start()

    def _ws_loop(self):
        import websocket  # websocket-client

        url = f"{self.ws_url}?clientId={self.client_id}"
        while True:
            try:
                ws = websocket.WebSocketApp(url, on_message=self._on_ws_message)
                ws.run_forever(ping_interval=25, ping_timeout=10)
            except Exception as exc:
                log.warning("ws loop error: %s", exc)
            time.sleep(3)

    def _on_ws_message(self, _ws, message):
        if isinstance(message, (bytes, bytearray)):
            return  # binary preview frames, not needed
        try:
            msg = json.loads(message)
        except ValueError:
            return
        mtype = msg.get("type")
        data = msg.get("data") or {}
        prompt_id = data.get("prompt_id")
        job = self._job_for(prompt_id)

        if mtype == "executing":
            if job is None:
                return
            node = data.get("node")
            with self.lock:
                if node is None:
                    return  # end of graph, execution_success handles it
                job["status"] = "running"
                if job.get("started") is None:
                    job["started"] = _now_ms()
                cls, title = self._node_info(job["id"], node)
                stage = STAGE_BY_TITLE.get(title) or STAGE_BY_CLASS.get(cls)
                if stage:
                    job["stage"] = stage
                if cls not in SAMPLER_CLASSES:
                    job["step"] = None
                    job["steps"] = None
        elif mtype == "progress":
            if job is None:
                return
            with self.lock:
                node = data.get("node")
                cls, title = self._node_info(job["id"], node) if node else (None, None)
                job["status"] = "running"
                if job.get("started") is None:
                    job["started"] = _now_ms()
                if cls in SAMPLER_CLASSES or cls is None:
                    job["step"] = data.get("value")
                    job["steps"] = data.get("max")
                    if cls in SAMPLER_CLASSES:
                        job["stage"] = STAGE_BY_TITLE.get(title, "Rendering")
        elif mtype == "executed":
            if job is None:
                return
            out = data.get("output") or {}
            files = []
            for key in ("video", "images", "gifs", "audio"):
                for item in out.get(key) or []:
                    if isinstance(item, dict) and item.get("filename"):
                        files.append(item)
            if files:
                with self.lock:
                    job.setdefault("_files", []).extend(files)
        elif mtype == "execution_error":
            if job is None:
                return
            detail = data.get("exception_message") or "Unknown engine error"
            ntype = data.get("node_type")
            with self.lock:
                job["status"] = "error"
                job["error"] = f"{ntype}: {detail}" if ntype else detail
                job["finished"] = _now_ms()
            log.error("job %s failed: %s", job["id"], job["error"])
        elif mtype == "execution_interrupted":
            if job is None:
                return
            with self.lock:
                job["status"] = "cancelled"
                job["finished"] = _now_ms()
        elif mtype == "execution_success":
            if job is None:
                return
            threading.Thread(target=self._finalize, args=(job["id"],), daemon=True).start()

    def _job_for(self, prompt_id):
        if not prompt_id:
            return None
        with self.lock:
            jid = self.by_prompt.get(prompt_id)
            return self.jobs.get(jid) if jid else None

    def _node_info(self, job_id, node_id):
        graph = self._graphs.get(job_id) or {}
        node = graph.get(str(node_id)) or {}
        return node.get("class_type"), (node.get("_meta") or {}).get("title")

    # ---------------------------------------------------------------- submit

    def submit(self, graph, params):
        """Queue a filled graph. Returns the job dict."""
        job_id = uuid.uuid4().hex[:12]
        payload = {"prompt": graph, "client_id": self.client_id}
        res = self._http("POST", "/prompt", payload, timeout=30)
        if not res or "prompt_id" not in res:
            raise RuntimeError(f"Engine rejected the job: {res!r}")
        prompt_id = res["prompt_id"]
        job = {
            "id": job_id,
            "prompt_id": prompt_id,
            "status": "queued",
            "stage": "Queued",
            "step": None,
            "steps": None,
            "params": params,
            "prompt": params.get("prompt", ""),
            "created": _now_ms(),
            "started": None,
            "finished": None,
            "output": None,
            "error": None,
        }
        with self.lock:
            self.jobs[job_id] = job
            self.order.append(job_id)
            self.by_prompt[prompt_id] = job_id
            self._graphs[job_id] = graph
        self.ensure_ws()
        log.info("job %s queued (prompt_id %s)", job_id, prompt_id)
        return job

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        if not job:
            return False
        if job["status"] == "running":
            try:
                self._http("POST", "/interrupt", {"client_id": self.client_id})
                return True
            except Exception as exc:
                log.warning("interrupt failed: %s", exc)
                return False
        if job["status"] == "queued":
            try:
                self._http("POST", "/queue", {"delete": [job["prompt_id"]]})
                with self.lock:
                    job["status"] = "cancelled"
                    job["finished"] = _now_ms()
                return True
            except Exception as exc:
                log.warning("queue delete failed: %s", exc)
                return False
        return False

    # -------------------------------------------------------------- finalize

    def _finalize(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job["status"] in ("done", "error"):
                return
            files = list(job.get("_files") or [])

        is_image = (job["params"] or {}).get("mode") == "image"
        wanted = (".png", ".jpg", ".jpeg", ".webp") if is_image else (".mp4", ".webm", ".mov", ".mkv")
        picked = None
        for item in files:
            if item.get("filename", "").lower().endswith(wanted):
                picked = item
                break
        if picked is None and files:
            picked = files[0]

        if picked is None:
            with self.lock:
                job["status"] = "error"
                job["error"] = "Render finished but no output file was produced."
                job["finished"] = _now_ms()
            return

        src = self.comfy_output_dir
        if picked.get("subfolder"):
            src = src / picked["subfolder"]
        src = src / picked["filename"]

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = "".join(
            c if c.isalnum() else "-" for c in job["prompt"][:42].strip().lower()
        ).strip("-") or "clip"
        while "--" in slug:
            slug = slug.replace("--", "-")
        ext = src.suffix or (".png" if is_image else ".mp4")
        dest = self.library_dir / f"{stamp}_{slug}{ext}"
        if dest.exists():
            dest = self.library_dir / f"{stamp}_{slug}_{job_id[:4]}{ext}"

        try:
            for _ in range(20):  # wait briefly if the file is still being flushed
                if src.exists() and src.stat().st_size > 0:
                    break
                time.sleep(0.5)
            shutil.move(str(src), str(dest))
        except Exception as exc:
            log.error("could not move %s: %s", src, exc)
            with self.lock:
                job["status"] = "error"
                job["error"] = f"Video was rendered but could not be moved: {exc}"
                job["finished"] = _now_ms()
            return

        poster = None if is_image else self._make_poster(dest)
        meta = {
            "file": dest.name,
            "type": "image" if is_image else "video",
            "poster": poster.name if poster else None,
            "prompt": job["prompt"],
            "params": job["params"],
            "created": _now_ms(),
            "render_ms": (_now_ms() - job["started"]) if job.get("started") else None,
            "model": "Ideogram 4 (fp8)" if is_image else "LTX-2.3 22B distilled (GGUF)",
        }
        try:
            dest.with_suffix(".json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.warning("sidecar write failed: %s", exc)

        with self.lock:
            job["status"] = "done"
            job["stage"] = "Done"
            job["output"] = dest.name
            job["finished"] = _now_ms()
        log.info("job %s done -> %s", job_id, dest.name)

    def _make_poster(self, video_path):
        try:
            import av

            with av.open(str(video_path)) as container:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                for frame in container.decode(stream):
                    img = frame.to_image()
                    poster = video_path.with_suffix(".jpg")
                    img.save(str(poster), "JPEG", quality=88)
                    return poster
        except Exception as exc:
            log.warning("poster failed for %s: %s", video_path.name, exc)
        return None

    # ---------------------------------------------------------------- state

    def active_jobs(self):
        with self.lock:
            out = []
            for jid in reversed(self.order):
                j = dict(self.jobs[jid])
                j.pop("_files", None)
                out.append(j)
            return out


class WorkflowBuilder:
    """Fills the workflow template (ComfyUI API format) with user parameters.

    Template nodes carry _meta.title markers like "@PROMPT" so node ids stay free.
    """

    def __init__(self, template_path, comfy_input_dir=None):
        self.template_path = Path(template_path)
        self.comfy_input_dir = Path(comfy_input_dir) if comfy_input_dir else None
        self._template = None
        self._mtime = None

    PLACEHOLDER = "mlab_placeholder.png"

    def _ensure_placeholder(self):
        if self.comfy_input_dir is None:
            return
        target = self.comfy_input_dir / self.PLACEHOLDER
        if target.exists():
            return
        self.comfy_input_dir.mkdir(parents=True, exist_ok=True)
        from PIL import Image

        Image.new("RGB", (64, 64), (19, 20, 16)).save(str(target), "PNG")

    def _stage_image(self, image_path, job_tag):
        """Copy the user's image into ComfyUI's input folder, return its name."""
        if self.comfy_input_dir is None:
            raise RuntimeError("WorkflowBuilder needs comfy_input_dir for image input.")
        src = Path(image_path)
        if not src.is_file():
            raise RuntimeError(f"Input image not found: {src}")
        suffix = src.suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            raise RuntimeError(f"Unsupported image type: {suffix}")
        name = f"mlab_in_{job_tag}{suffix}"
        self.comfy_input_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(self.comfy_input_dir / name))
        return name

    def _load(self):
        mtime = self.template_path.stat().st_mtime
        if self._template is None or mtime != self._mtime:
            self._template = json.loads(self.template_path.read_text(encoding="utf-8"))
            self._mtime = mtime
        return self._template

    def _by_title(self, graph, title):
        for node in graph.values():
            if (node.get("_meta") or {}).get("title") == title:
                return node
        return None

    def build(self, params, job_tag):
        """Two-stage graph per the official LTX-2.3 t2v template: the base pass
        renders at half resolution, the spatial upsampler doubles it, and a
        short second pass refines. @LATENT therefore gets half the target size.
        """
        graph = copy.deepcopy(self._load())
        fps = float(params.get("fps", 25))
        seconds = float(params.get("seconds", 4))
        frames = max(1, round(seconds * fps / 8.0)) * 8 + 1
        real_seconds = frames / fps
        width = int(params["width"])
        height = int(params["height"])
        base_w = max(64, (width // 2) // 32 * 32)
        base_h = max(64, (height // 2) // 32 * 32)
        seed = int(params["seed"])

        def set_input(title, key, value, required=True):
            node = self._by_title(graph, title)
            if node is None:
                if required:
                    raise RuntimeError(f"Workflow template is missing node {title}")
                return
            node["inputs"][key] = value

        image_path = params.get("image_path")
        if image_path:
            name = self._stage_image(image_path, job_tag)
            set_input("@INPUT_IMAGE", "image", name)
            set_input("@I2V_1", "bypass", False)
            set_input("@I2V_2", "bypass", False)
        else:
            self._ensure_placeholder()
            set_input("@INPUT_IMAGE", "image", self.PLACEHOLDER, required=False)
            set_input("@I2V_1", "bypass", True, required=False)
            set_input("@I2V_2", "bypass", True, required=False)

        set_input("@PROMPT", "text", params["prompt"])
        set_input("@NEGATIVE", "text", params.get("negative", ""), required=False)
        set_input("@LATENT", "width", base_w)
        set_input("@LATENT", "height", base_h)
        set_input("@LATENT", "length", int(frames))
        set_input("@AUDIO_LATENT", "frames_number", int(frames))
        set_input("@AUDIO_LATENT", "frame_rate", int(fps))
        set_input("@CONDITIONING", "frame_rate", fps)
        set_input("@SEED", "noise_seed", seed)
        set_input("@SEED2", "noise_seed", (seed + 1) % (2**32), required=False)
        set_input("@CREATE_VIDEO", "fps", fps)
        set_input("@SAVE", "filename_prefix", f"motionlab/{job_tag}")

        if params.get("quality") == "ultra" or seconds >= 8:
            # 1080p frames and long clips do not fit through the one-shot VAE
            # decode; tile spatially and temporally.
            node = self._by_title(graph, "@DECODE_VIDEO")
            node["class_type"] = "VAEDecodeTiled"
            node["inputs"].update(
                {"tile_size": 512, "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}
            )
        return graph, frames, real_seconds

    def build_image(self, params, job_tag):
        """Ideogram 4 text-to-image graph (Flux2 latent, 16 px grid).

        CFG runs on two models per the official template: the conditional DiT
        plus Ideogram's dedicated unconditional DiT (DualModelGuider, no
        negative connected = image-only unconditional pass).
        """
        graph = copy.deepcopy(self._load())
        width = int(params["width"])
        height = int(params["height"])
        steps = int(params.get("steps", 20))
        seed = int(params["seed"])

        def set_input(title, key, value, required=True):
            node = self._by_title(graph, title)
            if node is None:
                if required:
                    raise RuntimeError(f"Workflow template is missing node {title}")
                return
            node["inputs"][key] = value

        # The official workflow encodes the user's text as-is (plain language or
        # a structured JSON caption). Its 28k-char "caption prompt template" is
        # only a copy-paste helper for external LLMs, never encoder input.
        set_input("@PROMPT", "text", params["prompt"])
        set_input("@NEGATIVE", "text", params.get("negative", ""), required=False)
        set_input("@LATENT", "width", width)
        set_input("@LATENT", "height", height)
        set_input("@SCHED", "steps", steps)
        set_input("@SCHED", "width", width)
        set_input("@SCHED", "height", height)
        if params.get("mu") is not None:
            set_input("@SCHED", "mu", float(params["mu"]))
        if params.get("std") is not None:
            set_input("@SCHED", "std", float(params["std"]))
        set_input("@SEED", "noise_seed", seed)
        set_input("@SAVE", "filename_prefix", f"motionlab/{job_tag}")

        # Fall back to single-model CFG while the unconditional checkpoint is
        # still downloading (or was removed): drop the second UNETLoader link.
        neutral_model = ["16", 0]
        uncond_node = self._by_title(graph, "@UNET_UNCOND")
        if uncond_node is not None and self.comfy_input_dir is not None:
            uncond_file = (
                Path(self.comfy_input_dir).parent
                / "models" / "diffusion_models"
                / uncond_node["inputs"]["unet_name"]
            )
            if not uncond_file.is_file():
                guider = self._by_title(graph, "@GUIDER")
                guider["inputs"].pop("model_negative", None)
                for nid, node in list(graph.items()):
                    if (node.get("_meta") or {}).get("title") == "@UNET_UNCOND":
                        del graph[nid]
                neutral_model = ["1", 0]

        # Filter bypass, always on: the model's baked-in safety filter false-
        # positives on most prompts (even Ideogram's own README example). The
        # first 2 steps run a neutral guider (no text), so the refusal
        # attractor never forms; the prompt drives the remaining steps.
        graph["50"] = {
            "class_type": "SplitSigmas",
            "_meta": {"title": "@SPLIT"},
            "inputs": {"sigmas": ["13", 0], "step": 2},
        }
        graph["51"] = {
            "class_type": "BasicGuider",
            "_meta": {"title": "@NEUTRAL_GUIDER"},
            "inputs": {"model": neutral_model, "conditioning": ["18", 0]},
        }
        graph["52"] = {
            "class_type": "SamplerCustomAdvanced",
            "_meta": {"title": "@SAMPLE_NEUTRAL"},
            "inputs": {
                "noise": ["11", 0],
                "guider": ["51", 0],
                "sampler": ["12", 0],
                "sigmas": ["50", 0],
                "latent_image": ["8", 0],
            },
        }
        graph["53"] = {"class_type": "DisableNoise", "_meta": {"title": "@NONOISE"}, "inputs": {}}
        sampler = self._by_title(graph, "@SAMPLE_IMG")
        sampler["inputs"]["noise"] = ["53", 0]
        sampler["inputs"]["sigmas"] = ["50", 1]
        sampler["inputs"]["latent_image"] = ["52", 0]

        refs = list(params.get("ref_images") or [])[:3]
        if refs:
            # Experimental: reference images ride in as Qwen3-VL vision tokens
            # (the official Ideogram 4 release documents text-to-image only).
            # MotionLabRefEncode = higher-res VL pass + style-preserving template.
            prompt_node = self._by_title(graph, "@PROMPT")
            clip_link = prompt_node["inputs"]["clip"]
            new_inputs = {"clip": clip_link, "prompt": params["prompt"], "vl_size": 512}
            for i, ref_path in enumerate(refs, start=1):
                name = self._stage_image(ref_path, f"{job_tag}_r{i}")
                node_id = f"4{i}"
                graph[node_id] = {
                    "class_type": "LoadImage",
                    "_meta": {"title": f"@REF{i}"},
                    "inputs": {"image": name},
                }
                new_inputs[f"image{i}"] = [node_id, 0]
            prompt_node["class_type"] = "MotionLabRefEncode"
            prompt_node["inputs"] = new_inputs
        return graph
