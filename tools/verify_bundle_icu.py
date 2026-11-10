"""Repair a verified ICU name collision inside a newly built bundle only."""
from pathlib import Path
import json,os,hashlib
import pefile

def repair(folder):
    folder=Path(folder).resolve()
    internal=folder/'_internal'
    candidate=internal/'icuuc.dll'
    if not candidate.is_file(): return {'status':'no_bundled_icu'}
    def exports(path):
        pe=pefile.PE(str(path))
        result={s.name for s in getattr(pe,'DIRECTORY_ENTRY_EXPORT').symbols if s.name}
        pe.close();return result
    required=set(); consumers=[]
    for path in internal.rglob('*.dll'):
        pe=pefile.PE(str(path),fast_load=True)
        pe.parse_data_directories(directories=[1])
        for entry in getattr(pe,'DIRECTORY_ENTRY_IMPORT',[]):
            if entry.dll.lower()==b'icuuc.dll':
                if any(item.name is None for item in entry.imports): raise RuntimeError('Ordinal ICU import needs manual review')
                required.update(item.name for item in entry.imports)
                consumers.append(path.relative_to(folder).as_posix())
        pe.close()
    missing=required-exports(candidate)
    if not missing:return {'status':'compatible_bundled_icu'}
    system=Path(os.environ['SystemRoot'])/'System32/icuuc.dll'
    if not system.is_file() or not required.issubset(exports(system)):
        raise RuntimeError('No verified system ICU fallback; bundle left unchanged')
    backup=candidate.with_name('icuuc.dll.disabled-backup')
    if backup.exists():raise RuntimeError('Backup already exists; bundle left unchanged')
    sha=hashlib.sha256(candidate.read_bytes()).hexdigest()
    candidate.rename(backup)
    report={'status':'incompatible_bundled_icu_disabled','bundle_only':True,'consumers':consumers,
            'missing_symbols':sorted(s.decode() for s in missing),'disabled_dll_sha256':sha,
            'requires':'Windows system ICU with all listed symbols; verified on this PC only',
            'system_icu_sha256':hashlib.sha256(system.read_bytes()).hexdigest()}
    (folder/'RUNTIME_COMPATIBILITY.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    import sys
    print(json.dumps(repair(Path(sys.argv[1])),indent=2))
