"""Prepare a review-only copy of an existing Fubuki portable directory."""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OMIT_QT = ('_internal/PySide6/Qt6VirtualKeyboard.dll',
           '_internal/PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll')

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def prepare(folder: Path):
    folder = folder.resolve()
    exe = folder/'FubukiPet.exe'
    if not exe.is_file() or exe.read_bytes()[:2] != b'MZ':
        raise ValueError('An existing Windows bundle is required')
    # Only these exact, unused package files may be removed, within this copy.
    removed = []
    for name in OMIT_QT:
        target = (folder/name).resolve()
        if not target.is_relative_to(folder): raise ValueError('Out of scope path')
        if target.exists():
            target.unlink()
            removed.append(name)
    for name in ('README_ko.txt','RIGHTS_STATUS.md','THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT/name,folder/name)
    shutil.copytree(ROOT/'licenses',folder/'licenses',dirs_exist_ok=True)
    shutil.copy2(ROOT/'assets/runtime_candidate.json',folder/'_internal/assets/runtime_candidate.json')
    info_path=folder/'BUILD_INFO.json'
    info=json.loads(info_path.read_text(encoding='utf-8'))
    info['review_repack']={
        'public_release_approved':False,
        'changes':['Internal Library identifier removed from copied registry','Third-party license evidence added','Unused Qt Virtual Keyboard library and plugin omitted'],
        'base_executable_unchanged':True,
        'excluded_files':list(OMIT_QT),
        'corresponding_source_notice_review':'pending'}
    # Existing source_files hashes document the original CI build; make that scope explicit.
    info['source_files_scope']='pre-repack build, before review-only registry metadata edit'
    info_path.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    hashes={p.relative_to(folder).as_posix():sha(p) for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='FILE_HASHES.json'}
    (folder/'FILE_HASHES.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    return {'files':len(hashes),'removed':removed,'exe_sha256':sha(exe)}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path)
    print(json.dumps(prepare(p.parse_args().folder),indent=2))
