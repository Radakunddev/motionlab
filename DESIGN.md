# MotionLab design system

Desktop-only (pywebview / WebView2 window, min 1100x760). Self-contained: no CDN, no webfonts, system font stack. Dark theme only, earned by content: video frames are the hero and read best on near-black; evening use.

## Color (OKLCH, hue anchored at 125 lime)

Strategy: Restrained surface, Committed accent. Lime carries the primary action, live progress, selection and focus. Nothing else is lime. No pure #000/#fff; every neutral is tinted toward hue 125.

- `--bg`        oklch(0.147 0.006 125)  page
- `--bg-raise`  oklch(0.183 0.007 125)  composer, cards, viewer
- `--bg-sunken` oklch(0.128 0.005 125)  wells, thumbnails backdrop
- `--bg-hover`  oklch(0.22 0.008 125)   hover fills
- `--line`      oklch(0.31 0.01 125 / 0.55)  hairlines
- `--line-soft` oklch(0.31 0.01 125 / 0.28)
- `--text`      oklch(0.955 0.007 120)
- `--text-2`    oklch(0.74 0.012 120)
- `--text-3`    oklch(0.56 0.012 120)
- `--accent`    oklch(0.915 0.235 127)  acid lime
- `--accent-press` oklch(0.86 0.225 127)
- `--on-accent` oklch(0.19 0.03 127)
- `--danger`    oklch(0.7 0.19 27)
- `--warn`      oklch(0.82 0.16 85)

## Typography

Single family: `"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif`. Wordmark and buttons use the same family, heavier weights, not a display font.
Fixed rem scale, ratio ~1.2: 12 / 13.5 (base) / 16 / 19 / 23 / 28. Prompt textarea 17/1.5. Numbers in progress and metadata use `font-variant-numeric: tabular-nums`.
Wordmark: 13px, weight 800, letter-spacing 0.14em, uppercase: MOTION**LAB** (LAB in lime is the only decorative lime exception, 3 characters).

## Spacing and layout

8px base grid; section rhythm varies: topbar 56px; composer padding 24; composer-to-library gap 40; grid gap 14. Content column max 1060px centered. Top bar full-bleed with hairline. No sidebar in v1.

## Components

- Buttons: radius 10px, height 40 (primary) / 32 (secondary/ghost). Primary = lime fill, on-accent text, weight 700. States: hover raises lightness 3%, active presses, disabled = 40% desaturated + no shadow, loading = inline 14px spinner replacing icon only.
- Chips (aspect, duration, quality): radius 999, height 30, hairline border; selected = lime text + lime border + 8% lime tint fill, not full lime.
- Inputs/textarea: transparent fill on `--bg-raise`, hairline border, focus = 1.5px lime ring outside, no glow.
- Cards: single-level, radius 14px, hairline border, no shadow stack, never nested.
- Progress: 3px track bar in lime + stage label + `step k/8` + elapsed mm:ss, all tabular.
- Toasts: bottom right, `--bg-raise`, hairline, auto-dismiss 6s, error persists.
- Video cards: thumbnail poster, duration badge (11px, tabular) bottom-right, hover = play preview muted, focus-visible ring lime. Click opens overlay viewer (native video controls, metadata line, actions: Reuse prompt, Show in folder, Delete).

## Motion

150-250ms, `cubic-bezier(0.22, 1, 0.36, 1)` (ease-out-quint-ish). Motion only for state: chip select, card enter (120ms fade/2px rise), progress bar width, toast slide. Render-in-progress shimmer on the placeholder card is the one ambient animation, and it stops when done. `prefers-reduced-motion`: all transitions to 0, shimmer replaced by static stripe.

## Voice

Labels: "Generate", "Rendering", "Queued", "Engine warming up", "Show in folder", "Reuse prompt". Errors say what happened + one next step. No em dashes anywhere.
