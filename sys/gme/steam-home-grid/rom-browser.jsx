import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';

// Keep file navigation in the same native column flow as the library popup.
// Decky's bundled picker still emits the obsolete flow-children="right".
export function RomBrowser({ Focusable, backend, system, home, pick, close }) {
  const [folder, setFolder] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const rows = useRef(new Map()), active = useRef(true), pending = useRef(false);
  const load = async (path, offset = 0) => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError('');
    try {
      const next = await backend('browse', { system: system.id, path, offset });
      if (active.current) setFolder(next);
    } catch (e) { if (active.current) setError(e.message || String(e)); }
    finally { pending.current = false; if (active.current) setBusy(false); }
  };
  useEffect(() => { active.current = true; load(home); return () => { active.current = false; }; }, []);
  useLayoutEffect(() => { if (!busy) rows.current.get(0)?.TakeFocus(); }, [folder, busy]);
  const back = () => { close(); return true; };
  const items = [
    ['Cancel', close], ['Home', () => load(home)], ['Downloads', () => load(`${home}/Downloads`)],
    ['Mounted drives', () => load(`/run/media/${home.split('/').pop()}`)],
    ...(folder && folder.parent !== folder.path ? [['Parent folder', () => load(folder.parent)]] : []),
    ...(folder?.offset > 0 ? [['Previous page', () => load(folder.path, folder.offset - 100)]] : []),
    ...(folder?.entries || []).map(entry => [entry.name + (entry.directory ? '/' : ''),
      () => entry.directory ? load(entry.path) : pick(entry.path)]),
    ...(folder && folder.offset + 100 < folder.total ? [['Next page', () => load(folder.path, folder.offset + 100)]] : []),
  ];
  return <Focusable className="hlg-sort-menu hlg-import-menu" flow-children="column" autoFocus focusableIfEmpty
    role="dialog" aria-modal="true" aria-label="Choose ROM file" onCancel={back} onCancelActionDescription="Cancel"
    onMoveUp={() => true} onMoveDown={() => true} onMoveLeft={() => true} onMoveRight={() => true}>
    <h2>Choose ROM · {system.label}</h2>
    <div className="hlg-sort-note">{folder?.path || home}</div>
    {items.map(([label, action], index) => <Focusable key={`${folder?.path}-${label}`} className="hlg-sort-option"
      role="button" noFocusRing focusable={!busy} aria-disabled={busy}
      navRef={ref => { if (ref) rows.current.set(index, ref); else rows.current.delete(index); }}
      onGamepadFocus={e => (e.currentTarget || e.target)?.scrollIntoView({block:'nearest'})}
      onMoveUp={detail => { rows.current.get(Math.max(0, index - 1))?.TakeFocus(detail.button); return true; }}
      onMoveDown={detail => { rows.current.get(Math.min(items.length - 1, index + 1))?.TakeFocus(detail.button); return true; }}
      onActivate={() => { if (!pending.current) action(); }} onOKActionDescription="Select">{label}</Focusable>)}
    {busy && <div className="hlg-sort-note" role="status">Loading folder…</div>}
    {!busy && folder?.entries.length === 0 && <div className="hlg-sort-note">No supported ROM files or folders here.</div>}
    {error && <div className="hlg-audio-error" role="alert">{error}</div>}
  </Focusable>;
}
