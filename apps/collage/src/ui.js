import { exportCollage, LIMITS, check, isVideo, normalizeBlob } from './engine.js';

const hosts = new Set(['i.4cdn.org', 'files.catbox.moe', 'litter.catbox.moe', 'uguu.se']);
const id = 'ldg-collage-v2';
if (!document.getElementById(id)) init();

function init() {
  const host = document.createElement('div'); host.id = id;
  document.body.append(host);
  const root = host.attachShadow({ mode: 'open' });
  // Inherit the page's typography/colours. No local desktop service or font download.
  root.innerHTML = `<style>
    :host { font: inherit; color: inherit; }
    * { box-sizing: border-box; }
    button,input,select { font: inherit; color: inherit; }
    button,a,input,select { min-height: 28px; }
    button { cursor: pointer; } button:disabled { cursor: default; }
    :focus-visible { outline: 2px solid Highlight; outline-offset: 2px; }
    #open { position:fixed; bottom:8px; right:8px; z-index:2147483647; }
    #panel { position:fixed; inset:4%; z-index:2147483647; background:Canvas;
      color:CanvasText; border:1px solid; padding:8px; overflow:auto; font:15px sans-serif; }
    [hidden] { display:none !important; }
    .bar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px; }
    #list { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:4px; }
    .tile { border:1px solid GrayText; padding:4px; overflow-wrap:anywhere; }
    .tile img { width:100%; height:90px; object-fit:contain; }
    .tile label { display:block; } .tile input { vertical-align:middle; }
    #message { white-space:pre-wrap; overflow-wrap:anywhere; }
    #close { margin-left:auto; }
    #results { display:flex; flex-wrap:wrap; gap:8px; }
    #results article { max-width:240px; }
    #results a { display:block; padding:4px 0; }
    #results img,#results video { width:100%; max-height:180px; object-fit:contain; }
    #preview { position:fixed; inset:0; z-index:2147483647; background:#000; color:#fff;
      display:flex; align-items:center; justify-content:center; }
    #preview img,#preview video { max-width:100%; max-height:100%; object-fit:contain; }
    #preview-close { position:absolute; top:8px; right:8px; z-index:1; }
    summary { cursor:pointer; min-height:28px; }
    .help { font-size:0.9em; } fieldset { border:0; padding:0; margin:0; }
  </style>
  <button id="open" aria-expanded="false" aria-controls="panel">collage</button>
  <section id="panel" role="dialog" aria-modal="true" aria-label="collage" hidden>
    <div class="bar"><button id="close" aria-label="close collage">X</button></div>
    <fieldset id="settings">
    <div class="bar">
      <label>aspect ratio <select id="aspect"><option value="1">1:1</option><option value="1.7777777778">16:9</option><option value="0.5625">9:16</option></select></label>
      <label>scale <select id="edge"><option value="640">50% · 640px</option><option value="960">75% · 960px</option><option value="1280" selected>100% · 1280px</option><option value="1920">150% · 1920px</option><option value="2048">160% · 2048px</option></select></label>
      <button id="export">create collage</button><button id="cancel" disabled>cancel</button>
    </div>
    <details id="advanced"><summary>advanced</summary>
    <div class="bar">
      <label>add files <input id="files" type="file" accept="image/*,video/webm,video/mp4" multiple></label>
      <label>header image <input id="header" type="file" accept="image/*"></label></div>
    <div class="bar">
      <label>output <select id="format"><option value="auto">automatic</option><option value="webm">video · webm</option><option value="mp4">video · mp4 (h.264)</option><option value="jpeg">image · jpeg</option><option value="png">image · png</option></select></label>
      <label>fps <select id="fps"><option>15</option><option>24</option><option selected>30</option><option>60</option></select></label>
      <label>seconds <input id="duration" type="number" min="1" max="15" step="1" value="5" size="3"></label>
      <label>limit (MB) <input id="limit" type="number" min="0.1" max="32" step="0.1" value="4" size="3"></label>
      <label>collages <input id="parts" type="number" min="1" max="16" step="1" value="1" size="3"></label>
    </div></details></fieldset>
    <div class="bar"><button id="all">select all</button><button id="none">select none</button>
      <button id="clear">clear list</button><span id="count"></span></div>
    <div id="list" aria-label="media selection"></div>
    <p id="message" role="status" aria-live="polite"></p><div id="results"></div>
  </section>
  <section id="preview" role="dialog" aria-modal="true" aria-label="collage preview" hidden>
    <button id="preview-close" aria-label="close preview">X</button>
  </section>`;
  const $ = name => root.getElementById(name);
  for (const name of ['format', 'edge', 'aspect', 'fps', 'duration', 'limit', 'parts'])
    $(name).setAttribute('aria-label', { format: 'output', edge: 'scale', aspect: 'aspect ratio',
      fps: 'fps', duration: 'seconds', limit: 'limit (MB)', parts: 'collages' }[name]);
  const entries = new Map(); const resultUrls = []; let header = null, controller = null;
  const storageKey = `ldg-collage-v2:${location.pathname}`;
  let remembered = new Set();
  try {
    const saved = localStorage.getItem(storageKey);
    const thread = /\/thread\/(\d+)/.exec(location.pathname)?.[1];
    const legacy = JSON.parse(localStorage.getItem(`highlightedImages_${thread}`) || '[]');
    remembered = new Set(saved !== null ? JSON.parse(saved) : legacy.map(e => e.fullSrc));
  } catch {}
  const message = text => { $('message').textContent = text; };
  const persist = () => {
    try { remembered = new Set([...entries.values()].filter(e => e.selected && e.url).map(e => e.url));
      localStorage.setItem(storageKey, JSON.stringify([...remembered])); }
    catch { message('selection could not be saved; browser storage is full'); }
  };
  const count = () => { $('count').textContent = `${[...entries.values()].filter(e => e.selected).length}/${entries.size} selected`; };
  function add(entry) {
    if (entries.has(entry.key)) return;
    if (entries.size >= LIMITS.items) { message('list limit: 64 files'); return; }
    entries.set(entry.key, entry);
    const tile = document.createElement('div'); tile.className = 'tile';
    if (entry.thumb) { const img = new Image(); img.src = entry.thumb; img.loading = 'lazy'; img.alt = ''; tile.append(img); }
    const label = document.createElement('label'), box = document.createElement('input');
    box.type = 'checkbox'; box.checked = !!entry.selected;
    box.addEventListener('change', () => { entry.selected = box.checked; count(); persist(); syncMarks(); });
    label.append(box, document.createTextNode(` ${entry.name}`)); tile.append(label);
    const up = document.createElement('button'); up.textContent = 'move earlier';
    up.onclick = () => {
      if (controller) return;
      const items = [...entries.values()], i = items.indexOf(entry);
      if (i < 1) return;
      [items[i - 1], items[i]] = [items[i], items[i - 1]];
      entries.clear(); for (const item of items) entries.set(item.key, item);
      tile.parentNode.insertBefore(tile, tile.previousElementSibling); persist();
    };
    tile.append(up); entry.box = box; entry.tile = tile; $('list').append(tile); count();
  }
  function scan() {
    for (const a of document.querySelectorAll('a.fileThumb, .postMessage a[href]')) {
      let url; try { url = new URL(a.href); } catch { continue; }
      if (url.protocol !== 'https:' || !hosts.has(url.hostname)
        || !/\.(?:jpe?g|png|webp|gif|webm|mp4)$/i.test(url.pathname)) continue;
      add({ key: url.href, url: url.href, name: url.pathname.split('/').pop(),
        thumb: a.matches('a.fileThumb') ? a.querySelector('img')?.src : null,
        selected: remembered.has(url.href) || a.closest('.highlighted') !== null });
    }
  }
  function addFiles(files) {
    for (const file of files) {
      if (!file.type.startsWith('image/') && !/\.(webm|mp4)$/i.test(file.name)) {
        message(`unsupported file: ${file.name}`); continue;
      }
      const key = `file:${file.name}:${file.size}:${file.lastModified}`;
      if (entries.has(key) || entries.size >= LIMITS.items) continue;
      const thumb = file.type.startsWith('image/') ? URL.createObjectURL(file) : null;
      add({ key, file, name: file.name, thumb, selected: true });
    }
    persist();
  }
  let previousFocus;
  $('open').onclick = () => { if (!$('panel').hidden) { $('close').click(); return; }
    previousFocus = document.activeElement; if (!controller) scan(); $('panel').hidden = false;
    $('open').setAttribute('aria-expanded', 'true'); $('close').focus();
    if (document.querySelector('.chan-hv-options-menu')) message('the old collage script is also running; disable its older copies in your userscript manager'); };
  $('close').onclick = () => { $('panel').hidden = true; $('open').setAttribute('aria-expanded', 'false'); previousFocus?.focus(); };
  $('panel').addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); $('close').click(); }
    if (e.key !== 'Tab') return;
    const focusable = [...$('panel').querySelectorAll('button,input,select,a[href],summary'), $('open')].filter(e => !e.disabled && e.getClientRects().length);
    const first = focusable[0], last = focusable.at(-1);
    if (e.shiftKey && root.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && root.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  $('files').onchange = e => { addFiles(e.target.files); e.target.value = ''; };
  $('header').onchange = e => { header = e.target.files[0] || null; };
  $('panel').ondragover = e => e.preventDefault();
  $('panel').ondrop = e => { e.preventDefault(); if (!controller) addFiles(e.dataTransfer.files); };
  for (const [name, selected] of [['all', true], ['none', false]]) $(name).onclick = () => {
    for (const entry of entries.values()) { entry.selected = selected; entry.box.checked = selected; } count(); persist(); syncMarks();
  };
  $('clear').onclick = () => {
    for (const e of entries.values()) if (e.file && e.thumb) URL.revokeObjectURL(e.thumb);
    entries.clear(); $('list').replaceChildren(); remembered.clear(); count(); persist(); syncMarks();
  };
  $('cancel').onclick = () => controller?.abort(new DOMException('cancelled', 'AbortError'));
  $('format').onchange = () => {
    const image = $('format').value !== 'auto' && !isVideo($('format').value); $('fps').disabled = $('duration').disabled = image;
  };
  $('export').onclick = async () => {
    if (controller) return;
    scan();
    const chosen = [...entries.values()].filter(e => e.selected);
    if (!chosen.length) { message('select at least one file'); return; }
    const parts = Number($('parts').value);
    if (!Number.isInteger(parts) || parts < 1 || parts > Math.min(16, chosen.length)) { message('invalid collage count'); return; }
    const opts = { format: $('format').value, edge: Number($('edge').value), aspect: Number($('aspect').value),
      fps: Number($('fps').value), duration: Number($('duration').value), maxBytes: Number($('limit').value) * 1e6 };
    controller = new AbortController(); const signal = controller.signal;
    const controls = [...$('panel').querySelectorAll('button,input,select')].filter(el => !['close', 'cancel'].includes(el.id));
    const disabled = controls.map(e => e.disabled); controls.forEach(e => { e.disabled = true; }); $('cancel').disabled = false;
    closePreview(); $('results').replaceChildren(); resultUrls.splice(0).forEach(url => URL.revokeObjectURL(url));
    try {
      const groups = Array.from({ length: parts }, () => []);
      chosen.forEach((entry, i) => groups[i % parts].push(entry));
      for (let part = 0; part < parts; part++) {
        const blobs = []; let bytes = header?.size || 0;
        if (header) blobs.push(header);
        for (const entry of groups[part]) {
          check(signal); message(`collage ${part + 1}/${parts}: loading ${blobs.length + 1}`);
          const blob = entry.file || await fetchBlob(entry.url, signal, LIMITS.bytes - bytes);
          bytes += blob.size;
          if (bytes > LIMITS.bytes) throw new Error('selected files exceed 256 MiB; split this collage');
          blobs.push(blob);
        }
        const result = await exportCollage(blobs, { ...opts, header: !!header }, signal,
          text => message(`collage ${part + 1}/${parts}: ${text}`));
        check(signal);
        const url = URL.createObjectURL(result.blob); resultUrls.push(url);
        const link = document.createElement('a'); link.href = url;
        const board = location.pathname.split('/')[1] || 'custom';
        const thread = /\/thread\/(\d+)/.exec(location.pathname)?.[1] || 'custom';
        link.download = `highlights_${board}_${thread}_${Math.floor(Date.now() / 1000)}_${part + 1}.${result.extension}`;
        link.textContent = `save collage ${part + 1} · ${result.width}×${result.height} · ${(result.blob.size / 1e6).toFixed(2)} MB`
          + (result.frames ? ` · ${result.frames} frames at ${result.fps} fps` : '');
        const card = document.createElement('article'), show = document.createElement('button');
        show.setAttribute('aria-label', `preview collage ${part + 1}`);
        const thumbnail = document.createElement(result.frames ? 'video' : 'img');
        thumbnail.src = url;
        if (result.frames) { thumbnail.muted = true; thumbnail.preload = 'metadata'; }
        else thumbnail.alt = `collage ${part + 1}`;
        show.append(thumbnail); show.onclick = () => openPreview(url, !!result.frames, show);
        card.append(show, link); $('results').append(card);
      }
      message('ready to save');
    } catch (e) { message(signal.aborted ? 'cancelled' : e.message || String(e)); }
    finally { controls.forEach((el, i) => { el.disabled = disabled[i]; }); $('cancel').disabled = true; controller = null; }
  };
  let previewFocus;
  function closePreview() {
    const media = $('preview').querySelector('img,video');
    if (media) { if (media.tagName === 'VIDEO') { media.pause(); media.removeAttribute('src'); media.load(); } media.remove(); }
    const wasOpen = !$('preview').hidden;
    $('preview').hidden = true; $('panel').inert = false; $('open').disabled = false;
    if (wasOpen) previewFocus?.focus();
  }
  function openPreview(url, video, trigger) {
    closePreview(); previewFocus = trigger;
    const media = document.createElement(video ? 'video' : 'img'); media.src = url;
    if (video) { media.controls = true; media.loop = true; media.muted = true; media.playsInline = true; }
    else media.alt = 'collage preview';
    $('preview').append(media); $('preview').hidden = false;
    $('panel').inert = true; $('open').disabled = true; $('preview-close').focus();
    if (video) media.play().catch(() => {}); // Native controls remain available.
  }
  $('preview-close').onclick = closePreview;
  $('preview').onclick = e => { if (e.target === $('preview')) closePreview(); };
  $('preview').onkeydown = e => {
    if (e.key === 'Escape') { e.preventDefault(); closePreview(); }
    if (e.key === 'Tab' && !$('preview').querySelector('video')) { e.preventDefault(); $('preview-close').focus(); }
  };
  // One small button per media link; process only newly inserted subtrees.
  // Marking works with a keyboard, touch or a mouse, without modifier keys.
  const marks = new Map();
  function syncMarks() {
    for (const [button, url] of marks) {
      if (!button.isConnected) { marks.delete(button); continue; }
      button.setAttribute('aria-pressed', String(entries.get(url)?.selected ?? remembered.has(url)));
      button.textContent = button.getAttribute('aria-pressed') === 'true' ? 'selected' : 'collage +';
      button.disabled = !!controller;
    }
  }
  function markLinks(node) {
    if (!(node instanceof Element) || node === host || node.hasAttribute('data-ldg-mark')) return;
    const links = node.matches('a.fileThumb, .postMessage a[href]') ? [node] : node.querySelectorAll('a.fileThumb, .postMessage a[href]');
    for (const a of links) {
      if (a.dataset.ldgMarked) continue;
      let u; try { u = new URL(a.href); } catch { continue; }
      if (u.protocol !== 'https:' || !hosts.has(u.hostname) || !/\.(jpe?g|png|webp|gif|webm|mp4)$/i.test(u.pathname)) continue;
      a.dataset.ldgMarked = '1';
      const button = document.createElement('button'); button.type = 'button'; button.dataset.ldgMark = '1';
      button.style.cssText = 'font:inherit;min-height:28px;cursor:pointer';
      button.setAttribute('aria-label', `select ${u.pathname.split('/').pop()} for collage`);
      marks.set(button, u.href); a.after(button);
      button.onclick = () => {
        if (controller) return;
        // Seed the complete remembered selection before saving changes.
        scan();
        const e = entries.get(u.href); if (!e) return;
        e.selected = !e.selected; e.box.checked = e.selected; count(); persist(); syncMarks();
      };
    }
    syncMarks();
  }
  const observer = new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) markLinks(node);
  });
  markLinks(document.body); observer.observe(document.body, { childList: true, subtree: true });
  count();
}

export function fetchBlob(url, signal, budget) {
  return new Promise((resolve, reject) => {
    check(signal);
    let request, done = false;
    const finish = (err, blob) => { if (done) return; done = true;
      signal.removeEventListener('abort', abort); err ? reject(err) : resolve(blob); };
    const abort = () => { finish(signal.reason); request?.abort(); };
    signal.addEventListener('abort', abort, { once: true });
    try {
      request = GM_xmlhttpRequest({ method: 'GET', url, responseType: 'blob', timeout: 60000,
        onprogress: e => { if (e.loaded > budget || e.lengthComputable && e.total > budget) {
          finish(new Error('download exceeds remaining memory budget')); request?.abort(); } },
        onload: r => {
          if (r.status !== 200) finish(new Error(`download failed (${r.status}): ${url}`));
          else try {
            const blob = normalizeBlob(r.response);
            if (blob.size > budget) finish(new Error('invalid or oversized download'));
            else finish(null, blob);
          } catch (e) { finish(e); }
        },
        onerror: () => finish(new Error(`download failed: ${url}`)),
        ontimeout: () => finish(new Error(`download timed out: ${url}`)),
        onabort: () => finish(new Error('download aborted')),
      });
    } catch (e) { finish(e); }
  });
}
