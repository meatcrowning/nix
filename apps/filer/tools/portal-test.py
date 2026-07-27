#!/usr/bin/env python3
"""Headless conformance test for apps/filer/portal.py.

Runs on a PRIVATE session bus (dbus-run-session), with a stub delegate backend
and a stub `filer` binary, so nothing touches the user's desktop and no window
is ever created.
"""
import json
import os
import subprocess
import sys
import time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "portal.py")
IFACE = "org.freedesktop.impl.portal.FileChooser"
REQ_IFACE = "org.freedesktop.impl.portal.Request"
PATH = "/org/freedesktop/portal/desktop"
FILER_NAME = "org.freedesktop.impl.portal.desktop.filer"
STUB_NAME = "org.freedesktop.impl.portal.desktop.teststub"

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


STUB_XML = """
<node>
  <interface name='org.freedesktop.impl.portal.FileChooser'>
    <method name='OpenFile'>
      <arg type='o' direction='in'/><arg type='s' direction='in'/>
      <arg type='s' direction='in'/><arg type='s' direction='in'/>
      <arg type='a{sv}' direction='in'/>
      <arg type='u' direction='out'/><arg type='a{sv}' direction='out'/>
    </method>
    <method name='SaveFile'>
      <arg type='o' direction='in'/><arg type='s' direction='in'/>
      <arg type='s' direction='in'/><arg type='s' direction='in'/>
      <arg type='a{sv}' direction='in'/>
      <arg type='u' direction='out'/><arg type='a{sv}' direction='out'/>
    </method>
    <method name='SaveFiles'>
      <arg type='o' direction='in'/><arg type='s' direction='in'/>
      <arg type='s' direction='in'/><arg type='s' direction='in'/>
      <arg type='a{sv}' direction='in'/>
      <arg type='u' direction='out'/><arg type='a{sv}' direction='out'/>
    </method>
  </interface>
  <interface name='org.freedesktop.impl.portal.Request'>
    <method name='Close'/>
  </interface>
</node>
"""


class Stub:
    """Stands in for the gtk/kde backend. Records what it was asked, answers
    SaveFile/SaveFiles immediately, and holds OpenFile open until Close()."""

    def __init__(self, conn):
        self.conn = conn
        self.seen = []
        self.closed = []
        node = Gio.DBusNodeInfo.new_for_xml(STUB_XML)
        self.req_iface = node.lookup_interface(REQ_IFACE)
        self._pending = {}
        conn.register_object(PATH, node.lookup_interface(IFACE), self._call, None, None)

    def _call(self, conn, sender, path, iface, method, params, inv):
        handle = params.unpack()[0]
        self.seen.append((method, handle))
        if method == "SaveFiles":
            inv.return_value(GLib.Variant("(ua{sv})", (
                0, {"uris": GLib.Variant("as", ["file:///tmp/stub-a", "file:///tmp/stub-b"])})))
            return
        if method == "SaveFile":
            inv.return_value(GLib.Variant("(ua{sv})", (
                0, {"uris": GLib.Variant("as", ["file:///tmp/stub-save.txt"])})))
            return
        # OpenFile: stay open, export a Request so the proxy's Close can land
        self._pending[handle] = inv
        rid = conn.register_object(handle, self.req_iface, self._req, None, None)
        self._pending[handle + "#reg"] = rid

    def _req(self, conn, sender, path, iface, method, params, inv):
        inv.return_value(None)
        self.closed.append(path)
        pend = self._pending.pop(path, None)
        if pend:
            pend.return_value(GLib.Variant("(ua{sv})", (1, {})))


def make_stub_filer(tmp, behaviour):
    """A fake `filer` that reads the pick spec and behaves as told."""
    p = os.path.join(tmp, "fake-filer")
    with open(p, "w") as f:
        f.write(f"""#!/usr/bin/env python3
import json, os, sys, time
spec = json.load(open(sys.argv[2]))
json.dump(spec, open(os.path.join({tmp!r}, "last-spec.json"), "w"))
b = {behaviour!r}
if b == "hang":
    time.sleep(120)
elif b == "cancel":
    sys.exit(0)                      # no result file written
elif b == "crash":
    sys.exit(9)
else:
    json.dump({{"uris": ["file:///tmp/picked%20one.txt"],
               "current_filter": "Images"}}, open(spec["result"], "w"))
""")
    os.chmod(p, 0o755)
    return p


