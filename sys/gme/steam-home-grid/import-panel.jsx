import React, { useState, useEffect, useRef, useLayoutEffect } from 'react';
import { callable } from '@decky/api';
import { importRom } from './import-client.mjs';
import { RomBrowser } from './rom-browser.jsx';

const backend = callable('rom_import');
export function ImportPanel({ Focusable, TextField, close, imported }) {
  const [config, setConfig] = useState(null), [systemIndex, setSystemIndex] = useState(0);
  const [browsing, setBrowsing] = useState(false), [confirmRegionMismatch, setConfirmRegionMismatch] = useState(false);
  const [path, setPath] = useState(''), [query, setQuery] = useState('');
  const [matches, setMatches] = useState(null), [match, setMatch] = useState(null);
  const [year, setYear] = useState(''), [developer, setDeveloper] = useState('');
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [result, setResult] = useState(null);
  const first = useRef(null), active = useRef(true), locked = useRef(false);
  const system = config?.systems[systemIndex];
  useEffect(() => {
    active.current = true;
    backend('systems', {}).then(value => { if (active.current) setConfig(value); })
      .catch(e => { if (active.current) setError(e.message); });
    return () => { active.current = false; };
  }, []);
  useLayoutEffect(() => { if (!busy) first.current?.TakeFocus(); }, [!!config, !!match, !!result, busy, browsing]);
  const job = async (label, action) => {
    if (locked.current) return;
    locked.current = true; setBusy(label); setError('');
    try { await action(); }
    catch (e) { if (active.current) setError(e.message || String(e)); }
    finally { locked.current = false; if (active.current) setBusy(''); }
  };
  const reset = () => { setMatches(null); setMatch(null); setResult(null); };
  const changeSystem = step => {
    if (!config || locked.current) return true;
    setSystemIndex((systemIndex + step + config.systems.length) % config.systems.length); reset();
    return true;
  };
  const browse = () => setBrowsing(true);
  const pickFile = filename => {
    setPath(filename); setQuery(filename.split('/').pop().replace(/\.[^.]+$/, '')); reset(); setBrowsing(false);
  };
  const search = () => job('Searching game catalog…', async () => {
    const found = await backend('search', { system: system.id, path, query });
    if (active.current) { setMatches(found.matches); setPath(found.path); }
  });
  const choose = entry => { setMatch(entry); setYear(entry.year); setDeveloper(entry.developer); setConfirmRegionMismatch(false); };
  const add = () => job('Adding game and artwork…', async () => {
    const added = await importRom({ system: system.id, path, match: match.id, year, developer, confirmRegionMismatch },
      { backend, apps: window.SteamClient.Apps, allApps: window.appStore.allApps, refresh: imported,
        hasArtwork: (app, type) => !!(type === 1 ? window.appStore.GetCustomHeroImageURLs(app) : window.appStore.GetCustomVerticalCapsuleURLs(app)).length });
    if (active.current) setResult(added);
  });
  const back = () => { if (!locked.current) { if (match && !result) setMatch(null); else close(); } return true; };
  const button = (label, action, primary = false) => <Focusable className="hlg-sort-option" noFocusRing
    focusable={!busy} aria-disabled={!!busy} role="button" onActivate={() => { if (!locked.current) action(); }}
    navRef={primary ? ref => { first.current = ref; } : undefined} onOKActionDescription="Select">{label}</Focusable>;
  if (browsing) return <RomBrowser Focusable={Focusable} backend={backend} system={system}
    home={config.home} pick={pickFile} close={() => setBrowsing(false)} />;
  if (!TextField) return <Focusable className="hlg-sort-menu hlg-import-menu" autoFocus onCancel={back}>
    <div className="hlg-audio-error">Steam’s text input is unavailable. Reopen Steam to retry.</div>{button('Back', close, true)}
  </Focusable>;
  return <Focusable className="hlg-sort-menu hlg-import-menu" flow-children="column" autoFocus focusableIfEmpty
    role="dialog" aria-modal="true" aria-label="Import ROM" onCancel={back} onCancelActionDescription="Back">
    <h2>Import ROM</h2>
    <div className="hlg-sort-note">The ROM stays where it is. Keep its drive connected when playing.</div>
    {result ? <>
      <div className="hlg-sort-note" role="status">Added {result.title} to your library.</div>
      {result.warning && <div className="hlg-sort-note">{result.warning}</div>}
      {button('Done', close, true)}
      {button('Import another ROM', () => { reset(); setPath(''); setQuery(''); })}
    </> : match ? <>
      <div className="hlg-sort-note">{match.title} · {system.label}</div>
      <div className="hlg-import-fields">
        <TextField label="Developer" value={developer} disabled={!!busy} onChange={e => setDeveloper(e.target.value)} />
        <TextField label="Release year" value={year} disabled={!!busy} onChange={e => setYear(e.target.value)} />
      </div>
      <div className="hlg-sort-note">Confirm the console version and credits. Fill in any missing fields before adding.</div>
      {match.regionMismatch && <>
        <div className="hlg-audio-error">This region does not match the ROM filename.</div>
        {button(confirmRegionMismatch ? 'Use different region: confirmed' : 'Confirm using this different region',
          () => setConfirmRegionMismatch(value => !value), true)}
      </>}
      {(!match.regionMismatch || confirmRegionMismatch) && button('Add to library', add, !match.regionMismatch)}
      {button('Choose a different match', () => setMatch(null))}
    </> : config ? <>
      <Focusable className="hlg-sort-option" noFocusRing focusable={!busy} role="button"
        navRef={ref => { first.current = ref; }} onActivate={() => changeSystem(1)}
        onMoveLeft={() => changeSystem(-1)} onMoveRight={() => changeSystem(1)} onOKActionDescription="Change console">
        Console: {system.label}<span>
          <button tabIndex={-1} onClick={e => { e.stopPropagation(); changeSystem(-1); }}>‹</button>
          <button tabIndex={-1} onClick={e => { e.stopPropagation(); changeSystem(1); }}>›</button>
        </span>
      </Focusable>
      {button(path ? 'ROM: ' + path.split('/').pop() : 'Choose ROM file…', browse)}
      {path && <>
        <div className="hlg-import-fields"><TextField label="Game title" value={query} disabled={!!busy}
          onChange={e => { setQuery(e.target.value); setMatches(null); }} /></div>
        {button('Search metadata', search)}
      </>}
      {matches && <div className="hlg-sort-note">{matches.length ? 'Choose the matching game and region:' : 'No matches. Try a shorter title or check the console.'}</div>}
      {matches?.map(entry => <React.Fragment key={entry.id}>{button(
        `${entry.regionMismatch ? 'Different region · ' : ''}${entry.title} — ${entry.year || 'Year unknown'} · ${entry.developer || 'Developer unknown'}`, () => choose(entry))}</React.Fragment>)}
      {button('Back', close)}
    </> : <div className="hlg-sort-note">Loading import settings…</div>}
    {busy && <div className="hlg-sort-note" role="status">{busy}</div>}
    {error && <div className="hlg-audio-error" role="alert">{error}</div>}
  </Focusable>;
}
