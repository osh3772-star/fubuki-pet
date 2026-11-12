"""Offline coverage for the optional 30-character reply target."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from windows_pet.chat_window import ChatWindow
from windows_pet.chat_bubble import BubbleChat
from windows_pet.chatgpt_client import REPLY_CHAR_LIMIT_OPTIONS, build_persona_instructions
from windows_pet.local_cli_clients import _validate_and_format_messages

class ShortReplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
    def test_options_preserve_default_and_existing_choices(self):
        self.assertEqual(REPLY_CHAR_LIMIT_OPTIONS[0][1], 80)
        self.assertEqual([v for _, v in REPLY_CHAR_LIMIT_OPTIONS], [80, 30, 150, None])
        self.assertIn(("아주 짧게 (30자)", 30), REPLY_CHAR_LIMIT_OPTIONS)
    def test_selection_reaches_every_provider(self):
        w = ChatWindow(Path("."), mock=True)
        try:
            self.assertEqual(w.reply_limit_selector.currentData(), 80)
            w.reply_limit_selector.setCurrentIndex(w.reply_limit_selector.findData(30))
            self.assertEqual(w.max_reply_chars, 30)
            self.assertTrue(all(p.max_reply_chars == 30 for p in w.providers.values()))
            w.reply_limit_selector.setCurrentIndex(w.reply_limit_selector.findData(None))
            self.assertTrue(all(p.max_reply_chars is None for p in w.providers.values()))
        finally:
            w.shutdown()
            w.deleteLater()
            self.app.processEvents()
    def test_prompt_target_is_thirty_in_both_transports(self):
        self.assertIn("공백 포함 30자 이내", build_persona_instructions(30))
        self.assertIn("30자", _validate_and_format_messages([{"role": "user", "content": "안녕"}], max_reply_chars=30))
    def test_compact_preview_does_not_mutate_full_answer(self):
        from types import SimpleNamespace
        answer = "가" * 45
        preview = BubbleChat._compact_reply_text(SimpleNamespace(max_reply_chars=30), answer)
        self.assertEqual(preview, "가" * 30 + "… [펼치기에서 전체 보기]")
        self.assertEqual(answer, "가" * 45)
