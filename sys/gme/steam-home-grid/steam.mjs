// Some Decky components install getters on contextType that temporarily stub
// React. Do not use the SDK's CommonUIModule scan: reading those getters while
// discovering an unrelated component can leave Steam's React stubbed globally.
export function findFocusable(requireModule) {
  for (const id of Object.keys(requireModule.m)) {
    let module;
    try { module = requireModule(id); } catch { continue; }
    for (const candidate of [module, ...Object.values(module || {})]) {
      const render = typeof candidate === 'function' ? candidate : candidate?.render;
      if (typeof render === 'function' && /const\{"flow-children":\w+,onActivate:/.test(String(render))) return candidate;
    }
  }
  throw new Error('Steam controller navigation component was not found');
}

export function steamNavigation() {
  const win = window.SteamUIStore.GetFocusedWindowInstance();
  if (!win) throw new Error('No active Steam window');
  return win;
}
