import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { findFocusable, findTextField, steamNavigation } from './steam.mjs';
import { afterPatch } from '@decky/ui/dist/utils/patcher';
import { definePlugin, routerHook, callable } from '@decky/api';
import { libraryGroups, edgeFades, revealScroll, metadataLine, controllerSupport, displayTitle, systemName, adjacentApp, librarySections, validSort, verticalNeighbor } from './model.mjs';
import css from './style.css';
import { SystemIcon } from './system-icon.jsx';
import { AudioPanel } from './audio-panel.jsx';
import { SettingsPanel } from './settings-panel.jsx';
import { ImportPanel } from './import-panel.jsx';
import { createHomeHistory } from './home-history.mjs';

const homeHistory = createHomeHistory();
const store = () => window.appStore;
const readMetadata = callable('library_metadata');
let Focusable, TextField;
function resolveSteamUI() {
  window.webpackChunksteamui.push([[Symbol('home-library-grid')], {}, requireModule => {
    Focusable = findFocusable(requireModule);
    TextField = findTextField(requireModule);
  }]);
}

function artwork(app, kind) {
  if (!app) return [];
  const s = store();
  if (kind === 'cover') return [...s.GetCustomVerticalCapsuleURLs(app),
    ...s.GetCachedVerticalCapsuleURL(app), s.GetVerticalCapsuleURLForApp(app)];
  const file = window.appDetailsStore?.GetAppDetails(app.appid)?.libraryAssets?.strHeroImage || 'library_hero.jpg';
  return [...s.GetCustomHeroImageURLs(app),
    `https://steamloopback.host/assets/${app.appid}/${file}?c=${app.local_cache_version || 0}`,
    ...(app.BIsShortcut() ? [] : [`https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/${app.appid}/${file}`])];
}

function Picture({ sources, className, lazy = false }) {
  const [index, setIndex] = useState(0);
  if (index >= sources.length) return null;
  return <img className={className} src={sources[index]} alt="" loading={lazy ? 'lazy' : 'eager'}
    draggable={false} onError={() => setIndex(i => i + 1)} />;
}

