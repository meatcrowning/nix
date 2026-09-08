import {
  Input, BlobSource, MP4, WEBM, MATROSKA, VideoSampleSink,
  Output, BufferTarget, WebMOutputFormat, Mp4OutputFormat, CanvasSource, canEncodeVideo,
} from 'mediabunny';

export const LIMITS = Object.freeze({ items: 64, videos: 8, bytes: 256 * 1024 ** 2,
  sourcePixels: 32 * 1024 ** 2, videoPixels: 24 * 1024 ** 2 });
// Yield to input/cancellation without the nested-timer clamp on every frame.
// No animation frames: export must not depend on visible-tab refresh rate.
let channel;
const pending = [];
export const yieldTask = () => new Promise(resolve => {
  if (typeof MessageChannel === 'undefined') { setTimeout(resolve, 0); return; }
  if (!channel) {
    channel = new MessageChannel();
    channel.port1.onmessage = () => pending.shift()?.();
  }
  pending.push(resolve); channel.port2.postMessage(null);
});
export function check(signal) {
  if (signal?.aborted) throw signal.reason || new DOMException('cancelled', 'AbortError');
}
export const isVideo = format => format === 'webm' || format === 'mp4';
export function normalizeBlob(value) {
  if (value instanceof Blob) return value;
  // Userscript managers may return a Blob from a different JS realm.
  if (!['[object Blob]', '[object File]'].includes(Object.prototype.toString.call(value)))
    throw new Error('invalid media file');
  const blob = new Blob([value], { type: value.type });
  if (blob.size !== value.size) throw new Error('browser could not read the media file');
  return blob;
}
export function dimensions(w, h) {
  if (!Number.isFinite(w * h) || w < 1 || h < 1 || w * h > LIMITS.sourcePixels)
    throw new Error('source exceeds 32 megapixels or has invalid dimensions');
}
export function options(raw = {}) {
  const o = { format: 'webm', fps: 30, duration: 5, edge: 1280, aspect: 1,
    maxBytes: 4_000_000, ...raw };
  if (!['webm', 'mp4', 'jpeg', 'png'].includes(o.format) || ![15, 24, 30, 60].includes(o.fps)
    || !Number.isFinite(o.duration) || o.duration < 1 || o.duration > 15
    || !Number.isFinite(o.edge) || o.edge < 320 || o.edge > (isVideo(o.format) ? 2048 : 4096)
    || !Number.isFinite(o.aspect) || o.aspect < 0.25 || o.aspect > 4
    || !Number.isFinite(o.maxBytes) || o.maxBytes < 100_000 || o.maxBytes > 32_000_000)
    throw new Error('invalid export settings');
  o.frameCount = Math.round(o.duration * o.fps);
  o.duration = o.frameCount / o.fps;
  return o;
}
export function canvas(w, h) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const ctx = c.getContext('2d', { alpha: false, colorSpace: 'srgb' });
  if (!ctx) throw new Error('2d canvas is unavailable');
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, w, h);
  return { canvas: c, ctx };
}
export function canvasBlob(c, type, quality) {
  return new Promise((resolve, reject) => c.toBlob(b => b ? resolve(b)
    : reject(new Error('image encoding failed')), type, quality));
}

