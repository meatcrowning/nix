"""Cross-host dial propagation with temporary files only; no desktop or audio."""
import json
from pathlib import Path
import tempfile
from shared_dials import SharedDials

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);shared=root/'shared';shared.mkdir()
    keys={'fps','grid','trailFill','softness','panel','intervals'}
    top=SharedDials(keys,root/'top',shared,'top')
    air=SharedDials(keys,root/'air',shared,'air')
    top.read({})
    top.save({'fps':76,'grid':2048,'trailFill':8,'softness':4,'panel':True,'intervals':{'W':[10,15]}})
    seeded=air.read({'grid':640,'panel':False})
    assert seeded['grid']==2048 and seeded['trailFill']==8 and seeded['fps']==76
    assert seeded['panel'] is False
    assert seeded['intervals']=={'W':[10,15]}
    print('PASS: air inherits top tuning while panel visibility stays local')
    # Startup/shutdown must not publish unchanged inherited settings.
    air.save(seeded)
    assert not (shared/'air.json').exists()
    original=(shared/'top.json').read_bytes()
    top.save({'fps':76,'grid':2048,'trailFill':8,'softness':4,'panel':False,'intervals':{'W':[10,15]}})
    assert (shared/'top.json').read_bytes()==original
    print('PASS: unchanged saves never claim remote settings or churn timestamps')
    # Offline edits to different dials merge, even from stale local views.
    top.save({'softness':2})
    air.save(dict(seeded,trailFill=4))
    merged=top.read({})
    assert merged['softness']==2 and merged['trailFill']==4 and merged['grid']==2048
    air.read({});air.save({'softness':1})
    assert top.read({})['softness']==1
    print('PASS: separate host files merge independent edits; latest edit wins per dial')
    (shared/'air.json').write_text('{broken')
    assert top.read({})['grid']==2048
    records=json.loads((shared/'top.json').read_text())
    records['panel']={'updated':9999999999999999999,'value':True}
    records['grid']={'updated':1,'value':float('nan')}
    (shared/'top.json').write_text(json.dumps(records))
    assert top.read({'panel':False,'grid':640})['panel'] is False
    assert top.read({'grid':640})['grid']==640
    print('PASS: malformed records, nonfinite values and local-only settings are ignored')
