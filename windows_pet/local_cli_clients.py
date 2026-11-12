"""Local official CLI clients for Gemini CLI and Antigravity (Gemini only).

Never reads OAuth tokens, cookies, or local credential files.
Never uses or accepts API keys; strips API key environment variables before
invoking the official local CLI executable.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import queue
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time

from .chatgpt_client import (
    Cancelled,
    ChatGPTError,
    DEFAULT_MAX_REPLY_CHARS,
    PERSONA,
    _check,
    validate_model_reasoning_effort,
    build_persona_instructions,
)

PROVIDERS = (
    ("chatgpt", "ChatGPT 구독 (OpenAI 공식 로그인)"),
    ("gemini", "Gemini (로컬 Gemini CLI)"),
    ("antigravity_gemini", "Antigravity Gemini (로컬 Antigravity)"),
    ("claude", "Claude (로컬 Claude Code 구독)"),
)

GEMINI_CLI_MODELS = (
    ("auto", "자동 (Gemini CLI 기본값)"),
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview"),
    ("gemini-3-pro-preview", "Gemini 3 Pro Preview"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash"),
    ("gemini-3-flash-preview", "Gemini 3 Flash Preview"),
    ("gemini-2.5-pro", "Gemini 2.5 Pro"),
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite"),
    ("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite"),
)

VALID_GEMINI_CLI_SLUGS = frozenset(slug for slug, _ in GEMINI_CLI_MODELS)
# Exact documented model IDs, not provider-wide or future-prefix guesses.
# https://ai.google.dev/gemini-api/docs/thinking
# https://geminicli.com/docs/reference/configuration/
_GEMINI_THINKING_LEVEL_MODELS = frozenset((
    "gemini-3.1-pro-preview", "gemini-3-pro-preview", "gemini-3.8-flash",
    "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
))
_GEMINI_THINKING_BUDGET_MODELS = frozenset(("gemini-2.5-pro",))


def _gemini_reasoning_efforts(model):
    if model in _GEMINI_THINKING_LEVEL_MODELS | _GEMINI_THINKING_BUDGET_MODELS:
        return ("low", "high")
    return None


def _gemini_effort_config(model, effort):
    if effort not in (_gemini_reasoning_efforts(model) or ()):
        raise ValueError("Unsupported Gemini model/effort configuration")
    if model in _GEMINI_THINKING_BUDGET_MODELS:
        # Fubuki's low/high presets, not native named Gemini 2.5 effort tiers.
        thinking = {"thinkingBudget": 1024 if effort == "low" else 24576}
    else:
        thinking = {"thinkingLevel": effort.upper()}
    return {"customOverrides": [{
        "match": {"model": model},
        "modelConfig": {"generateContentConfig": {"thinkingConfig": thinking}},
    }]}


def _is_owned_gemini_effort_config(config):
    """Recognize only exact payloads this app writes or historically wrote."""
    for effort in ("low", "high"):
        for model in _GEMINI_THINKING_LEVEL_MODELS | _GEMINI_THINKING_BUDGET_MODELS:
            if config == _gemini_effort_config(model, effort):
                return True
        legacy = {"customAliases": {
            "chat-base-3": {"extends": "chat-base", "modelConfig": {
                "generateContentConfig": {"thinkingConfig": {"thinkingLevel": effort.upper()}}}},
            "chat-base-2.5": {"extends": "chat-base", "modelConfig": {
                "generateContentConfig": {"thinkingConfig": {
                    "thinkingBudget": 1024 if effort == "low" else 24576}}}},
        }}
        if config == legacy:
            return True
    return False


ANTIGRAVITY_DEFAULT_GEMINI_MODELS = (
    ("gemini-4-argon-high", "Gemini 4 Argon (High)"),
    ("gemini-4-argon-medium", "Gemini 4 Argon (Medium)"),
    ("gemini-4-argon-low", "Gemini 4 Argon (Low)"),
    ("gemini-3.8-flash-high", "Gemini 3.8 Flash (High)"),
    ("gemini-3.8-flash-medium", "Gemini 3.8 Flash (Medium)"),
    ("gemini-3.8-flash-low", "Gemini 3.8 Flash (Low)"),
)

STRIPPED_API_KEY_VARS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
)


def _sanitized_env() -> dict[str, str]:
    """Return environment with all paid API key variables removed."""
    env = dict(os.environ)
    for key in STRIPPED_API_KEY_VARS:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    env["GEMINI_CLI_NO_RELAUNCH"] = "true"
    env["DISABLE_AUTOUPDATER"] = "1"
    env["NO_UPDATE_NOTIFIER"] = "1"
    return env


def _creation_flags() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


def _terminate_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=_creation_flags(),
            )
            if proc.poll() is not None:
                proc.wait(timeout=2)
                return
        except Exception:
            pass
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass


# Keep pipe I/O off the caller thread: a CLI may be silent, stop reading stdin,
# or fill stderr before emitting its first JSON event.
CLI_REPLY_TIMEOUT = 180.0
_PIPE_POLL_INTERVAL = 0.05
_MAX_EVENT_CHARS = 256 * 1024


def _check_reply_deadline(cancel_event, deadline):
    _check(cancel_event)
    if time.monotonic() >= deadline:
        raise ChatGPTError("응답 제한 시간을 넘겨 중단했습니다. 다시 시도하세요.")


def _wait_for_cli(proc, cancel_event, deadline):
    # Continue honoring Stop even after the final result or stdout EOF.
    exit_deadline = min(deadline, time.monotonic() + 5)
    while True:
        _check_reply_deadline(cancel_event, deadline)
        remaining = exit_deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("local CLI", 5)
        try:
            return proc.wait(timeout=min(_PIPE_POLL_INTERVAL, remaining))
        except subprocess.TimeoutExpired:
            pass


@contextmanager
def _cli_output(proc, prompt, cancel_event, deadline):
    """Bounded JSON-line queue, discarded stderr, and interruptible input writes.

    Each worker owns and closes its pipe. Never close a pipe from the caller
    while another thread holds its I/O lock, which itself could block Stop.
    """
    lines = queue.Queue(maxsize=32)
    stopped = threading.Event()
    eof = object()

    def enqueue(item):
        while not stopped.is_set():
            try:
                lines.put(item, timeout=_PIPE_POLL_INTERVAL)
                return
            except queue.Full:
                pass

    def read_stdout():
        try:
            while not stopped.is_set():
                line = proc.stdout.readline(_MAX_EVENT_CHARS + 1)
                if not line:
                    break
                if len(line) > _MAX_EVENT_CHARS:
                    enqueue(ChatGPTError("응답이 너무 길어 중단했습니다. 더 짧은 답변을 요청하세요."))
                    break
                enqueue(line)
        except (OSError, ValueError):
            enqueue(ChatGPTError("CLI 응답 연결이 중단되었습니다. 다시 시도하세요."))
        finally:
            proc.stdout.close()
            enqueue(eof)

    def drain_stderr():
        try:
            while not stopped.is_set() and proc.stderr.read(4096):
                pass  # Diagnostics may contain private data; never retain/display them.
        except (OSError, ValueError):
            pass
        finally:
            proc.stderr.close()

    def write_stdin():
        try:
            if prompt is not None:
                proc.stdin.write(prompt)
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass

    def iterate():
        while True:
            _check_reply_deadline(cancel_event, deadline)
            try:
                item = lines.get(timeout=_PIPE_POLL_INTERVAL)
            except queue.Empty:
                continue
            _check_reply_deadline(cancel_event, deadline)
            if item is eof:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    workers = []
    try:
        for pipe, target in ((proc.stdout, read_stdout),
                             (proc.stderr, drain_stderr),
                             (proc.stdin, write_stdin)):
            if pipe is not None:
                worker = threading.Thread(target=target, daemon=True, name="local-cli-pipe")
                worker.start()
                workers.append(worker)
        yield iterate()
    finally:
        stopped.set()
        _terminate_process(proc)
        # Bound cleanup even if an inherited pipe is held by a descendant.
        join_deadline = time.monotonic() + 1
        for worker in workers:
            worker.join(timeout=max(0, join_deadline - time.monotonic()))


def _validate_and_format_messages(
    messages: list[dict],
    max_reply_chars: int | None = DEFAULT_MAX_REPLY_CHARS,
) -> str:
    """Validate conversation history and build a plain-text prompt."""
    if len(messages) > 100:
        raise ChatGPTError("대화가 너무 깁니다. 새 대화를 시작하세요.")
    input_chars = 0
    persona_text = build_persona_instructions(max_reply_chars)
    lines = [
        f"[시스템 지침]\n{persona_text}\n도구나 파일 작업, 명령 실행 없이 오직 대화 답변 텍스트만 출력하세요.",
        "[대화 기록]",
    ]
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in ("developer", "user", "assistant")
            or not isinstance(message.get("content"), str)
        ):
            raise ChatGPTError("지원하지 않는 대화 형식입니다.")
        content = message["content"]
        input_chars += len(content)
        if input_chars > 60000:
            raise ChatGPTError("대화가 너무 깁니다. 새 대화를 시작하세요.")
        role = message["role"]
        speaker = "시스템" if role == "developer" else ("사용자" if role == "user" else "후부키")
        lines.append(f"{speaker}: {content}")
    if max_reply_chars is not None:
        lines.append(
            f"\n위 대화의 마지막 사용자 발화에 대해 후부키로서 공백 포함 {max_reply_chars}자 이내(1~2문장)로 짧고 간결하게 답하세요 "
            "(기본 언어는 한국어이며, 사용자가 일본어나 영어로 말하면 해당 언어로 답하세요)."
        )
    else:
        lines.append(
            "\n위 대화의 마지막 사용자 발화에 대해 후부키로서 자연스럽고 친절하게 답하세요 "
            "(기본 언어는 한국어이며, 사용자가 일본어나 영어로 말하면 해당 언어로 답하세요)."
        )
    return "\n\n".join(lines)


def _is_gemini_model_slug(slug: str) -> bool:
    """Accept only Gemini models; explicitly exclude Claude and other providers."""
    if not isinstance(slug, str) or not slug.strip():
        return False
    lower = slug.strip().lower()
    if "claude" in lower or "gpt" in lower or "anthropic" in lower:
        return False
    return lower == "auto" or lower.startswith("gemini")


def _find_gemini_cli_command() -> list[str]:
    """Locate the official Gemini CLI executable without reading credentials."""
    candidates = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "npm" / "gemini.cmd")
    which_cmd = shutil.which("gemini.cmd") or shutil.which("gemini")
    if which_cmd:
        candidates.append(Path(which_cmd))
    for candidate in candidates:
        if candidate.is_file():
            bundle_js = candidate.parent / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js"
            node_exe = candidate.parent / "node.exe"
            if not node_exe.is_file():
                prog_node = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe"
                if prog_node.is_file():
                    node_exe = prog_node
                else:
                    which_node = shutil.which("node.exe") or shutil.which("node")
                    if which_node:
                        node_exe = Path(which_node)
            if bundle_js.is_file() and node_exe.is_file():
                return [str(node_exe), str(bundle_js)]
            return [str(candidate)]
    raise ChatGPTError("로컬에서 공식 Gemini CLI(gemini)를 찾지 못했습니다. 설치 상태를 확인하세요.")


def _find_antigravity_cli_command() -> list[str]:
    """Locate the official Antigravity CLI (agy) executable."""
    candidates = []
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        candidates.append(Path(localappdata) / "agy" / "bin" / "agy.exe")
    which_agy = shutil.which("agy.exe") or shutil.which("agy")
    if which_agy:
        candidates.append(Path(which_agy))
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]
    raise ChatGPTError("로컬에서 공식 Antigravity CLI(agy)를 찾지 못했습니다. 설치 상태를 확인하세요.")


class GeminiCLIClient:
    """Client that talks to the user's locally logged-in official Gemini CLI."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.workspace_dir = self.data_dir / "gemini_cli_workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connected = False
        self._label = ""
        self.max_reply_chars: int | None = DEFAULT_MAX_REPLY_CHARS

    def session_info(self):
        with self._lock:
            return {
                "connected": self._connected,
                "email": self._label if self._connected else "",
                "name": "Gemini CLI",
                "sharing": self._connected,
                "mock": False,
                "provider": "gemini",
            }

    def open_cli_login(self):
        cmd = shutil.which("gemini.cmd") or shutil.which("gemini")
        if not cmd:
            appdata = os.environ.get("APPDATA", "")
            candidate = Path(appdata) / "npm" / "gemini.cmd"
            if candidate.is_file():
                cmd = str(candidate)
        if not cmd:
            raise ChatGPTError("공식 Gemini CLI(gemini) 실행 파일을 찾지 못했습니다.")
        if os.name == "nt":
            subprocess.Popen(
                ["cmd.exe", "/c", "start", "Gemini CLI Login", "cmd.exe", "/k", cmd],
                cwd=str(self.workspace_dir),
                env=_sanitized_env(),
            )
        else:
            raise ChatGPTError("터미널에서 직접 gemini 명령을 실행해 로그인하세요.")

    def sign_in(self, cancel_event=None):
        _check(cancel_event)
        base_cmd = _find_gemini_cli_command()
        ver_str = self._read_installed_version(base_cmd)
        if not ver_str:
            try:
                completed = subprocess.run(
                    [*base_cmd, "--version"],
                    cwd=str(self.workspace_dir),
                    env=_sanitized_env(),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                    creationflags=_creation_flags(),
                )
            except subprocess.TimeoutExpired:
                raise ChatGPTError("Gemini CLI 확인 시간이 초과되었습니다.") from None
            except OSError:
                raise ChatGPTError("Gemini CLI를 실행하지 못했습니다.") from None
            _check(cancel_event)
            version = (completed.stdout or "").strip().splitlines()
            ver_str = version[-1].strip() if version else ""
            if completed.returncode != 0 or not ver_str:
                raise ChatGPTError("Gemini CLI 상태를 확인하지 못했습니다. 터미널에서 gemini 로그인을 확인하세요.")
        with self._lock:
            self._connected = True
            self._label = f"로컬 Gemini CLI v{ver_str}"
        return self.session_info()

    @staticmethod
    def _read_installed_version(base_cmd: list[str]) -> str:
        try:
            script = Path(base_cmd[-1])
            if script.is_file():
                pkg_json = script.resolve().parents[1] / "package.json"
                if pkg_json.is_file():
                    data = json.loads(pkg_json.read_text(encoding="utf-8"))
                    ver = str(data.get("version", "")).strip()
                    if ver:
                        return ver
        except Exception:
            pass
        return ""

    def try_fast_connect(self) -> bool:
        try:
            base_cmd = _find_gemini_cli_command()
        except ChatGPTError:
            return False
        ver_str = self._read_installed_version(base_cmd) or "local"
        with self._lock:
            self._connected = True
            self._label = f"로컬 Gemini CLI v{ver_str}"
        return True

    def list_models(self, cancel_event=None):
        _check(cancel_event)
        with self._lock:
            if not self._connected:
                raise ChatGPTError("먼저 로컬 Gemini CLI에 연결하세요.")
        return [{"slug": slug, "display_name": name} for slug, name in GEMINI_CLI_MODELS]

    def supported_reasoning_efforts(self, model):
        # Model docs establish valid knobs, but project settings can lose to
        # system settings and installed CLI overrides. Until resolved config
        # is verified, do not advertise a setting that may be silently ignored.
        return None

    def _configure_workspace_effort(self, model, reasoning_effort: str | None) -> None:
        settings_dir = self.workspace_dir / ".gemini"
        settings_file = settings_dir / "settings.json"
        try:
            if settings_file.exists():
                payload = json.loads(settings_file.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError()
            else:
                payload = {}
            existing = payload.get("modelConfigs")
            owned = _is_owned_gemini_effort_config(existing)
            if reasoning_effort is None:
                # Default means native CLI configuration. Remove only a known
                # app-generated override, never the user's other settings.
                if not owned:
                    return
                payload.pop("modelConfigs")
            else:
                if existing not in (None, {}) and not owned:
                    raise ChatGPTError("기존 Gemini 모델 설정과 충돌해 추론 강도를 적용하지 않았습니다. "
                                       "'CLI 기본값'을 선택하세요. 요청은 전송하지 않았습니다.")
                payload["modelConfigs"] = _gemini_effort_config(model, reasoning_effort)
            settings_dir.mkdir(parents=True, exist_ok=True)
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=settings_dir,
                                                 prefix=".settings-", suffix=".tmp", delete=False) as handle:
                    temp_path = Path(handle.name)
                    json.dump(payload, handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, settings_file)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            raise ChatGPTError("Gemini 작업공간 설정을 확인하거나 저장하지 못했습니다. "
                               "요청은 전송하지 않았습니다.") from None

    def stream_reply(self, messages, model, on_delta, cancel_event=None, *, reasoning_effort=None):
        _check(cancel_event)
        with self._lock:
            if not self._connected:
                raise ChatGPTError("먼저 로컬 Gemini CLI에 연결하세요.")
        selected_model = model or "auto"
        if not _is_gemini_model_slug(selected_model) or selected_model not in VALID_GEMINI_CLI_SLUGS:
            raise ChatGPTError("지원하지 않는 Gemini 모델입니다.")
        validate_model_reasoning_effort(self, selected_model, reasoning_effort)
        self._configure_workspace_effort(selected_model, reasoning_effort)
        limit = getattr(self, "max_reply_chars", DEFAULT_MAX_REPLY_CHARS)
        prompt = _validate_and_format_messages(messages, max_reply_chars=limit)
        base_cmd = _find_gemini_cli_command()
        short_rule = f"공백 포함 {limit}자 이내(1~2문장)로 짧게" if limit is not None else "자연스럽게"
        cmd = [
            *base_cmd,
            "-p",
            f"위 대화 기록의 마지막 사용자 말에 후부키로서 {short_rule} 답하세요 (기본 한국어, 일본어·영어 질문 시 해당 언어로 응답).",
            "-o",
            "stream-json",
            "--approval-mode",
            "plan",
            "-e",
            "none",
        ]
        if selected_model != "auto":
            cmd.extend(["-m", selected_model])
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.workspace_dir),
                env=_sanitized_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=_creation_flags(),
            )
        except OSError:
            raise ChatGPTError("로컬 Gemini CLI를 실행하지 못했습니다.") from None

        parts: list[str] = []
        response_chars = 0
        completed_ok = False
        deadline = time.monotonic() + CLI_REPLY_TIMEOUT
        try:
            with _cli_output(proc, prompt, cancel_event, deadline) as output:
                for raw_line in output:
                    line = raw_line.strip()
                    if not line or not line.startswith("{"):
                        continue
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            continue
                    except ValueError:
                        continue
                    kind = event.get("type")
                    if kind == "message" and event.get("role") == "assistant":
                        delta = event.get("content", "")
                        if not isinstance(delta, str):
                            raise ChatGPTError("응답 텍스트 형식이 올바르지 않습니다.")
                        if delta:
                            response_chars += len(delta)
                            if response_chars > 20000:
                                raise ChatGPTError("응답이 너무 길어 중단했습니다. 더 짧은 답변을 요청하세요.")
                            parts.append(delta)
                            on_delta(delta)
                    elif kind == "result":
                        if event.get("status") == "success":
                            completed_ok = True
                            break
                        raise ChatGPTError("Gemini CLI 응답이 실패했습니다. 로그인 상태나 사용량을 확인하세요.")
                    elif kind == "error":
                        raise ChatGPTError("Gemini CLI 오류가 발생했습니다. 로그인 상태나 사용량을 확인하세요.")
                _wait_for_cli(proc, cancel_event, deadline)
        except Cancelled:
            _terminate_process(proc)
            raise
        except ChatGPTError:
            _terminate_process(proc)
            raise
        except Exception:
            _terminate_process(proc)
            raise ChatGPTError("Gemini CLI 응답 연결이 중단되었습니다. 다시 시도하세요.") from None
        finally:
            _terminate_process(proc)

        _check(cancel_event)
        if not completed_ok or not parts:
            raise ChatGPTError("Gemini CLI에서 완료된 응답을 받지 못했습니다. 터미널에서 gemini 로그인 상태를 확인하세요.")
        return "".join(parts)

    def logout(self):
        with self._lock:
            self._connected = False
            self._label = ""
        return {
            "revoked": True,
            "message": "후부키에서 Gemini CLI 연결을 해제했습니다.",
        }