// Justified rows preserve source aspect ratios and order. Dynamic programming
// selects row breaks; no random layout or completion-order-dependent placement.
export function layout(media, edge, aspect = 1, header = false) {
  if (!media.length) throw new Error('select at least one file');
  if (header && media.length > 1) {
    const body = layout(media.slice(1), edge, aspect);
    const headerH = body.width * media[0].height / media[0].width;
    const scale = Math.min(1, edge / (body.height + headerH));
    const width = Math.max(2, Math.floor(body.width * scale / 2) * 2);
    const height = Math.max(2, Math.floor((body.height + headerH) * scale / 2) * 2);
    const hh = Math.round(headerH * scale);
    return { width, height, placements: [{ index: 0, x: 0, y: 0, width, height: hh },
      ...body.placements.map(p => ({ index: p.index + 1, x: Math.round(p.x * width / body.width),
        y: hh + Math.round(p.y * (height - hh) / body.height),
        width: Math.max(1, Math.round(p.width * width / body.width)),
        height: Math.max(1, Math.round(p.height * (height - hh) / body.height)) }))] };
  }
  const ratios = media.map(m => m.width / m.height);
  const ideal = Math.sqrt(1 / (aspect * ratios.reduce((a, b) => a + b, 0)));
  const cost = [0], prev = [0];
  for (let end = 1; end <= ratios.length; end++) {
    cost[end] = Infinity; let sum = 0;
    for (let start = end - 1; start >= 0; start--) {
      sum += ratios[start];
      const h = 1 / sum, score = cost[start] + (h - ideal) ** 2;
      if (score < cost[end]) { cost[end] = score; prev[end] = start; }
    }
  }
  const rows = []; let end = ratios.length;
  while (end) { const start = prev[end]; rows.unshift([start, end]); end = start; }
  const heights = rows.map(([a, b]) => 1 / ratios.slice(a, b).reduce((s, r) => s + r, 0));
  const height = heights.reduce((a, b) => a + b, 0);
  const widthPx = Math.max(2, Math.floor(edge / Math.max(1, height) / 2) * 2);
  const heightPx = Math.max(2, Math.floor(widthPx * height / 2) * 2);
  const placements = []; let y = 0;
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
  if (['pq', 'hlg', 'smpte2084', 'arib-std-b67'].includes(color?.transfer))
    throw new Error('HDR video needs tone mapping; use an SDR source');
}

// Each source is fetched once by the UI. Metadata/decode passes reuse that Blob.
// No ImageDecoder requirement: ordinary static image decoding works on older browsers.
export async function prepare(blob, signal, edge = 2048) {
  check(signal);
  blob = normalizeBlob(blob);
  if (!blob.size) throw new Error('empty media file');
  const head = new Uint8Array(await blob.slice(0, 16).arrayBuffer());
  const image = /image\//.test(blob.type) || head[0] === 0xff && head[1] === 0xd8
    || head[0] === 0x89 && head[1] === 0x50 || String.fromCharCode(...head.slice(0, 3)) === 'GIF'
    || String.fromCharCode(...head.slice(8, 12)) === 'WEBP';
  if (image) {
    const url = URL.createObjectURL(blob), img = new Image();
    try {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => finish(new Error('image decode timed out')), 30000);
        const abort = () => finish(signal.reason);
        const finish = error => { clearTimeout(timer); signal?.removeEventListener('abort', abort);
          img.onload = img.onerror = null; error ? reject(error) : resolve(); };
        img.onload = () => finish(); img.onerror = () => finish(new Error('cannot decode image'));
        signal?.addEventListener('abort', abort, { once: true }); img.src = url;
      });
      check(signal); dimensions(img.naturalWidth, img.naturalHeight);
      const w = img.naturalWidth, h = img.naturalHeight;
      const scale = Math.min(1, edge / Math.max(w, h));
      const tile = canvas(Math.max(1, Math.round(w * scale)), Math.max(1, Math.round(h * scale)));
      tile.ctx.drawImage(img, 0, 0, tile.canvas.width, tile.canvas.height);
      return { kind: 'image', blob, width: w, height: h, pixels: tile.canvas.width * tile.canvas.height,
        async paint(ctx, p) {
          check(signal);
          ctx.drawImage(tile.canvas, p.x, p.y, p.width, p.height);
        }, dispose() { tile.canvas.width = tile.canvas.height = 1; } };
    } finally { img.src = ''; URL.revokeObjectURL(url); }
  }
  if (typeof VideoDecoder === 'undefined') throw new Error('this browser has no WebCodecs video decoder');
  const input = new Input({ source: new BlobSource(blob), formats: [MP4, WEBM, MATROSKA] });
  try {
    const track = await input.getPrimaryVideoTrack();
    if (!track || !await track.canDecode()) throw new Error('this browser cannot decode this video codec');
    rejectHDR(await track.getColorSpace());
    const width = await track.getDisplayWidth(), height = await track.getDisplayHeight();
    dimensions(width, height);
    const start = await track.getFirstTimestamp(), end = await track.computeDuration();
    if (!Number.isFinite(end - start) || end <= start) throw new Error('video has invalid timestamps');
    check(signal);
    return { kind: 'video', blob, input, track, width, height, start, duration: end - start,
      dispose() { input.dispose(); } };
  } catch (e) { input.dispose(); throw e; }
}

