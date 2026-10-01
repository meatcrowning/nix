import React from 'react';

// Small hardware silhouettes keep system identity legible in monochrome.
export function SystemIcon({ system }) {
  let shape;
  if (!system) return null;
  if (system === 'PC') shape = <><rect x="3" y="3" width="18" height="13" rx="1"/><path d="M12 16v5m-5 0h10"/></>;
  else if (/Game Boy Advance|PSP|PlayStation Portable/.test(system)) shape = <><rect x="1" y="6" width="22" height="12" rx="4"/><rect x="8" y="8" width="8" height="8" rx="1"/><path d="M3 12h4m-2-2v4m13-3h1m1 2h1"/></>;
  else if (/Game Boy/.test(system)) shape = <><path d="M6 2h12v16l-4 4H6z"/><rect x="8" y="5" width="8" height="7" rx="1"/><path d="M8 16h4m-2-2v4m4-2h1m1-2h1"/></>;
  else if (system === 'GameCube') shape = <><path d="m12 2 9 5v10l-9 5-9-5V7zm-9 5 9 5 9-5M12 12v10"/><path d="m8 6 4-2 4 2-4 2z"/></>;
  else if (system === 'PlayStation 2') shape = <><path d="M3 5h18v14H3zm0 4h18M5 12h10m-10 3h7m5 0h2"/></>;
  else if (system === 'PlayStation') shape = <><rect x="2" y="5" width="20" height="14" rx="2"/><circle cx="12" cy="11" r="5"/><path d="M4 8h1m14 0h1M6 17h4m4 0h4"/></>;
  else if (/Nintendo 64|N64/.test(system)) shape = <><path d="M3 8q9-6 18 0v11H3zM7 5V3h10v2M6 13v2m4-2v2m4-2v2m4-2v2"/></>;
  else if (/SNES|Super Nintendo/.test(system)) shape = <><rect x="2" y="6" width="20" height="13" rx="3"/><path d="M7 6V4h10v2M7 9h10M6 13v3m3-3v3m6 1h3"/></>;
  else shape = <><rect x="2" y="5" width="20" height="14" rx="1"/><path d="M2 14h20M7 5v9m3-6h9M5 17h2m3 0h2"/></>;
  return <svg className="hlg-system-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">{shape}</svg>;
}
