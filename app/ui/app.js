/* MotionLab frontend. Talks to Python through the pywebview bridge. */

"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  mode: "video",
  aspect: "16:9",
  imgAspect: "1:1",
  seconds: 4,
  headroom: false,
  engine: "offline",
  activeJob: null,
  clockSkew: 0,
  library: [],
  firstRenderSeen: localStorage.getItem("ml_first_render_done") === "1",
  viewerItem: null,
  imagePath: null,
  refImages: [],
  libFilter: "all",
  libQuery: "",
};

/* ------------------------------------------------------------ bridge */

function api() {
  if (window.pywebview && window.pywebview.api) return window.pywebview.api;
  return null;
}

async function call(method, ...args) {
  const a = api();
  if (!a) throw new Error("Bridge not ready");
  return a[method](...args);
}

/* ------------------------------------------------------------- toasts */

function toast(message, kind = "ok", sticky = false) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  el.title = "Click to dismiss";
  el.addEventListener("click", () => el.remove());
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), sticky ? 12000 : 6000);
}

/* -------------------------------------------------------------- chips */

function wireChips(groupEl, onPick) {
  groupEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    for (const c of groupEl.querySelectorAll(".chip")) {
      c.classList.toggle("selected", c === btn);
      c.setAttribute("aria-checked", c === btn ? "true" : "false");
    }
    onPick(btn.dataset.value);
  });
}

/* ------------------------------------------------------------- engine */

const ENGINE_LABEL = {
  offline: "Engine offline",
  starting: "Engine warming up",
  ready: "Engine ready",
  failed: "Engine failed",
};

function renderEngine(phase) {
  state.engine = phase;
  $("enginePill").dataset.phase = phase;
  $("engineLabel").textContent = ENGINE_LABEL[phase] || phase;
  if (phase === "failed" && !$("enginePill").dataset.wiredRetry) {
    $("enginePill").dataset.wiredRetry = "1";
    $("enginePill").style.cursor = "pointer";
    $("enginePill").title = "Click to retry, check logs\\engine.log if it keeps failing";
    $("enginePill").addEventListener("click", async () => {
      if (state.engine !== "failed") return;
      await call("retry_engine");
      toast("Restarting the engine.");
    });
  }
}

/* -------------------------------------------------------- render strip */