class AntigravityGeminiClient:
    """Client that talks to the user's locally logged-in Antigravity CLI (Gemini models only)."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.workspace_dir = self.data_dir / "antigravity_workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connected = False
        self._label = ""
        self.max_reply_chars: int | None = DEFAULT_MAX_REPLY_CHARS
        self._cached_models: list[dict[str, str]] = []

    def session_info(self):
        with self._lock:
            return {
                "connected": self._connected,
                "email": self._label if self._connected else "",
                "name": "Antigravity Gemini",
                "sharing": self._connected,
                "mock": False,
                "provider": "antigravity_gemini",
            }

    def open_cli_login(self):
        base_cmd = _find_antigravity_cli_command()
        if os.name == "nt":
            subprocess.Popen(
                ["cmd.exe", "/c", "start", "Antigravity CLI Login", "cmd.exe", "/k", base_cmd[0]],
                cwd=str(self.workspace_dir),
                env=_sanitized_env(),
            )
        else:
            raise ChatGPTError("터미널에서 직접 agy 명령을 실행해 로그인하세요.")

    def _fetch_gemini_models(self, cancel_event=None) -> list[dict[str, str]]:
        _check(cancel_event)
        base_cmd = _find_antigravity_cli_command()
        try:
            completed = subprocess.run(
                [*base_cmd, "models"],
                cwd=str(self.workspace_dir),
                env=_sanitized_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=25,
                creationflags=_creation_flags(),
            )
        except subprocess.TimeoutExpired:
            raise ChatGPTError("Antigravity 모델 목록 확인 시간이 초과되었습니다.") from None
        except OSError:
            raise ChatGPTError("Antigravity CLI(agy)를 실행하지 못했습니다.") from None
        _check(cancel_event)
        if completed.returncode != 0:
            raise ChatGPTError("Antigravity CLI에서 모델 목록을 가져오지 못했습니다. agy 로그인 상태를 확인하세요.")
        models = []
        for raw_line in (completed.stdout or "").splitlines():
            line = raw_line.strip()
            if not line or "\t" not in line:
                continue
            slug, display_name = line.split("\t", 1)
            slug = slug.strip()
            display_name = display_name.strip() or slug
            if _is_gemini_model_slug(slug):
                models.append({"slug": slug, "display_name": display_name})
        if not models:
            raise ChatGPTError("사용 가능한 Antigravity Gemini 모델이 없습니다. agy 로그인 상태를 확인하세요.")
        return models

    def try_fast_connect(self) -> bool:
        try:
            _find_antigravity_cli_command()
        except ChatGPTError:
            return False
        models = [{"slug": slug, "display_name": name} for slug, name in ANTIGRAVITY_DEFAULT_GEMINI_MODELS]
        with self._lock:
            self._connected = True
            if not self._cached_models:
                self._cached_models = models
            self._label = f"로컬 Antigravity (Gemini {len(self._cached_models)}개 모델)"
        return True

    def sign_in(self, cancel_event=None):
        models = self._fetch_gemini_models(cancel_event)
        with self._lock:
            self._connected = True
            self._cached_models = models
            self._label = f"로컬 Antigravity (Gemini {len(models)}개 모델)"
        return self.session_info()

    def list_models(self, cancel_event=None, *, force_refresh: bool = False):
        _check(cancel_event)
        with self._lock:
            if not self._connected:
                raise ChatGPTError("먼저 로컬 Antigravity에 연결하세요.")
            if not force_refresh and self._cached_models:
                return list(self._cached_models)
        models = self._fetch_gemini_models(cancel_event)
        with self._lock:
            self._cached_models = models
            self._label = f"로컬 Antigravity (Gemini {len(models)}개 모델)"
        return models

    def supported_reasoning_efforts(self, model):
        # `agy models` provides names, not --effort capabilities. A suffix such
        # as "high" is part of the selected model ID, not evidence for other
        # tiers. Do not probe /effort without a verified version and schema.
        return None

    def stream_reply(self, messages, model, on_delta, cancel_event=None, *, reasoning_effort=None):
        validate_model_reasoning_effort(self, model, reasoning_effort)
        _check(cancel_event)
        with self._lock:
            if not self._connected:
                raise ChatGPTError("먼저 로컬 Antigravity에 연결하세요.")
        if not _is_gemini_model_slug(model):
            raise ChatGPTError("Antigravity에서는 Gemini 모델만 사용할 수 있습니다.")
        limit = getattr(self, "max_reply_chars", DEFAULT_MAX_REPLY_CHARS)
        prompt = _validate_and_format_messages(messages, max_reply_chars=limit)
        base_cmd = _find_antigravity_cli_command()
        cmd = [
            *base_cmd,
            "-p",
            prompt,
            "--model",
            model,
            "--output-format",
            "stream-json",
            "--disable-slash-commands",
            "--sandbox",
        ]
        if reasoning_effort is not None:
            cmd.extend(["--effort", reasoning_effort])
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.workspace_dir),
                env=_sanitized_env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=_creation_flags(),
            )
        except OSError:
            raise ChatGPTError("로컬 Antigravity CLI(agy)를 실행하지 못했습니다.") from None

        parts: list[str] = []
        response_chars = 0
        completed_ok = False
        deadline = time.monotonic() + CLI_REPLY_TIMEOUT
        try:
            with _cli_output(proc, None, cancel_event, deadline) as output:
                for raw_line in output:
                    line = raw_line.strip()
                    if not line or not line.startswith("{"):
                        continue
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            continue
                    except ValueError:
                        continue
                    kind = event.get("event")
                    if kind == "step_update":
                        step = event.get("step_update")
                        if isinstance(step, dict) and step.get("step_type") == "agent_response":
                            delta = step.get("text_delta", "")
                            if not isinstance(delta, str):
                                raise ChatGPTError("응답 텍스트 형식이 올바르지 않습니다.")
                            if delta:
                                response_chars += len(delta)
                                if response_chars > 20000:
                                    raise ChatGPTError("응답이 너무 길어 중단했습니다. 더 짧은 답변을 요청하세요.")
                                parts.append(delta)
                                on_delta(delta)
                    elif kind == "result":
                        res = event.get("result")
                        if isinstance(res, dict) and res.get("status") == "SUCCESS":
                            fallback = res.get("response", "")
                            if not parts and isinstance(fallback, str) and fallback:
                                if len(fallback) > 20000:
                                    raise ChatGPTError("응답이 너무 길어 중단했습니다. 더 짧은 답변을 요청하세요.")
                                parts.append(fallback)
                                on_delta(fallback)
                            completed_ok = True
                            break
                        raise ChatGPTError("Antigravity 응답이 완료되지 않았습니다. 로그인 상태나 사용량을 확인하세요.")
                _wait_for_cli(proc, cancel_event, deadline)
        except Cancelled:
            _terminate_process(proc)
            raise
        except ChatGPTError:
            _terminate_process(proc)
            raise
        except Exception:
            _terminate_process(proc)
            raise ChatGPTError("Antigravity 응답 연결이 중단되었습니다. 다시 시도하세요.") from None
        finally:
            _terminate_process(proc)

        _check(cancel_event)
        result_text = "".join(parts).strip()
        if not completed_ok or not result_text:
            raise ChatGPTError("Antigravity에서 완료된 응답을 받지 못했습니다. agy 로그인 상태를 확인하세요.")
        return result_text

    def logout(self):
        with self._lock:
            self._connected = False
            self._label = ""
            self._cached_models = []
        return {
            "revoked": True,
            "message": "후부키에서 Antigravity 연결을 해제했습니다.",
        }


class MockLocalCLIClient:
    """Offline mock client for Gemini CLI and Antigravity Gemini in --chat-mock mode."""

    def __init__(self, provider: str = "gemini", data_dir=None):
        self.provider = provider
        self.connected = False
        self.max_reply_chars: int | None = DEFAULT_MAX_REPLY_CHARS

    def session_info(self):
        label = "Claude Code 데모" if self.provider == "claude" else "Antigravity Gemini 데모" if self.provider == "antigravity_gemini" else "Gemini CLI 데모"
        return {
            "connected": self.connected,
            "email": label if self.connected else "",
            "name": label,
            "sharing": self.connected,
            "mock": True,
            "provider": self.provider,
        }

    def open_cli_login(self):
        return None

    def sign_in(self, cancel_event=None):
        _check(cancel_event)
        self.connected = True
        return self.session_info()

    def list_models(self, cancel_event=None):
        _check(cancel_event)
        if not self.connected:
            raise ChatGPTError("오프라인 데모에 먼저 연결하세요.")
        if self.provider == "claude":
            return [{"slug": "auto", "display_name": "Claude 자동 [오프라인 데모]"}]
        if self.provider == "antigravity_gemini":
            return [
                {"slug": "gemini-4-argon-high", "display_name": "Gemini 4 Argon (High) [오프라인 데모]"},
                {"slug": "gemini-3.8-flash-high", "display_name": "Gemini 3.8 Flash (High) [오프라인 데모]"},
            ]
        return [
            {"slug": "auto", "display_name": "자동 (Gemini CLI 기본값) [오프라인 데모]"},
            {"slug": "gemini-3.1-pro-preview", "display_name": "Gemini 3.1 Pro Preview [오프라인 데모]"},
        ]

    def supported_reasoning_efforts(self, model):
        # Demo controls mirror production, not hypothetical provider support.
        return None

    def stream_reply(self, messages, model, on_delta, cancel_event=None, *, reasoning_effort=None):
        validate_model_reasoning_effort(self, model, reasoning_effort)
        self.list_models(cancel_event)
        tag = "Claude Code" if self.provider == "claude" else "Antigravity Gemini" if self.provider == "antigravity_gemini" else "Gemini CLI"
        text = f"[오프라인 데모 · {tag}] 안녕하세요! 후부키 {tag} 연결 화면이 정상 작동하고 있어요."
        for start in range(0, len(text), 3):
            _check(cancel_event)
            on_delta(text[start:start + 3])
            time.sleep(0.02)
        return text

    def logout(self):
        self.connected = False
        return {"revoked": True, "message": "데모 연결을 해제했습니다."}

