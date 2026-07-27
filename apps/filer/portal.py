#!/usr/bin/env python3
"""filer-portal — an `org.freedesktop.impl.portal.FileChooser` BACKEND.

This is what makes `filer` the desktop's file-open dialog. It is NOT the portal
apps talk to: applications call the *frontend*
`org.freedesktop.portal.FileChooser` on `org.freedesktop.portal.Desktop`
(xdg-desktop-portal), and xdp turns around and calls a *backend* — one of the
`org.freedesktop.impl.portal.desktop.*` services — over the `impl.` interface
implemented here. Contract verified against
`/usr/share/dbus-1/interfaces/org.freedesktop.impl.portal.FileChooser.xml`
(xdg-desktop-portal 1.22.1), not from memory.

Three facts shape every design decision below.

1. **Backend selection is per INTERFACE, not per method.** xdp resolves
   `org.freedesktop.impl.portal.FileChooser` to exactly one `.portal` file and
   sends OpenFile, SaveFile *and* SaveFiles there. There is no per-method
   fallback and no "unimplemented, try the next backend" path — an
   `UnknownMethod` error propagates straight to the calling app as a broken
   dialog. So "implement OpenFile only" is impossible as stated. What IS
   possible, and is what this does, is to implement all three and **proxy** the
   ones filer has no UI for to the backend that already works (gtk here, kde on
   `top`). Save dialogs therefore behave exactly as they do today.

2. **The backend's Request object has only `Close()` — there is no `Response`
   signal on this side.** (`org.freedesktop.impl.portal.Request.xml` declares
   `Close` and nothing else.) The backend answers by *returning from the method*
   — `(u response, a{sv} results)` — whenever the user is done, which is why the
   reply is delayed rather than signalled. The `Response` signal an app sees is
   emitted by xdp on the *frontend* Request object. Getting this backwards is
   the classic way to make every file dialog on the machine hang forever.

3. **A hang is worse than a wrong answer.** Every exit path from a method call
   ends in exactly one `invocation.return_value(...)`; `_Reply` enforces the
   "exactly one" with a latch, and anything unexpected returns response 2
   (error) instead of going quiet. Response codes are 0 success, 1 cancelled by
   the user, 2 other error.

## Delegation

`FILER_PORTAL_DELEGATE` (default `gtk`) names the backend that SaveFile and
SaveFiles are forwarded to — it is a bus-name suffix, so `gtk` means
`org.freedesktop.impl.portal.desktop.gtk`. On `top` set it to `kde`, which is
what `sys/dsk/hyprland.nix` routes FileChooser to today.

`FILER_PORTAL_OPEN` (default `filer`) selects who answers OpenFile. Set it to
`delegate` to hand OpenFile over too, which turns this service into a
pass-through — the useful setting for bisecting a problem without editing
portals.conf.

Forwarding is a real proxy, not a redirect: the `handle` object path is passed
through unchanged, so the delegate exports its own Request object at that path
under *its* bus name, and a `Close()` that xdp sends to us at that path is
forwarded on. Both objects can coexist because they live on different bus
names.

## The picker

OpenFile spawns `filer --pick <spec.json>` (see `pick.py`), which writes its
answer to the `result` path named in the spec and exits. A subprocess — rather
than hosting the QML in here — is deliberate: a crash or a hang in the picker
costs one dialog, and `Close()` can kill it, whereas a picker hosted in the
backend process would take every future dialog down with it. If the picker
cannot even be spawned we fall through to the delegate rather than fail.
"""
import json
import os
import shutil
import signal
import sys
import tempfile
import warnings

# PyGObject deprecates `register_object` in favour of a GDBus API it does not
# actually bind yet. Left alone it prints a traceback-style warning on every
# request (each one exports a Request object), which turns a working file dialog
# into pages of journal noise.
warnings.filterwarnings("ignore", message=r".*register_object is deprecated.*")

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

IFACE = "org.freedesktop.impl.portal.FileChooser"
REQUEST_IFACE = "org.freedesktop.impl.portal.Request"
BUS_NAME = "org.freedesktop.impl.portal.desktop.filer"
OBJECT_PATH = "/org/freedesktop/portal/desktop"

