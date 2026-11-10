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
    with tempfile.TemporaryDirectory(prefix='fubuki-move-', ignore_cleanup_errors=True) as root:
        root = Path(root)
        moved = root / '이동한 フブキ folder'
        moved.mkdir()
        destination = moved / 'FubukiPet.exe'
        shutil.copy2(exe, destination)
        if list(moved.iterdir()) != [destination]:
            raise RuntimeError('Relocation test folder is not isolated')
        env = dict(os.environ, FUBUKI_DATA_DIR=str(root / 'offline-data'), QT_QPA_PLATFORM='offscreen')
        for arguments in (['--help'], ['--chat-mock', '--smoke-test']):
            process = subprocess.Popen([str(destination), *arguments], cwd=moved, env=env,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                # Only the test process tree belongs to this harness. Preserve
                # its diagnostic before an error dialog can hide the real cause.
                for log in (root/'offline-data'/'logs').glob('*.log'):
                    print(log.name, log.read_text(encoding='utf-8', errors='replace')[-12000:], flush=True)
                if os.name == 'nt':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'], check=False,
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                else:process.kill()
                process.wait(timeout=10)
                raise RuntimeError(f'Moved EXE timed out for {arguments}') from None
            if code != 0:
                raise RuntimeError(f'Moved EXE failed for {arguments}: {code}')
            results.append({'arguments': arguments, 'exit_code': code})
        if (moved / '_internal').exists():
            raise RuntimeError('Build unexpectedly depends on a neighboring _internal folder')
    return {'standalone_python_embedded': True, 'moved_exe_only': True,
            'unicode_path': True, 'offline_tests': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.exe.resolve()), ensure_ascii=False, indent=2))
