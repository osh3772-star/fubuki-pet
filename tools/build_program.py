"""Build a native, portable Fubuki folder without certifying manual acceptance."""
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


def runtime_files(root: Path = ROOT) -> list[Path]:
    registry_path = root / 'assets/runtime_candidate.json'
    registry = json.loads(registry_path.read_text(encoding='utf-8'))
    names = {'assets/runtime_candidate.json', 'config/default-settings.json', registry['placeholder']}
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
    readme = ROOT / 'README_ko.txt'
    if readme.exists(): shutil.copy2(readme, folder / readme.name)
    files = {p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob('*'))
             if p.is_file() and p.name != 'FILE_HASHES.json'}
    (folder / 'FILE_HASHES.json').write_text(json.dumps(files, indent=2), encoding='utf-8')
    return Path(shutil.make_archive(str(folder.parent / 'FubukiPet_Windows_Portable'), 'zip', folder.parent, folder.name))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack-only', type=Path)
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
    options = ['--noconfirm', '--clean', '--windowed', '--onedir', '--noupx',
               '--name', 'FubukiPet', '--distpath', str(output), '--workpath', str(work / 'work'),
               '--specpath', str(work), '--paths', str(ROOT),
               '--exclude-module', 'PyQt5', '--exclude-module', 'PyQt6', '--exclude-module', 'PySide2']
    resources = runtime_files()
    for source in resources:
        relative_parent = source.relative_to(ROOT).parent.as_posix()
        options.extend(['--add-data', f'{source};{relative_parent}'])
    options.append(str(ROOT / 'launcher.py'))
    PyInstaller.__main__.run(options)
    folder = output / 'FubukiPet'
    exe = folder / 'FubukiPet.exe'
    if not exe.is_file(): raise RuntimeError('PyInstaller did not create FubukiPet.exe')
    info = {'program': 'Fubuki Pet', 'version': '1.0.0', 'built_at_utc': stamp,
            'platform': platform.platform(), 'python': sys.version,
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