def call(conn, method, handle, options, timeout=8000):
    """Call OUR backend and pump the main loop until it answers.

    Must NOT be call_sync: the stub delegate lives in this process's main loop,
    so a blocking call would deadlock the test against its own stub whenever the
    request is proxied."""
    box = {}
    loop = GLib.MainLoop()

    def cb(c, res):
        try:
            box["r"] = c.call_finish(res).unpack()
        except GLib.Error as e:
            box["e"] = e
        loop.quit()

    conn.call(FILER_NAME, PATH, IFACE, method,
              GLib.Variant("(osssa{sv})", (handle, "app.test", "", "T", options)),
              GLib.VariantType("(ua{sv})"), Gio.DBusCallFlags.NONE, timeout, None, cb)
    GLib.timeout_add(timeout + 2000, lambda: (loop.quit(), False)[1])
    loop.run()
    if "r" not in box:
        raise AssertionError(f"{method} never answered: {box.get('e')}")
    return box["r"]


def main():
    tmp = os.environ["T_TMP"]
    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    stub = Stub(conn)
    ready = GLib.MainLoop()
    Gio.bus_own_name_on_connection(conn, STUB_NAME, Gio.BusNameOwnerFlags.NONE,
                                   lambda *a: ready.quit(), None)
    ready.run()

    procs = []

    def start_portal(**env):
        e = dict(os.environ)
        e["FILER_PORTAL_DELEGATE"] = "teststub"
        e.update(env)
        p = subprocess.Popen([sys.executable, PORTAL], env=e,
                             stderr=subprocess.PIPE, text=True)
        procs.append(p)
        # wait for the name
        for _ in range(100):
            try:
                conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                               "org.freedesktop.DBus", "NameHasOwner",
                               GLib.Variant("(s)", (FILER_NAME,)),
                               GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 2000, None)
                if conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                  "org.freedesktop.DBus", "NameHasOwner",
                                  GLib.Variant("(s)", (FILER_NAME,)),
                                  GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE,
                                  2000, None).unpack()[0]:
                    return p
            except GLib.Error:
                pass
            time.sleep(0.05)
        raise SystemExit("portal never took the bus name")

    def stop_all():
        for p in procs:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        procs.clear()
        time.sleep(0.3)

    # ---- 1. introspection: all three methods, correct signatures ----
    start_portal(FILER_BIN=make_stub_filer(tmp, "ok"))
    xml = conn.call_sync(FILER_NAME, PATH, "org.freedesktop.DBus.Introspectable",
                         "Introspect", None, GLib.VariantType("(s)"),
                         Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    for m in ("OpenFile", "SaveFile", "SaveFiles"):
        check(f"introspect exposes {m}", f'name="{m}"' in xml)
    # Request is exported on the per-request handle path, not here; tests 7/8
    # exercise it for real.

    # ---- 2. OpenFile via the picker, options round-trip ----
    opts = {
        "multiple": GLib.Variant("b", True),
        "directory": GLib.Variant("b", False),
        "accept_label": GLib.Variant("s", "_Choose"),
        "current_folder": GLib.Variant("ay", list(b"/home/lam/Pictures\0")),
        "filters": GLib.Variant("a(sa(us))", [
            ("Images", [(0, "*.png"), (1, "image/jpeg")]),
            ("Text", [(0, "*.txt")]),
        ]),
        "current_filter": GLib.Variant("(sa(us))", ("Text", [(0, "*.txt")])),
    }
    resp, results = call(conn, "OpenFile", "/org/freedesktop/portal/desktop/request/x/t1", opts)
    check("OpenFile response == 0", resp == 0, resp)
    check("OpenFile returns file:// uris",
          results.get("uris") == ["file:///tmp/picked%20one.txt"], results.get("uris"))
    check("OpenFile echoes current_filter",
          results.get("current_filter") == ("Images", [(0, "*.png"), (1, "image/jpeg")]),
          results.get("current_filter"))
    spec = json.load(open(os.path.join(tmp, "last-spec.json")))
    check("spec: multiple decoded", spec["multiple"] is True)
    check("spec: current_folder NUL-stripped", spec["current_folder"] == "/home/lam/Pictures",
          spec["current_folder"])
    check("spec: accept_label passed", spec["accept_label"] == "_Choose")
    check("spec: filters split glob/mime",
          spec["filters"] == [{"name": "Images", "patterns": ["*.png"], "mimes": ["image/jpeg"]},
                              {"name": "Text", "patterns": ["*.txt"], "mimes": []}], spec["filters"])
    check("spec: current_filter decoded", spec["current_filter"]["name"] == "Text")
    check("spec: mode == open", spec["mode"] == "open")
    check("picker path did NOT reach the delegate", stub.seen == [], stub.seen)

    # ---- 3. directory mode ----
    call(conn, "OpenFile", "/org/freedesktop/portal/desktop/request/x/t2",
         {"directory": GLib.Variant("b", True)})
    spec = json.load(open(os.path.join(tmp, "last-spec.json")))
    check("spec: mode == dir for directory:true", spec["mode"] == "dir", spec["mode"])

    # ---- 4. SaveFile / SaveFiles proxy verbatim to the delegate ----
    resp, results = call(conn, "SaveFile", "/org/freedesktop/portal/desktop/request/x/t3",
                         {"current_name": GLib.Variant("s", "out.txt")})
    check("SaveFile proxied, response 0", resp == 0, resp)
    check("SaveFile returns the delegate's uris",
          results.get("uris") == ["file:///tmp/stub-save.txt"], results)
    resp, results = call(conn, "SaveFiles", "/org/freedesktop/portal/desktop/request/x/t4", {})
    check("SaveFiles proxied, response 0", resp == 0, resp)
    check("SaveFiles returns both uris", len(results.get("uris", [])) == 2, results)
    check("delegate saw SaveFile+SaveFiles with the SAME handle",
          [m for m, h in stub.seen] == ["SaveFile", "SaveFiles"]
          and stub.seen[0][1] == "/org/freedesktop/portal/desktop/request/x/t3",
          stub.seen)
    stop_all()

    # ---- 5. picker cancels (no result file) -> response 1, never a hang ----
    start_portal(FILER_BIN=make_stub_filer(tmp, "cancel"))
    resp, _ = call(conn, "OpenFile", "/org/freedesktop/portal/desktop/request/x/t5", {})
    check("cancelled picker -> response 1", resp == 1, resp)
    stop_all()

    # ---- 6. picker crashes -> response 1, never a hang ----
    start_portal(FILER_BIN=make_stub_filer(tmp, "crash"))
    resp, _ = call(conn, "OpenFile", "/org/freedesktop/portal/desktop/request/x/t6", {})
    check("crashed picker -> response 1", resp == 1, resp)
    stop_all()

    # ---- 7. missing filer binary -> falls through to the delegate ----
    stub.seen.clear()
    start_portal(FILER_BIN="/nonexistent/filer")
    handle = "/org/freedesktop/portal/desktop/request/x/t7"
    got = {}

    def openfile_async(h):
        def cb(c, res):
            try:
                got["r"] = c.call_finish(res).unpack()
            except GLib.Error as e:
                got["e"] = e
            loop.quit()
        conn.call(FILER_NAME, PATH, IFACE, "OpenFile",
                  GLib.Variant("(osssa{sv})", (h, "a", "", "T", {})),
                  GLib.VariantType("(ua{sv})"), Gio.DBusCallFlags.NONE, 20000, None, cb)

    loop = GLib.MainLoop()
    openfile_async(handle)
    # the stub holds OpenFile open; abort it via our Close and expect response 1
    GLib.timeout_add(600, lambda: (conn.call_sync(
        FILER_NAME, handle, REQ_IFACE, "Close", None, None,
        Gio.DBusCallFlags.NONE, 5000, None), False)[1])
    GLib.timeout_add(15000, lambda: (loop.quit(), False)[1])
    loop.run()
    check("no filer binary -> OpenFile delegated",
          any(m == "OpenFile" for m, _ in stub.seen), stub.seen)
    check("Close() is forwarded to the delegate's Request", handle in stub.closed, stub.closed)
    check("forwarded Close yields the delegate's answer (1), not a hang",
          got.get("r", (None,))[0] == 1, got)
    stop_all()

    # ---- 8. Close() aborts a hung picker instead of hanging the app ----
    start_portal(FILER_BIN=make_stub_filer(tmp, "hang"))
    handle = "/org/freedesktop/portal/desktop/request/x/t8"
    got = {}
    loop = GLib.MainLoop()
    openfile_async(handle)
    GLib.timeout_add(800, lambda: (conn.call_sync(
        FILER_NAME, handle, REQ_IFACE, "Close", None, None,
        Gio.DBusCallFlags.NONE, 5000, None), False)[1])
    GLib.timeout_add(15000, lambda: (loop.quit(), False)[1])
    loop.run()
    check("Close() on a hung picker -> response 1", got.get("r", (None,))[0] == 1, got)

    # ---- 9. FILER_PORTAL_OPEN=delegate turns it into a pass-through ----
    stop_all()
    stub.seen.clear()
    start_portal(FILER_BIN=make_stub_filer(tmp, "ok"), FILER_PORTAL_OPEN="delegate")
    handle = "/org/freedesktop/portal/desktop/request/x/t9"
    loop = GLib.MainLoop()
    got = {}
    openfile_async(handle)
    GLib.timeout_add(600, lambda: (conn.call_sync(
        FILER_NAME, handle, REQ_IFACE, "Close", None, None,
        Gio.DBusCallFlags.NONE, 5000, None), False)[1])
    GLib.timeout_add(15000, lambda: (loop.quit(), False)[1])
    loop.run()
    check("FILER_PORTAL_OPEN=delegate sends OpenFile to the delegate",
          any(m == "OpenFile" for m, _ in stub.seen), stub.seen)
    stop_all()

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("all portal backend checks passed")


main()
