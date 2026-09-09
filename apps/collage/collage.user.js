// ==UserScript==
// @name         ldg collage
// @namespace    ldg-collage
// @version      2.5.11
// @description  Image and fixed-frame-rate video collages, entirely in your browser
// @match        https://boards.4chan.org/*/thread/*
// @match        https://boards.4channel.org/*/thread/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @require      https://cdn.jsdelivr.net/npm/mediabunny@1.55.7/dist/bundles/mediabunny.cjs#sha256=194c80aaff75b420184c1b82f932863b1318d47bb51fc07754658608707f82fb
// @connect      i.4cdn.org
// @connect      files.catbox.moe
// @connect      litter.catbox.moe
// @connect      uguu.se
// @run-at       document-idle
// ==/UserScript==
// Selection workflow inspired by https://rentry.org/yueessiz,
// https://rentry.org/ldgcollage and https://rentry.org/ldgcollage_v2.
// Media processing stays in your browser; no server or external application.
// Mediabunny 1.55.7 (MPL-2.0) is loaded separately by the userscript manager.
// Library source: https://github.com/Vanilagy/mediabunny
// Separate our IIFE from @require code that may end without a semicolon.
;
(() => {
  // src/mediabunny.js
  var {
    Input,
    BlobSource,
    MP4,
    WEBM,
    MATROSKA,
    VideoSampleSink,
    Output,
    BufferTarget,
    WebMOutputFormat,
    Mp4OutputFormat,
    CanvasSource,
    canEncodeVideo
  } = Mediabunny;

  // src/engine.js
  var LIMITS = Object.freeze({
    items: 64,
    bytes: 256 * 1024 ** 2,
    sourcePixels: 32 * 1024 ** 2
  });
  var LARGE_VIDEO_JOB = Object.freeze({ videos: 8, pixels: 24 * 1024 ** 2 });
  var DEFAULT_MAX_BYTES = 4 * 1024 ** 2;
  function checkOutputSize(blob, maxBytes) {
    if (!Number.isFinite(maxBytes) || maxBytes <= 0 || blob.size > Math.floor(maxBytes))
      throw new Error("finished collage exceeds the selected output size limit");
  }
  var channel;
  var pending = [];
  var yieldTask = () => new Promise((resolve) => {
    if (typeof MessageChannel === "undefined") {
      setTimeout(resolve, 0);
      return;
    }
    if (!channel) {
      channel = new MessageChannel();
      channel.port1.onmessage = () => pending.shift()?.();
    }
    pending.push(resolve);
    channel.port2.postMessage(null);
  });
  function check(signal) {
    if (signal?.aborted) throw signal.reason || new DOMException("cancelled", "AbortError");
  }
  var isVideo = (format) => format === "webm" || format === "mp4";
  function normalizeBlob(value) {
    if (value instanceof Blob) return value;
    if (!["[object Blob]", "[object File]"].includes(Object.prototype.toString.call(value)))
      throw new Error("invalid media file");
    const blob = new Blob([value], { type: value.type });
    if (blob.size !== value.size) throw new Error("browser could not read the media file");
    return blob;
  }
  function dimensions(w, h) {
    if (!Number.isFinite(w * h) || w < 1 || h < 1 || w * h > LIMITS.sourcePixels)
      throw new Error("source exceeds 32 megapixels or has invalid dimensions");
  }
  function parseAspect(value) {
    const text = String(value).trim();
    const number = "(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:e[+-]?\\d+)?";
    const match = new RegExp(`^(${number})(?:\\s*[:/x\xD7]\\s*(${number}))?$`, "i").exec(text);
    const ratio = match ? Number(match[1]) / (match[2] === void 0 ? 1 : Number(match[2])) : NaN;
    if (!Number.isFinite(ratio) || ratio <= 0) throw new Error("enter a positive aspect ratio, such as 2:3, 0.5 or 3/7");
    return ratio;
  }
  function options(raw = {}) {
    const o = {
      format: "webm",
      fps: 30,
      duration: 5,
      edge: 1280,
      aspect: 1,
      maxBytes: DEFAULT_MAX_BYTES,
      ...raw
    };
    if (!["auto", "webm", "mp4", "jpeg", "png"].includes(o.format) || ![15, 24, 30, 60].includes(o.fps) || o.duration !== "auto" && (!Number.isFinite(o.duration) || o.duration <= 0 || o.duration > 300) || !Number.isFinite(o.edge) || o.edge < 320 || o.edge > (isVideo(o.format) || o.format === "auto" ? 2048 : 4096) || !Number.isFinite(o.aspect) || o.aspect < 2 / o.edge || o.aspect > o.edge / 2 || !Number.isFinite(o.maxBytes) || o.maxBytes < 1e5 || o.maxBytes > 32e6)
      throw new Error("invalid export settings");
    if (o.duration !== "auto") {
      o.frameCount = Math.max(1, Math.round(o.duration * o.fps));
      o.duration = o.frameCount / o.fps;
    }
    return o;
  }
  function canvas(w, h) {
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d", { alpha: false, colorSpace: "srgb" });
    if (!ctx) throw new Error("2d canvas is unavailable");
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);
    return { canvas: c, ctx };
  }
  function canvasBlob(c, type, quality) {
    return new Promise((resolve, reject) => c.toBlob((b) => b ? resolve(b) : reject(new Error("image encoding failed")), type, quality));
  }
  function layout(media, edge, aspect = 1, header = false) {
    if (!media.length) throw new Error("select at least one file");
    if (header && media.length > 1) {
      const bodyAspect = 1 / Math.max(1 / aspect - media[0].height / media[0].width, 1e-6);
      const body = layout(media.slice(1), edge, bodyAspect);
      const headerH = body.width * media[0].height / media[0].width;
      const scale = Math.min(1, edge / (body.height + headerH));
      const width = Math.max(2, Math.floor(body.width * scale / 2) * 2);
      const height2 = Math.max(2, Math.floor((body.height + headerH) * scale / 2) * 2);
      const hh = Math.round(headerH * scale);
      return { width, height: height2, placements: [
        { index: 0, x: 0, y: 0, width, height: hh },
        ...body.placements.map((p) => ({
          index: p.index + 1,
          x: Math.round(p.x * width / body.width),
          y: hh + Math.round(p.y * (height2 - hh) / body.height),
          width: Math.max(1, Math.round((p.x + p.width) * width / body.width) - Math.round(p.x * width / body.width)),
          height: Math.max(1, Math.round((p.y + p.height) * (height2 - hh) / body.height) - Math.round(p.y * (height2 - hh) / body.height))
        }))
      ] };
    }
    const ratios = media.map((m) => m.width / m.height);
    const ideal = Math.sqrt(1 / (aspect * ratios.reduce((a, b) => a + b, 0)));
    const candidates = [];
    const trials = 65;
    for (let trial = 0; trial < trials; trial++) {
      const target = ideal * 2 ** ((trial - 32) / 8);
      const cost = [0], prev = [0];
      for (let end2 = 1; end2 <= ratios.length; end2++) {
        cost[end2] = Infinity;
        let sum = 0;
        for (let start = end2 - 1; start >= 0; start--) {
          sum += ratios[start];
          const h = 1 / sum, score = cost[start] + (h - target) ** 2;
          if (score < cost[end2]) {
            cost[end2] = score;
            prev[end2] = start;
          }
        }
      }
      const candidate = [];
      let end = ratios.length;
      while (end) {
        const start = prev[end];
        candidate.unshift([start, end]);
        end = start;
      }
      const totalHeight = candidate.reduce((sum, [a, b]) => sum + 1 / ratios.slice(a, b).reduce((s, r) => s + r, 0), 0);
      const error = Math.abs(Math.log(totalHeight * aspect));
      const areas = candidate.flatMap(([a, b]) => {
        const sum = ratios.slice(a, b).reduce((s, r) => s + r, 0);
        return ratios.slice(a, b).map((r) => r / (sum * sum));
      });
      areas.sort((a, b) => a - b);
      const median = areas[Math.floor((areas.length - 1) / 2)];
      candidates.push({ rows: candidate, error, spread: areas.at(-1) / median });
    }
    const spreadLimit = Math.max(2.5, Math.min(...candidates.map((c) => c.spread)) * (1 + 1e-9));
    const { rows } = candidates.filter((c) => c.spread <= spreadLimit).sort((a, b) => a.error - b.error || a.spread - b.spread)[0];
    const heights = rows.map(([a, b]) => 1 / ratios.slice(a, b).reduce((s, r) => s + r, 0));
    const height = heights.reduce((a, b) => a + b, 0);
    const widthPx = Math.max(2, Math.floor(edge / Math.max(1, height) / 2) * 2);
    const heightPx = Math.max(2, Math.floor(widthPx * height / 2) * 2);
    const placements = [];
    let y = 0;
    rows.forEach(([a, b], row) => {
      const bottom = row === rows.length - 1 ? heightPx : Math.round(y + heights[row] * widthPx);
      let x = 0;
      for (let i = a; i < b; i++) {
        const right = i === b - 1 ? widthPx : Math.round(x + ratios[i] * heights[row] * widthPx);
        placements.push({ index: i, x, y, width: Math.max(1, right - x), height: Math.max(1, bottom - y) });
        x = right;
      }
      y = bottom;
    });
    return { width: widthPx, height: heightPx, placements };
  }
  function rejectHDR(color) {
    if (["pq", "hlg", "smpte2084", "arib-std-b67"].includes(color?.transfer))
      throw new Error("HDR video needs tone mapping; use an SDR source");
  }
  async function prepare(blob, signal, edge = 2048) {
    check(signal);
    blob = normalizeBlob(blob);
    if (!blob.size) throw new Error("empty media file");
    const head = new Uint8Array(await blob.slice(0, 16).arrayBuffer());
    const image = /image\//.test(blob.type) || head[0] === 255 && head[1] === 216 || head[0] === 137 && head[1] === 80 || String.fromCharCode(...head.slice(0, 3)) === "GIF" || String.fromCharCode(...head.slice(8, 12)) === "WEBP";
    if (image) {
      const url = URL.createObjectURL(blob), img = new Image();
      try {
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => finish(new Error("image decode timed out")), 3e4);
          const abort2 = () => finish(signal.reason);
          const finish = (error) => {
            clearTimeout(timer);
            signal?.removeEventListener("abort", abort2);
            img.onload = img.onerror = null;
            error ? reject(error) : resolve();
          };
          img.onload = () => finish();
          img.onerror = () => finish(new Error("cannot decode image"));
          signal?.addEventListener("abort", abort2, { once: true });
          img.src = url;
        });
        check(signal);
        dimensions(img.naturalWidth, img.naturalHeight);
        const w = img.naturalWidth, h = img.naturalHeight;
        const scale = Math.min(1, edge / Math.max(w, h));
        const tile = canvas(Math.max(1, Math.round(w * scale)), Math.max(1, Math.round(h * scale)));
        tile.ctx.drawImage(img, 0, 0, tile.canvas.width, tile.canvas.height);
        return {
          kind: "image",
          blob,
          width: w,
          height: h,
          pixels: tile.canvas.width * tile.canvas.height,
          async paint(ctx, p) {
            check(signal);
            ctx.drawImage(tile.canvas, p.x, p.y, p.width, p.height);
          },
          dispose() {
            tile.canvas.width = tile.canvas.height = 1;
          }
        };
      } finally {
        img.src = "";
        URL.revokeObjectURL(url);
      }
    }
    if (typeof VideoDecoder === "undefined") throw new Error("this browser has no WebCodecs video decoder");
    const input = new Input({ source: new BlobSource(blob), formats: [MP4, WEBM, MATROSKA] });
    const abort = () => input.dispose();
    const dispose = () => {
      signal?.removeEventListener("abort", abort);
      input.dispose();
    };
    signal?.addEventListener("abort", abort, { once: true });
    try {
      check(signal);
      const track = await input.getPrimaryVideoTrack();
      if (!track || !await track.canDecode()) throw new Error("this browser cannot decode this video codec");
      rejectHDR(await track.getColorSpace());
      const width = await track.getDisplayWidth(), height = await track.getDisplayHeight();
      dimensions(width, height);
      const start = await track.getFirstTimestamp(), end = await track.computeDuration();
      if (!Number.isFinite(end - start) || end <= start) throw new Error("video has invalid timestamps");
      check(signal);
      return {
        kind: "video",
        blob,
        input,
        track,
        width,
        height,
        start,
        duration: end - start,
        dispose
      };
    } catch (e) {
      dispose();
      throw e;
    }
  }
  function videoReader(m, signal, samples = () => new VideoSampleSink(m.track).samples(m.start)) {
    let iterator, current, next, cycle = -1;
    const close = async () => {
      current?.close();
      next?.close();
      current = next = void 0;
      const old = iterator;
      iterator = void 0;
      if (old) await old.return();
    };
    const read = async () => {
      check(signal);
      const { value } = await iterator.next();
      if (signal?.aborted) {
        value?.close();
        check(signal);
      }
      if (value && (!Number.isFinite(value.timestamp) || current && value.timestamp < current.timestamp)) {
        value.close();
        throw new Error("video has invalid frame timestamps");
      }
      return value;
    };
    return {
      async at(index, fps) {
        check(signal);
        const elapsed = index / fps;
        const loop = Math.floor((elapsed + 1e-9) / m.duration);
        const time = m.start + Math.max(0, elapsed - loop * m.duration);
        if (loop !== cycle) {
          await close();
          cycle = loop;
          iterator = samples();
          current = await read();
          next = await read();
        }
        while (next && next.timestamp <= time + 1e-7) {
          current?.close();
          current = next;
          next = void 0;
          next = await read();
        }
        if (!current || current.timestamp > time + 1e-7)
          throw new Error(`no decoded source frame at ${time.toFixed(6)}s`);
        return current;
      },
      close
    };
  }
  async function exportCollage(blobs, raw, signal, progress = () => {
  }, warn = async () => {
  }) {
    const o = options(raw);
    const media = [];
    let total = 0, videoPixels = 0, videoCount = 0, imagePixels = 0;
    if (!blobs.length || blobs.length > LIMITS.items) throw new Error("select 1\u201364 files");
    for (const b of blobs) total += b.size;
    if (total > LIMITS.bytes) throw new Error("selected files exceed 256 MiB");
    try {
      for (let i = 0; i < blobs.length; i++) {
        check(signal);
        progress(`reading ${i + 1}/${blobs.length}`);
        const name = blobs[i].name || `source ${i + 1}`;
        let m;
        try {
          m = await prepare(blobs[i], signal, o.edge);
        } catch (e) {
          check(signal);
          throw new Error(`${name}: ${e.message || e}`);
        }
        m.name = name;
        media.push(m);
        imagePixels += m.pixels || 0;
        if (imagePixels > LIMITS.sourcePixels) throw new Error("still images exceed 32 megapixels after resizing; split this collage");
        if (m.kind === "video") {
          videoPixels += m.width * m.height;
          videoCount++;
        }
        await yieldTask();
      }
      if (o.format === "auto") o.format = media.some((m) => m.kind === "video") ? "webm" : "jpeg";
      if (isVideo(o.format) && (videoCount > LARGE_VIDEO_JOB.videos || videoPixels > LARGE_VIDEO_JOB.pixels)) {
        await warn({ videos: videoCount, pixels: videoPixels });
        check(signal);
      }
      if (o.duration === "auto") {
        const longest = Math.max(0, ...media.filter((m) => m.kind === "video").map((m) => m.duration));
        if (isVideo(o.format) && longest > 300) throw new Error("longest video exceeds 300 seconds; set seconds explicitly");
        o.frameCount = Math.max(1, Math.ceil((longest || 5) * o.fps - 1e-8));
        o.duration = o.frameCount / o.fps;
      }
      const l = layout(media, o.edge, o.aspect, o.header);
      const base = canvas(l.width, l.height);
      try {
        for (const p of l.placements) {
          const m = media[p.index];
          check(signal);
          if (m.kind === "image") {
            await m.paint(base.ctx, p);
            m.dispose();
          } else if (!isVideo(o.format)) {
            const s = await new VideoSampleSink(m.track).getSample(m.start);
            if (!s) throw new Error("video has no first frame");
            try {
              rejectHDR(s.colorSpace);
              s.draw(base.ctx, p.x, p.y, p.width, p.height);
            } finally {
              s.close();
            }
          }
        }
        if (!isVideo(o.format)) return await encodeImage(base.canvas, o, signal, progress);
        if (typeof VideoEncoder === "undefined") throw new Error("this browser has no WebCodecs video encoder");
        let bitrate = Math.floor(o.maxBytes * 8 * 0.88 / o.duration);
        const codec = await selectCodec(o.format, l.width, l.height, bitrate);
        let lastBytes = 0;
        for (let attempt = 1; attempt <= 3; attempt++) {
          const result = await encodeVideo(media, l, base.canvas, o, codec, bitrate, signal, progress, attempt);
          if (result.blob.size <= o.maxBytes) return result;
          lastBytes = result.blob.size;
          bitrate = Math.floor(bitrate * o.maxBytes / result.blob.size * 0.8);
          check(signal);
          await yieldTask();
        }
        throw new Error(`video is ${(lastBytes / 1e6).toFixed(2)} MB after 3 passes; limit is ${(o.maxBytes / 1e6).toFixed(2)} MB. increase limit (MB), or reduce scale or seconds in advanced`);
      } finally {
        base.canvas.width = base.canvas.height = 1;
      }
    } finally {
      for (const m of media) m.dispose();
    }
  }
  async function selectCodec(format, width, height, bitrate, probe = canEncodeVideo) {
    for (const codec of format === "mp4" ? ["avc"] : ["vp8", "vp9"]) {
      if (await probe(codec, {
        width,
        height,
        bitrate,
        latencyMode: "quality",
        hardwareAcceleration: "no-preference"
      })) return codec;
    }
    throw new Error(format === "mp4" ? "this browser cannot encode mp4 at these dimensions; try webm or image output" : "this browser cannot encode webm at these dimensions; try mp4 or image output");
  }
  async function encodeImage(c, o, signal, progress) {
    if (o.format === "png") {
      check(signal);
      progress("encoding png");
      const blob = await canvasBlob(c, "image/png");
      check(signal);
      if (blob.size > o.maxBytes) throw new Error("png exceeds the size limit; choose jpeg or smaller dimensions");
      return { blob, extension: "png", width: c.width, height: c.height };
    }
    let low = 0.35, high = 0.95, best = null;
    for (let i = 0; i < 7; i++) {
      check(signal);
      progress(`encoding jpeg ${i + 1}/7`);
      const quality = i === 0 ? high : (low + high) / 2;
      const blob = await canvasBlob(c, "image/jpeg", quality);
      if (blob.size <= o.maxBytes) {
        best = blob;
        low = quality;
        if (i === 0) break;
      } else high = quality;
      await yieldTask();
    }
    check(signal);
    if (!best) throw new Error("jpeg exceeds the size limit; reduce dimensions");
    return { blob: best, extension: "jpg", width: c.width, height: c.height };
  }
  async function encodeVideo(media, l, base, o, codec, bitrate, signal, progress, attempt) {
    const target = new BufferTarget();
    const output = new Output({ format: o.format === "mp4" ? new Mp4OutputFormat() : new WebMOutputFormat(), target });
    const frame = canvas(l.width, l.height);
    const stamps = [];
    const source = new CanvasSource(frame.canvas, {
      codec,
      bitrate,
      latencyMode: "quality",
      hardwareAcceleration: "no-preference",
      keyFrameInterval: 2,
      onEncodedPacket: (packet) => {
        stamps.push(packet.timestamp);
      }
    });
    output.addVideoTrack(source, { frameRate: o.fps });
    const readers = /* @__PURE__ */ new Map();
    const abort = () => {
      for (const m of media) if (m.input) m.input.dispose();
    };
    signal?.addEventListener("abort", abort, { once: true });
    let finalized = false;
    try {
      check(signal);
      await output.start();
      for (const p of l.placements) {
        const m = media[p.index];
        if (m.kind === "video") readers.set(p.index, videoReader(m, signal));
      }
      for (let i = 0; i < o.frameCount; i++) {
        check(signal);
        frame.ctx.drawImage(base, 0, 0);
        for (const p of l.placements) {
          const reader = readers.get(p.index);
          if (!reader) continue;
          try {
            const sample = await reader.at(i, o.fps);
            rejectHDR(sample.colorSpace);
            sample.draw(frame.ctx, p.x, p.y, p.width, p.height);
          } catch (e) {
            check(signal);
            throw new Error(`${media[p.index].name}, output frame ${i + 1}: ${e.message || e}`);
          }
        }
        await source.add(i / o.fps, 1 / o.fps);
        progress(`pass ${attempt}: frame ${i + 1}/${o.frameCount}`);
        await yieldTask();
      }
      check(signal);
      source.close();
      await output.finalize();
      finalized = true;
      check(signal);
      stamps.sort((a, b) => a - b);
      if (stamps.length !== o.frameCount || stamps.some((t, i) => Math.abs(t - i / o.fps) > 1e-5))
        throw new Error("encoder returned missing or mistimed frames");
      return {
        blob: new Blob([target.buffer], { type: `video/${o.format}` }),
        extension: o.format,
        width: l.width,
        height: l.height,
        frames: stamps.length,
        fps: o.fps,
        duration: o.duration
      };
    } finally {
      signal?.removeEventListener("abort", abort);
      for (const reader of readers.values()) await reader.close().catch(() => {
      });
      if (!finalized) await output.cancel().catch(() => {
      });
      frame.canvas.width = frame.canvas.height = 1;
    }
  }

  // src/ui.js
  var hosts = /* @__PURE__ */ new Set(["i.4cdn.org", "files.catbox.moe", "litter.catbox.moe", "uguu.se"]);
  var id = "ldg-collage-v2";
  if (!document.getElementById(id)) init();
  function init() {
    const host = document.createElement("div");
    host.id = id;
    document.body.append(host);
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `<style>
    :host { font: inherit; color: #e8eaed; color-scheme:dark; }
    * { box-sizing: border-box; }
    button,input,select { font: inherit; color: #e8eaed; background:#303134; border:1px solid #757575; }
    input[type=range],input[type=checkbox] { accent-color:#a8c7fa; }
    button,a,input,select { min-height: 28px; }
    button { cursor: pointer; } button:disabled { cursor: default; color:#9aa0a6; }
    button:not(:disabled):hover { background:#414348; }
    :focus-visible { outline: 2px solid Highlight; outline-offset: 2px; }
    #open { position:fixed; bottom:8px; right:8px; z-index:2147483647; }
    #panel { position:fixed; inset:4%; z-index:2147483647; background:#202124;
      color:#e8eaed; border:1px solid #757575; padding:8px; overflow:auto; font:15px sans-serif; }
    [hidden] { display:none !important; }
    .bar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px; }
    #list { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:4px; }
    .tile { cursor:pointer; border:1px solid GrayText; padding:4px; overflow-wrap:anywhere; }
    .tile.selected { background:#90ee90; color:#000; }
    .tile img,.tile canvas { width:100%; height:90px; object-fit:contain; }
    .tile .source-preview { display:block; width:100%; min-height:90px; }
    .source-preview img,.source-preview canvas { pointer-events:none; }
    .selection { display:block; }
    .selection:focus-visible { outline:2px solid currentColor; outline-offset:1px; }
    #panel-head { position:sticky; top:-8px; z-index:2; display:flex; gap:8px;
      align-items:flex-start; background:#202124; padding:8px 0; }
    #message { flex:1; min-width:0; margin:0; white-space:pre-wrap; overflow-wrap:anywhere; }
    #close { flex:none; margin-left:auto; }
    #preview { position:fixed; inset:0; margin:0; border:0; padding:0; width:100vw; height:100vh;
      max-width:none; max-height:none; background:#000; color:#fff;
      align-items:center; justify-content:center; }
    #preview[open] { display:flex; }
    #preview img,#preview video { max-width:calc(100vw - 64px); max-height:calc(100vh - 64px); object-fit:contain; }
    #preview img { cursor:zoom-out; }
    #preview-status { position:absolute; bottom:8px; }
    #preview-close { position:absolute; top:8px; right:8px; z-index:1; }
    #warning { max-width:min(440px,90vw); background:#202124; color:#e8eaed; border:1px solid #757575; }
    #warning::backdrop { background:#0009; }
    summary { cursor:pointer; min-height:28px; }
    .help { font-size:0.9em; } fieldset { border:0; padding:0; margin:0; }
    @media (forced-colors:active) {
      #panel,#panel-head,#warning { background:Canvas; color:CanvasText; border-color:CanvasText; }
      button,input,select,button:not(:disabled):hover { background:ButtonFace; color:ButtonText; border-color:ButtonText; }
      button:disabled { color:GrayText; }
    }
  </style>
  <button id="open" aria-expanded="false" aria-controls="panel">collage</button>
  <section id="panel" role="dialog" aria-modal="true" aria-label="collage" hidden>
    <div id="panel-head"><p id="message" role="status" aria-live="polite"></p><button id="close" aria-label="close collage">X</button></div>
    <fieldset id="settings">
    <div class="bar">
      <label>aspect ratio <input id="aspect" type="text" value="1:1" placeholder="2:3, 0.5, 3/7" size="12" list="ratios"></label>
      <datalist id="ratios"><option value="1:1"><option value="16:9"><option value="9:16"><option value="4:3"><option value="3:2"><option value="2:3"><option value="21:9"></datalist>
      <label>scale <input id="edge" type="range" min="320" max="2048" step="2" value="1280"><output id="scale-value" for="edge">100% \xB7 1280px</output></label>
      <button id="export">create collage</button><button id="cancel" disabled>cancel</button>
    </div>
    <details id="advanced"><summary>advanced</summary>
    <div class="bar">
      <label>add files <input id="files" type="file" accept="image/*,video/webm,video/mp4" multiple></label>
      <label>header image <input id="header" type="file" accept="image/*"></label></div>
    <div class="bar">
      <label>output <select id="format"><option value="auto">automatic</option><option value="webm">video \xB7 webm</option><option value="mp4">video \xB7 mp4 (h.264)</option><option value="jpeg">image \xB7 jpeg</option><option value="png">image \xB7 png</option></select></label>
      <label>fps <select id="fps"><option>15</option><option>24</option><option selected>30</option><option>60</option></select></label>
      <label>seconds <input id="duration" type="number" min="0.01" max="300" step="any" placeholder="auto" size="6"></label>
      <label>limit (MB) <input id="limit" type="number" min="0.1" max="32" step="any" value="${DEFAULT_MAX_BYTES / 1e6}" size="8" title="maximum size of each finished collage, not its input files"></label>
      <label>collages <input id="parts" type="number" min="1" max="16" step="1" value="1" size="3"></label>
    </div></details></fieldset>
    <div class="bar"><label>show <select id="view" aria-label="gallery view"><option value="all">all files</option><option value="selected">selected only</option></select></label>
      <button id="all">select all</button><button id="none">select none</button>
      <button id="clear">Clear imported</button><span id="count"></span></div>
    <div id="list" aria-label="media selection"></div>
  </section>
  <dialog id="warning" aria-label="large video collage" aria-describedby="warning-text">
    <p id="warning-text"></p>
    <label><input id="warning-remember" type="checkbox">don't warn me again</label>
    <p id="warning-error" role="status"></p>
    <div class="bar"><button id="warning-continue">continue rendering</button><button id="warning-cancel">cancel</button></div>
  </dialog>
  <dialog id="preview" aria-label="media preview" hidden>
    <button id="preview-close" aria-label="close preview">X</button>
    <p id="preview-status" role="status"></p>
  </dialog>`;
    const $ = (name) => root.getElementById(name);
    for (const name of ["format", "edge", "aspect", "fps", "duration", "limit", "parts"])
      $(name).setAttribute("aria-label", {
        format: "output",
        edge: "scale",
        aspect: "aspect ratio",
        fps: "fps",
        duration: "seconds",
        limit: "limit (MB)",
        parts: "collages"
      }[name]);
    const entries = /* @__PURE__ */ new Map();
    let header = null, controller = null;
    const storageKey = `ldg-collage-v2:${location.pathname}`;
    let remembered = /* @__PURE__ */ new Set();
    try {
      const saved = localStorage.getItem(storageKey);
      const thread = /\/thread\/(\d+)/.exec(location.pathname)?.[1];
      const legacy = JSON.parse(localStorage.getItem(`highlightedImages_${thread}`) || "[]");
      remembered = new Set(saved !== null ? JSON.parse(saved) : legacy.map((e) => e.fullSrc));
    } catch {
    }
    const message = (text) => {
      $("message").textContent = text;
    };
    const warningKey = "ldg-collage-hide-large-video-warning";
    let warningAccepted = false;
    function warnLargeJob(info, signal) {
      let hidden = false;
      try {
        hidden = typeof GM_getValue === "function" ? GM_getValue(warningKey, false) === true : localStorage.getItem(warningKey) === "true";
      } catch {
      }
      if (hidden || warningAccepted) return Promise.resolve();
      check(signal);
      return new Promise((resolve, reject) => {
        const dialog = $("warning");
        $("warning-text").textContent = `${info.videos} videos \xB7 ${(info.pixels / 1e6).toFixed(1)} MP. this large collage may slow or freeze your browser, run out of memory, or fail to export. slow rendering alone does not make the output choppy`;
        $("warning-remember").checked = false;
        $("warning-error").textContent = "";
        const focus = root.activeElement;
        const finish = (error) => {
          signal.removeEventListener("abort", abort);
          dialog.close();
          $("panel").inert = false;
          $("open").disabled = false;
          dialog.oncancel = $("warning-continue").onclick = $("warning-cancel").onclick = null;
          focus?.focus();
          error ? reject(error) : resolve();
        };
        const abort = () => finish(signal.reason || new DOMException("cancelled", "AbortError"));
        $("warning-continue").onclick = () => {
          if ($("warning-remember").checked) {
            try {
              if (typeof GM_setValue === "function") GM_setValue(warningKey, true);
              else localStorage.setItem(warningKey, "true");
            } catch {
              $("warning-error").textContent = "preference could not be saved; uncheck to continue once";
              return;
            }
          }
          warningAccepted = true;
          finish();
        };
        $("warning-cancel").onclick = () => controller.abort(new DOMException("cancelled", "AbortError"));
        dialog.oncancel = (e) => {
          e.preventDefault();
          $("warning-cancel").click();
        };
        signal.addEventListener("abort", abort, { once: true });
        dialog.showModal();
        $("panel").inert = true;
        $("open").disabled = true;
        $("warning-continue").focus();
      });
    }
    const persist = () => {
      try {
        remembered = new Set([...entries.values()].filter((e) => e.selected && e.url).map((e) => e.url));
        localStorage.setItem(storageKey, JSON.stringify([...remembered]));
      } catch {
        message("selection could not be saved; browser storage is full");
      }
    };
    const count = () => {
      $("count").textContent = `${[...entries.values()].filter((e) => e.selected).length}/${entries.size} selected`;
      for (const e of entries.values()) if (e.tile) {
        e.tile.hidden = $("view").value === "selected" && !e.selected;
        e.tile.classList.toggle("selected", !!e.selected);
        e.selection.setAttribute("aria-checked", String(!!e.selected));
      }
    };
    $("view").onchange = count;
    $("edge").oninput = () => {
      $("scale-value").value = `${Math.round(Number($("edge").value) / 12.8)}% \xB7 ${$("edge").value}px`;
    };
    const thumbnailEntries = /* @__PURE__ */ new WeakMap(), thumbnailQueue = /* @__PURE__ */ new Set();
    let thumbnailActive = 0;
    const thumbnailObserver = new IntersectionObserver((records) => {
      for (const record of records) {
        const entry = thumbnailEntries.get(record.target);
        if (record.isIntersecting) thumbnailQueue.add(entry);
        else thumbnailQueue.delete(entry);
      }
      pumpThumbnails();
    }, { root: $("panel"), rootMargin: "180px" });
    function pumpThumbnails() {
      while (thumbnailActive < 2 && thumbnailQueue.size) {
        const entry = thumbnailQueue.values().next().value;
        thumbnailQueue.delete(entry);
        if (!entry.tile.isConnected || entry.thumb || entry.thumbnailDone || entry.cancelThumbnail) continue;
        thumbnailObserver.unobserve(entry.tile);
        thumbnailActive++;
        const video = document.createElement("video");
        video.muted = true;
        video.playsInline = true;
        video.preload = "auto";
        let finished = false;
        const finish = () => {
          if (finished) return;
          finished = true;
          clearTimeout(timer);
          video.onloadeddata = video.onerror = null;
          video.pause();
          video.removeAttribute("src");
          video.load();
          entry.cancelThumbnail = null;
          entry.thumbnailDone = true;
          thumbnailActive--;
          pumpThumbnails();
        };
        const timer = setTimeout(finish, 12e3);
        entry.cancelThumbnail = finish;
        video.onerror = finish;
        video.onloadeddata = () => {
          try {
            if (entry.tile.isConnected && !entry.thumb && video.videoWidth && video.videoHeight) {
              const canvas2 = document.createElement("canvas");
              const scale = Math.min(1, 320 / Math.max(video.videoWidth, video.videoHeight));
              canvas2.width = Math.max(1, Math.round(video.videoWidth * scale));
              canvas2.height = Math.max(1, Math.round(video.videoHeight * scale));
              canvas2.getContext("2d").drawImage(video, 0, 0, canvas2.width, canvas2.height);
              entry.show.replaceChildren(canvas2);
            }
          } catch {
          } finally {
            finish();
          }
        };
        if (!entry.url && !entry.previewUrl) entry.previewUrl = URL.createObjectURL(entry.file);
        video.src = entry.url || entry.previewUrl;
      }
    }
    function add(entry) {
      if (entries.has(entry.key)) return;
      entries.set(entry.key, entry);
      const tile = document.createElement("div");
      tile.className = "tile";
      const show = document.createElement("button");
      show.className = "source-preview";
      show.setAttribute("aria-label", `preview ${entry.name}`);
      if (entry.thumb) {
        const img = new Image();
        img.src = entry.thumb;
        img.loading = "lazy";
        img.alt = "";
        show.append(img);
      } else show.textContent = "preview";
      show.onclick = () => {
        if (!entry.url && !entry.previewUrl) entry.previewUrl = URL.createObjectURL(entry.file);
        const video = entry.file?.type.startsWith("video/") || /\.(webm|mp4)(?:[?#]|$)/i.test(entry.url || entry.name);
        openPreview(entry.url || entry.previewUrl, video, show);
      };
      tile.append(show);
      const selection = document.createElement("div");
      selection.className = "selection";
      selection.setAttribute("role", "checkbox");
      selection.tabIndex = 0;
      selection.setAttribute("aria-checked", String(!!entry.selected));
      selection.textContent = entry.name;
      tile.append(selection);
      tile.onclick = (e) => {
        if (e.target.closest(".source-preview") || controller) return;
        entry.selected = !entry.selected;
        count();
        persist();
        syncMarks();
      };
      selection.onkeydown = (e) => {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault();
          selection.click();
        }
      };
      entry.selection = selection;
      entry.tile = tile;
      entry.show = show;
      $("list").append(tile);
      if (!entry.thumb && (entry.file?.type.startsWith("video/") || /\.(webm|mp4)(?:[?#]|$)/i.test(entry.url || entry.name))) {
        thumbnailEntries.set(tile, entry);
        thumbnailObserver.observe(tile);
      }
    }
    function scan() {
      for (const a of document.querySelectorAll("a.fileThumb, .postMessage a[href]")) {
        let url;
        try {
          url = new URL(a.href);
        } catch {
          continue;
        }
        if (url.protocol !== "https:" || !hosts.has(url.hostname) || !/\.(?:jpe?g|png|webp|gif|webm|mp4)$/i.test(url.pathname)) continue;
        add({
          key: url.href,
          url: url.href,
          name: url.pathname.split("/").pop(),
          thumb: a.querySelector("img")?.src || a.querySelector("video[poster]")?.poster,
          selected: remembered.has(url.href) || a.closest(".highlighted") !== null
        });
      }
      count();
    }
    function addFiles(files) {
      for (const file of files) {
        const image = file.type.startsWith("image/") || /\.(jpe?g|png|webp|gif)$/i.test(file.name);
        if (!image && !/\.(webm|mp4)$/i.test(file.name)) {
          message(`unsupported file: ${file.name}`);
          continue;
        }
        const key = `file:${file.name}:${file.size}:${file.lastModified}`;
        if (entries.has(key)) continue;
        const thumb = image ? URL.createObjectURL(file) : null;
        add({ key, file, name: file.name, thumb, selected: true });
      }
      count();
      persist();
    }
    let previousFocus;
    $("open").onclick = () => {
      if (!$("panel").hidden) {
        $("close").click();
        return;
      }
      previousFocus = document.activeElement;
      if (!controller) scan();
      $("panel").hidden = false;
      $("open").setAttribute("aria-expanded", "true");
      $("close").focus();
      if (document.querySelector(".chan-hv-options-menu")) message("the old collage script is also running; disable its older copies in your userscript manager");
    };
    $("close").onclick = () => {
      $("panel").hidden = true;
      $("open").setAttribute("aria-expanded", "false");
      previousFocus?.focus();
    };
    $("panel").addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        $("close").click();
      }
      if (e.key !== "Tab") return;
      const focusable = [...$("panel").querySelectorAll("button,input,select,a[href],summary"), $("open")].filter((e2) => !e2.disabled && e2.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (e.shiftKey && root.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && root.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });
    $("files").onchange = (e) => {
      addFiles(e.target.files);
      e.target.value = "";
    };
    $("header").onchange = (e) => {
      header = e.target.files[0] || null;
    };
    $("panel").ondragover = (e) => e.preventDefault();
    $("panel").ondrop = (e) => {
      e.preventDefault();
      if (!controller) addFiles(e.dataTransfer.files);
    };
    for (const [name, selected] of [["all", true], ["none", false]]) $(name).onclick = () => {
      for (const entry of entries.values()) {
        entry.selected = selected;
      }
      count();
      persist();
      syncMarks();
    };
    $("clear").onclick = () => {
      closePreview();
      for (const [key, e] of entries) if (e.file) {
        thumbnailObserver.unobserve(e.tile);
        thumbnailQueue.delete(e);
        e.cancelThumbnail?.();
        if (e.thumb) URL.revokeObjectURL(e.thumb);
        if (e.previewUrl) URL.revokeObjectURL(e.previewUrl);
        e.tile.remove();
        entries.delete(key);
      }
      header = null;
      $("header").value = "";
      $("files").value = "";
      count();
      persist();
      syncMarks();
    };
    $("cancel").onclick = () => controller?.abort(new DOMException("cancelled", "AbortError"));
    $("format").onchange = () => {
      const image = $("format").value !== "auto" && !isVideo($("format").value);
      $("fps").disabled = $("duration").disabled = image;
    };
    $("export").onclick = async () => {
      if (controller) return;
      scan();
      const chosen = [...entries.values()].filter((e) => e.selected);
      if (!chosen.length) {
        message("select at least one file");
        return;
      }
      const parts = Number($("parts").value);
      if (!Number.isInteger(parts) || parts < 1 || parts > Math.min(16, chosen.length)) {
        message("invalid collage count");
        return;
      }
      if (Math.ceil(chosen.length / parts) + (header ? 1 : 0) > LIMITS.items) {
        message("at most 64 files per collage; increase collages or select fewer files");
        return;
      }
      let aspect;
      try {
        aspect = parseAspect($("aspect").value);
      } catch (e) {
        message(e.message);
        $("aspect").focus();
        return;
      }
      const opts = {
        format: $("format").value,
        edge: Number($("edge").value),
        aspect,
        fps: Number($("fps").value),
        duration: $("duration").value === "" ? "auto" : Number($("duration").value),
        maxBytes: Number($("limit").value) * 1e6
      };
      if (opts.format !== "auto" && !isVideo(opts.format)) {
        opts.duration = 5;
        opts.fps = 30;
      }
      try {
        options(opts);
      } catch (e) {
        message(e.message);
        return;
      }
      if (header && header.size > LIMITS.bytes) {
        message("header exceeds 256 MiB");
        return;
      }
      warningAccepted = false;
      controller = new AbortController();
      const signal = controller.signal;
      syncMarks();
      const controls = [...$("panel").querySelectorAll("button,input,select")].filter((el) => !["close", "cancel"].includes(el.id));
      const disabled = controls.map((e) => e.disabled);
      controls.forEach((e) => {
        e.disabled = true;
      });
      $("cancel").disabled = false;
      closePreview();
      try {
        const groups = Array.from({ length: parts }, () => []);
        chosen.forEach((entry, i) => groups[i % parts].push(entry));
        for (let part = 0; part < parts; part++) {
          const blobs = [];
          let bytes = header?.size || 0;
          if (header) blobs.push(header);
          for (const entry of groups[part]) {
            check(signal);
            message(`collage ${part + 1}/${parts}: loading ${blobs.length + 1}`);
            const blob = entry.file || await fetchBlob(entry.url, signal, LIMITS.bytes - bytes);
            bytes += blob.size;
            if (bytes > LIMITS.bytes) throw new Error("selected files exceed 256 MiB; split this collage");
            blobs.push(entry.file || new File([blob], entry.name, { type: blob.type }));
          }
          const result = await exportCollage(
            blobs,
            { ...opts, header: !!header },
            signal,
            (text) => message(`collage ${part + 1}/${parts}: ${text}`),
            (info) => warnLargeJob(info, signal)
          );
          check(signal);
          checkOutputSize(result.blob, opts.maxBytes);
          const url = URL.createObjectURL(result.blob);
          const link = document.createElement("a");
          link.href = url;
          const board = location.pathname.split("/")[1] || "custom";
          const thread = /\/thread\/(\d+)/.exec(location.pathname)?.[1] || "custom";
          link.download = `highlights_${board}_${thread}_${Math.floor(Date.now() / 1e3)}_${part + 1}.${result.extension}`;
          link.hidden = true;
          root.append(link);
          try {
            link.click();
          } finally {
            link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 6e4);
          }
        }
        message(`${parts} download${parts === 1 ? "" : "s"} requested; check browser downloads`);
      } catch (e) {
        message(signal.aborted ? "cancelled" : e.message || String(e));
      } finally {
        controls.forEach((el, i) => {
          el.disabled = disabled[i];
        });
        $("cancel").disabled = true;
        controller = null;
        syncMarks();
      }
    };
    let previewFocus;
    function closePreview() {
      const media = $("preview").querySelector("img,video");
      if (media) {
        if (media.tagName === "VIDEO") {
          media.pause();
          media.removeAttribute("src");
          media.load();
        }
        media.remove();
      }
      const wasOpen = !$("preview").hidden;
      if ($("preview").open) $("preview").close();
      $("preview").hidden = true;
      $("panel").inert = false;
      $("open").disabled = false;
      if (wasOpen) previewFocus?.focus();
    }
    function openPreview(url, video, trigger) {
      closePreview();
      previewFocus = trigger;
      const media = document.createElement(video ? "video" : "img");
      media.src = url;
      if (video) {
        media.controls = true;
        media.loop = true;
        media.muted = true;
        media.playsInline = true;
      } else media.alt = "collage preview";
      $("preview-status").textContent = "";
      media.onerror = () => {
        $("preview-status").textContent = "this file could not be previewed";
      };
      if (!video) media.onclick = closePreview;
      $("preview").append(media);
      $("preview").hidden = false;
      $("preview").showModal();
      $("panel").inert = true;
      $("open").disabled = true;
      $("preview-close").focus();
      if (video) media.play().catch(() => {
      });
    }
    $("preview-close").onclick = closePreview;
    $("preview").oncancel = (e) => {
      e.preventDefault();
      closePreview();
    };
    $("preview").onclick = (e) => {
      if (e.target === $("preview")) closePreview();
    };
    $("preview").onkeydown = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closePreview();
      }
      if (e.key === "Tab" && !$("preview").querySelector("video")) {
        e.preventDefault();
        $("preview-close").focus();
      }
    };
    const marks = /* @__PURE__ */ new Map();
    const linkMarks = /* @__PURE__ */ new WeakMap();
    function syncMarks() {
      for (const entry of entries.values()) entry.tile.inert = !!controller;
      for (const [button, url] of marks) {
        if (!button.isConnected) {
          marks.delete(button);
          continue;
        }
        button.setAttribute("aria-pressed", String(entries.get(url)?.selected ?? remembered.has(url)));
        const selected = button.getAttribute("aria-pressed") === "true";
        button.style.backgroundColor = selected ? "#90ee90" : "yellow";
        const label = selected ? "collage \u2212" : "collage +";
        if (button.textContent !== label) button.textContent = label;
        button.disabled = !!controller;
      }
    }
    function placeMark(a, button) {
      const info = a.matches("a.fileThumb") && a.closest(".file")?.querySelector(".fileText, .file-info");
      if (!info) {
        if (a.nextSibling !== button) a.after(button);
        return;
      }
      const formatted = info.matches(".file-info") ? info : info.querySelector(".file-info");
      if (formatted) {
        if (formatted.nextSibling !== button) formatted.after(button);
        return;
      }
      let sauce = info.querySelector("a.sauce");
      if (sauce) {
        while (sauce.parentElement !== info) sauce = sauce.parentElement;
        if (sauce.previousSibling !== button) info.insertBefore(button, sauce);
      } else if (info.lastChild !== button) info.append(button);
    }
    function markLinks(node) {
      if (!(node instanceof Element) || node === host || node.hasAttribute("data-ldg-mark")) return;
      const links = node.matches("a.fileThumb, .postMessage a[href]") ? [node] : node.querySelectorAll("a.fileThumb, .postMessage a[href]");
      for (const a of links) {
        const existing = linkMarks.get(a);
        if (existing) {
          placeMark(a, existing);
          marks.set(existing, a.href);
          continue;
        }
        let u;
        try {
          u = new URL(a.href);
        } catch {
          continue;
        }
        if (u.protocol !== "https:" || !hosts.has(u.hostname) || !/\.(jpe?g|png|webp|gif|webm|mp4)$/i.test(u.pathname)) continue;
        a.dataset.ldgMarked = "1";
        const label = `select ${u.pathname.split("/").pop()} for collage`;
        const orphan = a.matches("a.fileThumb") && [...a.closest(".file")?.querySelectorAll("button[data-ldg-mark]") || []].find((b) => !marks.has(b) && b.getAttribute("aria-label") === label);
        const button = orphan || document.createElement("button");
        button.type = "button";
        button.dataset.ldgMark = "1";
        button.style.cssText = "display:inline-block;font:inherit;line-height:1;height:1em;min-height:0;width:9ch;padding:0;margin:0 0 0 4px;border:0;background:yellow;color:black;vertical-align:baseline;white-space:nowrap;cursor:pointer";
        button.setAttribute("aria-label", label);
        marks.set(button, u.href);
        linkMarks.set(a, button);
        placeMark(a, button);
        button.onclick = () => {
          if (controller) return;
          scan();
          const e = entries.get(u.href);
          if (!e) return;
          e.selected = !e.selected;
          count();
          persist();
          syncMarks();
        };
      }
      syncMarks();
    }
    const observer = new MutationObserver((records) => {
      const files = /* @__PURE__ */ new Set();
      for (const record of records) {
        const file = record.target instanceof Element && record.target.closest(".file");
        if (file) files.add(file);
        for (const node of record.addedNodes) markLinks(node);
      }
      for (const file of files) markLinks(file);
    });
    markLinks(document.body);
    observer.observe(document.body, { childList: true, subtree: true });
    count();
  }
  function fetchBlob(url, signal, budget) {
    return new Promise((resolve, reject) => {
      check(signal);
      let request, done = false;
      const finish = (err, blob) => {
        if (done) return;
        done = true;
        signal.removeEventListener("abort", abort);
        err ? reject(err) : resolve(blob);
      };
      const abort = () => {
        finish(signal.reason);
        request?.abort();
      };
      signal.addEventListener("abort", abort, { once: true });
      try {
        request = GM_xmlhttpRequest({
          method: "GET",
          url,
          responseType: "blob",
          timeout: 6e4,
          onprogress: (e) => {
            if (e.loaded > budget || e.lengthComputable && e.total > budget) {
              finish(new Error("download exceeds remaining memory budget"));
              request?.abort();
            }
          },
          onload: (r) => {
            if (r.status !== 200) finish(new Error(`download failed (${r.status}): ${url}`));
            else try {
              const blob = normalizeBlob(r.response);
              if (blob.size > budget) finish(new Error("invalid or oversized download"));
              else finish(null, blob);
            } catch (e) {
              finish(e);
            }
          },
          onerror: () => finish(new Error(`download failed: ${url}`)),
          ontimeout: () => finish(new Error(`download timed out: ${url}`)),
          onabort: () => finish(new Error("download aborted"))
        });
      } catch (e) {
        finish(e);
      }
    });
  }
})();
