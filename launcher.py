"""Entry point for the existing app; windowed builds log failures to disk."""
from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys


def launch_arguments(arguments:list[str], frozen:bool)->list[str]:
    result=list(arguments)
    if frozen and '--candidate-art' not in result and not any(a in result for a in ('-h','--help')):
        result.append('--candidate-art')
    return result


def launch()->int:
    from windows_pet.events import data_directory
    folder=data_directory()/'logs'
    folder.mkdir(parents=True, exist_ok=True)
    handler=RotatingFileHandler(folder/'launch.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger=logging.getLogger('fubuki.launch')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    # PyInstaller --windowed can set standard streams to None.
    opened=[]
    for name in ('stdout','stderr'):
        if getattr(sys,name) is None:
            stream=open(folder/'console.log','a',encoding='utf-8',buffering=1)
            setattr(sys,name,stream)
            opened.append((name,stream))
    sys.argv=launch_arguments(sys.argv, bool(getattr(sys,'frozen',False)))
    logger.info('Launch requested; frozen=%s',bool(getattr(sys,'frozen',False)))
    try:
        from windows_pet.app import main
        code=main()
        logger.info('Application returned %s',code)
        return code
    except Exception:
        logger.exception('Application failed to start or run')
        message='Fubuki Pet failed. See: '+str(folder/'launch.log')
        if sys.platform=='win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,message,'Fubuki Pet',0x10)
        elif sys.stderr is not None:
            print(message,file=sys.stderr)
        return 1
    finally:
        for name,stream in opened:
            stream.close()
            setattr(sys,name,None)
        logger.removeHandler(handler)
        handler.close()


if __name__=='__main__':
    raise SystemExit(launch())
