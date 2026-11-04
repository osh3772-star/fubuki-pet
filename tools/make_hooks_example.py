"""Write an EXAMPLE only. Never modify .codex/hooks.json or trust settings."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
python=ROOT/'.venv/Scripts/python.exe';script=ROOT/'tools/codex_hook_bridge.py'
command=f'"{python}" "{script}"'
hooks={name:[{'hooks':[{'type':'command','command':command,'commandWindows':command,'timeout':2}]}] for name in ['UserPromptSubmit','PreToolUse','PermissionRequest','Stop','SessionEnd']}
p=ROOT/'hooks.example.json';p.write_text(json.dumps({'description':'Optional local Codex lifecycle → Fubuki prototype; never reports Stop as success. Review and merge manually, never overwrite existing hooks.','hooks':hooks},indent=2),encoding='utf-8');print(p)
