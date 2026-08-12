# Driving MotionLab (for Claude)

MotionLab root: `C:\Users\User\motionlab`. Renders run on the local GPU and take minutes:
queue, then poll. Two transports; use B when localhost HTTP is unreachable
(sandboxed shells).

## A. HTTP (when reachable)

Port: read `C:\Users\User\motionlab\logs\runtime.json` -> `ui_port`.
- `GET  /api/state` - engine phase + jobs (id, status, stage, step, output)
- `POST /api/generate` - body below; returns {"ok": true, "job": id, "seed": n}
- `POST /api/cancel` - {"job_id": "..."}
- `GET  /api/library` - recent outputs

## B. File bridge (always works with folder access)

- Write params as JSON to `C:\Users\User\motionlab\inbox\job_<timestamp>.json`
- Within ~3 s the app writes `job_<timestamp>.result.json` next to it
  ({"ok": true, "job": id} or an error)
- Poll `C:\Users\User\motionlab\inbox\state.json` (rewritten every 3 s) for engine phase and
  job progress; wait for your job id to reach status "done"
- Cancel: write {"cancel": "<job_id>"} as a new job file
- If the app is not running (state.json stale): start it with
  `cmd /c start "" "C:\Users\User\motionlab\MotionLab.bat"` and wait 1-2 minutes.

## Generate bodies

Video (LTX-2, audio included):
{"prompt": "...", "seconds": 4, "aspect": "16:9", "quality": "fast", "seed": "random", "image_path": ""}
- seconds 2-12; aspect 16:9|9:16|1:1; quality fast|balanced|high|ultra
- image_path: absolute path -> image-to-video
Image (Ideogram 4, posters/text):
{"mode": "image", "prompt": "...", "aspect": "1:1", "img_size": "std", "seed": "random", "ref_images": []}
- aspect 1:1|16:9|9:16|4:3|3:4|3:2|2:3|21:9; img_size std|large|xl
Edit (Qwen-Image-Edit, keeps identity):
{"mode": "edit", "prompt": "the change", "image_path": "abs path", "ref_images": ["<= 2 abs paths"], "seed": "random"}

Finished files land in `C:\Users\User\motionlab\outputs\` (mp4/png + .json sidecar; videos
get a .jpg poster). Report the absolute path to the user. Memory rules the
API enforces itself: one render at a time, some duration/quality combos are
locked until the machine's pagefile is enlarged; surface its error messages.
