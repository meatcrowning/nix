import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { findFocusable, steamNavigation } from './steam.mjs';
import { afterPatch } from '@decky/ui/dist/utils/patcher';
import { definePlugin, routerHook, callable } from '@decky/api';
import { libraryGroups, edgeFades, revealScroll, metadataLine, controllerSupport, displayTitle, systemName, adjacentApp, librarySections, sortModes, validSort, verticalNeighbor } from './model.mjs';
import css from './style.css';
import { SystemIcon } from './system-icon.jsx';
import { AudioPanel } from './audio-panel.jsx';

let rememberedApp = null, rememberedScroll = 0;
const store = () => window.appStore;
const readMetadata = callable('library_metadata');
let Focusable;
function resolveSteamUI() {
  window.webpackChunksteamui.push([[Symbol('home-library-grid')], {}, requireModule => {
    Focusable = findFocusable(requireModule);
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
  const [panel, setPanel] = useState(null);
  const toolbar = useRef(new Map()), sortOptions = useRef(new Map());
  const lastControl = useRef('sort'), returnTarget = useRef(null), openedFrom = useRef('grid');
  const openPanel = (name, from = 'grid') => { openedFrom.current = from; setPanel(name); return true; };
  const closePanel = () => { returnTarget.current = openedFrom.current; setPanel(null); };
  const [metadata, setMetadata] = useState({});
  useEffect(() => {
    let active = true;
    readMetadata().then(data => { if (active) setMetadata(data || {}); })
      .catch(error => console.warn('[Home Library Grid] Metadata unavailable', error));
    return () => { active = false; };
  }, []);
  const [groups, setGroups] = useState(() => libraryGroups(store().allApps));
  const sections = librarySections(groups, metadata, sortMode);
  const all = sections.flatMap(section => section.apps);
  const [selected, setSelected] = useState(() => all.find(a => a.appid === rememberedApp) || all[0]);
  const controller = controllerSupport(selected, metadata[selected?.appid]);
  const viewport = useRef(null);
  const navigation = useRef(new Map());
  const focusGrid = detail => {
    (navigation.current.get(selected?.appid) || navigation.current.get(all[0]?.appid))?.TakeFocus(detail?.button);
    return true;
  };
  const focusControl = (name, detail) => { lastControl.current = name; toolbar.current.get(name)?.TakeFocus(detail?.button); return true; };
  useLayoutEffect(() => {
    if (panel === 'sort') sortOptions.current.get(sortMode)?.TakeFocus();
    if (!panel && returnTarget.current) {
      const target = returnTarget.current; returnTarget.current = null;
      if (target === 'grid') focusGrid(); else focusControl(target);
    }
  }, [panel]);
  const verticalMove = (app, step, detail) => {
    const cards = [...viewport.current.querySelectorAll('.hlg-card')].map(el => ({appid:Number(el.dataset.appid),top:el.offsetTop,left:el.offsetLeft,width:el.offsetWidth}));
    const next = verticalNeighbor(cards, app.appid, step);
    if (next) navigation.current.get(next)?.TakeFocus(detail.button);
    else if (step < 0) focusControl(lastControl.current, detail);
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
    rememberedScroll = el.scrollTop;
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
  }, [groups]);
  useLayoutEffect(() => {
    const el = viewport.current;
    el.scrollTop = rememberedScroll;
    const Observer = el.ownerDocument.defaultView.ResizeObserver;
    const observer = new Observer(measure);
    observer.observe(el);
    observer.observe(el.firstElementChild);
    measure();
    return () => observer.disconnect();
  }, []);
  const select = (app, element) => {
    rememberedApp = app.appid;
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
    setSortMode(mode);
    try { localStorage.setItem('home-library-grid-sort', mode); } catch {}
    rememberedScroll = 0;
    viewport.current.scrollTop = 0;
    closePanel();
  };
  const renderGroup = ({key, label, apps, downloadable, system}) => apps.length ? <React.Fragment key={key}>
    {label && <h2 className="hlg-section" aria-label={label}>{system ? <SystemIcon system={system} /> : label}{system && downloadable && <span>Available to install</span>}<span>{apps.length}</span></h2>}
    {apps.map(app => <Focusable key={app.appid} className="hlg-card" noFocusRing
      navRef={handle => { if (handle) navigation.current.set(app.appid, handle); else navigation.current.delete(app.appid); }}
      onMoveRight={detail => move(app, 1, detail)} onMoveLeft={detail => move(app, -1, detail)}
      onMoveUp={detail => verticalMove(app, -1, detail)} onMoveDown={detail => verticalMove(app, 1, detail)}
      data-appid={app.appid} aria-label={`${displayTitle(app)}${downloadable ? ', available to install' : ''}`}
      preferredFocus={app.appid === (rememberedApp || all[0]?.appid)}
      onGamepadFocus={e => select(app, e.currentTarget || e.target)}
      onFocus={e => select(app, e.currentTarget)}
      onActivate={() => steamNavigation().Navigate(`/library/app/${app.appid}`)}
      onOKActionDescription="Select" onCancelActionDescription="Back"
      onOptionsButton={() => openPanel('sort')} onOptionsActionDescription="Sort"
      onSecondaryButton={() => openPanel('audio')} onSecondaryActionDescription="Audio"
      onCancel={() => steamNavigation().NavigateBack()}>
      <span className="hlg-fallback">{displayTitle(app)}</span>
      <Picture key={`${app.appid}-${app.rt_custom_image_mtime}-${app.local_cache_version}`} sources={artwork(app, 'cover')} lazy />
      {downloadable && <span className="hlg-download" aria-hidden="true">↓</span>}
    </Focusable>)}
  </React.Fragment> : null;
  return <Focusable className="home-library-grid" flow-children="column">
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
      {['sort','audio'].map(name => <Focusable key={name} className={`hlg-sort-button hlg-${name}-button`}
        navRef={ref => {if(ref) toolbar.current.set(name,ref); else toolbar.current.delete(name);}} focusable={!panel} noFocusRing
        aria-haspopup={name==='sort'?'menu':'dialog'} aria-expanded={panel===name} aria-label={name==='sort'?'Sort games':'Audio settings'}
        onMoveDown={focusGrid} onMoveLeft={detail=>focusControl('sort',detail)} onMoveRight={detail=>focusControl('audio',detail)}
        onCancel={focusGrid} onActivate={() => openPanel(name,name)} onOKActionDescription={name==='sort'?'Sort':'Audio'}>
        {name === 'sort' ? `Sort: ${sortModes.find(([id]) => id === sortMode)[1]} ▾` : 'Audio ♪'}
      </Focusable>)}
    </Focusable>
    {panel && <div className="hlg-sort-backdrop" onClick={closePanel} />}
    {panel === 'audio' && <AudioPanel Focusable={Focusable} close={closePanel} />}
    {panel === 'sort' && <Focusable className="hlg-sort-menu" flow-children="column" role="menu" aria-label="Sort games" autoFocus
        onCancel={() => { closePanel(); return true; }} onCancelActionDescription="Close"
        onMoveUp={() => true} onMoveDown={() => true} onMoveLeft={() => true} onMoveRight={() => true}>
        <div className="hlg-sort-note">Installed games first</div>
        {sortModes.map(([id, label], index) => <Focusable key={id} className="hlg-sort-option" role="menuitemradio"
          aria-checked={id === sortMode} preferredFocus={id === sortMode}
          navRef={ref=>{if(ref)sortOptions.current.set(id,ref);else sortOptions.current.delete(id);}} noFocusRing
          onMoveUp={detail=>{sortOptions.current.get(sortModes[Math.max(0,index-1)][0])?.TakeFocus(detail.button);return true;}}
          onMoveDown={detail=>{sortOptions.current.get(sortModes[Math.min(sortModes.length-1,index+1)][0])?.TakeFocus(detail.button);return true;}}
          onActivate={() => chooseSort(id)} onOKActionDescription="Apply">
          {label}<span aria-hidden="true">{id === sortMode ? '✓' : ''}</span>
        </Focusable>)}
      </Focusable>}
    <div className="hlg-scroll" ref={viewport} onScroll={measure} data-fade-top={edges.top} data-fade-bottom={edges.bottom}>
      <Focusable className="hlg-covers" flow-children="grid" autoFocus childFocusDisabled={!!panel}>
        {sections.map(renderGroup)}
        {!all.length && <div className="hlg-empty">Your library is loading…</div>}
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