function fmtElapsed(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function renderQueue(queuedJobs) {
  const wrap = $("rsQueue");
  wrap.innerHTML = "";
  wrap.hidden = queuedJobs.length === 0;
  queuedJobs.forEach((j, i) => {
    const row = document.createElement("div");
    row.className = "rs-queue-row";
    row.innerHTML = `
      <span class="rs-queue-pos">${i + 1}</span>
      <span class="rs-queue-prompt">${escapeHtml(j.prompt || "")}</span>
      <button class="pill-x" title="Remove from queue" aria-label="Remove from queue">&#10005;</button>`;
    row.querySelector("button").addEventListener("click", async () => {
      await call("cancel", j.id);
      poll(true);
    });
    wrap.appendChild(row);
  });
}

function renderJob(job, queuedBehind) {
  const strip = $("renderStrip");
  if (!job) {
    strip.hidden = true;
    state.activeJob = null;
    setGenerating(false);
    renderQueue([]);
    return;
  }
  strip.hidden = false;
  state.activeJob = job;
  setGenerating(true);

  let stage = job.stage || "Queued";
  if (job.status === "queued") stage = "Queued";
  $("rsStage").textContent = stage;

  let detail = "";
  if (job.step && job.steps) detail = `step ${job.step}/${job.steps}`;
  if (queuedBehind > 0) detail += `${detail ? " · " : ""}${queuedBehind} more queued`;
  $("rsDetail").textContent = detail;

  const started = job.started || job.created;
  $("rsElapsed").textContent = fmtElapsed(Date.now() - state.clockSkew - started);

  const bar = $("rsBar");
  if (job.step && job.steps) {
    bar.classList.remove("indeterminate");
    bar.style.width = `${Math.round((job.step / job.steps) * 100)}%`;
  } else {
    bar.classList.add("indeterminate");
    bar.style.width = "30%";
  }
  $("rsNote").hidden = state.firstRenderSeen;
}

function setGenerating(active) {
  const btn = $("btnGenerate");
  btn.querySelector(".btn-label").textContent = active ? "Queue next" : "Generate";
}

/* ------------------------------------------------------------- library */

function fmtMeta(item) {
  const p = item.params || {};
  const parts = [];
  if (p.width && p.height) parts.push(`${p.width}x${p.height}`);
  if (p.real_seconds) parts.push(`${p.real_seconds}s`);
  if (p.seed !== undefined) parts.push(`seed ${p.seed}`);
  if (item.render_ms) parts.push(`rendered in ${fmtElapsed(item.render_ms)}`);
  if (item.size_mb) parts.push(`${item.size_mb} MB`);
  return parts.join(" · ");
}

function renderLibrary(items) {
  state.library = items;
  applyLibraryView();
}

function applyLibraryView() {
  const all = state.library || [];
  const q = (state.libQuery || "").trim().toLowerCase();
  const items = all.filter((it) => {
    const type = (it.type === "image" || it.type === "edit") ? "image" : "video";
    if (state.libFilter !== "all" && type !== state.libFilter) return false;
    if (q && !`${it.prompt || ""} ${it.file || ""}`.toLowerCase().includes(q)) return false;
    return true;
  });
  $("libCount").textContent = all.length
    ? (items.length === all.length ? `${all.length} clip${all.length > 1 ? "s" : ""}` : `${items.length} of ${all.length}`)
    : "";
  $("emptyState").hidden = all.length > 0;
  $("libNoMatch").hidden = !(all.length > 0 && items.length === 0);
  const grid = $("grid");
  grid.innerHTML = "";
  for (const item of items) {
    const card = document.createElement("button");
    card.className = "card";
    card.type = "button";
    if (item.type === "image" || item.type === "edit") {
      card.innerHTML = `
        <img class="thumb" src="${item.url}" alt="" loading="lazy">
        <span class="badge">${item.type === "edit" ? "EDIT" : "IMG"}</span>
        <p class="card-prompt">${escapeHtml(item.prompt || item.file)}</p>`;
    } else {
      const dur = (item.params && item.params.real_seconds) ? `${Math.round(item.params.real_seconds)}s` : "";
      card.innerHTML = `
        ${item.poster_url
          ? `<img class="thumb" src="${item.poster_url}" alt="" loading="lazy">`
          : `<video class="thumb" src="${item.url}" preload="metadata" muted playsinline></video>`}
        ${dur ? `<span class="badge">${dur}</span>` : ""}
        <p class="card-prompt">${escapeHtml(item.prompt || item.file)}</p>`;
      card.addEventListener("mouseenter", () => hoverPreview(card, item, true));
      card.addEventListener("mouseleave", () => hoverPreview(card, item, false));
    }
    card.addEventListener("click", () => openViewer(item));
    card.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      showCtxMenu(e.clientX, e.clientY, [
        { label: "Copy prompt", action: () => copyPrompt(item.prompt || "") },
        { label: "Show in folder", action: () => call("reveal", item.file) },
        { label: "Reuse prompt", action: () => reuseItem(item) },
        { label: "Delete", danger: true, action: () => deleteItem(item, false) },
      ]);
    });
    grid.appendChild(card);
  }
}

