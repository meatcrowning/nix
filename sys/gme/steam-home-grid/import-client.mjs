// AddShortcut can return an ID before Steam has applied the requested fields.
// Observe the native details callback; a returned ID alone is not success.
export function verifyShortcut(apps, appid, expected, timeout = 8000) {
  return new Promise((resolve, reject) => {
    let subscription, done = false;
    const unquote = value => String(value || '').replace(/^"(.*)"$/, '$1');
    const finish = error => {
      if (done) return;
      done = true; clearTimeout(timer); subscription?.unregister();
      if (error) reject(error); else resolve();
    };
    const timer = setTimeout(() => finish(new Error('Steam did not save the correct game name or launch command. Retry the import.')), timeout);
    try {
      subscription = apps.RegisterForAppDetails(appid, details => {
        if (details?.strDisplayName === expected.title
          && unquote(details.strShortcutExe) === expected.exe
          && unquote(details.strShortcutStartDir) === expected.startDir
          && (details.strShortcutLaunchOptions ?? details.strLaunchOptions) === expected.options) finish();
      });
      if (done) subscription?.unregister();
    } catch (error) { finish(error); }
  });
}

export async function importRom(request, { backend, apps, allApps, refresh, hasArtwork = () => true, verify = verifyShortcut }) {
  const prepared = await backend('prepare', request);
  const candidates = [prepared.existingAppId, prepared.expectedAppId].filter(Boolean);
  const existing = allApps.find(app => candidates.includes(app.appid));
  if (existing && ((existing.display_name !== prepared.title && existing.appid !== prepared.existingAppId) || !existing.BIsShortcut?.()))
    throw new Error('This shortcut ID belongs to another game. Import stopped without changing it.');
  // Pass an unquoted executable, with empty optional fields: Steam quotes it
  // internally. Set the name/options explicitly after creation on every build.
  const appid = existing?.appid || await apps.AddShortcut(prepared.title, prepared.exe, '', '');
  if (!Number.isInteger(appid) || appid <= 0) throw new Error('Steam could not add this shortcut. Try again.');
  await backend('record', { slug: prepared.slug, appid });
  await apps.SetShortcutExe(appid, `"${prepared.exe}"`);
  await apps.SetShortcutStartDir(appid, `"${prepared.startDir}"`);
  await apps.SetShortcutLaunchOptions(appid, prepared.options);
  await apps.SetShortcutName(appid, prepared.title);
  await verify(apps, appid, prepared);
  // Required properties are verified before committing metadata or reporting success.
  const warnings = prepared.warning ? [prepared.warning] : [];
  for (const asset of prepared.artwork || []) {
    if (existing && hasArtwork(existing, asset.type)) continue;
    try { await apps.SetCustomArtworkForApp(appid, asset.data, asset.extension, asset.type); }
    catch { warnings.push(`${asset.label} could not be applied. Retry the import to fill it in.`); }
  }
  await backend('finish', { slug: prepared.slug, appid });
  await refresh();
  return { appid, title: prepared.title, warning: warnings.join(' ') };
}
