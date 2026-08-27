#!/usr/bin/env python3
"""Pin a BLE input device's link-layer connection parameters.

A BLE mouse advertises "Peripheral Preferred Connection Parameters" and both
BlueZ and the kernel take it at its word.  The Logitech ERGO M575 asks for
interval 7.5-11.25 ms and **slave latency 44** (measured 2026-08-26; BlueZ
stores it verbatim in /var/lib/bluetooth/<adapter>/<dev>/info).  Latency is
the number of connection events the peripheral may skip when it has nothing
to send, so an idle trackball is allowed to stop listening for 45 x 11.25 ms
= half a second.  Moving it feels fine; STARTING to move it after a pause
does not, and that is the "sluggish, not laggy, not jittery" the USB receiver
never had (the receiver polls at a flat 125 Hz and cannot skip).

Hand-editing that stored file loses: BlueZ re-reads the characteristic on
every connect and writes it back.  So this asserts the parameters where they
actually live -- on the link -- with an HCI LE Connection Update the moment
the device connects, and again if anything moves them afterwards.

Needs root (raw HCI socket).  Read-only towards everything else on the
adapter: it only ever touches the handles whose address is on its own list.
"""
import argparse, os, select, socket, struct, sys, time

AF_BLUETOOTH, BTPROTO_HCI = 31, 1
HCI_CHANNEL_RAW, HCI_CHANNEL_MONITOR = 0, 2
MON_EVENT_PKT = 3
OP_LE_CONN_UPDATE = (0x08 << 10) | 0x0013


def log(msg):
    print("%s ble-fastconn: %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def addr_str(b):
    return ":".join("%02X" % x for x in reversed(b))


class Adapter:
    def __init__(self, index):
        self.index = index
        self.cmd = socket.socket(AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI)
        self.cmd.bind((index,))

    def conn_update(self, handle, imin, imax, latency, timeout):
        params = struct.pack("<HHHHHHH", handle, imin, imax, latency, timeout, 0, 0)
        self.cmd.send(bytes([0x01]) + struct.pack("<HB", OP_LE_CONN_UPDATE, len(params)) + params)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("addresses", nargs="+", help="BD_ADDR of the LE device(s) to pin")
    ap.add_argument("--index", type=int, default=0, help="hci index (default 0)")
    # 6 = 7.5 ms, the shortest interval the Bluetooth core spec allows, which
    # beats the receiver's 8 ms.  latency 0 = never skip an event.  The cost is
    # radio wakeups, i.e. the mouse's battery; that is the trade being made.
    ap.add_argument("--interval", type=int, default=6)
    ap.add_argument("--latency", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=200, help="supervision timeout, x10 ms")
    ap.add_argument("--once", action="store_true", help="blind-update every live handle, then exit")
    ap.add_argument("--adopt", action="store_true", help="same blind pass at start, then keep watching")
    args = ap.parse_args()

    want = {a.upper() for a in args.addresses}
    ad = Adapter(args.index)

    mon = socket.socket(AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI)
    mon.bind((0xFFFF, HCI_CHANNEL_MONITOR))

    handles = {}      # handle -> address
    last_set = {}     # handle -> monotonic of our last update, to not ping-pong

    def apply(handle, why):
        now = time.monotonic()
        if now - last_set.get(handle, 0) < 1.0:
            return
        last_set[handle] = now
        ad.conn_update(handle, args.interval, args.interval, args.latency, args.timeout)
        log("handle %d (%s): %s -> interval %.2fms latency %d"
            % (handle, handles.get(handle, "?"), why, args.interval * 1.25, args.latency))

    if args.once or args.adopt:
        # No connect event to wait for: try every live handle.  A handle that is
        # not ours answers "Unknown Connection Identifier" and nothing happens.
        for name in os.listdir("/sys/class/bluetooth"):
            if name.startswith("hci%d:" % args.index):
                h = int(name.split(":")[1])
                handles[h] = "?"
                ad.conn_update(h, args.interval, args.interval, args.latency, args.timeout)
                log("handle %d: blind update sent" % h)

    deadline = time.monotonic() + 3 if args.once else None
    if not args.once:
        log("watching for %s" % ", ".join(sorted(want)))
    while deadline is None or time.monotonic() < deadline:
        r, _, _ = select.select([mon], [], [], 0.5 if args.once else 30)
        if not r:
            continue
        pkt = mon.recv(2048)
        if len(pkt) < 6:
            continue
        opcode, index, plen = struct.unpack("<HHH", pkt[:6])
        if opcode != MON_EVENT_PKT or index != args.index:
            continue
        ev = pkt[6:6 + plen]
        if len(ev) < 2:
            continue
        if ev[0] == 0x05 and len(ev) >= 5:            # Disconnection Complete
            handles.pop(struct.unpack("<H", ev[3:5])[0], None)
            continue
        if ev[0] != 0x3E:
            continue
        sub, body = ev[2], ev[3:]
        if sub in (0x01, 0x0A) and len(body) >= 10:   # (Enhanced) Connection Complete
            status, handle = body[0], struct.unpack("<H", body[1:3])[0]
            addr = addr_str(body[4:10])
            if status == 0 and addr in want:
                handles[handle] = addr
                apply(handle, "connected")
        elif sub == 0x03 and len(body) >= 9:          # Connection Update Complete
            status, handle, iv, lat, sup = struct.unpack("<BHHHH", body[:9])
            if status == 0 and handle in handles:
                if iv != args.interval or lat != args.latency:
                    log("handle %d drifted to interval %.2fms latency %d" % (handle, iv * 1.25, lat))
                    apply(handle, "re-asserting")
                else:
                    log("handle %d (%s): interval %.2fms latency %d timeout %dms"
                        % (handle, handles[handle], iv * 1.25, lat, sup * 10))


if __name__ == "__main__":
    sys.exit(main())