function hoverPreview(card, item, on) {
  let vid = card.querySelector("video.thumb");
  if (on) {
    if (!vid) {
      const img = card.querySelector("img.thumb");
      if (!img) return;
      vid = document.createElement("video");
      vid.className = "thumb";
      vid.src = item.url;
      vid.muted = true; vid.loop = true; vid.playsInline = true;
      vid.poster = item.poster_url || "";
      img.replaceWith(vid);
    }
    vid.play().catch(() => {});
  } else if (vid) {
    vid.pause();
    vid.currentTime = 0;
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* -------------------------------------------------------------- viewer */

function openViewer(item) {
  state.viewerItem = item;
  const isImage = item.type === "image" || item.type === "edit";
  $("viewerVideo").hidden = isImage;
  $("viewerImage").hidden = !isImage;
  if (isImage) {
    $("viewerImage").src = item.url;
  } else {
    $("viewerVideo").src = item.url;
  }
  $("viewerPrompt").textContent = item.prompt || "";
  $("viewerMeta").textContent = fmtMeta(item);
  $("viewer").hidden = false;
  if (!isImage) $("viewerVideo").play().catch(() => {});
}

function closeViewer() {
  $("viewer").hidden = true;
  $("viewerVideo").pause();
  $("viewerVideo").removeAttribute("src");
  $("viewerVideo").load();
  $("viewerImage").removeAttribute("src");
  state.viewerItem = null;
}

/* ------------------------------------------------------------ generate */

async function generate() {
  $("toasts").innerHTML = "";  // stale toasts confuse more than they help
  const prompt = $("prompt").value.trim();
  if (!prompt) {
    toast("Write a prompt first.", "error");
    $("prompt").focus();
    return;
  }
  if (state.engine !== "ready") {
    toast(state.engine === "failed"
      ? "Engine failed to start. Click the status pill to retry."
      : "Engine is still warming up. It will be ready shortly.", "error");
    return;
  }
  const params = state.mode === "image"
    ? {
        mode: "image",
        prompt,
        aspect: state.imgAspect,
        img_size: $("imgSize").value,
        seed: $("seed").value.trim() || "random",
        ref_images: state.refImages.map((r) => r.path),
      }
    : state.mode === "edit"
    ? {
        mode: "edit",
        prompt,
        image_path: state.imagePath || "",
        ref_images: state.refImages.map((r) => r.path),
        seed: $("seed").value.trim() || "random",
      }
    : {
        prompt,
        aspect: state.aspect,
        seconds: state.seconds,
        quality: $("quality").value,
        seed: $("seed").value.trim() || "random",
        image_path: state.imagePath || "",
      };
  if (state.mode === "edit" && !state.imagePath) {
    toast("Pick the image to edit first (Image button).", "error");
    $("btnGenerate").disabled = false;
    return;
  }
  const btn = $("btnGenerate");
  btn.disabled = true;
  try {
    const res = await call("generate", params);
    if (!res.ok) {
      toast(res.error || "Could not start the render.", "error", true);
    } else {
      toast(`Render queued. Seed ${res.seed}.`);
    }
  } catch (err) {
    toast(String(err), "error", true);
  } finally {
    btn.disabled = false;
  }
  poll(true);
}

/* ---------------------------------------------------------------- poll */

let lastJobStatus = new Map();
let libraryDirty = true;

async function poll(fast = false) {
  if (!api()) return;
  let s;
  try {
    s = await call("get_state");
  } catch {
    return;
  }
  state.clockSkew = Date.now() - s.now;
  renderEngine(s.engine);

  if (s.headroom !== state.headroom) {
    state.headroom = !!s.headroom;
    refreshDurations();
  }

  if (s.mcp_url !== state.mcpUrl) {
    state.mcpUrl = s.mcp_url || null;
  }

  if (s.update && s.update.version && !state.updateNotified) {
    state.updateNotified = true;
    toast(`Update ${s.update.version} is ready${s.update.notes ? `: ${s.update.notes}` : ""}. It installs on the next app start.`, "ok", true);
  }

  const jobs = s.jobs || [];
  const active = jobs.find((j) => j.status === "running") || jobs.find((j) => j.status === "queued");
  const waiting = jobs.filter((j) => j.status === "queued" && j !== active);
  renderJob(active || null, waiting.length);
  renderQueue(waiting.slice().reverse());  // jobs arrive newest-first; queue reads oldest-first

  for (const j of jobs) {
    const prev = lastJobStatus.get(j.id);
    if (prev !== j.status) {
      lastJobStatus.set(j.id, j.status);
      if (j.status === "done") {
        state.firstRenderSeen = true;
        localStorage.setItem("ml_first_render_done", "1");
        toast("Clip ready.");
        libraryDirty = true;
      } else if (j.status === "error") {
        toast(`Render failed: ${j.error || "unknown error"}`, "error", true);
      } else if (j.status === "cancelled") {
        toast("Render cancelled.");
      }
    }
  }

  if (libraryDirty) {
    libraryDirty = false;
    try { renderLibrary(await call("library")); } catch { libraryDirty = true; }
  }
}

/* ----------------------------------------------------------------- init */

function allowedSeconds(quality, headroom) {
  if (quality === "ultra") return [2, 4];
  if (quality === "high") return headroom ? [2, 4, 6, 8, 10, 12] : [2, 4, 6];
  return headroom ? [2, 4, 6, 8, 10, 12] : [2, 4, 6, 8];
}

function refreshDurations() {
  const allowed = allowedSeconds($("quality").value, state.headroom);
  for (const c of $("durationGroup").querySelectorAll(".chip")) {
    c.hidden = !allowed.includes(Number(c.dataset.value));
  }
  if (!allowed.includes(state.seconds)) {
    pickChip($("durationGroup"), String(allowed[allowed.length - 1]));
  }
}

/* --------------------------------------------------------- context menu */

function hideCtxMenu() {
  $("ctxMenu").hidden = true;
}

function showCtxMenu(x, y, entries) {
  const menu = $("ctxMenu");
  menu.innerHTML = "";
  for (const e of entries) {
    const b = document.createElement("button");
    b.className = `ctx-item${e.danger ? " danger" : ""}`;
    b.textContent = e.label;
    b.addEventListener("click", () => { hideCtxMenu(); e.action(); });
    menu.appendChild(b);
  }
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  menu.hidden = false;
  const pad = 8;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(x, window.innerWidth - rect.width - pad)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - rect.height - pad)}px`;
}

async function copyPrompt(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Prompt copied.");
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    toast("Prompt copied.");
  }
}

function reuseItem(it) {
  $("prompt").value = it.prompt || "";
  pickChip($("modeGroup"), it.type === "image" ? "image" : "video");
  if (it.params) {
    if (it.params.seed !== undefined) $("seed").value = it.params.seed;
    if (it.type === "image") {
      pickChip($("imgAspectGroup"), it.params.aspect);
      if (it.params.img_size) $("imgSize").value = it.params.img_size;
    } else {
      pickChip($("aspectGroup"), it.params.aspect);
      if (it.params.quality) $("quality").value = it.params.quality;
      refreshDurations();
      pickChip($("durationGroup"), String(Math.round(it.params.seconds || 4)));
    }
  }
  if (!$("viewer").hidden) closeViewer();
  $("prompt").focus();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function deleteItem(item, fromViewer) {
  if (!window.confirm("Delete this from disk?")) return;
  call("delete_item", item.file).then((res) => {
    if (res.ok) {
      toast("Deleted.");
      if (fromViewer) closeViewer();
      libraryDirty = true;
      poll(true);
    } else {
      toast(res.error || "Could not delete the file.", "error");
    }
  });
}

const REF_CAP = { image: 3, edit: 2 };

function setMode(mode) {
  state.mode = mode;
  const image = mode === "image";
  const edit = mode === "edit";
  $("durationGroup").hidden = image || edit;
  $("qualityWrap").hidden = image || edit;
  $("imgSizeWrap").hidden = !image;
  $("aspectGroup").hidden = image || edit;
  $("imgAspectGroup").hidden = !image;
  $("btnImageLabel").textContent = image ? "References" : "Image";
  $("btnImage").title = image
    ? "Add up to 3 reference images (experimental)"
    : edit
      ? "Pick the image to edit, then up to 2 references (e.g. a character)"
      : "Animate a starting image (image to video)";
  const cap = REF_CAP[mode] || 0;
  $("btnImage").hidden = image ? state.refImages.length >= cap
    : edit ? (!!state.imagePath && state.refImages.length >= cap)
    : !!state.imagePath;
  $("imagePill").hidden = image || !state.imagePath;
  $("refPills").hidden = !(image || edit);
  $("prompt").placeholder = image
    ? "Describe your image. Subject, style, composition, text."
    : edit
      ? "Describe the edit. What changes, what stays, who appears."
      : "Describe your shot. Subject, camera, light, sound.";
  $("composerHint").textContent = image
    ? "Ideogram 4 renders locally. Great at posters, text and graphic styles. References are experimental. Ctrl+Enter also works."
    : edit
      ? "Qwen-Image-Edit 2511, 4-step lightning. First image is edited; extra references carry identity (characters, objects)."
      : "Audio is generated with the video. Ctrl+Enter also works. Balanced and High need more memory, step up once Fast runs stable.";
  $("btnGenerate").setAttribute("aria-label", edit ? "Run edit" : image ? "Generate image" : "Generate video");
  renderRefPills();
}

function renderRefPills() {
  const wrap = $("refPills");
  wrap.innerHTML = "";
  state.refImages.forEach((r, i) => {
    const pill = document.createElement("div");
    pill.className = "image-pill";
    pill.innerHTML = `
      ${r.preview ? `<img src="${r.preview}" alt="">` : ""}
      <span>${escapeHtml(r.name || "image")}</span>
      <button class="pill-x" title="Remove reference" aria-label="Remove reference">&#10005;</button>`;
    pill.querySelector(".pill-x").addEventListener("click", () => {
      state.refImages.splice(i, 1);
      renderRefPills();
      $("btnImage").hidden = state.refImages.length >= 3;
    });
    wrap.appendChild(pill);
  });
  wrap.hidden = state.mode !== "image";
}

