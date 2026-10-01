import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';

const labels = { Default: 'Steam default', 'Nintendo GameCube Menu SFX': 'GameCube',
  'Kingdom Hearts Menu': 'Kingdom Hearts', 'NFS Underground PS2 Beta UI sounds': 'NFS Underground',
  'Metal Gear Solid SFX Pack for AudioLoader': 'Metal Gear Solid', 'Xbox 360 Metro UI Sounds': 'Xbox 360 Metro' };
export function AudioPanel({ Focusable, close }) {
  const [audio, setAudio] = useState(null), [error, setError] = useState('');
  const latest = useRef(null), rows = useRef(new Map()), revision = useRef(0), pending = useRef(0);
  useEffect(() => {
    const refresh = () => {
      if (pending.current) return;
      const next = window.SteamHomeAudio?.read();
      if (next?.sounds.length) { latest.current = next; setAudio(next); }
    };
    refresh(); const timer = setInterval(refresh, 500);
    return () => clearInterval(timer);
  }, []);
  useLayoutEffect(() => { if (audio) rows.current.get(0)?.TakeFocus(); }, [!!audio]);
  const write = async changes => {
    const version = ++revision.current; pending.current++;
    const next = { ...latest.current, ...changes }; latest.current = next; setAudio(next); setError('');
    try {
      const saved = await window.SteamHomeAudio.write(changes);
      if (version === revision.current) { latest.current = saved; setAudio(saved); }
    } catch (e) { setError(e.message || 'Could not save audio settings'); }
    finally { pending.current--; }
  };
  const sound = step => {
    const a = latest.current, choices = ['Default', ...a.sounds];
    const i = choices.indexOf(a.sound);
    write({sound: choices[(i + step + choices.length) % choices.length]}); return true;
  };
  const volume = (key, step) => { write({[key]: Math.max(0, Math.min(1, Math.round(latest.current[key] * 10 + step) / 10))}); return true; };
  const ambience = () => { const a = latest.current; write({music:'PS2 Ambience',musicEnabled: !(a.musicEnabled && a.music !== 'None')}); return true; };
  const row = (index, label, value, left, right, slider = false) => <Focusable key={index}
    className="hlg-audio-row" focusable noFocusRing navRef={ref => { if (ref) rows.current.set(index,ref); else rows.current.delete(index); }}
    onMoveUp={detail => { rows.current.get(Math.max(0,index-1))?.TakeFocus(detail.button); return true; }}
    onMoveDown={detail => { rows.current.get(Math.min(3,index+1))?.TakeFocus(detail.button); return true; }}
    onMoveLeft={left} onMoveRight={right} onActivate={right} onOKActionDescription="Change"
    aria-label={`${label}: ${value}`} role={slider ? 'slider' : 'button'}
    aria-valuemin={slider ? 0 : undefined} aria-valuemax={slider ? 100 : undefined} aria-valuenow={slider ? parseInt(value) : undefined}>
    <span>{label}</span><div className="hlg-audio-value">
      <button tabIndex={-1} aria-label={`Decrease ${label}`} onClick={e=>{e.stopPropagation();left();}}>‹</button>
      <strong>{value}</strong><button tabIndex={-1} aria-label={`Increase ${label}`} onClick={e=>{e.stopPropagation();right();}}>›</button>
    </div>
  </Focusable>;
  return <Focusable className="hlg-sort-menu hlg-audio-menu" flow-children="column" autoFocus focusableIfEmpty
    role="dialog" aria-label="Audio settings" onCancel={()=>{close();return true;}} onCancelActionDescription="Close"
    onMoveUp={()=>true} onMoveDown={()=>true} onMoveLeft={()=>true} onMoveRight={()=>true}>
    <div className="hlg-sort-note">Left / Right to change · Back to close</div>
    {audio ? <>
      {row(0,'Menu sounds',labels[audio.sound] || audio.sound,()=>sound(-1),()=>sound(1))}
      {row(1,'Sound volume',`${Math.round(audio.soundVolume*100)}%`,()=>volume('soundVolume',-1),()=>volume('soundVolume',1),true)}
      {row(2,'PS2 ambience',audio.musicEnabled && audio.music!=='None' ? 'On' : 'Off',ambience,ambience)}
      {row(3,'Ambience volume',`${Math.round(audio.musicVolume*100)}%`,()=>volume('musicVolume',-1),()=>volume('musicVolume',1),true)}
      <div className="hlg-sort-note">Choose Steam default to disable a sound pack. Volume 0 mutes menu sounds. Ambience is experimental.</div>
    </> : <div className="hlg-sort-note">Audio settings are loading…</div>}
    {error && <div className="hlg-audio-error" role="alert">{error}</div>}
  </Focusable>;
}
