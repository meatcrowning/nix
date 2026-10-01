// Only local installs belong in the first group; remote streaming availability
// and Steam's numeric display_status are not evidence of a local installation.
export function libraryGroups(apps) {
  const ready = [], available = [], seen = new Set();
  for (const app of apps) {
    if (!app.appid || seen.has(app.appid)) continue;
    seen.add(app.appid);
    const shortcut = app.BIsShortcut?.() ?? app.app_type === 1073741824;
    if (!shortcut && app.app_type !== 1 && !app.BIsDemo?.()) continue;
    if (app.visible_in_game_list === false || app.BIsAppBlocked?.()) continue;
    const local = app.local_per_client_data ?? app.per_client_data?.find(c => String(c.clientid) === '0');
    if (shortcut || local?.installed) ready.push(app);
    else if ((app.BIsOwned?.() ?? app.subscribed_to) && !app.BIsUnreleased?.()
      && local?.is_available_on_current_platform && !local?.is_invalid_os_type) available.push(app);
  }
  const alphabetic = (a, b) => (a.sort_as || a.display_name).localeCompare(b.sort_as || b.display_name)
    || a.appid - b.appid;
  ready.sort((a, b) => (b.rt_last_time_played || 0) - (a.rt_last_time_played || 0) || alphabetic(a, b));
  available.sort(alphabetic);
  return { ready, available };
}

export function edgeFades(top, height, total) {
  return { top: top > 2, bottom: top + height < total - 2 };
}

export function revealScroll(top, height, cardTop, cardHeight, margin = 22) {
  if (cardTop < top + margin) return Math.max(0, cardTop - margin);
  if (cardTop + cardHeight > top + height - margin) return cardTop + cardHeight - height + margin;
  return top;
}

export function metadataLine(app, details = {}) {
  if (!app) return '';
  const timestamp = app.rt_original_release_date || app.rt_steam_release_date;
  const year = details.year || (timestamp ? new Date(timestamp * 1000).getUTCFullYear() : '');
  const platform = systemName(app, details);
  return [platform, year, details.developer].filter(Boolean).join(' · ');
}

// Strip only explicit platform suffixes, preserving years and edition names.
export function displayTitle(app) {
  return (app?.display_name || '').replace(/\s*[([{](?:PC|PS1|PS2|PS3|PSP|PlayStation(?: 2| 3| Portable)?|GameCube|GC|NES|SNES|Nintendo 64|N64|Game Boy(?: Advance| Color)?|GBA|GBC|GB)[)\]}]\s*$/i, '').trim();
}

export function systemName(app, details = {}) {
  return details.console || (app && !app.BIsShortcut?.() ? 'PC' : '');
}

export function adjacentApp(apps, appid, step) {
  const index = apps.findIndex(app => app.appid === appid);
  return index < 0 ? undefined : apps[index + step];
}

export const sortModes = [
  ['recent', 'Recently played'], ['title', 'Title A–Z'], ['console', 'Console'],
  ['newest', 'Newest first'], ['oldest', 'Oldest first'], ['developer', 'Developer'],
];
export const validSort = value => sortModes.some(([id]) => id === value) ? value : 'recent';

export function librarySections(groups, metadata, mode) {
  const title = (a, b) => displayTitle(a).localeCompare(displayTitle(b)) || a.appid - b.appid;
  const details = app => metadata[app.appid] || {};
  const year = app => Number(details(app).year) || new Date((app.rt_original_release_date || app.rt_steam_release_date || 0) * 1000).getUTCFullYear();
  const release = app => details(app).year || app.rt_original_release_date || app.rt_steam_release_date ? year(app) : null;
  const category = app => mode === 'console' ? systemName(app, details(app)) || 'Other systems'
    : details(app).developer || 'Unknown developer';
  const compare = (a, b) => {
    if (mode === 'recent') return (b.rt_last_time_played || 0) - (a.rt_last_time_played || 0) || title(a, b);
    if (mode === 'newest' || mode === 'oldest') {
      const ay = release(a), by = release(b);
      return (ay === null) - (by === null) || (ay !== null && by !== null ? (ay - by) * (mode === 'newest' ? -1 : 1) : 0) || title(a, b);
    }
    return title(a, b);
  };
  const sections = [];
  for (const [key, downloadable] of [['ready', false], ['available', true]]) {
    const apps = [...groups[key]];
    if (mode === 'console' || mode === 'developer') {
      const buckets = new Map();
      for (const app of apps) {
        const label = category(app);
        if (!buckets.has(label)) buckets.set(label, []);
        buckets.get(label).push(app);
      }
      for (const label of [...buckets.keys()].sort((a, b) => a.localeCompare(b))) {
        sections.push({ key: `${key}-${label}`, label: label + (downloadable ? ' · Available to install' : ''),
          system: mode === 'console' ? label : null, apps: buckets.get(label).sort(title), downloadable });
      }
    } else if (apps.length) sections.push({ key, label: downloadable ? 'Available to install' : '', apps: apps.sort(compare), downloadable });
  }
  return sections;
}
