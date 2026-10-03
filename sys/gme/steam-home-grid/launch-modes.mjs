export function saveLaunchOptions(apps, appid, options, timeout = 8000) {
  return new Promise((resolve, reject) => {
    let subscription, done = false;
    const finish = error => {
      if (done) return;
      done = true; clearTimeout(timer); subscription?.unregister();
      error ? reject(error) : resolve();
    };
    const timer = setTimeout(() => finish(new Error('Steam did not save the selected mode. Please try again.')), timeout);
    Promise.resolve().then(() => apps.SetShortcutLaunchOptions(appid, options)).then(() => {
      subscription = apps.RegisterForAppDetails(appid, details => {
        if ((details.strShortcutLaunchOptions ?? details.strLaunchOptions) === options) finish();
      });
      if (done) subscription?.unregister();
    }).catch(finish);
  });
}

// Intercept only launch requests for shortcuts with explicit mode metadata.
// Continue through Steam so overlays, playtime and the Stop button stay native.
export function installLaunchModes({ apps, getApp, metadata, choose, reportError, save = saveLaunchOptions }) {
  const original = apps.RunGame;
  let disposed = false;
  const pending = new Set();
  const wrapped = function (...args) {
    const app = getApp(args[0]);
    if (!app?.BIsShortcut?.()) return original.apply(this, args);
    if (pending.has(app.appid)) return;
    pending.add(app.appid);
    return (async () => {
      try {
        const details = (await metadata())[app.appid];
        if (disposed) return;
        const modes = details?.launchModes;
        if (!Array.isArray(modes) || !modes.length) return original.apply(this, args);
        const index = await choose(app.appid, modes);
        if (disposed || index === null) return;
        if (!Number.isInteger(index) || !modes[index]?.options) throw new Error('The selected game mode is unavailable.');
        await save(apps, app.appid, modes[index].options);
        if (!disposed) return original.apply(this, args);
      } catch (error) {
        reportError(error);
      } finally {
        pending.delete(app.appid);
      }
    })();
  };
  apps.RunGame = wrapped;
  return () => {
    disposed = true;
    if (apps.RunGame === wrapped) apps.RunGame = original;
  };
}