async function init() {
  wireChips($("modeGroup"), setMode);
  wireChips($("aspectGroup"), (v) => { state.aspect = v; });
  wireChips($("imgAspectGroup"), (v) => { state.imgAspect = v; });
  wireChips($("durationGroup"), (v) => { state.seconds = Number(v); });

  $("btnGenerate").addEventListener("click", generate);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) generate();
    if (e.key === "Escape") {
      if (!$("ctxMenu").hidden) hideCtxMenu();
      else if (!$("viewer").hidden) closeViewer();
    }
  });
  $("btnDice").addEventListener("click", () => { $("seed").value = ""; $("seed").focus(); });
  $("btnImage").addEventListener("click", async () => {
    const wantRefs = state.mode === "image" || (state.mode === "edit" && state.imagePath);
    if (wantRefs) {
      const res = await call("pick_image", true);
      if (!res.ok) {
        if (!res.cancelled) toast(res.error || "Could not open the file picker.", "error");
        return;
      }
      const cap = REF_CAP[state.mode] || 3;
      const room = cap - state.refImages.length;
      state.refImages.push(...(res.items || []).slice(0, room));
      setMode(state.mode);
      return;
    }
    const res = await call("pick_image");
    if (!res.ok) {
      if (!res.cancelled) toast(res.error || "Could not open the file picker.", "error");
      return;
    }
    setImage(res);
  });
  $("btnImageClear").addEventListener("click", () => setImage(null));
  $("btnFolder").addEventListener("click", () => call("open_outputs"));

  refreshClaudeDot();
  $("btnClaude").addEventListener("click", async () => {
    const link = await call("claude_link").catch(() => null);
    if (link && link.connected) {
      if (window.confirm("Claude Desktop is already connected. Disconnect?")) {
        await call("disconnect_claude");
        toast("Disconnected. Restart Claude Desktop to apply.");
      }
      refreshClaudeDot();
      return;
    }
    const res = await call("connect_claude");
    if (res.ok) {
      toast("Connected. Restart Claude Desktop, then MotionLab shows up among its tools (no connector URL needed).", "ok", true);
    } else if (state.mcpUrl) {
      try { await navigator.clipboard.writeText(state.mcpUrl); } catch { /* needs focus */ }
      toast(`${res.error || "Claude Desktop not found."} For other MCP clients the endpoint URL is on your clipboard: ${state.mcpUrl}`, "error", true);
    } else {
      toast(res.error || "Could not connect.", "error", true);
    }
    refreshClaudeDot();
  });
  $("btnCancel").addEventListener("click", async () => {
    if (state.activeJob) await call("cancel", state.activeJob.id);
  });

  $("viewerBackdrop").addEventListener("click", closeViewer);
  $("btnCloseViewer").addEventListener("click", closeViewer);
  $("btnReuse").addEventListener("click", () => {
    if (state.viewerItem) reuseItem(state.viewerItem);
  });
  $("btnReveal").addEventListener("click", () => {
    if (state.viewerItem) call("reveal", state.viewerItem.file);
  });
  $("btnDelete").addEventListener("click", () => {
    if (state.viewerItem) deleteItem(state.viewerItem, true);
  });

  document.addEventListener("click", (e) => {
    if (!$("ctxMenu").hidden && !$("ctxMenu").contains(e.target)) hideCtxMenu();
  });
  document.addEventListener("scroll", hideCtxMenu, true);
  window.addEventListener("blur", hideCtxMenu);

  $("quality").addEventListener("change", refreshDurations);
  refreshDurations();

  wireChips($("libFilterGroup"), (v) => { state.libFilter = v; applyLibraryView(); });
  let searchTimer = null;
  $("libSearch").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.libQuery = e.target.value;
      applyLibraryView();
    }, 150);
  });

  try {
    const d = await call("get_defaults");
    const wrap = $("samples");
    for (const s of d.samples) {
      const b = document.createElement("button");
      b.className = "chip";
      b.textContent = s;
      b.addEventListener("click", () => {
        $("prompt").value = s;
        $("prompt").focus();
      });
      wrap.appendChild(b);
    }
  } catch { /* bridge races on startup, samples are cosmetic */ }

  poll(true);
  (function loop() {
    setTimeout(async () => {
      try { await poll(); } catch { /* keep looping */ }
      loop();
    }, state.activeJob ? 700 : 1600);
  })();
}