# Response codes, per the portal spec.
OK, CANCELLED, ERROR = 0, 1, 2

NODE_XML = """
<node>
  <interface name='org.freedesktop.impl.portal.FileChooser'>
    <method name='OpenFile'>
      <arg type='o' name='handle' direction='in'/>
      <arg type='s' name='app_id' direction='in'/>
      <arg type='s' name='parent_window' direction='in'/>
      <arg type='s' name='title' direction='in'/>
      <arg type='a{sv}' name='options' direction='in'/>
      <arg type='u' name='response' direction='out'/>
      <arg type='a{sv}' name='results' direction='out'/>
    </method>
    <method name='SaveFile'>
      <arg type='o' name='handle' direction='in'/>
      <arg type='s' name='app_id' direction='in'/>
      <arg type='s' name='parent_window' direction='in'/>
      <arg type='s' name='title' direction='in'/>
      <arg type='a{sv}' name='options' direction='in'/>
      <arg type='u' name='response' direction='out'/>
      <arg type='a{sv}' name='results' direction='out'/>
    </method>
    <method name='SaveFiles'>
      <arg type='o' name='handle' direction='in'/>
      <arg type='s' name='app_id' direction='in'/>
      <arg type='s' name='parent_window' direction='in'/>
      <arg type='s' name='title' direction='in'/>
      <arg type='a{sv}' name='options' direction='in'/>
      <arg type='u' name='response' direction='out'/>
      <arg type='a{sv}' name='results' direction='out'/>
    </method>
  </interface>
  <interface name='org.freedesktop.impl.portal.Request'>
    <method name='Close'/>
  </interface>
</node>
"""


def log(*a):
    print("filer-portal:", *a, file=sys.stderr, flush=True)


def _delegate_name():
    return "org.freedesktop.impl.portal.desktop." + os.environ.get(
        "FILER_PORTAL_DELEGATE", "gtk")


def _filer_bin():
    """Absolute path to the filer wrapper. Resolved like filer's own _resolve():
    D-Bus activation gives us a minimal PATH that need not contain the nix
    profile, so fall back to it explicitly."""
    env = os.environ.get("FILER_BIN")
    if env:
        return env if os.path.exists(env) else None
    found = shutil.which("filer")
    if found:
        return found
    cand = os.path.expanduser("~/.nix-profile/bin/filer")
    return cand if os.path.exists(cand) else None


# ---- option decoding --------------------------------------------------------
# The wire types are awkward enough to be worth isolating: `current_folder` is a
# NUL-terminated `ay` in filesystem encoding (not a string), and a filter is
# `(s a(us))` where the u is 0 for a glob pattern and 1 for a MIME type.

def _bytes_to_path(v):
    """`ay` (NUL-terminated, filesystem encoding) -> str, or None."""
    if v is None:
        return None
    try:
        raw = bytes(v)
    except TypeError:
        return None
    raw = raw.split(b"\0", 1)[0]
    if not raw:
        return None
    return os.fsdecode(raw)


def _filter_to_json(f):
    """`(s a(us))` -> {name, patterns, mimes}."""
    name, rules = f[0], f[1]
    pats, mimes = [], []
    for kind, value in rules:
        (pats if int(kind) == 0 else mimes).append(str(value))
    return {"name": str(name), "patterns": pats, "mimes": mimes}


def _decode_options(options):
    """The subset of the options vardict the picker understands. Unknown keys
    are ignored on purpose — the spec says a backend may ignore any of them, and
    silently dropping one is a worse dialog, never a hang."""
    def g(k, default=None):
        v = options.get(k)
        return default if v is None else v

    spec = {
        "multiple": bool(g("multiple", False)),
        "directory": bool(g("directory", False)),
        "accept_label": str(g("accept_label", "") or ""),
        "modal": bool(g("modal", True)),
        "current_folder": _bytes_to_path(g("current_folder")),
        "current_name": str(g("current_name", "") or ""),
        "filters": [],
        "current_filter": None,
    }
    try:
        spec["filters"] = [_filter_to_json(f) for f in g("filters", [])]
    except Exception as e:            # a malformed filter must not kill the dialog
        log("ignoring unparseable filters:", e)
    try:
        cf = g("current_filter")
        if cf is not None:
            spec["current_filter"] = _filter_to_json(cf)
    except Exception as e:
        log("ignoring unparseable current_filter:", e)
    return spec


