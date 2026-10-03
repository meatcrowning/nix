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

// Importing the SDK Menu also evaluates its CommonUIModule scan, which reads
// trampoline contextType getters. Discover only the native menu exports here.
export function findLaunchMenu(requireModule) {
  let showContextMenu, Menu, MenuItem;
  for (const id of Object.keys(requireModule.m)) {
    let module;
    try { module = requireModule(id); } catch { continue; }
    const exports = Object.values(module || {});
    for (const value of exports) {
      const source = typeof value === 'function' ? String(value) : '';
      if (source.includes('GetContextMenuManagerFromWindow(') && source.includes('.CreateContextMenuInstance(')) showContextMenu = value;
      const render = value && Object.getOwnPropertyDescriptor(value, 'render')?.value;
      if ((typeof render === 'function' && String(render).includes('bPlayAudio:'))
        || (value?.prototype?.OnOKButton && value?.prototype?.OnMouseEnter)) {
        MenuItem = value;
        Menu ||= exports.find(candidate => typeof candidate === 'function'
          && String(candidate).includes('useId') && String(candidate).includes('labelId'));
      }
      if (value?.prototype?.HideIfSubmenu && value?.prototype?.HideMenu) Menu = value;
    }
    if (showContextMenu && Menu && MenuItem) return {showContextMenu, Menu, MenuItem};
  }
  throw new Error('Steam mode menu components are unavailable');
}
