# MotionLab

## Product purpose
Local, offline desktop studio for open-weight video models. v1 runs Lightricks LTX-2.3 (22B distilled, GGUF quant) through a headless ComfyUI engine on the user's own GPU. Type a prompt, get a video with synchronized audio. No accounts, no API keys, no cloud, no cost per generation.

## Users
A single creator on a Windows laptop (RTX 4060, 8 GB VRAM). Comfortable with creative tools (Higgsfield, Runway), not with Python or node graphs. Uses it in the evening, generates a handful of clips per session, waits minutes per render. The app must make long local renders feel calm and legible, not broken.

## Register
product

## Brand and tone
Reference point named by the user: Higgsfield. Deep near-black surface, one acid-lime accent, confident type, video-first. Tone in copy: short, direct, a little dry. English UI. No hype words, no exclamation marks.

## Anti-references
- "AI slop" neon dashboards: glow on everything, gradient text, glass cards everywhere.
- ComfyUI's own graph aesthetic: the entire point is hiding the graph.
- Generic SaaS cream/indigo landing look.

## Strategic principles
1. The prompt composer is the product. One obvious action per screen state.
2. Renders are slow on this hardware: progress must always be truthful (real steps, real stage names, elapsed time), never a fake spinner.
3. Everything the app generates lives in plain files the user can open in Explorer.
4. The engine (ComfyUI + model) is invisible plumbing. Its state is one status pill, never a wall of logs, and logs stay one click away.