async function refreshClaudeDot() {
  try {
    const link = await call("claude_link");
    $("claudeDot").classList.toggle("on", !!link.connected);
    $("btnClaudeLabel").textContent = link.connected ? "Claude linked" : "Claude";
    $("btnClaude").title = link.connected
      ? "Claude Desktop is connected (restart it once after connecting). Click to disconnect."
      : "One click connects MotionLab to Claude Desktop. The MCP endpoint also serves other clients.";
  } catch { /* bridge race at startup */ }
}

function pickChip(group, value) {
  const btn = [...group.querySelectorAll(".chip")].find((c) => c.dataset.value === value);
  if (btn) btn.click();
}

function setImage(res) {
  state.imagePath = res ? res.path : null;
  if (res) {
    $("imageName").textContent = res.name || "image";
    if (res.preview) { $("imageThumb").src = res.preview; $("imageThumb").hidden = false; }
    else $("imageThumb").hidden = true;
  } else {
    $("imageThumb").removeAttribute("src");
  }
  setMode(state.mode);  // recomputes pill and button visibility per mode
}

if (window.pywebview && window.pywebview.api) init();
else window.addEventListener("pywebviewready", init);

/* Browser preview fallback: if the pywebview bridge never appears (opened in a
   plain browser during development), boot with a mock API so the UI is visible. */