class _Reply:
    """One method invocation's single permitted answer.

    Every path out of a call — success, cancel, spawn failure, exception,
    Close() — goes through here, and the latch makes a double-reply (which D-Bus
    treats as a protocol error) impossible. `done` is the only thing the rest of
    the code has to get right."""

    def __init__(self, invocation, on_done=None):
        self._inv = invocation
        self._on_done = on_done
        self._sent = False

    @property
    def sent(self):
        return self._sent

    def done(self, response, results=None):
        if self._sent:
            return
        self._sent = True
        body = GLib.Variant("(ua{sv})", (int(response), results or {}))
        try:
            self._inv.return_value(body)
        except Exception as e:
            log("failed to return reply:", e)
        if self._on_done:
            self._on_done()

    def done_variant(self, variant):
        """Return a `(ua{sv})` variant we got verbatim from the delegate."""
        if self._sent:
            return
        self._sent = True
        try:
            self._inv.return_value(variant)
        except Exception as e:
            log("failed to forward reply:", e)
        if self._on_done:
            self._on_done()


class Portal:
    def __init__(self, conn):
        self.conn = conn
        self.node = Gio.DBusNodeInfo.new_for_xml(NODE_XML)
        self.iface = self.node.lookup_interface(IFACE)
        self.request_iface = self.node.lookup_interface(REQUEST_IFACE)
        # handle path -> a callable that aborts that request
        self._closers = {}
        # handle path -> Gio registration id for the Request object
        self._request_regs = {}

        conn.register_object(OBJECT_PATH, self.iface, self._on_call, None, None)

    # -- Request object lifecycle --------------------------------------------

    def _export_request(self, handle, closer):
        """Export `org.freedesktop.impl.portal.Request` at `handle`.

        The spec requires the backend to export this for the duration of the
        interaction; xdp calls Close() on it to abort (app went away, or the app
        called Close on the frontend Request). Not exporting it means an
        abandoned dialog stays on screen forever."""
        self._closers[handle] = closer
        try:
            rid = self.conn.register_object(handle, self.request_iface,
                                            self._on_request_call, None, None)
            self._request_regs[handle] = rid
        except Exception as e:
            # Non-fatal: the dialog still works, it just cannot be aborted
            # remotely. Never let this take the request itself down.
            log("could not export Request at", handle, ":", e)

    def _unexport_request(self, handle):
        self._closers.pop(handle, None)
        rid = self._request_regs.pop(handle, None)
        if rid is not None:
            try:
                self.conn.unregister_object(rid)
            except Exception:
                pass

    def _on_request_call(self, conn, sender, path, iface, method, params, invocation):
        if method != "Close":
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD, method)
            return
        invocation.return_value(None)
        closer = self._closers.get(path)
        if closer:
            try:
                closer()
            except Exception as e:
                log("close handler failed:", e)

    # -- FileChooser ----------------------------------------------------------

    def _on_call(self, conn, sender, path, iface, method, params, invocation):
        if method not in ("OpenFile", "SaveFile", "SaveFiles"):
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD, method)
            return
        try:
            handle, app_id, parent_window, title, options = params.unpack()
        except Exception as e:
            log("unparseable", method, "call:", e)
            invocation.return_value(GLib.Variant("(ua{sv})", (ERROR, {})))
            return

        want_filer = (method == "OpenFile"
                      and os.environ.get("FILER_PORTAL_OPEN", "filer") != "delegate")
        if want_filer and self._open_with_filer(handle, title, options, params, invocation):
            return
        self._delegate(handle, method, params, invocation)

    # -- the filer picker ------------------------------------------------------

    def _open_with_filer(self, handle, title, options, params, invocation):
        """Run `filer --pick`. Returns False (having replied to nothing) if the
        picker could not be started, so the caller can still delegate."""
        binary = _filer_bin()
        if not binary:
            log("filer not found on PATH; delegating OpenFile")
            return False

        spec = _decode_options(options)
        spec["mode"] = "dir" if spec["directory"] else "open"
        spec["title"] = str(title or "")

        try:
            fd, specfile = tempfile.mkstemp(prefix="filer-pick-", suffix=".json")
            os.close(fd)
            resultfile = specfile[:-5] + ".result.json"
            spec["result"] = resultfile
            with open(specfile, "w", encoding="utf-8") as f:
                json.dump(spec, f)
        except OSError as e:
            log("could not write pick spec:", e)
            return False

        def cleanup():
            for p in (specfile, resultfile):
                try:
                    os.unlink(p)
                except OSError:
                    pass
            self._unexport_request(handle)

        reply = _Reply(invocation, on_done=cleanup)

        try:
            proc = Gio.Subprocess.new([binary, "--pick", specfile],
                                      Gio.SubprocessFlags.NONE)
        except GLib.Error as e:
            log("could not spawn filer:", e)
            cleanup()
            return False

        def finished(p, res):
            try:
                p.wait_finish(res)
            except GLib.Error as e:
                log("picker wait failed:", e)
            if reply.sent:                       # Close() already answered
                return
            try:
                with open(resultfile, encoding="utf-8") as f:
                    out = json.load(f)
            except (OSError, ValueError):
                # No result file: the user cancelled, or the picker died. Either
                # way "cancelled" is the honest, non-hanging answer.
                reply.done(CANCELLED)
                return
            uris = [str(u) for u in out.get("uris", [])]
            if not uris:
                reply.done(CANCELLED)
                return
            results = {"uris": GLib.Variant("as", uris),
                       "writable": GLib.Variant("b", True)}
            name = out.get("current_filter")
            chosen = next((f for f in spec["filters"] if f["name"] == name), None)
            if chosen:
                rules = [(0, p) for p in chosen["patterns"]] + \
                        [(1, m) for m in chosen["mimes"]]
                results["current_filter"] = GLib.Variant("(sa(us))",
                                                         (chosen["name"], rules))
            reply.done(OK, results)

        proc.wait_async(None, finished)

        def close():
            # SIGTERM, then let `finished` report. force_exit() would leave the
            # result file unread even when the user had already chosen.
            try:
                proc.send_signal(signal.SIGTERM)
            except Exception:
                pass
            reply.done(CANCELLED)

        self._export_request(handle, close)
        return True

    # -- delegation ------------------------------------------------------------

    def _delegate(self, handle, method, params, invocation):
        """Forward the call verbatim to the delegate backend, including the
        `handle`, so its Request object lands on the path xdp expects."""
        dest = _delegate_name()
        reply = _Reply(invocation, on_done=lambda: self._unexport_request(handle))

        def got(conn, res):
            try:
                out = conn.call_finish(res)
            except GLib.Error as e:
                log("delegate", dest, method, "failed:", e)
                reply.done(ERROR)
                return
            reply.done_variant(out)

        def close():
            # Forward the abort; the delegate then returns from its method and
            # `got` delivers that answer. Do NOT reply here, or the real reply
            # would be dropped.
            self.conn.call(dest, handle, REQUEST_IFACE, "Close", None, None,
                           Gio.DBusCallFlags.NONE, 5000, None, None)

        self._export_request(handle, close)
        self.conn.call(dest, OBJECT_PATH, IFACE, method, params,
                       GLib.VariantType("(ua{sv})"), Gio.DBusCallFlags.NONE,
                       GLib.MAXINT, None, got)


def main():
    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    Portal(conn)

    loop = GLib.MainLoop()

    def acquired(*_):
        log("owning", BUS_NAME, "| delegate =", _delegate_name(),
            "| OpenFile =", os.environ.get("FILER_PORTAL_OPEN", "filer"))

    def lost(*_):
        log("lost", BUS_NAME, "- exiting")
        loop.quit()

    Gio.bus_own_name_on_connection(conn, BUS_NAME,
                                   Gio.BusNameOwnerFlags.NONE, acquired, lost)
    loop.run()


if __name__ == "__main__":
    main()