function HomeGrid() {
  const [sortMode, setSortMode] = useState(() => { try { return validSort(localStorage.getItem('home-library-grid-sort')); } catch { return 'recent'; } });
  const [controllersOnly, setControllersOnly] = useState(() => { try { return localStorage.getItem('home-library-grid-controllers') === 'true'; } catch { return false; } });
  const [panel, setPanel] = useState(null);
  const menuButton = useRef(null), returnToGrid = useRef(false);
  const openPanel = () => { setPanel('settings'); return true; };
  const closePanel = () => { returnToGrid.current = true; setPanel(null); return true; };
  const [metadata, setMetadata] = useState({});
  const [metadataReady, setMetadataReady] = useState(false);
  useEffect(() => {
    let active = true;
    readMetadata().then(data => { if (active) setMetadata(data || {}); })
      .catch(error => console.warn('[Home Library Grid] Metadata unavailable', error))
      .finally(() => { if (active) setMetadataReady(true); });
    return () => { active = false; };
  }, []);
  const [groups, setGroups] = useState(() => libraryGroups(store().allApps));
  const sections = librarySections(groups, metadata, sortMode, controllersOnly);
  const all = sections.flatMap(section => section.apps);
  const [selected, setSelected] = useState(() => all.find(a => a.appid === homeHistory.appid) || all[0]);
  const controller = controllerSupport(selected, metadata[selected?.appid]);
  const viewport = useRef(null);
  const navigation = useRef(new Map());
  const restoreFrame = useRef(null);
  const restoreReturn = () => {
    const el = viewport.current;
    if (!el || !homeHistory.pending || restoreFrame.current !== null) return;
    const win = el.ownerDocument.defaultView;
    restoreFrame.current = win.requestAnimationFrame(() => {
      restoreFrame.current = null;
      // Steam can retain an inactive route's DOM. Only restore visible Home.
      if (!el.getClientRects().length || panel || !metadataReady) return;
      if (!all.some(app => app.appid === homeHistory.pending?.appid)) {
        homeHistory.pending = null;
        return;
      }
      if (homeHistory.restore(navigation.current, el)) {
        setSelected(store().allApps.find(app => app.appid === homeHistory.appid));
        measure();
      }
    });
  };
  useLayoutEffect(() => { restoreReturn(); }, [groups, metadata, metadataReady, panel]);
  useEffect(() => {
    const win = viewport.current.ownerDocument.defaultView;
    return () => { if (restoreFrame.current !== null) win.cancelAnimationFrame(restoreFrame.current); };
  }, []);
  const focusGrid = detail => {
    (navigation.current.get(selected?.appid) || navigation.current.get(all[0]?.appid))?.TakeFocus(detail?.button);
    return true;
  };
  useLayoutEffect(() => {
    if (!panel && returnToGrid.current) {
      returnToGrid.current = false;
      if (all.length) focusGrid(); else menuButton.current?.TakeFocus();
    }
  }, [panel]);
  const verticalMove = (app, step, detail) => {
    const cards = [...viewport.current.querySelectorAll('.hlg-card')].map(el => ({appid:Number(el.dataset.appid),top:el.offsetTop,left:el.offsetLeft,width:el.offsetWidth}));
    const next = verticalNeighbor(cards, app.appid, step);
    if (next) navigation.current.get(next)?.TakeFocus(detail.button);
    else if (step < 0) menuButton.current?.TakeFocus(detail.button);
    return true;
  };
  const move = (app, step, detail) => {
    const next = adjacentApp(all, app.appid, step);
    // Consume horizontal movement at the library endpoints as well.
    if (next) navigation.current.get(next.appid)?.TakeFocus(detail.button);
    return true;
  };
  const [edges, setEdges] = useState({ top: false, bottom: false });
  const measure = () => {
    const el = viewport.current;
    if (!el) return;
    homeHistory.measure(el.scrollTop);
    const next = edgeFades(el.scrollTop, el.clientHeight, el.scrollHeight);
    setEdges(old => old.top === next.top && old.bottom === next.bottom ? old : next);
  };
  useEffect(() => {
    // Also pick up completed installs/uninstalls while Home remains open.
    const timer = setInterval(() => setGroups(libraryGroups(store().allApps)), 5000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!all.some(a => a.appid === selected?.appid)) setSelected(all[0]);
  }, [groups, metadata, controllersOnly, sortMode]);
  useLayoutEffect(() => {
    const el = viewport.current;
    el.scrollTop = homeHistory.scroll;
    const Observer = el.ownerDocument.defaultView.ResizeObserver;
    const observer = new Observer(measure);
    observer.observe(el);
    observer.observe(el.firstElementChild);
    measure();
    return () => observer.disconnect();
  }, []);
  const select = (app, element) => {
    if (!homeHistory.select(app.appid)) return;
    setSelected(app);
    const el = viewport.current;
    if (el && element) {
      const rect = element.getBoundingClientRect(), outer = el.getBoundingClientRect();
      el.scrollTop = revealScroll(el.scrollTop, el.clientHeight,
        rect.top - outer.top + el.scrollTop, rect.height);
      measure();
    }
  };
  const chooseSort = mode => {
    homeHistory.pending = null;
    setSortMode(mode);
    try { localStorage.setItem('home-library-grid-sort', mode); } catch {}
    homeHistory.scroll = 0;
    viewport.current.scrollTop = 0;
  };
  const toggleControllers = () => {
    homeHistory.pending = null;
    const next = !controllersOnly; setControllersOnly(next);
    try { localStorage.setItem('home-library-grid-controllers', String(next)); } catch {}
    homeHistory.scroll = 0; viewport.current.scrollTop = 0;
    return true;
  };
  const imported = async () => {
    setMetadata(await readMetadata());
    setGroups(libraryGroups(store().allApps));
  };
  const renderGroup = ({key, label, apps, downloadable, system}) => apps.length ? <React.Fragment key={key}>
    {label && <h2 className="hlg-section" aria-label={label}>{system ? <SystemIcon system={system} /> : label}{system && downloadable && <span>Available to install</span>}<span>{apps.length}</span></h2>}
    {apps.map(app => <Focusable key={app.appid} navKey={`game-${app.appid}`} className="hlg-card" noFocusRing
      navRef={handle => { if (handle) navigation.current.set(app.appid, handle); else navigation.current.delete(app.appid); }}
      onMoveRight={detail => move(app, 1, detail)} onMoveLeft={detail => move(app, -1, detail)}
      onMoveUp={detail => verticalMove(app, -1, detail)} onMoveDown={detail => verticalMove(app, 1, detail)}
      data-appid={app.appid} aria-label={`${displayTitle(app)}${downloadable ? ', available to install' : ''}`}
      preferredFocus={app.appid === (homeHistory.appid || all[0]?.appid)}
      onGamepadFocus={e => select(app, e.currentTarget || e.target)}
      onFocus={e => select(app, e.currentTarget)}
      onActivate={() => {
        homeHistory.leave(app.appid, viewport.current.scrollTop);
        steamNavigation().Navigate(`/library/app/${app.appid}`);
      }}
      onOKActionDescription="Select" onCancelActionDescription="Back"
      onSecondaryButton={openPanel} onSecondaryActionDescription="Library settings"
      onCancel={() => steamNavigation().NavigateBack()}>
      <span className="hlg-fallback">{displayTitle(app)}</span>
      <Picture key={`${app.appid}-${app.rt_custom_image_mtime}-${app.local_cache_version}`} sources={artwork(app, 'cover')} lazy />
      {downloadable && <span className="hlg-download" aria-hidden="true">↓</span>}
    </Focusable>)}
  </React.Fragment> : null;
  return <Focusable className="home-library-grid" navKey="home-library-grid" flow-children="column"
    onFocusWithin={focused => { if (focused) restoreReturn(); }}
    onSecondaryButton={!panel ? openPanel : undefined} onSecondaryActionDescription={!panel ? "Library settings" : undefined}>
    <style>{css}</style>
    <div className="hlg-hero"><Picture key={`${selected?.appid}-${selected?.rt_custom_image_mtime}`} sources={artwork(selected, 'hero')} /></div>
    <Focusable className="hlg-heading" flow-children="row" childFocusDisabled={!!panel}>
      <h1>{displayTitle(selected) || 'Your library'}</h1>
      <span className="hlg-metadata">{sortMode !== 'console' && <SystemIcon system={systemName(selected, metadata[selected?.appid])} />}{metadataLine(selected, metadata[selected?.appid])}
        {controller && <svg className="hlg-controller" data-support={controller.level} viewBox="0 0 24 24"
          role="img" aria-label={controller.label}><title>{controller.label}</title>
          <path d="M7 6h10c2 0 3 2 3.5 4l1 6c.5 3-2 4-3.5 2l-2-2H8l-2 2c-1.5 2-4 1-3.5-2l1-6C4 8 5 6 7 6Z" />
          <path d="M8 9v5m-2.5-2.5h5" /><circle cx="16" cy="10" r=".8" /><circle cx="18" cy="13" r=".8" />
        </svg>}
      </span>
    </Focusable>
    <Focusable className="hlg-sort-button hlg-settings-button" noFocusRing
      navRef={ref => { menuButton.current = ref; }} focusable={!panel}
      aria-label="Library settings" aria-haspopup="dialog" aria-expanded={!!panel}
      onMoveDown={focusGrid} onCancel={focusGrid} onActivate={openPanel} onOKActionDescription="Library settings">
      Library settings
    </Focusable>
    {panel && <div className="hlg-sort-backdrop" onClick={panel === 'import' ? undefined : closePanel} />}
    {panel === 'settings' && <SettingsPanel Focusable={Focusable} sortMode={sortMode}
      controllersOnly={controllersOnly} chooseSort={chooseSort} toggleControllers={toggleControllers}
      audio={() => setPanel('audio')} importRom={() => setPanel('import')} close={closePanel} />}
    {panel === 'audio' && <AudioPanel Focusable={Focusable} close={() => setPanel('settings')} />}
    {panel === 'import' && <ImportPanel Focusable={Focusable} TextField={TextField} close={() => setPanel('settings')} imported={imported} />}
    <div className="hlg-scroll" ref={viewport} onScroll={measure} data-fade-top={edges.top} data-fade-bottom={edges.bottom}>
      <Focusable className="hlg-covers" navKey="home-covers" flow-children="grid"
        navEntryPreferPosition={4} autoFocus childFocusDisabled={!!panel}>
        {sections.map(renderGroup)}
        {!all.length && <Focusable className="hlg-empty" onActivate={openPanel} onOKActionDescription="Library settings">{controllersOnly ? 'No games with known controller support. Open Library settings to show all games.' : 'Your library is loading…'}</Focusable>}
      </Focusable>
    </div>
  </Focusable>;
}

