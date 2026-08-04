#!/usr/bin/env python3
"""Ask of every file: is the AUDIO the recording its tags claim?

The library's dedupe sweep answered "are these two files the same?". This
answers a different question that no amount of comparing files to each other
can settle: a file can be the only copy of a track and still hold the wrong
audio. ~94% of this library carries a MusicBrainz release id in its own tags,
which gives an outside opinion on how long each track should be.

    scan    read tags + real audio length out of every file      (needs mutagen)
    fetch   pull each referenced MB release, 1 req/s, cached     (stdlib only)
    report  compare, classify, write the work list               (stdlib only)

State lives in ~/.cache/library-tag-audit/ so every step resumes.

    audit-tags-vs-mb.py scan && audit-tags-vs-mb.py fetch && audit-tags-vs-mb.py report

WHAT THE OUTPUT IS AND IS NOT
A flag means "this file's length disagrees with MusicBrainz's length for the
track it claims to be". That is a *work list*, not a verdict: a different
master, a 7" edit tagged to the 12" release, or a hidden track counted into the
canonical length all produce the same signal as genuinely wrong audio. What it
cannot do is name what the audio actually is - only a fingerprint service
(AcoustID) can. Findings were spot-checked with chromaprint before this was
written: the tempting shortcut of "the file's length matches track N on the
same release, so it must BE track N" was wrong in 13 of 14 cases tested, which
is why this script does not draw that conclusion.

Provenance: written after Baltra/Ted turned out to hold two rips of one album
where each was wrong about DIFFERENT tracks - see docs/library-tag-audit.md.
"""
import collections
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

ROOT = os.environ.get('AUDIT_ROOT', '/run/media/lam/SSD/aud')
STATE = os.path.expanduser('~/.cache/library-tag-audit')
CACHE = os.path.join(STATE, 'mbcache')
SCAN = os.path.join(STATE, 'tagscan.json')
OUT = os.path.join(STATE, 'audit.json')
UA = 'lam-library-audit/1.0 ( joelcvan@gmail.com )'
# Directories the reorg/sweep tooling also excludes: staging areas, not the library.
EXCL = {'_inbox', 'Staging', 'Transfer', '_quarantine', '_reorg'}
EXTS = ('.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aiff', '.wma')

# A pressing difference shifts a whole folder by a second or two; anything past
# this is not an offset, it is a folder full of bad files (subtracting it would
# hide them and slander the good ones).
MAX_FOLDER_OFFSET = 3.0
MIN_FILES_FOR_OFFSET = 5
FLAG_ABS = 6.0          # seconds of residual
FLAG_REL = 0.03         # ...and this fraction of the canonical length


# ---------------------------------------------------------------- scan
def cmd_scan():
    import mutagen                      # only this step needs it
    os.makedirs(STATE, exist_ok=True)
    out, n = [], 0
    for dirpath, dirnames, files in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCL]
        for f in files:
            if not f.lower().endswith(EXTS):
                continue
            p = os.path.join(dirpath, f)
            n += 1
            try:
                m = mutagen.File(p)
            except Exception as e:
                out.append({'path': p, 'err': type(e).__name__})
                continue
            if m is None:
                continue

            def g(*keys):
                t = m.tags or {}
                for k in keys:
                    try:
                        v = t.get(k)
                    except Exception:
                        v = None
                    if v:
                        val = v[0] if isinstance(v, list) else v
                        if isinstance(val, bytes):
                            # MP4FreeForm values (----:com.apple.iTunes: frames)
                            # are bytes; str() would yield "b'...'"
                            try:
                                val = val.decode('utf-8')
                            except UnicodeDecodeError:
                                val = str(val)
                        return str(val)
                return None

            out.append({
                'path': p,
                'dur': round(getattr(m.info, 'length', 0) or 0, 2),
                'album_mbid': g('TXXX:MusicBrainz Album Id', 'musicbrainz_albumid',
                                '----:com.apple.iTunes:MusicBrainz Album Id'),
                'rtid': g('TXXX:MusicBrainz Release Track Id', 'musicbrainz_releasetrackid',
                          '----:com.apple.iTunes:MusicBrainz Release Track Id'),
                'trck': g('TRCK', 'tracknumber', 'trkn'),
                'disc': g('TPOS', 'discnumber', 'disk'),
                'title': g('TIT2', 'title', '\xa9nam'),
                'album': g('TALB', 'album', '\xa9alb'),
                'artist': g('TPE1', 'artist', '\xa9ART'),
                'isrc': g('TSRC', 'isrc'),
            })
            if n % 1000 == 0:
                print(n, flush=True)
    json.dump(out, open(SCAN, 'w'), ensure_ascii=False)
    tagged = sum(1 for r in out if r.get('album_mbid'))
    print(f"scanned {n} files -> {SCAN}  ({tagged} name a MusicBrainz release)")


# ---------------------------------------------------------------- fetch
def cmd_fetch():
    os.makedirs(CACHE, exist_ok=True)
    scan = json.load(open(SCAN))
    ids = sorted({r['album_mbid'] for r in scan
                  if r.get('album_mbid') and len(r['album_mbid']) == 36})
    todo = [i for i in ids if not os.path.exists(os.path.join(CACHE, i + '.json'))]
    print(f"{len(ids)} releases referenced, {len(todo)} to fetch", flush=True)
    dead = got = miss = 0
    for n, rid in enumerate(todo, 1):
        url = (f"https://musicbrainz.org/ws/2/release/{rid}"
               "?fmt=json&inc=recordings+artist-credits")
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=30) as f:
                    body = f.read()
                json.loads(body)                      # don't cache truncated JSON
                open(os.path.join(CACHE, rid + '.json'), 'wb').write(body)
                got, dead = got + 1, 0
                break
            except urllib.error.HTTPError as e:
                if e.code in (400, 404):              # gone for good, remember that
                    open(os.path.join(CACHE, rid + '.json'), 'w').write('{"error":%d}' % e.code)
                    miss, dead = miss + 1, 0
                    break
                time.sleep(1.5 * (attempt + 1))       # 503 means slow down, retry SAME id
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        else:
            dead += 1
            print(f"  gave up on {rid}", flush=True)
        if dead >= 10:
            print("10 in a row failed - stopping, re-run to resume", flush=True)
            break
        if n % 100 == 0:
            print(f"  {n}/{len(todo)} ok={got} notfound={miss}", flush=True)
        time.sleep(1.05)                              # MB asks for <=1 req/s
    print(f"done: ok={got} notfound={miss}")


