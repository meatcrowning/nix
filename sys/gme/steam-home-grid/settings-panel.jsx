import React, { useLayoutEffect, useRef } from 'react';
import { sortModes } from './model.mjs';

export function SettingsPanel({ Focusable, sortMode, controllersOnly, chooseSort, toggleControllers, audio, importRom, close }) {
  const rows = useRef(new Map());
  useLayoutEffect(() => { rows.current.get(0)?.TakeFocus(); }, []);
  const sort = step => {
    const index = sortModes.findIndex(([id]) => id === sortMode);
    chooseSort(sortModes[(index + step + sortModes.length) % sortModes.length][0]);
    return true;
  };
  const items = [
    ['Sort', sortModes.find(([id]) => id === sortMode)[1], () => sort(1), () => sort(-1)],
    ['Controller support only', controllersOnly ? 'On' : 'Off', toggleControllers, toggleControllers],
    ['Audio settings', '›', audio], ['Import ROM', '›', importRom], ['Close', '', close],
  ];
  return <Focusable className="hlg-sort-menu hlg-settings-menu" role="dialog" aria-modal="true" aria-label="Library settings"
    flow-children="column" autoFocus onCancel={close} onCancelActionDescription="Close"
    onMoveUp={() => true} onMoveDown={() => true} onMoveLeft={() => true} onMoveRight={() => true}>
    <h2>Library settings</h2>
    <div className="hlg-sort-note">Changes apply immediately · Installed games first</div>
    {items.map(([label, value, activate, left], index) => <Focusable key={label}
      className="hlg-sort-option" noFocusRing role={index === 1 ? 'switch' : 'button'}
      aria-checked={index === 1 ? controllersOnly : undefined} aria-label={`${label}: ${value}`}
      navRef={ref => { if (ref) rows.current.set(index, ref); else rows.current.delete(index); }}
      onMoveUp={detail => { rows.current.get(Math.max(0, index - 1))?.TakeFocus(detail.button); return true; }}
      onMoveDown={detail => { rows.current.get(Math.min(items.length - 1, index + 1))?.TakeFocus(detail.button); return true; }}
      onMoveLeft={left || (() => true)} onMoveRight={left ? activate : () => true}
      onActivate={activate} onOKActionDescription={left ? 'Change' : 'Select'}>
      <span>{label}</span><span>{left && <button tabIndex={-1} aria-label={`Previous ${label}`} onClick={e => { e.stopPropagation(); left(); }}>‹</button>}
        {value}{left && <button tabIndex={-1} aria-label={`Next ${label}`} onClick={e => { e.stopPropagation(); activate(); }}>›</button>}</span>
    </Focusable>)}
    <div className="hlg-sort-note">Controller support includes full, partial and emulator support. Partial support may still need a keyboard.</div>
  </Focusable>;
}
