#!/usr/bin/env python3
"""Scratch SQLite worker deadlines and reused row identity; no GUI/audio."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metadatawrites import MetadataWrites

with tempfile.TemporaryDirectory(prefix='player-metadata-worker-') as scratch:
    path = Path(scratch) / 'library.db'
    con = sqlite3.connect(path)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('CREATE TABLE tracks (id INTEGER PRIMARY KEY, path TEXT, rating REAL, favorite INTEGER, play_count INTEGER, last_played REAL, meta_mtime REAL)')
    con.execute("INSERT INTO tracks VALUES (1, '/old.flac', 0, 0, 0, 0, 0)")
    con.commit()
    worker = MetadataWrites(path, timeout=0.15)

    def job(seq, field='rating', path='/old.flac'):
        return {'seq': seq, 'id': 1, 'path': path, 'field': field,
                'value': 0.8, 'time': time.time()}

    con.execute('BEGIN IMMEDIATE')
    start = time.monotonic()
    for i in range(20):
        worker.submit(job(i))
    worker.wait()
    elapsed = time.monotonic() - start
    results = worker.results()
    assert len(results) == 20 and all(error and row is None for _, row, error in results)
    assert elapsed < 0.8, f'queued lock waits multiplied: {elapsed:.2f}s'
    con.rollback()
    assert con.execute('SELECT rating FROM tracks').fetchone()[0] == 0

    # Writer waits while deletion/import reuses the INTEGER PRIMARY KEY.
    con.execute('BEGIN IMMEDIATE')
    con.execute('DELETE FROM tracks')
    con.execute("INSERT INTO tracks VALUES (1, '/new.flac', 0, 0, 0, 0, 0)")
    worker.submit(job(21))
    con.commit()
    worker.wait()
    result = worker.results()[0]
    assert result[1] is None and 'no longer' in result[2]
    assert con.execute('SELECT rating FROM tracks').fetchone()[0] == 0
    worker.submit(job(22, path='/new.flac'))
    worker.submit(job(23, field='play_count', path='/new.flac'))
    worker.wait()
    results = worker.results()
    assert len(results) == 2 and all(not error for _, _, error in results)
    assert con.execute('SELECT rating, play_count FROM tracks').fetchone() == (0.8, 1)
    con.close()
    print(f'metadata worker: 20 blocked jobs drained in {elapsed:.2f}s; reused ids rejected; restart and increment passed')