function* times(m, o) {
  const span = Math.max(1, Math.round(m.duration * 1e6));
  const start = Math.round(m.start * 1e6);
  for (let i = 0; i < o.frameCount; i++) yield (start + Math.round(i * 1e6 / o.fps) % span) / 1e6;
}

export async function exportCollage(blobs, raw, signal, progress = () => {}) {
  const o = options(raw); const media = [];
  let total = 0, videoPixels = 0, videoCount = 0, imagePixels = 0;
  if (!blobs.length || blobs.length > LIMITS.items) throw new Error('select 1–64 files');
  for (const b of blobs) total += b.size;
  if (total > LIMITS.bytes) throw new Error('selected files exceed 256 MiB');
  try {
    for (let i = 0; i < blobs.length; i++) {
      check(signal); progress(`reading ${i + 1}/${blobs.length}`);
      const m = await prepare(blobs[i], signal, o.edge); media.push(m);
      imagePixels += m.pixels || 0;
      if (imagePixels > LIMITS.sourcePixels) throw new Error('still images exceed 32 megapixels after resizing; split this collage');
      if (m.kind === 'video') {
        videoPixels += m.width * m.height; videoCount++;
        if (videoCount > LIMITS.videos || videoPixels > LIMITS.videoPixels)
          throw new Error('use at most 8 videos totalling 24 megapixels; split this collage');
      }
      await yieldTask();
    }
    const l = layout(media, o.edge, o.aspect, o.header);
    const base = canvas(l.width, l.height);
    try {
      for (const p of l.placements) {
        const m = media[p.index]; check(signal);
        if (m.kind === 'image') {
          await m.paint(base.ctx, p);
          // The composited base is reused by every frame and bitrate retry.
          // Release redundant tile canvases before allocating video decoders.
          m.dispose();
        } else if (!isVideo(o.format)) {
          const s = await new VideoSampleSink(m.track).getSample(m.start);
          if (!s) throw new Error('video has no first frame');
          try { rejectHDR(s.colorSpace); s.draw(base.ctx, p.x, p.y, p.width, p.height); } finally { s.close(); }
        }
      }
      if (!isVideo(o.format)) return await encodeImage(base.canvas, o, signal, progress);
      if (typeof VideoEncoder === 'undefined') throw new Error('this browser has no WebCodecs video encoder');
      let bitrate = Math.floor(o.maxBytes * 8 * 0.88 / o.duration);
      const codec = await selectCodec(o.format, l.width, l.height, bitrate);
      for (let attempt = 1; attempt <= 3; attempt++) {
        const result = await encodeVideo(media, l, base.canvas, o, codec, bitrate, signal, progress, attempt);
        if (result.blob.size <= o.maxBytes) return result;
        bitrate = Math.floor(bitrate * o.maxBytes / result.blob.size * 0.8);
        check(signal); await yieldTask();
      }
      throw new Error('video exceeds the size limit after 3 passes; reduce dimensions or duration');
    } finally { base.canvas.width = base.canvas.height = 1; }
  } finally { for (const m of media) m.dispose(); }
}

