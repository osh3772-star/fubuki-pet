"""Optional public Codex lifecycle-hook adapter. Never installs itself.

Consumes event names only. Never reads transcript_path, prompt, tool results,
ChatGPT memory, network tokens, or internal processes. Stop means REVIEW,
not success. Always exits 0. Stop emits an empty JSON object, as required by its
public output schema. No approval, denial, blocking, or task modification.
"""
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from windows_pet.events import emit
MAPPING={'UserPromptSubmit':'working','PreToolUse':'working','PermissionRequest':'waiting','Stop':'review','SessionEnd':'idle'}

def map_event(payload):
    if not isinstance(payload,dict):return None
    state=MAPPING.get(payload.get('hook_event_name'))
    session=payload.get('session_id')
    if state is None or not isinstance(session,str) or len(session)>128:return None
    return state,session

def main():
    event_name=None
    try:
        data=sys.stdin.buffer.read(65537)
        if len(data)>65536:return
        payload=json.loads(data)
        if isinstance(payload,dict):event_name=payload.get('hook_event_name')
        mapped=map_event(payload)
        if mapped:emit(mapped[0],'codex_hook',mapped[1])
    except (OSError,ValueError,TypeError):pass
    finally:
        if event_name=='Stop':print('{}')
if __name__=='__main__':main()
