#!/usr/bin/env python3
"""Three-way merge for Saves files that both hosts edit.

Unison calls this for a conflict on a merge-listed file:
    merge.py sqlite|lines CURRENT1 CURRENT2 ARCHIVE NEW
ARCHIVE is the last synced version, or empty on the first sync. A change made
on one side wins over the untouched other side. A row or line changed
differently on both sides keeps the newer file's version.
"""
import os
import shutil
import sqlite3
import sys


def lines(a, b, base, out):
    def read(path):
        if not path or not os.path.exists(path):
            return []
        with open(path, encoding="utf-8", errors="surrogateescape") as f:
            return f.read().splitlines()

    one, two, old = read(a), read(b), set(read(base))
    have_one, have_two = set(one), set(two)
    # A line one side dropped since the last sync stays dropped; a new line on
    # either side is kept. Order is the first file's, then the second's new lines.
    merged = [l for l in one if l in have_two or l not in old]
    merged += [l for l in two if l not in have_one and l not in old]
    seen, result = set(), []
    for l in merged:
        # Blank and comment lines may repeat; data lines appear once.
        if l.strip() and not l.startswith("#"):
            if l in seen:
                continue
            seen.add(l)
        result.append(l)
    with open(out, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write("".join(l + "\n" for l in result))


def rows(db, table, key):
    cols = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
    found = {}
    for r in db.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}"'):
        row = dict(zip(cols, r))
        found[tuple(row[c] for c in key) if key else tuple(r)] = row
    return found


def sqlite(a, b, base, out):
    newer_first = os.path.getmtime(a) >= os.path.getmtime(b)
    tmp = out + ".merging"
    shutil.copyfile(a, tmp)
    db = sqlite3.connect(tmp)
    two = sqlite3.connect(f"file:{b}?mode=ro", uri=True)
    old = sqlite3.connect(f"file:{base}?mode=ro", uri=True) if base and os.path.exists(base) else None
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for (sql, name) in two.execute(
            "SELECT sql, name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if name not in tables:
            db.execute(sql)
            tables.append(name)
    for table in tables:
        info = list(db.execute(f'PRAGMA table_info("{table}")'))
        key = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
        mine = rows(db, table, key)

        def other(conn):
            try:
                return rows(conn, table, key) if conn else {}
            except sqlite3.OperationalError:
                return {}

        theirs, base_rows = other(two), other(old)
        merged = {}
        for k in mine.keys() | theirs.keys():
            x, y, o = mine.get(k), theirs.get(k), base_rows.get(k)
            if x == y or y == o:
                pick = x
            elif x == o:
                pick = y
            else:
                pick = x if newer_first else y
                if pick is None:  # deleted on the newer side, edited on the older
                    pick = y if newer_first else x
            if pick is not None:
                merged[k] = pick
        cols = [r[1] for r in info]
        db.execute(f'DELETE FROM "{table}"')
        db.executemany(
            f'INSERT INTO "{table}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
            f'VALUES ({", ".join("?" * len(cols))})',
            [tuple(r.get(c) for c in cols) for r in merged.values()])
    db.commit()
    db.close()
    os.replace(tmp, out)


if __name__ == "__main__":
    # CURRENTARCHOPT expands to nothing when there is no archive version.
    args = sys.argv[1:]
    kind, a, b, base, out = args if len(args) == 5 else (*args[:3], "", args[3])
    {"lines": lines, "sqlite": sqlite}[kind](a, b, base, out)
