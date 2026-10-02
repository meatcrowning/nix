// Steam owns live shortcuts; the backend owns launchers and metadata.
export async function importRom(request, { backend, apps, allApps, refresh, hasArtwork = () => true }) {
  const prepared = await backend('prepare', request);
  const candidates = [prepared.existingAppId, prepared.expectedAppId].filter(Boolean);
  const existing = allApps.find(app => candidates.includes(app.appid));
  if (existing && (existing.display_name !== prepared.title || !existing.BIsShortcut?.()))
    throw new Error('This shortcut ID belongs to another game. Import stopped without changing it.');
  const appid = existing?.appid || await apps.AddShortcut(prepared.title, `"${prepared.exe}"`, prepared.options, '');
  if (!Number.isInteger(appid) || appid <= 0) throw new Error('Steam could not add this shortcut. Try again.');
  // Persist the returned ID before artwork or property changes; retry is idempotent.
  await backend('finish', { slug: prepared.slug, appid });
  let warning = prepared.warning;
  try {
    await apps.SetShortcutStartDir(appid, `"${prepared.startDir}"`);
    await apps.SetShortcutLaunchOptions(appid, prepared.options);
    if (prepared.portrait && (!existing || !hasArtwork(existing)))
      await apps.SetCustomArtworkForApp(appid, prepared.portrait, 'png', 0);
  } catch (error) {
    warning = `Game added, but Steam could not apply all properties or artwork: ${error.message || error}`;
  }
  await refresh();
  return { appid, title: prepared.title, warning };
}
