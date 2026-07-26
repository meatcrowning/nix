#!/usr/bin/env python3
"""Name the audio in a file by acoustic fingerprint, via AcoustID.

This is the piece `audit-tags-vs-mb.py` cannot do: it says "this file's length
disagrees with the track it claims", and this says what the audio actually IS.

    acoustid-id.py FILE...                  # identify these files
    acoustid-id.py --audit [--class A,B]    # identify everything the audit flagged
    acoustid-id.py --audit --all            # ...including class C folders

Key: $ACOUSTID_KEY, else ~/.local/state/acoystid/apikey (0600). Never in the repo.
Results cache in ~/.cache/acoustid-id/<sha1-of-fingerprint>.json, so a re-run is
free and interrupted runs resume.

Reading the output: AcoustID returns candidate recordings with a match score.
A score below ~0.85 on a full-length fingerprint is a weak claim - treat it as a
hint, not an identification. When several recordings share a fingerprint (the
same track on ten compilations) they are all listed; that is normal, not
ambiguity about what the audio is.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.acoustid.org/v2/lookup'
CACHE = os.path.expanduser('~/.cache/acoustid-id')
AUDIT = os.path.expanduser('~/.cache/library-tag-audit/audit.json')
KEYFILE = os.path.expanduser('~/.local/state/acoustid/apikey')
UA = 'lam-library-audit/1.0 ( joelcvan@gmail.com )'


def key():
    k = os.environ.get('ACOUSTID_KEY')
    if not k and os.path.exists(KEYFILE):
        k = open(KEYFILE).read().strip()
    if not k:
        sys.exit(f"no AcoustID key: set $ACOUSTID_KEY or put one in {KEYFILE}")
    return k


def fingerprint(path):
    """Whole-file fingerprint. Length matters: AcoustID matches on the first
    ~2 min by default, and a wrong-audio file can share an intro with the real
    one, so don't shorten this."""
    r = subprocess.run(['fpcalc', '-json', path], capture_output=True, text=True)
    if r.returncode != 0:
        return None, None
    d = json.loads(r.stdout)
    return int(d['duration']), d['fingerprint']


# SPACE-separated, not '+'-separated: urlencode escapes a literal '+' to %2B and
# the API then silently ignores the whole meta list, answering with bare ids and
# a perfect score - which looks like "identified" and tells you nothing.
META = 'recordings releasegroups'


def lookup(dur, fp, k):
    h = hashlib.sha1((META + '\0' + fp).encode()).hexdigest()
    cp = os.path.join(CACHE, h + '.json')
    if os.path.exists(cp):
        return json.load(open(cp))
    q = urllib.parse.urlencode({'client': k, 'duration': dur, 'fingerprint': fp,
                                'meta': META})
    for attempt in range(4):
        try:
            req = urllib.request.Request(API, data=q.encode(),
                                         headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=40) as f:
                d = json.loads(f.read())
            os.makedirs(CACHE, exist_ok=True)
            json.dump(d, open(cp, 'w'), ensure_ascii=False)
            return d
        except urllib.error.HTTPError as e:
            if e.code == 400:                       # malformed/unknown -> don't retry
                return {'status': 'error', 'error': {'message': f'HTTP 400'}}
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return {'status': 'error', 'error': {'message': 'gave up'}}


def best(d, limit=3):
    """Flatten to (score, artist, title, [release groups]) rows, best first."""
    rows = []
    for res in (d.get('results') or []):
        for rec in (res.get('recordings') or [{}]):
            artist = ' & '.join(a.get('name', '') for a in (rec.get('artists') or []))
            rgs = [rg.get('title') for rg in (rec.get('releasegroups') or [])][:4]
            rows.append((res.get('score', 0), artist, rec.get('title') or '', rgs,
                         (rec.get('duration') or 0)))
    rows.sort(key=lambda r: -r[0])
    return rows[:limit]


def identify(paths, k, pace=0.4):
    out = []
    for n, p in enumerate(paths, 1):
        dur, fp = fingerprint(p)
        if not fp:
            print(f"  ! could not fingerprint {p}", flush=True)
            continue
        d = lookup(dur, fp, k)
        rows = best(d)
        out.append({'path': p, 'dur': dur, 'candidates': [
            {'score': round(r[0], 3), 'artist': r[1], 'title': r[2],
             'releasegroups': r[3], 'rec_dur': r[4]} for r in rows]})
        short = p.split('/aud/')[-1]
        if not rows:
            print(f"[{n}/{len(paths)}] {short}\n      NOT IN ACOUSTID", flush=True)
        else:
            print(f"[{n}/{len(paths)}] {short}  ({dur}s)", flush=True)
            for r in rows:
                print(f"      {r[0]:.2f}  {r[1]} - {r[2]}"
                      f"{('  [' + '; '.join(x for x in r[3] if x) + ']') if r[3] else ''}",
                      flush=True)
        time.sleep(pace)                            # AcoustID allows ~3/s; stay under
    return out


def main():
    argv = sys.argv[1:]
    k = key()
    if '--audit' in argv:
        a = json.load(open(AUDIT))
        want = 'A,B'
        if '--class' in argv:
            want = argv[argv.index('--class') + 1]
        paths = []
        if 'A' in want:
            paths += [p['path'] for p in a['wrong']]
        if 'B' in want:
            paths += [p['path'] for p in a['short']]
        if '--all' in argv or 'C' in want:
            for e in a['edition']:
                paths += [os.path.join(e['folder'], f)
                          for f in sorted(os.listdir(e['folder']))
                          if f.lower().endswith(('.mp3', '.flac', '.m4a', '.opus', '.ogg'))]
        paths = list(dict.fromkeys(paths))
    else:
        paths = [p for p in argv if not p.startswith('--')]
    if not paths:
        print(__doc__)
        sys.exit(2)
    res = identify(paths, k)
    out = os.path.join(CACHE, 'last-run.json')
    os.makedirs(CACHE, exist_ok=True)
    json.dump(res, open(out, 'w'), ensure_ascii=False, indent=1)
    named = sum(1 for r in res if r['candidates'])
    print(f"\n{named}/{len(res)} identified -> {out}")


if __name__ == '__main__':
    main()
