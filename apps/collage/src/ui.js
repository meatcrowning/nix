import { exportCollage, LIMITS, check, isVideo, normalizeBlob, parseAspect } from './engine.js';

const hosts = new Set(['i.4cdn.org', 'files.catbox.moe', 'litter.catbox.moe', 'uguu.se']);
const id = 'ldg-collage-v2';
if (!document.getElementById(id)) init();

function init() {
  const host = document.createElement('div'); host.id = id;
  document.body.append(host);
  const root = host.attachShadow({ mode: 'open' });
  // Self-contained dark controls; thread selection buttons retain their yellow fill.
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
    .tile { border:1px solid GrayText; padding:4px; overflow-wrap:anywhere; }
    .tile img { width:100%; height:90px; object-fit:contain; }
    .tile .source-preview { display:block; width:100%; min-height:90px; }
    .source-preview img { pointer-events:none; }
    .tile label { display:block; } .tile input { vertical-align:middle; }
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
      <label>scale <input id="edge" type="range" min="320" max="2048" step="2" value="1280"><output id="scale-value" for="edge">100% · 1280px</output></label>
      <button id="export">create collage</button><button id="cancel" disabled>cancel</button>
    </div>
    <details id="advanced"><summary>advanced</summary>
    <div class="bar">
      <label>add files <input id="files" type="file" accept="image/*,video/webm,video/mp4" multiple></label>
      <label>header image <input id="header" type="file" accept="image/*"></label></div>
    <div class="bar">
      <label>output <select id="format"><option value="auto">automatic</option><option value="webm">video · webm</option><option value="mp4">video · mp4 (h.264)</option><option value="jpeg">image · jpeg</option><option value="png">image · png</option></select></label>
      <label>fps <select id="fps"><option>15</option><option>24</option><option selected>30</option><option>60</option></select></label>
      <label>seconds <input id="duration" type="number" min="0.01" max="300" step="any" placeholder="auto" size="6"></label>
      <label>limit (MB) <input id="limit" type="number" min="0.1" max="32" step="0.1" value="4" size="3"></label>
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
  const $ = name => root.getElementById(name);
  for (const name of ['format', 'edge', 'aspect', 'fps', 'duration', 'limit', 'parts'])
    $(name).setAttribute('aria-label', { format: 'output', edge: 'scale', aspect: 'aspect ratio',
      fps: 'fps', duration: 'seconds', limit: 'limit (MB)', parts: 'collages' }[name]);
  const entries = new Map(); let header = null, controller = null;
  const storageKey = `ldg-collage-v2:${location.pathname}`;
  let remembered = new Set();
  try {
    const saved = localStorage.getItem(storageKey);
    const thread = /\/thread\/(\d+)/.exec(location.pathname)?.[1];
    const legacy = JSON.parse(localStorage.getItem(`highlightedImages_${thread}`) || '[]');
    remembered = new Set(saved !== null ? JSON.parse(saved) : legacy.map(e => e.fullSrc));
  } catch {}
  const message = text => { $('message').textContent = text; };
  const warningKey = 'ldg-collage-hide-large-video-warning';
  let warningAccepted = false;
  function warnLargeJob(info, signal) {
    let hidden = false;
    try { hidden = typeof GM_getValue === 'function' ? GM_getValue(warningKey, false) === true : localStorage.getItem(warningKey) === 'true'; } catch {}
    if (hidden || warningAccepted) return Promise.resolve();
    check(signal);
    return new Promise((resolve, reject) => {
      const dialog = $('warning');
      $('warning-text').textContent = `${info.videos} videos · ${(info.pixels / 1e6).toFixed(1)} MP. this large collage may slow or freeze your browser, run out of memory, or fail to export. slow rendering alone does not make the output choppy`;
      $('warning-remember').checked = false; $('warning-error').textContent = '';
      const focus = root.activeElement;
      const finish = error => {
        signal.removeEventListener('abort', abort);
        dialog.close(); $('panel').inert = false; $('open').disabled = false;
        dialog.oncancel = $('warning-continue').onclick = $('warning-cancel').onclick = null;
        focus?.focus(); error ? reject(error) : resolve();
      };
      const abort = () => finish(signal.reason || new DOMException('cancelled', 'AbortError'));
      $('warning-continue').onclick = () => {
        if ($('warning-remember').checked) {
          try {
            if (typeof GM_setValue === 'function') GM_setValue(warningKey, true);
            else localStorage.setItem(warningKey, 'true');
          } catch { $('warning-error').textContent = 'preference could not be saved; uncheck to continue once'; return; }
        }
        warningAccepted = true; finish();
      };
      $('warning-cancel').onclick = () => controller.abort(new DOMException('cancelled', 'AbortError'));
      dialog.oncancel = e => { e.preventDefault(); $('warning-cancel').click(); };
      signal.addEventListener('abort', abort, { once:true });
      dialog.showModal(); $('panel').inert = true; $('open').disabled = true; $('warning-continue').focus();
    });
  }
  const persist = () => {
    try { remembered = new Set([...entries.values()].filter(e => e.selected && e.url).map(e => e.url));
      localStorage.setItem(storageKey, JSON.stringify([...remembered])); }
    catch { message('selection could not be saved; browser storage is full'); }
  };
  const count = () => {
    $('count').textContent = `${[...entries.values()].filter(e => e.selected).length}/${entries.size} selected`;
    for (const e of entries.values()) if (e.tile) e.tile.hidden = $('view').value === 'selected' && !e.selected;
  };
  $('view').onchange = count;
  $('edge').oninput = () => { $('scale-value').value = `${Math.round(Number($('edge').value) / 12.8)}% · ${$('edge').value}px`; };
  function add(entry) {
    if (entries.has(entry.key)) return;
    entries.set(entry.key, entry);
    const tile = document.createElement('div'); tile.className = 'tile';
    const show = document.createElement('button'); show.className = 'source-preview';
    show.setAttribute('aria-label', `preview ${entry.name}`);
    if (entry.thumb) { const img = new Image(); img.src = entry.thumb; img.loading = 'lazy'; img.alt = ''; show.append(img); }
    else show.textContent = 'preview';
    show.onclick = () => {
      if (!entry.url && !entry.previewUrl) entry.previewUrl = URL.createObjectURL(entry.file);
      const video = entry.file?.type.startsWith('video/') || /\.(webm|mp4)(?:[?#]|$)/i.test(entry.url || entry.name);
      openPreview(entry.url || entry.previewUrl, video, show);
    };
    tile.append(show);
    const label = document.createElement('label'), box = document.createElement('input');
    box.type = 'checkbox'; box.checked = !!entry.selected;
    box.addEventListener('change', () => { entry.selected = box.checked; count(); persist(); syncMarks(); });
    label.append(box, document.createTextNode(` ${entry.name}`)); tile.append(label);
    entry.box = box; entry.tile = tile; $('list').append(tile); count();
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
      if (entries.has(key)) continue;
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
    closePreview();
    for (const [key, e] of entries) if (e.file) {
      if (e.thumb) URL.revokeObjectURL(e.thumb);
      if (e.previewUrl) URL.revokeObjectURL(e.previewUrl);
      e.tile.remove(); entries.delete(key);
    }
    header = null; $('header').value = ''; $('files').value = '';
    count(); persist(); syncMarks();
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
    if (Math.ceil(chosen.length / parts) + (header ? 1 : 0) > LIMITS.items) {
      message('at most 64 files per collage; increase collages or select fewer files'); return;
    }
    let aspect;
    try { aspect = parseAspect($('aspect').value); } catch (e) { message(e.message); $('aspect').focus(); return; }
    const opts = { format: $('format').value, edge: Number($('edge').value), aspect,
      fps: Number($('fps').value), duration: $('duration').value === '' ? 'auto' : Number($('duration').value), maxBytes: Number($('limit').value) * 1e6 };
    warningAccepted = false;
    controller = new AbortController(); const signal = controller.signal;
    const controls = [...$('panel').querySelectorAll('button,input,select')].filter(el => !['close', 'cancel'].includes(el.id));
    const disabled = controls.map(e => e.disabled); controls.forEach(e => { e.disabled = true; }); $('cancel').disabled = false;
    closePreview();
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
          text => message(`collage ${part + 1}/${parts}: ${text}`), info => warnLargeJob(info, signal));
        check(signal);
        const url = URL.createObjectURL(result.blob);
        const link = document.createElement('a'); link.href = url;
        const board = location.pathname.split('/')[1] || 'custom';
        const thread = /\/thread\/(\d+)/.exec(location.pathname)?.[1] || 'custom';
        link.download = `highlights_${board}_${thread}_${Math.floor(Date.now() / 1000)}_${part + 1}.${result.extension}`;
        link.hidden = true; root.append(link);
        try { link.click(); }
        finally {
          link.remove();
          // Firefox consumes the URL asynchronously. Do not revoke on the next export.
          setTimeout(() => URL.revokeObjectURL(url), 60000);
        }
      }
      // An anchor cannot confirm a disk write or bypass browser download permissions.
      message(`${parts} download${parts === 1 ? '' : 's'} requested; check browser downloads`);
    } catch (e) { message(signal.aborted ? 'cancelled' : e.message || String(e)); }
    finally { controls.forEach((el, i) => { el.disabled = disabled[i]; }); $('cancel').disabled = true; controller = null; }
  };
  let previewFocus;
  function closePreview() {
    const media = $('preview').querySelector('img,video');
    if (media) { if (media.tagName === 'VIDEO') { media.pause(); media.removeAttribute('src'); media.load(); } media.remove(); }
    const wasOpen = !$('preview').hidden;
    if ($('preview').open) $('preview').close();
    $('preview').hidden = true; $('panel').inert = false; $('open').disabled = false;
    if (wasOpen) previewFocus?.focus();
  }
  function openPreview(url, video, trigger) {
    closePreview(); previewFocus = trigger;
    const media = document.createElement(video ? 'video' : 'img'); media.src = url;
    if (video) { media.controls = true; media.loop = true; media.muted = true; media.playsInline = true; }
    else media.alt = 'collage preview';
    $('preview-status').textContent = '';
    media.onerror = () => { $('preview-status').textContent = 'this file could not be previewed'; };
    if (!video) media.onclick = closePreview;
    $('preview').append(media); $('preview').hidden = false; $('preview').showModal();
    $('panel').inert = true; $('open').disabled = true; $('preview-close').focus();
    if (video) media.play().catch(() => {}); // Native controls remain available.
  }
  $('preview-close').onclick = closePreview;
  $('preview').oncancel = e => { e.preventDefault(); closePreview(); };
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
      button.textContent = button.getAttribute('aria-pressed') === 'true' ? 'collage −' : 'collage +';
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
      button.style.cssText = 'display:inline-block;font:inherit;line-height:1;height:1em;min-height:0;width:9ch;padding:0;margin:0 0 0 4px;border:0;background:yellow;color:black;vertical-align:baseline;white-space:nowrap;cursor:pointer';
      button.setAttribute('aria-label', `select ${u.pathname.split('/').pop()} for collage`);
      marks.set(button, u.href);
      const info = a.matches('a.fileThumb') && a.closest('.file')?.querySelector('.fileText, .file-info');
      if (info) info.append(button); else a.after(button);
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
