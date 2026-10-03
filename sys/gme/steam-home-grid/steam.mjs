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

// Native text fields provide Steam's controller keyboard without the SDK's
// CommonUIModule scan (see the contextType getter constraint above).
export function findTextField(requireModule) {
  for (const id of Object.keys(requireModule.m)) {
    let module;
    try { module = requireModule(id); } catch { continue; }
    for (const candidate of [module, ...Object.values(module || {})]) {
      if (!candidate || !['function', 'object'].includes(typeof candidate)) continue;
      if (typeof Object.getOwnPropertyDescriptor(candidate, 'validateUrl')?.value === 'function'
        && typeof Object.getOwnPropertyDescriptor(candidate, 'validateEmail')?.value === 'function') return candidate;
    }
  }
  return null;
}

// Reuse Steam's own launch-options dialog, including its controller navigation.
// Find the export by its purpose, not a webpack ID that changes between builds.
export function findLaunchOptionsDialog(requireModule) {
  for (const [id, factory] of Object.entries(requireModule.m)) {
    if (!String(factory).includes('showing launch options')) continue;
    for (const value of Object.values(requireModule(id))) {
      if (typeof value === 'function' && String(value).includes('showing launch options')) return value;
    }
  }
  throw new Error('Steam launch options dialog is unavailable');
}
