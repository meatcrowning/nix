import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { findFocusable, steamNavigation } from './steam.mjs';
import { afterPatch } from '@decky/ui/dist/utils/patcher';
import { definePlugin, routerHook, callable } from '@decky/api';
import { libraryGroups, edgeFades, revealScroll, metadataLine } from './model.mjs';
import css from './style.css';

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
  const [metadata, setMetadata] = useState({});
  useEffect(() => {
    let active = true;
    readMetadata().then(data => { if (active) setMetadata(data || {}); })
      .catch(error => console.warn('[Home Library Grid] Metadata unavailable', error));
    return () => { active = false; };
  }, []);
  const [groups, setGroups] = useState(() => libraryGroups(store().allApps));
  const all = [...groups.ready, ...groups.available];
  const [selected, setSelected] = useState(() => all.find(a => a.appid === rememberedApp) || all[0]);
  const viewport = useRef(null);
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
  const renderGroup = (label, apps, downloadable) => apps.length ? <React.Fragment key={label}>
    {downloadable && <h2 className="hlg-section">{label}<span>{apps.length}</span></h2>}
    {apps.map(app => <Focusable key={app.appid} className="hlg-card" noFocusRing
      data-appid={app.appid} aria-label={`${app.display_name}${downloadable ? ', available to install' : ''}`}
      preferredFocus={app.appid === (rememberedApp || all[0]?.appid)}
      onGamepadFocus={e => select(app, e.currentTarget || e.target)}
      onFocus={e => select(app, e.currentTarget)}
      onActivate={() => steamNavigation().Navigate(`/library/app/${app.appid}`)}
      onOKActionDescription="Select" onCancelActionDescription="Back"
      onCancel={() => steamNavigation().NavigateBack()}>
      <span className="hlg-fallback">{app.display_name}</span>
      <Picture key={`${app.appid}-${app.rt_custom_image_mtime}-${app.local_cache_version}`} sources={artwork(app, 'cover')} lazy />
      {downloadable && <span className="hlg-download" aria-hidden="true">↓</span>}
    </Focusable>)}
  </React.Fragment> : null;
  return <div className="home-library-grid">
    <style>{css}</style>
    <div className="hlg-hero"><Picture key={`${selected?.appid}-${selected?.rt_custom_image_mtime}`} sources={artwork(selected, 'hero')} /></div>
    <div className="hlg-heading"><h1>{selected?.display_name || 'Your library'}</h1>
      <span>{metadataLine(selected, metadata[selected?.appid])}</span></div>
    <div className="hlg-scroll" ref={viewport} onScroll={measure} data-fade-top={edges.top} data-fade-bottom={edges.bottom}>
      <Focusable className="hlg-covers" flow-children="grid" autoFocus>
        {renderGroup('Installed', groups.ready, false)}
        {renderGroup('Available to install', groups.available, true)}
        {!all.length && <div className="hlg-empty">Your library is loading…</div>}
      </Focusable>
    </div>
  </div>;
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
