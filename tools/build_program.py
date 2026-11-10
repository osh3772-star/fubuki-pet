"""Build a movable, self-contained Windows EXE (or an explicit legacy folder)."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def runtime_files(root: Path = ROOT) -> list[Path]:
    registry_path = root / 'assets/runtime_candidate.json'
    registry = json.loads(registry_path.read_text(encoding='utf-8'))
    names = {'assets/runtime_candidate.json', 'assets/app-icon.ico', 'config/default-settings.json', registry['placeholder']}
    # Chat typography is app-private: bundle both fonts and their OFL notices.
    names.update('assets/fonts/' + name for name in (
        'NotoSansKR.ttf', 'NotoSansKR-OFL.txt',
        'NotoSansJP.ttf', 'NotoSansJP-OFL.txt'))
    for clip in registry['clips'].values():
        names.update(clip['frames'])
    files = []
    for name in sorted(names):
        source = (root / name).resolve()
        if not source.is_relative_to(root.resolve()) or not source.is_file():
            raise ValueError(f'Missing or invalid runtime asset: {name}')
        files.append(source)
    return files


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def package(folder: Path) -> Path:
    exe = folder / 'FubukiPet.exe'
    if not exe.is_file() or exe.read_bytes()[:2] != b'MZ':
        raise RuntimeError('An actual Windows executable is required for Windows packaging.')
    if (folder/'_internal').is_dir():
        from tools.prepare_bundle import prepare
        prepare(folder)
    else:
        for name in ('RIGHTS_STATUS.md','THIRD_PARTY_NOTICES.md'):
            shutil.copy2(ROOT/name,folder/name)
        shutil.copytree(ROOT/'licenses',folder/'licenses',dirs_exist_ok=True)
    readme = ROOT / 'README_ko.txt'
    if readme.exists(): shutil.copy2(readme, folder / readme.name)
    files = {p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob('*'))
             if p.is_file() and p.name != 'FILE_HASHES.json'}
    (folder / 'FILE_HASHES.json').write_text(json.dumps(files, indent=2), encoding='utf-8')
    return Path(shutil.make_archive(str(folder.parent / 'FubukiPet_Windows_Portable'), 'zip', folder.parent, folder.name))


def single_file_spec(resources, output, work):
    """Use the normal PyInstaller Analysis, then validate DLLs before archiving."""
    datas=[(str(p),p.relative_to(ROOT).parent.as_posix()) for p in resources]
    return f'''# Generated for this exact source tree; all dependencies go in EXE.
import sys, json
sys.path.insert(0, {str(ROOT)!r})
from pathlib import Path
from tools.verify_bundle_icu import validate_binary_toc
a = Analysis([{str(ROOT/'launcher.py')!r}], pathex=[{str(ROOT)!r}],
    binaries=[], datas={datas!r}, hiddenimports=[], hookspath=[], runtime_hooks=[],
    excludes=['PyQt5','PyQt6','PySide2'], noarchive=False, optimize=0)
a.binaries, report = validate_binary_toc(a.binaries)
Path({str(work/'runtime-compatibility.json')!r}).write_text(json.dumps(report), encoding='utf-8')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='FubukiPet',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    icon=[{str(ROOT/'assets/app-icon.ico')!r}])
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack-only', type=Path)
    parser.add_argument('--onedir', action='store_true', help='Legacy folder bundle; keep _internal beside EXE')
    args = parser.parse_args()
    if args.pack_only:
        print(package(args.pack_only.resolve()))
        return 0
    if sys.platform != 'win32':
        parser.error('Run this builder on Windows. It does not cross-compile or simulate an EXE.')
    import PyInstaller.__main__
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    output = ROOT / 'dist' / stamp
    work = ROOT / 'build' / stamp
    folder = output / 'FubukiPet'
    options = ['--noconfirm', '--clean', '--windowed', '--onedir', '--noupx',
               '--icon', str(ROOT / 'assets/app-icon.ico'),
               '--name', 'FubukiPet', '--distpath', str(output), '--workpath', str(work / 'work'),
               '--specpath', str(work), '--paths', str(ROOT),
               '--exclude-module', 'PyQt5', '--exclude-module', 'PyQt6', '--exclude-module', 'PySide2']
    resources = runtime_files()
    if args.onedir:
        for source in resources:
            relative_parent = source.relative_to(ROOT).parent.as_posix()
            options.extend(['--add-data', f'{source};{relative_parent}'])
        options.append(str(ROOT / 'launcher.py'))
        PyInstaller.__main__.run(options)
    else:
        work.mkdir(parents=True,exist_ok=True)
        spec=work/'FubukiPet.spec'
        spec.write_text(single_file_spec(resources,output,work),encoding='utf-8')
        PyInstaller.__main__.run(['--noconfirm','--clean','--distpath',str(folder),
                                 '--workpath',str(work/'work'),str(spec)])
    exe = folder / 'FubukiPet.exe'
    if not exe.is_file(): raise RuntimeError('PyInstaller did not create FubukiPet.exe')
    from tools.verify_exe_icon import verify
    icon_verification = verify(exe, ROOT / 'assets/app-icon.ico')
    if args.onedir:
        from tools.verify_bundle_icu import repair
        runtime_compatibility = repair(folder)
    else:
        runtime_compatibility=json.loads((work/'runtime-compatibility.json').read_text(encoding='utf-8'))
    info = {'program': 'Fubuki Pet', 'version': '1.0.0', 'built_at_utc': stamp,
            'platform': platform.platform(), 'python': sys.version,
            'bundle_mode': 'onedir' if args.onedir else 'onefile',
            'runtime_compatibility': runtime_compatibility,
            'icon_verification': icon_verification,
            'exe_sha256': sha(exe), 'manual_validation': 'user_pending',
            'artwork': 'existing integrated illustrations; original provenance retained in source',
            'source_files': {p.relative_to(ROOT).as_posix(): sha(p)
                             for p in [ROOT / 'launcher.py', *sorted((ROOT / 'windows_pet').glob('*.py')), *resources]}}
    (folder / 'BUILD_INFO.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    archive = package(folder)
    (ROOT / 'dist/latest-build.txt').write_text(str(folder), encoding='utf-8')
    print(f'EXE: {exe}\nPortable ZIP: {archive}\nManual/visual acceptance: left to the user.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
