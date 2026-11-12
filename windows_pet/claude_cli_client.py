"""Text-only adapter for the user's unmodified, locally installed Claude Code.

The official CLI owns authentication. No credential files are read or copied.
No API keys, injected OAuth tokens, custom gateways, or cloud providers are used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from .chatgpt_client import (
    Cancelled, ChatGPTError, DEFAULT_MAX_REPLY_CHARS, _check, validate_model_reasoning_effort,
)
from .local_cli_clients import (
    _sanitized_env, _creation_flags, _terminate_process, _validate_and_format_messages,
    _cli_output,
)

CLAUDE_MODELS = (("auto", "자동 (Claude Code 기본값)"), ("sonnet", "Claude Sonnet"), ("opus", "Claude Opus"), ("haiku", "Claude Haiku"))


def _claude_env(*, reasoning_effort=None):
    env = _sanitized_env()
    # Never inherit alternative billing, a token override, or a proxy endpoint.
    for key in tuple(env):
        if key.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_")) or key in (
            "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
            "CLAUDE_CODE_API_KEY_HELPER_TTL_MS", "CLAUDE_CONFIG_DIR",
        ):
            env.pop(key, None)
    # Claude Code gives this variable precedence over --effort. Remove it only
    # for this explicitly configured child; None preserves the CLI default.
    # https://code.claude.com/docs/en/model-config#adjust-effort-level
    if reasoning_effort is not None:
        env.pop("CLAUDE_CODE_EFFORT_LEVEL", None)
    return env


def _find_claude_command():
    candidates = [Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")]
    found = shutil.which("claude.exe") or shutil.which("claude")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        # Native binary only: never pass a .cmd wrapper to a shell.
        if candidate.is_file() and candidate.suffix.lower() not in (".cmd", ".bat"):
            return [str(candidate)]
    raise ChatGPTError("공식 Claude Code 네이티브 실행 파일을 찾지 못했습니다. Claude Code 설치 후 직접 로그인하세요.")


_CLAUDE_CAPABILITY_TIMEOUT = 15.0
_CLAUDE_PROTOCOL_EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _claude_chat_command(output_format="json"):
    return [*_find_claude_command(), "--safe-mode", "-p", "--output-format", output_format,
            "--tools", "", "--disallowedTools", "*", "--strict-mcp-config", "--mcp-config",
            '{"mcpServers":{}}', "--setting-sources", "", "--settings", '{"disableAllHooks":true}',
            "--disable-slash-commands", "--no-chrome", "--no-session-persistence", "--max-turns", "1"]


def _parse_claude_model_efforts(models):
    # Official Agent SDK ModelInfo, not guessed fields from a text/model name.
    # https://code.claude.com/docs/en/agent-sdk/typescript#modelinfo
    if not isinstance(models, list):
        return {}
    result, seen = {}, set()
    for item in models:
        if not isinstance(item, dict):
            continue
        alias = item.get("value")
        if not isinstance(alias, str) or alias == "auto" or alias not in dict(CLAUDE_MODELS):
            continue
        if alias in seen:
            result.pop(alias, None)
            continue
        seen.add(alias)
        if item.get("supportsEffort") is False:
            result[alias] = ()
            continue
        levels = item.get("supportedEffortLevels")
        if (item.get("supportsEffort") is not True or not isinstance(levels, list)
                or not levels or any(not isinstance(level, str) or level not in _CLAUDE_PROTOCOL_EFFORTS
                                     for level in levels)):
            continue
        result[alias] = tuple(level for level in _CLAUDE_PROTOCOL_EFFORTS if level in levels)
    return result


class ClaudeCLIClient:
    def __init__(self, data_dir):
        self.workspace_dir = Path(data_dir) / "claude_cli_workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._connected = False
        self._model_efforts = {}
        self.max_reply_chars = DEFAULT_MAX_REPLY_CHARS

    def session_info(self):
        return {"connected": self._connected, "email": "로컬 Claude Code 구독" if self._connected else "", "name": "Claude Code", "sharing": self._connected, "mock": False, "provider": "claude"}

    def _auth_status(self, cancel_event=None):
        _check(cancel_event)
        try:
            result = subprocess.run([*_find_claude_command(), "auth", "status"], cwd=str(self.workspace_dir), env=_claude_env(), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20, creationflags=_creation_flags())
            status = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self._connected = False
            raise ChatGPTError("Claude Code 로그인 상태를 확인하지 못했습니다. 최신 공식 CLI에서 claude auth login을 실행하세요.") from None
        _check(cancel_event)
        if result.returncode != 0 or not isinstance(status, dict) or status.get("loggedIn") is not True or status.get("authMethod") != "claude.ai":
            self._connected = False
            raise ChatGPTError("Claude 구독 직접 로그인이 필요합니다. API 키·토큰 주입·외부 공급자 연결은 사용하지 않습니다.")

    def sign_in(self, cancel_event=None):
        self._connected = False
        self._model_efforts = {}
        self._auth_status(cancel_event)
        self._connected = True
        self._model_efforts = self._probe_model_efforts(cancel_event)
        return self.session_info()

    def open_cli_login(self):
        # Let the owner authenticate in Anthropic's own flow, never in this app.
        cmd = _find_claude_command()
        if os.name != "nt":
            raise ChatGPTError("터미널에서 claude auth login을 실행하고 직접 로그인한 뒤 연결하세요.")
        subprocess.Popen([*cmd, "auth", "login"], cwd=str(self.workspace_dir), env=_claude_env(), creationflags=subprocess.CREATE_NEW_CONSOLE)

    def _probe_model_efforts(self, cancel_event=None):
        """Initialize the official control protocol without sending a user turn.

        Old/unsupported CLIs and failed metadata reads stay default-only. The
        bounded pipe reader drains stderr and honors cancellation even when the
        child is silent; no diagnostics or account data reach the UI.
        """
        _check(cancel_event)
        request_id = uuid.uuid4().hex
        request = json.dumps({"type": "control_request", "request_id": request_id,
                              "request": {"subtype": "initialize", "hooks": None}}) + "\n"
        proc = None
        try:
            cmd = [*_claude_chat_command("stream-json"), "--input-format", "stream-json", "--verbose"]
            proc = subprocess.Popen(cmd, cwd=str(self.workspace_dir), env=_claude_env(),
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                                    creationflags=_creation_flags())
            deadline = time.monotonic() + _CLAUDE_CAPABILITY_TIMEOUT
            with _cli_output(proc, request, cancel_event, deadline) as output:
                for raw_line in output:
                    try:
                        event = json.loads(raw_line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict) or event.get("type") != "control_response":
                        continue
                    response = event.get("response")
                    if not isinstance(response, dict) or response.get("request_id") != request_id:
                        continue
                    data = response.get("response")
                    if response.get("subtype") != "success" or not isinstance(data, dict):
                        return {}
                    return _parse_claude_model_efforts(data.get("models"))
        except Cancelled:
            raise
        except (ChatGPTError, OSError, ValueError, subprocess.SubprocessError):
            pass
        finally:
            if proc is not None:
                _terminate_process(proc)
        return {}

    def list_models(self, cancel_event=None, *, force_refresh=False):
        _check(cancel_event)
        if not self._connected:
            raise ChatGPTError("먼저 로컬 Claude Code 구독에 연결하세요.")
        if force_refresh:
            self._model_efforts = {}
            self._auth_status(cancel_event)
            self._model_efforts = self._probe_model_efforts(cancel_event)
        return [{"slug": code, "display_name": name} for code, name in CLAUDE_MODELS]

    def supported_reasoning_efforts(self, model):
        # No name-based inference, network call, or subprocess on the UI thread.
        if not self._connected or model == "auto":
            return None
        return self._model_efforts.get(model)

    def stream_reply(self, messages, model, on_delta, cancel_event=None, *, reasoning_effort=None):
        if not self._connected:
            raise ChatGPTError("먼저 로컬 Claude Code 구독에 연결하세요.")
        model = model or "auto"
        validate_model_reasoning_effort(self, model, reasoning_effort)
        if model not in dict(CLAUDE_MODELS):
            raise ChatGPTError("지원하지 않는 Claude 모델입니다.")
        prompt = _validate_and_format_messages(messages, self.max_reply_chars)
        self._auth_status(cancel_event)
        cmd = _claude_chat_command()
        if model != "auto":
            cmd += ["--model", model]
        if reasoning_effort is not None:
            cmd += ["--effort", reasoning_effort]
        proc = None
        try:
            proc = subprocess.Popen(cmd, cwd=str(self.workspace_dir), env=_claude_env(reasoning_effort=reasoning_effort), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=_creation_flags())
            deadline = time.monotonic() + 180
            first = True
            while True:
                _check(cancel_event)
                if time.monotonic() >= deadline:
                    raise ChatGPTError("Claude 응답 제한 시간을 넘겨 중단했습니다.")
                try:
                    stdout, _ = proc.communicate(input=prompt if first else None, timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    first = False
            _check(cancel_event)
            if proc.returncode != 0:
                raise ChatGPTError("Claude 응답을 받지 못했습니다. 로그인·모델 접근·구독 한도를 확인하세요. 유료 API로 전환하지 않습니다.")
            data = json.loads(stdout)
            if not isinstance(data, dict) or data.get("type") != "result" or data.get("is_error") or data.get("subtype") != "success":
                raise ChatGPTError("Claude 응답이 완료되지 않았습니다. 다시 연결해 주세요.")
            reply = data.get("result")
            if not isinstance(reply, str) or not reply.strip() or len(reply) > 20000:
                raise ChatGPTError("Claude에서 올바른 텍스트 응답을 받지 못했습니다.")
            on_delta(reply)
            return reply
        except (OSError, ValueError):
            raise ChatGPTError("Claude Code 실행 또는 응답 형식을 확인하지 못했습니다. 최신 CLI 설치 상태를 확인하세요.") from None
        finally:
            if proc is not None:
                _terminate_process(proc)

    def logout(self):
        self._connected = False
        self._model_efforts = {}
        return {"revoked": False, "message": "후부키 연결만 해제했습니다. Claude Code 로그인은 유지됩니다."}
