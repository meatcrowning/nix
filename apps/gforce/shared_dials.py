"""Dial settings carried by docs sync, with one writer file per host."""
import fcntl
import json
import math
import os
from pathlib import Path
import socket
import tempfile
import time


def valid(value):
    if isinstance(value,bool): return True
    if isinstance(value,(int,float)): return math.isfinite(value)
    if isinstance(value,list): return len(value)<=8 and all(valid(v) for v in value)
    if isinstance(value,dict): return len(value)<=16 and all(isinstance(k,str) and valid(v) for k,v in value.items())
    return False


class SharedDials:
    def __init__(self,keys,local_state,directory=None,host=None):
        self.keys=set(keys)-{'panel'}
        self.local_state=Path(local_state)
        self.directory=Path(directory or os.environ.get('GF_SHARED_DIALS_DIR','/home/lam/nix/docs/agents/gforce-settings'))
        self.host=host or os.environ.get('GF_SETTINGS_HOST') or {'top':'top','book':'air'}.get(socket.gethostname().split('.')[0])
        self.seen={}

    def records(self,host):
        try:
            data=json.loads((self.directory/(host+'.json')).read_text())
            return {k:v for k,v in data.items() if k in self.keys and isinstance(v,dict)
                    and isinstance(v.get('updated'),int) and v['updated']>0
                    and valid(v.get('value'))}
        except (OSError,ValueError,AttributeError): return {}

    def read(self,local):
        data=dict(local)
        # Separate writer files let offline changes merge without JSON conflict
        # markers. Per-setting timestamps preserve unrelated edits on each host.
        merged={}
        for host in ('air','top'):
            for key,record in self.records(host).items():
                if key not in merged or record['updated']>=merged[key]['updated']:
                    merged[key]=record
        data.update({k:r['value'] for k,r in merged.items()})
        self.seen={k:v for k,v in data.items() if k in self.keys}
        return data

    def save(self,data):
        changes={k:v for k,v in data.items() if k in self.keys and valid(v)
                 and (k not in self.seen or v!=self.seen[k])}
        # The app may run without the private repo, including isolated tests.
        # Never create a replacement docs tree when the real profile is absent.
        if not changes or self.host not in ('top','air') or not self.directory.is_dir(): return
        self.local_state.mkdir(parents=True,exist_ok=True)
        with (self.local_state/'shared-dials.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            records=self.records(self.host)
            stamp=time.time_ns()
            for key,value in changes.items():
                records[key]={'updated':stamp,'value':value}
            text=json.dumps(records,indent=1,sort_keys=True)+'\n'
            fd,tmp=tempfile.mkstemp(prefix='.'+self.host+'-',suffix='.tmp',dir=self.directory)
            try:
                with os.fdopen(fd,'w') as f:f.write(text)
                os.replace(tmp,self.directory/(self.host+'.json'))
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
        self.seen.update(changes)
