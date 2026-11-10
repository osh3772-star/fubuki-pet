"""Local, public-client Sign in with ChatGPT. No Codex credentials are read.

Network methods belong on a worker thread. Calling sign_in must follow an
explicit user action and consent UI. This module never executes model tools.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid
import webbrowser
from contextlib import contextmanager

import jwt
import requests

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
REVOKE = ISSUER + "/api/accounts/oauth/revoke"
JWKS = ISSUER + "/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DIRECT = "chatgpt.tokens.use.direct"
PERSONA = ("한국어로 친근한 데스크톱 반려 친구처럼 답하세요. 보통 1~3문장으로 간결하게 답하세요. "
           "실제 인물이나 공식 캐릭터라고 주장하지 마세요. 도구 실행이나 컴퓨터 작업을 수행했다고 주장하지 마세요.")
# Responses API enum, not a promise that a particular account/model supports it.
# https://developers.openai.com/api/docs/guides/reasoning
# SIWC's documented /models catalog does not specify effort capabilities.
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
REASONING_REJECTED = ("선택한 추론 강도를 적용할 수 없습니다. 설정에서 '서버 기본값' 또는 다른 단계를 "
                      "선택한 뒤 다시 보내세요. 요청은 자동 재전송하지 않았습니다.")


class ChatGPTError(RuntimeError):
    """Safe-to-display error, without server bodies or credentials."""


class Cancelled(ChatGPTError):
    pass


def _validate_reasoning_effort(value):
    # None means omission. In particular, the string 'none' is NOT omission.
    if value is not None and (not isinstance(value, str) or value not in REASONING_EFFORTS):
        raise ChatGPTError("올바르지 않은 추론 강도입니다. 설정에서 다시 선택하세요.")


def _is_reasoning_error(error):
    """Recognize a parameter error without exposing any server-provided text."""
    if not isinstance(error, dict):
        return False
    if error.get("param") in ("reasoning", "reasoning.effort", "reasoning_effort"):
        return True
    message = error.get("message", "")
    return isinstance(message, str) and ("reasoning" in message.lower() or "effort" in message.lower())


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled("작업을 취소했습니다.")


def _dpapi(data: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        raise ChatGPTError("실제 로그인은 Windows의 보호된 저장소가 필요합니다.")

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buf)
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    method = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    method.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    method.restype = wintypes.BOOL
    if not method(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ChatGPTError("Windows 보안 저장소를 읽거나 저장하지 못했습니다.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(target.pbData)


class ChatGPTClient:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "chatgpt-session.dpapi"
        self._lock = threading.RLock()
        self._http = requests.Session()
        # Do not inherit proxy credentials or .netrc authentication.
        self._http.trust_env = False
        self._record = {}
        with self._guard():
            self._load()
            if not self._record.get("host_id"):
                self._record["host_id"] = "urn:uuid:" + str(uuid.uuid4())
                self._save()

    @contextmanager
    def _guard(self):
        # Serialize rotating refresh tokens across threads AND app processes.
        with self._lock:
            handle = None
            kernel = None
            if os.name == "nt":
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
                kernel.CreateMutexW.restype = wintypes.HANDLE
                kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel.WaitForSingleObject.restype = wintypes.DWORD
                kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                key = hashlib.sha256(str(self.path.resolve()).lower().encode()).hexdigest()
                handle = kernel.CreateMutexW(None, False, "Local\\FubukiSIWC_" + key)
                if not handle:
                    raise ChatGPTError("로그인 저장소 잠금을 만들지 못했습니다.")
                if kernel.WaitForSingleObject(handle, 30000) not in (0, 0x80):
                    kernel.CloseHandle(handle)
                    raise ChatGPTError("다른 창의 로그인 작업이 끝난 후 다시 시도하세요.")
            try:
                yield
            finally:
                if handle:
                    kernel.ReleaseMutex(handle)
                    kernel.CloseHandle(handle)

    def _load(self):
        if self.path.exists():
            try:
                self._record = json.loads(_dpapi(self.path.read_bytes(), True))
                if not isinstance(self._record, dict):
                    raise ValueError()
            except ChatGPTError:
                raise
            except Exception:
                raise ChatGPTError("로그인 저장소가 손상되었습니다. 파일을 복구한 후 다시 시도하세요.") from None

    def _save(self):
        encrypted = _dpapi(json.dumps(self._record).encode())
        temp = self.path.with_name(self.path.name + "." + secrets.token_hex(6) + ".tmp")
        try:
            with open(temp, "xb") as f:
                f.write(encrypted)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)

    def session_info(self):
        with self._guard():
            self._load()
            r = self._record
            connected = bool(r.get("access_token") and r.get("subject"))
            return {"connected": connected, "email": r.get("email", ""),
                    "name": r.get("name", ""), "sharing": connected and DIRECT in r.get("scopes", []),
                    "mock": False}

    def _request(self, method, url, cancel=None, **kwargs):
        _check(cancel)
        try:
            response = self._http.request(method, url, timeout=(10, 25), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise ChatGPTError("OpenAI 연결에 실패했습니다. 인터넷 연결을 확인하세요.") from None
        try:
            # A rotating token may already have been consumed by the server.
            # Persist its replacement even if cancellation arrived in flight.
            if url != TOKEN:
                _check(cancel)
            if not 200 <= response.status_code < 300:
                status = response.status_code
                if status == 401:
                    raise ChatGPTError("로그인이 만료되었거나 취소되었습니다. 다시 로그인하세요.")
                if status == 429:
                    raise ChatGPTError("사용량 한도에 도달했습니다. 잠시 후 또는 ChatGPT 설정 확인 후 다시 시도하세요.")
                if status in (400, 422) and url == RESOURCE + "/responses":
                    try:
                        body = response.json()
                    except ValueError:
                        body = None
                    if isinstance(body, dict) and _is_reasoning_error(body.get("error")):
                        raise ChatGPTError(REASONING_REJECTED)
                    if "reasoning" in kwargs.get("json", {}):
                        raise ChatGPTError("OpenAI가 요청 설정을 거부했습니다. 모델의 추론 강도 지원 여부를 "
                                           "확인하거나 '서버 기본값'으로 다시 보내세요. 자동 재전송하지 않았습니다.")
                raise ChatGPTError(f"OpenAI 요청 실패 (HTTP {status}). 다시 로그인하거나 잠시 후 시도하세요.")
        except Exception:
            response.close()
            raise
        return response

    def _json(self, method, url, cancel=None, **kwargs):
        with self._request(method, url, cancel, **kwargs) as response:
            try:
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError()
                return result
            except ValueError:
                raise ChatGPTError("OpenAI 응답 형식이 올바르지 않습니다.") from None

    def _verify_identity(self, token, client_id, nonce, cancel):
        keys = self._json("GET", JWKS, cancel)
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise ValueError()
            matches = [k for k in keys.get("keys", []) if k.get("kid") == header["kid"]]
            if len(matches) != 1:
                raise ValueError()
            key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key
            identity = jwt.decode(token, key, algorithms=["RS256"], audience=client_id,
                                  issuer=ISSUER, leeway=30,
                                  options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]})
            if not isinstance(identity["sub"], str) or not identity["sub"]:
                raise ValueError()
            if not secrets.compare_digest(str(identity["nonce"]), nonce):
                raise ValueError()
            return identity
        except Exception:
            raise ChatGPTError("로그인 응답의 신원을 검증하지 못했습니다.") from None

    def _apply_tokens(self, data):
        if not isinstance(data.get("access_token"), str) or not data["access_token"]:
            raise ChatGPTError("로그인 응답에 접근 토큰이 없습니다.")
        if str(data.get("token_type", "")).lower() != "bearer":
            raise ChatGPTError("지원하지 않는 로그인 토큰 형식입니다.")
        if not isinstance(data.get("scope"), str):
            raise ChatGPTError("로그인 권한 응답이 없습니다.")
        try:
            lifetime = float(data["expires_in"])
            if not 0 < lifetime <= 86400:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ChatGPTError("로그인 만료 정보가 올바르지 않습니다.") from None
        self._record.update(access_token=data["access_token"],
                            scopes=data["scope"].split(), expires_at=time.time() + lifetime)
        for name in ("refresh_token", "id_token"):
            if isinstance(data.get(name), str) and data[name]:
                self._record[name] = data[name]

    def sign_in(self, cancel_event=None):
        _check(cancel_event)
        with self._guard():
            self._load()
            original = dict(self._record)
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        result = {}

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(handler):
                parsed = urlsplit(handler.path)
                if parsed.path != "/auth/callback":
                    handler.send_error(404)
                    return
                values = parse_qs(parsed.query, keep_blank_values=True)
                valid = all(len(v) == 1 for v in values.values())
                valid = valid and secrets.compare_digest(values.get("state", [""])[0], state)
                if not valid:
                    handler.send_error(400, "Invalid authorization callback")
                    return
                result.update({k: v[0] for k, v in values.items()})
                body = b"Sign-in callback received. Return to Fubuki Pet."
                handler.send_response(200)
                handler.send_header("Content-Type", "text/plain; charset=utf-8")
                handler.send_header("Cache-Control", "no-store")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)

        class LoopbackServer(HTTPServer):
            def get_request(self):
                connection, address = super().get_request()
                connection.settimeout(2)
                return connection, address

        server = LoopbackServer(("127.0.0.1", 0), Callback)
        server.timeout = .25
        redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
        client_id = original.get("client_id", "dynamic_agent_client")
        params = dict(client_id=client_id, ext_agent_host_id=original["host_id"],
                      response_type="code", redirect_uri=redirect, scope=SCOPES,
                      resource=RESOURCE, state=state, nonce=nonce,
                      code_challenge_method="S256", code_challenge=challenge)
        if client_id == "dynamic_agent_client":
            params["agent_name_hint"] = "Fubuki Pet"
        elif original.get("id_token"):
            params["id_token_hint"] = original["id_token"]
        try:
            if not webbrowser.open(AUTHORIZE + "?" + urlencode(params)):
                raise ChatGPTError("기본 브라우저를 열지 못했습니다.")
            deadline = time.monotonic() + 300
            while not result:
                _check(cancel_event)
                if time.monotonic() > deadline:
                    raise ChatGPTError("로그인 시간이 초과되었습니다. 다시 시도하세요.")
                server.handle_request()
        finally:
            server.server_close()
        _check(cancel_event)
        if result.get("error"):
            raise ChatGPTError("로그인이 취소되었거나 권한이 승인되지 않았습니다.")
        issued = result.get("client_id", client_id)
        if not result.get("code") or issued == "dynamic_agent_client" or not issued:
            raise ChatGPTError("로그인 등록 응답이 완전하지 않습니다.")
        if client_id != "dynamic_agent_client" and issued != client_id:
            raise ChatGPTError("다른 계정의 로그인 응답은 사용할 수 없습니다.")
        with self._guard():
            self._load()
            if self._record != original:
                raise ChatGPTError("다른 창에서 로그인 상태가 변경되었습니다. 다시 시도하세요.")
            self._record["client_id"] = issued
            self._save()  # Retain registration even if code exchange fails.
            data = self._json("POST", TOKEN, cancel_event, data=dict(
                grant_type="authorization_code", client_id=issued, code=result["code"],
                code_verifier=verifier, redirect_uri=redirect, resource=RESOURCE))
            identity = self._verify_identity(data.get("id_token", ""), issued, nonce, cancel_event)
            if original.get("subject") and identity["sub"] != original["subject"]:
                raise ChatGPTError("기존 계정과 다른 신원으로 로그인할 수 없습니다.")
            self._apply_tokens(data)
            self._record.update(subject=identity["sub"], issuer=ISSUER,
                                email=identity.get("email", ""), name=identity.get("name", ""))
            self._save()
        return self.session_info()

    def _access(self, cancel):
        _check(cancel)
        with self._guard():
            self._load()
            if not self._record.get("subject") or not self._record.get("access_token"):
                raise ChatGPTError("먼저 ChatGPT에 로그인하세요.")
            if self._record.get("expires_at", 0) <= time.time() + 45:
                if not self._record.get("refresh_token"):
                    raise ChatGPTError("다시 로그인해야 합니다.")
                data = self._json("POST", TOKEN, cancel, data=dict(
                    grant_type="refresh_token", client_id=self._record["client_id"],
                    refresh_token=self._record["refresh_token"], resource=RESOURCE))
                if not data.get("refresh_token"):
                    raise ChatGPTError("로그인 갱신 토큰이 없습니다. 다시 로그인하세요.")
                self._apply_tokens(data)
                self._save()
            if DIRECT not in self._record.get("scopes", []):
                raise ChatGPTError("ChatGPT 요금제 사용 권한이 없습니다. 다시 로그인하여 권한을 확인하세요.")
            return self._record["access_token"]

    def list_models(self, cancel_event=None):
        token = self._access(cancel_event)
        data = self._json("GET", RESOURCE + "/models", cancel_event,
                          headers={"Authorization": "Bearer " + token})
        models = data.get("models")
        if not isinstance(models, list):
            raise ChatGPTError("모델 목록 형식이 올바르지 않습니다.")
        return [{"slug": m["slug"], "display_name": m.get("display_name") or m["slug"]}
                for m in models if isinstance(m, dict) and m.get("visibility") == "list"
                and isinstance(m.get("slug"), str) and m["slug"]]

    def stream_reply(self, messages, model, on_delta, cancel_event=None, *, reasoning_effort=None):
        _validate_reasoning_effort(reasoning_effort)
        token = self._access(cancel_event)
        # Explicit allowlist: no tool definitions, tool calls, files, or arbitrary request fields.
        clean = []
        input_chars = 0
        if len(messages) > 100:
            raise ChatGPTError("대화가 너무 깁니다. 새 대화를 시작하세요.")
        for message in messages:
            if message.get("role") not in ("developer", "user", "assistant") or not isinstance(message.get("content"), str):
                raise ChatGPTError("지원하지 않는 대화 형식입니다.")
            input_chars += len(message["content"])
            if input_chars > 60000:
                raise ChatGPTError("대화가 너무 깁니다. 새 대화를 시작하세요.")
            clean.append({"role": message["role"], "content": message["content"]})
        payload = {"model": model, "input": clean, "instructions": PERSONA,
                   "store": False, "stream": True}
        if reasoning_effort is not None:
            payload["reasoning"] = {"effort": reasoning_effort}
        with self._request("POST", RESOURCE + "/responses", cancel_event,
                           headers={"Authorization": "Bearer " + token}, json=payload, stream=True) as response:
            parts, frame = [], []
            response_chars = 0
            deadline = time.monotonic() + 180

            def process(lines):
                nonlocal response_chars
                raw = "\n".join(lines)
                if not raw or raw == "[DONE]":
                    return False
                try:
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        raise ValueError()
                except ValueError:
                    raise ChatGPTError("응답 스트림이 손상되었습니다.") from None
                kind = event.get("type")
                if kind == "response.output_text.delta":
                    delta = event.get("delta", "")
                    if not isinstance(delta, str):
                        raise ChatGPTError("응답 텍스트 형식이 올바르지 않습니다.")
                    response_chars += len(delta)
                    if response_chars > 20000:
                        raise ChatGPTError("응답이 너무 길어 중단했습니다. 더 짧은 답변을 요청하세요.")
                    parts.append(delta)
                    on_delta(delta)
                elif kind == "response.completed":
                    return True
                elif kind in ("response.failed", "response.incomplete", "error"):
                    error = event.get("error", event)
                    if isinstance(event.get("response"), dict):
                        error = event["response"].get("error", error)
                    if _is_reasoning_error(error):
                        raise ChatGPTError(REASONING_REJECTED)
                    raise ChatGPTError("응답이 완료되지 않았습니다. 사용량 또는 연결 상태를 확인하세요.")
                return False

            try:
                for raw in response.iter_lines(chunk_size=1):
                    _check(cancel_event)
                    if time.monotonic() > deadline:
                        raise ChatGPTError("응답 제한 시간을 넘겨 중단했습니다. 다시 시도하세요.")
                    line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    if not line:
                        if process(frame):
                            return "".join(parts)
                        frame = []
                    elif line.startswith("data:"):
                        frame.append(line[5:].lstrip(" "))
                        if sum(map(len, frame)) > 2_000_000:
                            raise ChatGPTError("응답 이벤트가 너무 커서 중단했습니다.")
                if frame and process(frame):
                    return "".join(parts)
            except (requests.RequestException, UnicodeError):
                raise ChatGPTError("응답 연결이 중단되었습니다. 다시 시도하세요.") from None
        raise ChatGPTError("완료 확인 없이 응답 연결이 끝났습니다.")

    def logout(self):
        revoked = True
        with self._guard():
            self._load()
            if self._record.get("refresh_token"):
                revoked = False
                for attempt in range(2):
                    try:
                        with self._request("POST", REVOKE, data=dict(
                            token=self._record["refresh_token"], token_type_hint="refresh_token",
                            client_id=self._record["client_id"])):
                            revoked = True
                        break
                    except ChatGPTError:
                        if attempt == 0:
                            time.sleep(.5)
            for key in ("access_token", "refresh_token", "id_token", "scopes", "expires_at"):
                self._record.pop(key, None)
            self._save()
        return {"revoked": revoked, "message": "로그아웃했습니다." if revoked else
                "기기에서 로그아웃했습니다. 서버 연결 해제는 확인하지 못했습니다. ChatGPT 설정에서 앱 연결을 해제하세요."}


class MockChatGPTClient:
    """Explicit offline UI test mode, never touches real credentials or network."""
    def __init__(self, data_dir=None):
        self.connected = False

    def session_info(self):
        return {"connected": self.connected, "email": "offline-demo@example.invalid" if self.connected else "",
                "name": "오프라인 데모", "sharing": self.connected, "mock": True}

    def sign_in(self, cancel_event=None):
        _check(cancel_event)
        self.connected = True
        return self.session_info()

    def list_models(self, cancel_event=None):
        _check(cancel_event)
        if not self.connected:
            raise ChatGPTError("오프라인 데모에 먼저 연결하세요.")
        return [{"slug": "offline-demo", "display_name": "오프라인 데모 (실제 AI 아님)"}]

    def stream_reply(self, messages, model, on_delta, cancel_event=None, *, reasoning_effort=None):
        _validate_reasoning_effort(reasoning_effort)
        self.list_models(cancel_event)
        text = "[오프라인 데모] 안녕하세요! 후부키 채팅 창이 정상 작동하고 있어요. 실제 ChatGPT 연결은 설정에서 로그인해 주세요."
        for start in range(0, len(text), 3):
            _check(cancel_event)
            on_delta(text[start:start + 3])
            time.sleep(.025)
        return text

    def logout(self):
        self.connected = False
        return {"revoked": True, "message": "데모 연결을 해제했습니다."}
