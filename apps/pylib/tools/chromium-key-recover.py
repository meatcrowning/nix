#!/usr/bin/env python3
"""Find the kwallet secret that decrypts a Chromium profile's v11 blobs.

Chromium on Linux encrypts cookies and saved passwords with a key it keeps in
the desktop keyring. Which keyring slot it lands in depends on the password
store it picked, and that changes with the session (KDE -> kwallet, unknown DE
-> libsecret or the hardcoded `peanuts` fallback). A slot that is empty gets a
FRESH random key written into it, and everything written under the old one is
then undecryptable and gets deleted on the next run.

This reads every candidate slot out of kdewallet, tests each against a real
v11 blob from the profile, and says which one is the real key. It writes
nothing; `--adopt <slot>` is the separate, explicit step that copies the
winning key into the slot the browser reads today.
"""
import argparse, hashlib, os, shutil, sqlite3, subprocess, sys, tempfile

WALLET = "kdewallet"
# folder, entry.  Order is just presentation.
SLOTS = [
    ("Chrome Keys", "Chrome Safe Storage"),           # kwallet backend (KDE session)
    ("Chromium Keys", "Chromium Safe Storage"),
    ("Secret Service", "Chrome Safe Storage"),        # libsecret backend
    ("xdg-desktop-portal", "com.vivaldi.Vivaldi"),    # Secret portal (flatpak/sandboxed)
    ("xdg-desktop-portal", "org.chromium.Chromium"),
]

# ---------------------------------------------------------------- pure-python AES-128
_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
_INV = [0] * 256
for i, v in enumerate(_SBOX):
    _INV[v] = i
_INV = bytes(_INV)
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _xt(a):
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _expand(key):
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[x] for x in t]
            t[0] ^= _RCON[i // 4 - 1]
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    return w


def _decrypt_block(blk, w):
    s = [list(blk[i::4]) for i in range(4)]  # column-major -> state rows

    def addrk(rnd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rnd * 4 + c][r]

    addrk(10)
    for rnd in range(9, -1, -1):
        for r in range(1, 4):                       # inv shift rows
            s[r] = s[r][-r:] + s[r][:-r]
        for r in range(4):                          # inv sub bytes
            s[r] = [_INV[x] for x in s[r]]
        addrk(rnd)
        if rnd:                                     # inv mix columns
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = _mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9)
                s[1][c] = _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13)
                s[2][c] = _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11)
                s[3][c] = _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def aes128_cbc_decrypt(key, iv, data):
    w = _expand(key)
    out, prev = bytearray(), iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(_decrypt_block(blk, w), prev))
        prev = blk
    return bytes(out)


# ---------------------------------------------------------------- chromium os_crypt
def chromium_key(secret: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", secret, b"saltysalt", 1, 16)


def try_decrypt(secret: bytes, blob: bytes):
    """Return plaintext if `secret` decrypts this v10/v11 blob, else None."""
    body = blob[3:]
    if not body or len(body) % 16:
        return None
    pt = aes128_cbc_decrypt(chromium_key(secret), b" " * 16, body)
    pad = pt[-1]
    if not 1 <= pad <= 16 or pt[-pad:] != bytes([pad]) * pad:
        return None
    return pt[:-pad]


# ---------------------------------------------------------------- wallet + profile
def read_slot(folder, entry):
    p = subprocess.run(
        ["kwallet-query", "-f", folder, "-r", entry, WALLET],
        capture_output=True, text=True)
    if p.returncode != 0:
        return None, (p.stderr.strip() or "read failed")
    val = p.stdout.rstrip("\n")
    if not val or "not found" in val.lower():
        return None, "empty"
    return val.encode(), None


def samples(profile, n=6):
    """A few (label, blob) pairs from the profile's encrypted stores."""
    out = []
    for db, tbl, col in (("Cookies", "cookies", "encrypted_value"),
                         ("Login Data", "logins", "password_value")):
        src = os.path.join(profile, "Default", db)
        if not os.path.exists(src):
            continue
        tmp = os.path.join(tempfile.mkdtemp(), db.replace(" ", "_"))
        shutil.copy(src, tmp)
        con = sqlite3.connect(tmp)
        for (v,) in con.execute(f"select {col} from {tbl}"):
            if v and bytes(v[:3]) == b"v11":
                out.append((db, bytes(v)))
                if len([x for x in out if x[0] == db]) >= n:
                    break
        con.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.path.expanduser("~/.config/vivaldi"))
    ap.add_argument("--adopt", metavar="FOLDER/ENTRY",
                    help="copy the winning key into this slot (the only write)")
    a = ap.parse_args()

    blobs = samples(a.profile)
    if not blobs:
        sys.exit("no v11 blobs in that profile — nothing to match against")
    print(f"{len(blobs)} v11 samples from {a.profile}\n")

    winner = None
    for folder, entry in SLOTS:
        secret, err = read_slot(folder, entry)
        if secret is None:
            print(f"  {folder}/{entry}: {err}")
            continue
        hits = [(lbl, try_decrypt(secret, b)) for lbl, b in blobs]
        ok = sum(1 for _, pt in hits if pt is not None)
        mark = "MATCH" if ok == len(hits) else f"{ok}/{len(hits)}"
        print(f"  {folder}/{entry}: {mark}")
        if ok == len(hits) and winner is None:
            winner = (folder, entry, secret)

    if not winner:
        print("\nno stored secret decrypts this profile.")
        sys.exit(1)
    f, e, secret = winner
    print(f"\nthe real key is {f}/{e}")

    if a.adopt:
        tf, _, te = a.adopt.partition("/")
        if not te:
            sys.exit("--adopt takes FOLDER/ENTRY")
        p = subprocess.run(["kwallet-query", "-f", tf, "-w", te, WALLET],
                           input=secret.decode(), capture_output=True, text=True)
        if p.returncode != 0:
            sys.exit(p.stderr.strip() or "write failed")
        print(f"wrote it to {tf}/{te}")


if __name__ == "__main__":
    main()