# ---------------------------------------------------------------- report
def load_releases():
    rel = {}
    for f in os.listdir(CACHE):
        try:
            d = json.load(open(os.path.join(CACHE, f)))
        except Exception:
            continue
        if not isinstance(d, dict) or d.get('error'):
            continue
        bytrack, bypos = {}, {}
        for mi, m in enumerate(d.get('media') or [], 1):
            disc = m.get('position') or mi
            for t in m.get('tracks') or []:
                ln = t.get('length') or (t.get('recording') or {}).get('length') or 0
                e = {'title': t.get('title') or '', 'len': ln / 1000.0}
                bytrack[t['id']] = e
                bypos[(disc, t.get('position'))] = e
        rel[f[:-5]] = {'title': d.get('title'), 'bytrack': bytrack, 'bypos': bypos,
                       'discs': len(d.get('media') or [])}
    return rel


def num(s):
    digits = ''.join(c for c in str(s or '').split('/')[0] if c.isdigit())
    return int(digits) if digits else None


def cmd_report():
    scan = json.load(open(SCAN))
    rel = load_releases()
    paired, unresolved, untagged = [], 0, 0
    for r in scan:
        rid = r.get('album_mbid')
        if not rid:
            untagged += 1
            continue
        if rid not in rel:
            continue
        R = rel[rid]
        e, how = R['bytrack'].get(r.get('rtid')), 'rtid'
        if e is None:
            d, t = num(r.get('disc')) or 1, num(r.get('trck'))
            if t is None:
                continue
            e = R['bypos'].get((d, t))
            if e is None and R['discs'] == 1:
                e = R['bypos'].get((1, t))
            how = 'pos'
        if e is None or not e['len']:
            unresolved += 1
            continue
        paired.append({'path': r['path'], 'folder': os.path.dirname(r['path']),
                       'dur': r['dur'], 'canon': round(e['len'], 1),
                       'delta': r['dur'] - e['len'], 'how': how,
                       'file_title': r.get('title') or '', 'canon_title': e['title'],
                       'release': R['title'], 'mbid': rid})

    byfolder = collections.defaultdict(list)
    for p in paired:
        byfolder[p['folder']].append(p)

    wrong, short, edition = [], [], []
    for folder, ps in byfolder.items():
        off = statistics.median(p['delta'] for p in ps)
        if len(ps) < MIN_FILES_FOR_OFFSET or abs(off) > MAX_FOLDER_OFFSET:
            off = 0.0
        for p in ps:
            p['resid'] = round(p['delta'] - off, 1)
            p['folder_offset'] = round(off, 1)
        hits = [p for p in ps
                if abs(p['resid']) > FLAG_ABS and abs(p['resid']) > FLAG_REL * p['canon']]
        if len(ps) >= 5 and len(hits) > 0.6 * len(ps):
            # the whole folder disagrees: the TAGS name the wrong release, most
            # likely, and flagging every file in it would just be noise
            edition.append({'folder': folder, 'n': len(ps), 'bad': len(hits),
                            'release': ps[0]['release'], 'mbid': ps[0]['mbid'],
                            'median_offset': round(off, 1)})
            continue
        for p in hits:
            (short if p['resid'] < -20 and p['dur'] < 0.75 * p['canon'] else wrong).append(p)

    wrong.sort(key=lambda p: -abs(p['resid']))
    short.sort(key=lambda p: p['dur'] / p['canon'])
    edition.sort(key=lambda e: -e['bad'])
    json.dump({'wrong': wrong, 'short': short, 'edition': edition},
              open(OUT, 'w'), ensure_ascii=False, indent=1)

    print(f"files paired with a canonical MusicBrainz track : {len(paired)}")
    print(f"folders covered                                 : {len(byfolder)}")
    print(f"files with no MB release id (not auditable)      : {untagged}")
    print(f"named a release with no usable track length      : {unresolved}\n")
    print(f"A. length disagrees - suspect audio  : {len(wrong)}")
    print(f"B. much shorter than claimed         : {len(short)}")
    print(f"C. whole folder disagrees (wrong release tagged) : {len(edition)} folders\n")
    for p in wrong[:30]:
        print(f"  A {p['resid']:+8.1f}s  {p['dur']:7.1f} vs {p['canon']:7.1f}  "
              f"{p['path'].split('/aud/')[-1]}")
    for p in short[:20]:
        print(f"  B {100 * p['dur'] / p['canon']:5.1f}%  {p['dur']:7.1f} vs {p['canon']:7.1f}  "
              f"{p['path'].split('/aud/')[-1]}")
    for e in edition[:20]:
        print(f"  C {e['bad']:3d}/{e['n']:<3d}  {e['folder'].split('/aud/')[-1]}")
    print(f"\n-> {OUT}")


CMDS = {'scan': cmd_scan, 'fetch': cmd_fetch, 'report': cmd_report}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        print("commands:", ', '.join(CMDS))
        sys.exit(2)
    CMDS[sys.argv[1]]()
