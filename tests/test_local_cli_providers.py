"""Offline tests for Gemini CLI and Antigravity Gemini (no Claude, no API keys)."""
import io
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication

from windows_pet.chat_bubble import BubbleChat
from windows_pet.chat_window import ChatWindow, Operation
from windows_pet.chatgpt_client import (
    ChatGPTError,
    Cancelled,
    DEFAULT_MAX_REPLY_CHARS,
    PERSONA,
    REASONING_REJECTED,
)
from windows_pet.local_cli_clients import (
    AntigravityGeminiClient,
    GeminiCLIClient,
    MockLocalCLIClient,
    STRIPPED_API_KEY_VARS,
    _is_gemini_model_slug,
    _sanitized_env,
    _validate_and_format_messages,
)
from test_chat_ui import FakeClient


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakePopen:
    def __init__(self, lines, returncode=0):
        self.pid = 99999
        self.returncode = returncode
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("\n".join(lines) + "\n")
        self.stderr = io.StringIO("")
        self.terminated = False

    def poll(self):
        return self.returncode if self.terminated else None

    def wait(self, timeout=None):
        self.terminated = True
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True


class LocalCLIClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_sanitized_env_strips_all_api_keys(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "paid-gemini-key",
                "GOOGLE_API_KEY": "paid-google-key",
                "ANTHROPIC_API_KEY": "paid-claude-key",
                "ANTHROPIC_AUTH_TOKEN": "paid-claude-token",
                "OPENAI_API_KEY": "paid-openai-key",
            },
            clear=False,
        ):
            env = _sanitized_env()
            for key in STRIPPED_API_KEY_VARS:
                self.assertNotIn(key, env)

    def test_model_filter_excludes_claude_and_gpt(self):
        self.assertTrue(_is_gemini_model_slug("auto"))
        self.assertTrue(_is_gemini_model_slug("gemini-4-argon-high"))
        self.assertTrue(_is_gemini_model_slug("gemini-3.8-flash-medium"))
        self.assertTrue(_is_gemini_model_slug("gemini-3.1-pro-preview"))
        self.assertFalse(_is_gemini_model_slug("claude-opus-5-5-high"))
        self.assertFalse(_is_gemini_model_slug("claude-sonnet-5-5-medium"))
        self.assertFalse(_is_gemini_model_slug("gpt-oss-120b-medium"))
        self.assertFalse(_is_gemini_model_slug(""))

    def test_antigravity_models_excludes_claude_and_connects(self):
        client = AntigravityGeminiClient(self.temp.name)
        raw_catalog = "\n".join(
            [
                "gemini-4-argon-high\tGemini 4 Argon (High)",
                "gemini-3.8-flash-low\tGemini 3.8 Flash (Low)",
                "claude-opus-5-5-high\tClaude Opus 5.5 (High)",
                "claude-sonnet-5-5-medium\tClaude Sonnet 5.5 (Medium)",
                "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)",
            ]
        )
        with patch("windows_pet.local_cli_clients._find_antigravity_cli_command", return_value=["agy.exe"]):
            with patch(
                "windows_pet.local_cli_clients.subprocess.run",
                return_value=FakeCompletedProcess(0, stdout=raw_catalog),
            ) as run_mock:
                info = client.sign_in()
                self.assertTrue(info["connected"])
                models = client.list_models()
                slugs = [m["slug"] for m in models]
                self.assertEqual(slugs, ["gemini-4-argon-high", "gemini-3.8-flash-low"])
                for m in models:
                    self.assertNotIn("claude", m["slug"].lower())
                passed_env = run_mock.call_args.kwargs["env"]
                for key in STRIPPED_API_KEY_VARS:
                    self.assertNotIn(key, passed_env)

    def test_antigravity_stream_reply_and_effort_forwarding(self):
        client = AntigravityGeminiClient(self.temp.name)
        client._connected = True
        events = [
            json.dumps({"event": "init", "conversation_id": "c1"}),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "step_type": "agent_response",
                        "text_delta": "안녕! ",
                    },
                }
            ),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "step_type": "agent_response",
                        "text_delta": "안티그래비티 후부키야.",
                    },
                }
            ),
            json.dumps(
                {
                    "event": "result",
                    "result": {"status": "SUCCESS", "response": "안녕! 안티그래비티 후부키야."},
                }
            ),
        ]
        deltas = []
        with patch("windows_pet.local_cli_clients._find_antigravity_cli_command", return_value=["agy.exe"]):
            with patch("windows_pet.local_cli_clients.subprocess.Popen", return_value=FakePopen(events)) as popen_mock:
                reply = client.stream_reply(
                    [{"role": "user", "content": "인사해줘"}],
                    "gemini-4-argon-high",
                    deltas.append,
                    reasoning_effort="high",
                )
                self.assertEqual(reply, "안녕! 안티그래비티 후부키야.")
                self.assertEqual(deltas, ["안녕! ", "안티그래비티 후부키야."])
                cmd = popen_mock.call_args.args[0]
                self.assertIn("--model", cmd)
                self.assertIn("gemini-4-argon-high", cmd)
                self.assertIn("--effort", cmd)
                self.assertIn("high", cmd)
                self.assertIn("--sandbox", cmd)

    def test_antigravity_rejects_claude_model_and_unsupported_effort(self):
        client = AntigravityGeminiClient(self.temp.name)
        client._connected = True
        with self.assertRaises(ChatGPTError):
            client.stream_reply([{"role": "user", "content": "hi"}], "claude-opus-5-5-high", lambda d: None)
        with self.assertRaises(ChatGPTError) as caught:
            client.stream_reply(
                [{"role": "user", "content": "hi"}],
                "gemini-4-argon-high",
                lambda d: None,
                reasoning_effort="minimal",
            )
        self.assertEqual(str(caught.exception), REASONING_REJECTED)

    def test_gemini_cli_stream_reply_and_safety(self):
        client = GeminiCLIClient(self.temp.name)
        with patch("windows_pet.local_cli_clients._find_gemini_cli_command", return_value=["node.exe", "gemini.js"]):
            with patch(
                "windows_pet.local_cli_clients.subprocess.run",
                return_value=FakeCompletedProcess(0, stdout="0.66.0\n"),
            ):
                info = client.sign_in()
                self.assertTrue(info["connected"])
                models = client.list_models()
                self.assertTrue(any(m["slug"] == "auto" for m in models))
                self.assertTrue(all("claude" not in m["slug"] for m in models))

            events = [
                "Ripgrep is not available. Falling back to GrepTool.",
                json.dumps({"type": "init", "model": "auto"}),
                json.dumps({"type": "message", "role": "user", "content": "안녕"}),
                json.dumps({"type": "message", "role": "assistant", "content": "반가워요! 후부키예요.", "delta": True}),
                json.dumps({"type": "result", "status": "success"}),
            ]
            deltas = []
            with patch("windows_pet.local_cli_clients.subprocess.Popen", return_value=FakePopen(events)) as popen_mock:
                reply = client.stream_reply(
                    [{"role": "user", "content": "안녕"}],
                    "gemini-3.1-pro-preview",
                    deltas.append,
                    reasoning_effort="low",
                )
                self.assertEqual(reply, "반가워요! 후부키예요.")
                self.assertEqual(deltas, ["반가워요! 후부키예요."])
                cmd = popen_mock.call_args.args[0]
                self.assertIn("-m", cmd)
                self.assertIn("gemini-3.1-pro-preview", cmd)
                self.assertIn("--approval-mode", cmd)
                self.assertIn("plan", cmd)
                settings_file = client.workspace_dir / ".gemini" / "settings.json"
                self.assertTrue(settings_file.is_file())
                cfg = json.loads(settings_file.read_text(encoding="utf-8"))
                self.assertEqual(
                    cfg["modelConfigs"]["customAliases"]["chat-base-3"]["modelConfig"]["generateContentConfig"]["thinkingConfig"]["thinkingLevel"],
                    "LOW",
                )
            with self.assertRaises(ChatGPTError) as caught:
                client.stream_reply(
                    [{"role": "user", "content": "안녕"}],
                    "gemini-3.1-pro-preview",
                    lambda d: None,
                    reasoning_effort="xhigh",
                )
            self.assertEqual(str(caught.exception), REASONING_REJECTED)


class MultiProviderUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.chatgpt = FakeClient()
        self.gemini = MockLocalCLIClient("gemini")
        self.antigravity = MockLocalCLIClient("antigravity_gemini")
        self.window = BubbleChat(
            Path(self.temp.name),
            True,
            self.chatgpt,
            providers={
                "chatgpt": self.chatgpt,
                "gemini": self.gemini,
                "antigravity_gemini": self.antigravity,
            },
        )

    def tearDown(self):
        self.window.shutdown()
        self.window.deleteLater()
        self.app.processEvents()

    def wait(self):
        deadline = time.monotonic() + 5
        while self.window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertIsNone(self.window.worker)

    def test_switch_between_chatgpt_gemini_and_antigravity(self):
        self.assertEqual(self.window.current_provider, "chatgpt")
        self.assertEqual(self.window.provider_selector.count(), 3)

        # Switch to Gemini CLI via bubble selector
        self.window.bubble_provider.setCurrentIndex(1)
        self.assertEqual(self.window.current_provider, "gemini")
        self.assertEqual(self.window.provider_selector.currentData(), "gemini")
        self.assertTrue(self.window.cli_login_button.isVisibleTo(self.window))
        with patch("windows_pet.local_cli_clients.time.sleep"):
            self.window.connect_account()
            self.wait()
            self.assertGreaterEqual(self.window.models.count(), 2)
            self.window.input.setPlainText("제미나이 안녕")
            self.window.send()
            self.wait()
        self.assertIn("Gemini CLI", self.window.transcript.toPlainText())

        # Switch to Antigravity Gemini via settings selector
        self.window.select_provider("antigravity_gemini")
        self.assertEqual(self.window.current_provider, "antigravity_gemini")
        self.assertEqual(self.window.bubble_provider.currentData(), "antigravity_gemini")
        with patch("windows_pet.local_cli_clients.time.sleep"):
            self.window.connect_account()
            self.wait()
            self.assertGreaterEqual(self.window.models.count(), 2)
            for idx in range(self.window.models.count()):
                self.assertIn("gemini", self.window.models.itemData(idx))
            self.window.input.setPlainText("안티그래비티 안녕")
            self.window.send()
            self.wait()
        self.assertIn("Antigravity Gemini", self.window.transcript.toPlainText())

    def test_multilingual_persona_and_prompt_support_ko_ja_en(self):
        self.assertIn("한국어", PERSONA)
        self.assertIn("일본어", PERSONA)
        self.assertIn("영어", PERSONA)
        formatted = _validate_and_format_messages(
            [
                {"role": "user", "content": "안녕하세요 / こんにちは / Hello"},
            ]
        )
        self.assertIn("한국어", formatted)
        self.assertIn("일본어", formatted)
        self.assertIn("영어", formatted)

    def test_instant_focus_ime_and_idle_follow_anchor_no_repaint_lag(self):
        self.window.open_bubble()
        self.app.processEvents()
        self.assertFalse(self.window.bubble.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.assertTrue(self.window.input.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled))
        self.assertTrue(self.window.input.isEnabled())

        # Input stays enabled even while a background worker is running
        self.chatgpt.slow = True
        self.window.connect_account()
        self.wait()
        self.window.input.setPlainText("안녕")
        self.window.send()
        self.assertTrue(self.window.input.isEnabled())
        self.window.stop()
        self.wait()
        self.window.input.clear()

        # Korean, Japanese, and English IME preedit & commit work without lag or redundant repaints
        for sample in ("안녕하세요", "こんにちは", "Hello Fubuki"):
            preedit = QInputMethodEvent(sample[:1], [])
            QApplication.sendEvent(self.window.input, preedit)
            self.assertTrue(self.window.input.composing)
            commit = QInputMethodEvent()
            commit.setCommitString(sample + " ")
            QApplication.sendEvent(self.window.input, commit)
            self.assertFalse(self.window.input.composing)
        self.assertEqual(self.window.input.toPlainText(), "안녕하세요 こんにちは Hello Fubuki ")

        # Verify follow_anchor() skips redundant bubble.update() calls when geometry is unchanged
        self.window.follow_anchor(force=True)
        with patch.object(self.window.bubble, "update") as update_mock:
            for _ in range(10):
                self.window.follow_anchor()
            update_mock.assert_not_called()

    def test_compact_speech_bubble_vs_expand_full_history_and_default_char_limit(self):
        # Default character limit is 80 chars for concise AI answers
        self.assertEqual(self.window.max_reply_chars, DEFAULT_MAX_REPLY_CHARS)
        self.assertEqual(DEFAULT_MAX_REPLY_CHARS, 80)
        self.assertIn("80자 이내", PERSONA)

        long_answer = "후부키의 긴 답변입니다. " * 10
        self.window.history = [
            {"role": "user", "content": "첫 번째 질문"},
            {"role": "assistant", "content": "첫 번째 대답"},
            {"role": "user", "content": "방금 내가 한 말"},
            {"role": "assistant", "content": long_answer},
        ]
        self.window.open_bubble()
        self.window.render()
        self.window.follow_anchor(force=True)
        self.app.processEvents()

        # In default compact mode: shows current user utterance, hides old turns, and truncates long reply
        compact_text = self.window.transcript.toPlainText()
        self.assertFalse(self.window.expanded)
        self.assertEqual(self.window.expand_button.text(), "펼치기")
        self.assertIn("💬 나: 방금 내가 한 말", compact_text)
        self.assertNotIn("첫 번째 질문", compact_text)
        self.assertIn("[펼치기에서 전체 보기]", compact_text)
        self.assertEqual(self.window.transcript.verticalScrollBar().value(), 0)
        self.assertEqual(self.window.bubble.width(), 286)

        # Clicking '펼치기' expands the bubble and shows the entire history and full untruncated text
        self.window.expand_button.click()
        self.app.processEvents()
        expanded_text = self.window.transcript.toPlainText()
        self.assertTrue(self.window.expanded)
        self.assertEqual(self.window.expand_button.text(), "접기")
        self.assertIn("나: 첫 번째 질문", expanded_text)
        self.assertIn("후부키: 첫 번째 대답", expanded_text)
        self.assertIn("나: 방금 내가 한 말", expanded_text)
        self.assertIn(long_answer, expanded_text)
        self.assertEqual(self.window.bubble.width(), 360)

        # Clicking '접기' returns to compact speech-bubble mode
        self.window.expand_button.click()
        self.app.processEvents()
        self.assertFalse(self.window.expanded)
        self.assertEqual(self.window.expand_button.text(), "펼치기")
        self.assertEqual(self.window.bubble.width(), 286)

    def test_settings_window_matches_snow_bubble_design(self):
        self.window.open_settings()
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.objectName(), "fubukiSettings")
        self.assertTrue(self.window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(bool(self.window.windowFlags() & Qt.WindowType.FramelessWindowHint))
        self.assertEqual(self.window.settings_card.objectName(), "settingsCard")
        self.assertFalse(self.window.standalone_chat_box.isVisible())
        self.assertFalse(self.window.grab().isNull())
        self.window.close_settings_button.click()
        self.app.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_character_by_character_typewriter_animation(self):
        # Verify Operation splits a single large chunk into character-by-character deltas
        emitted_chars = []
        op = Operation(
            lambda cancel, emit: (emit("안녕 후부키!"), "안녕 후부키!")[1],
            char_delay=0.001,
        )
        op.delta.connect(emitted_chars.append)
        op.run()
        self.assertEqual(emitted_chars, list("안녕 후부키!"))

        # Verify live typing cursor appears during streaming and disappears on completion
        self.window.pending_user = "인사해줘"
        self.window.current_text = "안녕하"
        self.window.render()
        self.assertIn("후부키: 안녕하▍", self.window.transcript.toPlainText())
        self.window.on_result_test_complete = None
        self.window.operation = "chat"
        self.window.on_result("안녕하세요!")
        self.assertNotIn("▍", self.window.transcript.toPlainText())
        self.assertIn("후부키: 안녕하세요!", self.window.transcript.toPlainText())


if __name__ == "__main__":
    unittest.main()