setTimeout(() => {
  if (window.pywebview && window.pywebview.api) return;
  const mockLib = [];
  window.pywebview = {
    api: {
      get_state: async () => ({ engine: "starting", queue_running: 0, queue_pending: 0, jobs: [], now: Date.now() }),
      get_defaults: async () => ({
        samples: [
          "A woman in a yellow raincoat walks through neon-lit rain at night, reflections shimmer on the wet street, cinematic tracking shot, soft rain sound",
          "Close-up of an espresso pouring into a glass cup in warm morning light, steam rising, gentle cafe ambience",
          "A small sailboat glides across a glassy alpine lake at dawn, mist over the water, calm wind and water sounds",
          "Macro shot of a matchstick igniting in slow motion, sparks and smoke curling in dark space, sharp striking sound",
        ],
        model: "LTX-2.3 22B distilled Q4_K_M",
      }),
      generate: async () => ({ ok: false, error: "Preview mode: the engine bridge is not connected." }),
      pick_image: async () => ({ ok: false, cancelled: true }),
      cancel: async () => ({ ok: true }),
      library: async () => mockLib,
      delete_item: async () => ({ ok: true }),
      reveal: async () => ({ ok: true }),
      open_outputs: async () => ({ ok: true }),
      engine_log_tail: async () => ({ ok: true, lines: [] }),
      retry_engine: async () => ({ ok: true }),
    },
  };
  init();
}, 1200);
