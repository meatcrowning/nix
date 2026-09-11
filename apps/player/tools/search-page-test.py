#!/usr/bin/env python3
"""Exercise real search/page methods against scratch SQLite; no Qt or audio."""
import ast
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import artistalias          # pure stdlib + pylib/trackmatch; no Qt, no database

source = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
namespace = {"re": __import__("re")}
# Compile only pure query helpers and the methods under test. This cannot
# construct a player, open the real database or contact the desktop.
for node in source.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('_QUERY_TERM', '_YEAR_RANGE') for t in node.targets):
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<query>', 'exec'), namespace)
    if isinstance(node, ast.FunctionDef) and node.name in ('parse_query', 'year_in', 'track_row', 'query_free_text'):
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<query>', 'exec'), namespace)
namespace.update(re=__import__('re'))
for name, methods in {
    'Library': ('search', 'search_ids', 'query_parts'),
    'Bridge': ('search', '_show_search_page', 'searchPage', 'playSearch', 'playSearchAll', 'playFromModel'),
}.items():
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == name)
    selected = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in methods]
    for node in selected:
        node.decorator_list = []
    subset = ast.ClassDef(name=name, bases=[], keywords=[], body=selected, decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[subset], type_ignores=[])), '<search>', 'exec'), namespace)

con = sqlite3.connect(':memory:')
con.row_factory = sqlite3.Row
con.execute('CREATE TABLE tracks (id INTEGER PRIMARY KEY, title, artist, album, album_artist, genre, year, orig_year)')
con.executemany('INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                [(i, f'song {i}', 'Björk', 'record', 'Björk', 'rock', 1997, None) for i in range(1, 902)])
lib = namespace['Library']()
lib._con = con
lib._search_rows = None
lib.aliases = artistalias.Aliases([])      # no identities: the ordinary library
lib.tracks_by_ids = lambda ids: [dict(con.execute('SELECT * FROM tracks WHERE id=?', (i,)).fetchone()) for i in ids]
assert len(lib.search('BJÖRK genre:rock year:1997')) == 901
assert lib.search('genre:jazz') == []
assert lib.search('') == []

# One person, many names: an identity widens the ARTIST match and nothing else.
con.execute("INSERT INTO tracks VALUES (902, 'Angel', 'Chuck Person', 'eccojams',"
            " 'Chuck Person', 'rock', 1997, NULL)")
con.execute("INSERT INTO tracks VALUES (903, 'Chuck Person', 'Death Grips',"
            " 'the money store', 'Death Grips', 'rock', 1997, NULL)")
lib._search_rows = None
lib.aliases = artistalias.Aliases([["Björk", "Chuck Person"]])
ids = {r['id'] for r in lib.search('BJÖRK')}
assert 902 in ids, 'the other name\'s records must come back'
assert 903 not in ids, 'an alias must not match a TRACK TITLE'
other = {r['id'] for r in lib.search('chuck person')}
assert ids <= other, 'either name finds the whole body of work'
assert 903 in other, "…and the typed name keeps its ordinary title match"
assert len(lib.search('BJÖRK genre:jazz')) == 0, 'a field filter still narrows'
lib.aliases = artistalias.Aliases([])
lib._search_rows = None

class Model:
    def set_rows(self, rows):
        self.rows = rows
        self.count = len(rows)
    def get(self, i):
        return self.rows[i]

played = []
b = namespace['Bridge']()
b.SEARCH_PAGE_SIZE = 400
b._library = lib
b.searchModel = Model()
b.searchChanged = SimpleNamespace(emit=lambda: None)
b._player = SimpleNamespace(playTracks=lambda ids, start: played.append((ids, start)))
b.search('Björk')
assert len(b._search_ids) == 901 and b.searchModel.count == 400
seen = [r['trackId'] for r in b.searchModel.rows]
b.searchPage(1)
assert b._search_offset == 400 and b.searchModel.count == 400
seen.extend(r['trackId'] for r in b.searchModel.rows)
b.playSearch(20)
assert played[-1] == (list(range(1, 902)), 420)
b.playSearchAll()
assert played[-1] == (list(range(1, 902)), -1)
b.playFromModel(b.searchModel, 0)
assert played[-1][1] == 400
b.searchPage(1)
assert b._search_offset == 800 and b.searchModel.count == 101
seen.extend(r['trackId'] for r in b.searchModel.rows)
assert seen == list(range(1, 902))
b.searchPage(1)
assert b._search_offset == 800
b.searchPage(-1)
assert b._search_offset == 400
b.search('nothing matches')
assert not b._search_ids and b.searchModel.count == 0 and b._search_offset == 0
before = len(played)
b.playSearchAll()
assert len(played) == before
print('search: 901 results, bounded pages, Unicode/field filters, complete playback and reset passed')