// Probe the actual export mode, not a browser name, CPU count, or hardware-only
// preference. macOS and Linux on the same machine can expose different codecs.
export async function selectCodec(format, width, height, bitrate, probe = canEncodeVideo) {
  for (const codec of format === 'mp4' ? ['avc'] : ['vp8', 'vp9']) {
    if (await probe(codec, { width, height, bitrate, latencyMode: 'quality',
      hardwareAcceleration: 'no-preference' })) return codec;
  }
  throw new Error(format === 'mp4'
    ? 'this browser cannot encode mp4 at these dimensions; try webm or image output'
    : 'this browser cannot encode webm at these dimensions; try mp4 or image output');
}

async function encodeImage(c, o, signal, progress) {
  if (o.format === 'png') {
    check(signal); progress('encoding png'); const blob = await canvasBlob(c, 'image/png');
    check(signal);
    if (blob.size > o.maxBytes) throw new Error('png exceeds the size limit; choose jpeg or smaller dimensions');
    return { blob, extension: 'png', width: c.width, height: c.height };
  }
  let low = 0.35, high = 0.95, best = null;
  for (let i = 0; i < 7; i++) {
    check(signal); progress(`encoding jpeg ${i + 1}/7`);
    const quality = i === 0 ? high : (low + high) / 2;
    const blob = await canvasBlob(c, 'image/jpeg', quality);
    if (blob.size <= o.maxBytes) { best = blob; low = quality; if (i === 0) break; }
    else high = quality;
    await yieldTask();
  }
  check(signal);
  if (!best) throw new Error('jpeg exceeds the size limit; reduce dimensions');
  return { blob: best, extension: 'jpg', width: c.width, height: c.height };
}

async function encodeVideo(media, l, base, o, codec, bitrate, signal, progress, attempt) {
  const target = new BufferTarget();
  const output = new Output({ format: o.format === 'mp4' ? new Mp4OutputFormat() : new WebMOutputFormat(), target });
  const frame = canvas(l.width, l.height);
  const stamps = [];
  const source = new CanvasSource(frame.canvas, { codec, bitrate, latencyMode: 'quality', hardwareAcceleration: 'no-preference',
    keyFrameInterval: 2, onEncodedPacket: packet => { stamps.push(packet.timestamp); } });
  output.addVideoTrack(source, { frameRate: o.fps });
  const readers = new Map();
  const abort = () => { for (const m of media) if (m.input) m.input.dispose(); };
  signal?.addEventListener('abort', abort, { once: true });
  let finalized = false;
  try {
    check(signal); await output.start();
    for (const p of l.placements) {
      const m = media[p.index];
      if (m.kind === 'video') readers.set(p.index, new VideoSampleSink(m.track).samplesAtTimestamps(times(m, o)));
    }
    for (let i = 0; i < o.frameCount; i++) {
      check(signal);
      frame.ctx.drawImage(base, 0, 0);
      for (const p of l.placements) {
        const reader = readers.get(p.index); if (!reader) continue;
        const { value: sample } = await reader.next();
        if (!sample) throw new Error(`missing source frame at output frame ${i + 1}`);
        try { rejectHDR(sample.colorSpace); sample.draw(frame.ctx, p.x, p.y, p.width, p.height); }
        finally { sample.close(); }
      }
      // Presentation time is independent of how long decoding/drawing took.
      await source.add(i / o.fps, 1 / o.fps);
      progress(`pass ${attempt}: frame ${i + 1}/${o.frameCount}`);
      await yieldTask();
    }
    check(signal); source.close(); await output.finalize(); finalized = true;
    check(signal);
    stamps.sort((a, b) => a - b);
    if (stamps.length !== o.frameCount || stamps.some((t, i) => Math.abs(t - i / o.fps) > 0.00001))
      throw new Error('encoder returned missing or mistimed frames');
    return { blob: new Blob([target.buffer], { type: `video/${o.format}` }), extension: o.format,
      width: l.width, height: l.height, frames: stamps.length, fps: o.fps, duration: o.duration };
  } finally {
    signal?.removeEventListener('abort', abort);
    for (const reader of readers.values()) await reader.return().catch(() => {});
    if (!finalized) await output.cancel().catch(() => {});
    frame.canvas.width = frame.canvas.height = 1;
  }
}
