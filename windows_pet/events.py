"""Opt-in local file inbox. No network listener, transcript reads, or private API."""
from __future__ import annotations
import json,os,time,uuid
from pathlib import Path
from .core import JOB_STATES

def data_directory()->Path:
    override=os.environ.get('FUBUKI_DATA_DIR')
    if override:return Path(override).expanduser()
    base=Path(os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')
    return base/'FubukiPet'

def emit(state:str,origin:str='manual',session:str='default',directory:Path|None=None)->Path:
    if state not in JOB_STATES:raise ValueError('Invalid state')
    if origin not in {'manual','local_app','codex_hook'}:raise ValueError('Invalid origin')
    if not isinstance(session,str) or len(session)>128:raise ValueError('Invalid session')
    folder=(directory or data_directory())/'inbox';folder.mkdir(parents=True,exist_ok=True)
    # Bound queue growth if the pet is not running.
    old=sorted(folder.glob('*.json'),key=lambda p:p.name)
    for p in old[:-255]:
        try:p.unlink()
        except OSError:pass
    uid=uuid.uuid4().hex
    obj={'id':uid,'state':state,'origin':origin,'session':session,'created_at':time.time()}
    tmp=folder/f'.{uid}.tmp';dst=folder/f'{time.time_ns():020}_{uid}.json'
    tmp.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8');tmp.replace(dst)
    return dst

def read_events(directory:Path|None=None,now:float|None=None)->list[dict]:
    folder=(directory or data_directory())/'inbox';clock=time.time() if now is None else now
    if not folder.is_dir():return []
    result=[]
    for p in sorted(folder.glob('*.json'))[:64]:
        try:
            if p.is_symlink() or p.stat().st_size>4096:continue
            d=json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(d,dict):continue
            if not isinstance(d.get('created_at'),(float,int)) or not 0<=clock-d['created_at']<=60:continue
            if d.get('state') not in JOB_STATES or d.get('origin') not in {'manual','local_app','codex_hook'}:continue
            if not isinstance(d.get('session'),str) or len(d['session'])>128:continue
            if not isinstance(d.get('id'),str) or len(d['id'])>64:continue
            result.append(d)
        except (ValueError,OSError,TypeError):pass
        finally:
            try:p.unlink()
            except OSError:pass
    return result
