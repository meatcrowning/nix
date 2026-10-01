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
