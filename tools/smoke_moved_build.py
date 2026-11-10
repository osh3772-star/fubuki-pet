"""Prove that the EXE works alone after moving, with no network or real login."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from PyInstaller.archive.readers import CArchiveReader


def verify(exe: Path):
    archive = CArchiveReader(str(exe))
    names = {name.replace('\\', '/').lower() for name in archive.toc}
    if not any(name.startswith('python3') and name.endswith('.dll') for name in names):
        raise RuntimeError('EXE is not standalone: Python DLL is absent from its archive')
    results = []
    with tempfile.TemporaryDirectory(prefix='fubuki-move-') as root:
        root = Path(root)
        moved = root / '이동한 フブキ folder'
        moved.mkdir()
        destination = moved / 'FubukiPet.exe'
        shutil.copy2(exe, destination)
        if list(moved.iterdir()) != [destination]:
            raise RuntimeError('Relocation test folder is not isolated')
        env = dict(os.environ, FUBUKI_DATA_DIR=str(root / 'offline-data'), QT_QPA_PLATFORM='offscreen')
        for arguments in (['--help'], ['--chat-mock', '--smoke-test']):
            process = subprocess.run([str(destination), *arguments], cwd=moved, env=env,
                                     timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if process.returncode != 0:
                raise RuntimeError(f'Moved EXE failed for {arguments}: {process.returncode}')
            results.append({'arguments': arguments, 'exit_code': process.returncode})
        if (moved / '_internal').exists():
            raise RuntimeError('Build unexpectedly depends on a neighboring _internal folder')
    return {'standalone_python_embedded': True, 'moved_exe_only': True,
            'unicode_path': True, 'offline_tests': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.exe.resolve()), ensure_ascii=False, indent=2))