class SafeHome extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error) { console.error('[Home Library Grid]', error); }
  render() { return this.state.failed ? this.props.fallback : <HomeGrid />; }
}

// Preserve Steam's Page component, which owns the native header and footer.
// Replace its content rather than leaving an invisible carousel in the
// controller navigation tree. Immutable clones also preserve the fallback.
function replacePage(node) {
  if (!React.isValidElement(node)) return node;
  if (node.props && 'headerVisibility' in node.props && 'padForFooter' in node.props) {
    return React.cloneElement(node, {}, <SafeHome fallback={node.props.children} />);
  }
  if (!node.props?.children) return node;
  return React.cloneElement(node, {}, React.Children.map(node.props.children, replacePage));
}

export default definePlugin(() => {
  resolveSteamUI();
  if (!Focusable || !store()) throw new Error('Steam library components are unavailable');
  const patches = [], patched = new WeakSet();
  const patchType = (object, handler) => {
    if (!object || typeof object.type !== 'function' || patched.has(object)) return;
    patched.add(object);
    patches.push(afterPatch(object, 'type', handler));
  };
  const patch = routerHook.addPatch('/library/home', props => {
    patchType(props.children, (_args, result) => {
      patchType(result?.type, (_args, page) => {
        try { return replacePage(page); }
        catch (error) { console.error('[Home Library Grid] Keeping native Home', error); return page; }
      });
      return result;
    });
    return props;
  });
  return { name: 'Home Library Grid', titleView: <div>Home Library Grid</div>,
    content: <div style={{ padding: 16 }}>Installed games and shortcuts first, then your games available to install.</div>,
    icon: <span>▦</span>, onDismount() {
      routerHook.removePatch('/library/home', patch);
      for (const handle of patches.reverse()) handle.unpatch();
    } };
});

export { HomeGrid, replacePage, resolveSteamUI };
