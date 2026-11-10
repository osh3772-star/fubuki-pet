"""Offline tests for the reported IME and speech-bubble layout regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication
from windows_pet.chat_bubble import BubbleChat, BubbleInput
from test_chat_ui import FakeClient


class ChatLayoutFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_placeholder_hidden_during_uncommitted_korean(self):
        editor = BubbleInput()
        try:
            original = editor.placeholderText()
            self.assertTrue(original)
            QApplication.sendEvent(editor, QInputMethodEvent('아', []))
            self.assertEqual(editor.toPlainText(), '')
            self.assertEqual(editor.placeholderText(), '')
            QApplication.sendEvent(editor, QInputMethodEvent('', []))
            self.assertEqual(editor.placeholderText(), original)
            QApplication.sendEvent(editor, QInputMethodEvent('한', []))
            event = QInputMethodEvent()
            event.setCommitString('한')
            QApplication.sendEvent(editor, event)
            self.assertEqual(editor.toPlainText(), '한')
            self.assertEqual(editor.placeholderText(), original)
        finally:
            editor.deleteLater()

    def make_window(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        window = BubbleChat(Path(tmp.name), True, FakeClient())
        self.addCleanup(lambda: (window.shutdown(), window.deleteLater(), self.app.processEvents()))
        window.open_bubble()
        self.app.processEvents()
        return window

    def test_document_width_never_exceeds_actual_viewport(self):
        window = self.make_window()
        window.history = [{'role': 'assistant', 'content': '나랑 같이 신나게 이야기하자. '*100}]
        window.toggle_expand()
        for width in (350, 440, 300):
            window.apply_user_resize(width, 300)
            for _ in range(3):
                self.app.processEvents()
                window.follow_anchor(force=True)
            self.assertLessEqual(window.transcript.document().size().width(), window.transcript.viewport().width())
            self.assertGreater(window.transcript.verticalScrollBar().maximum(), 0)
            self.assertEqual(window.transcript.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def test_name_has_its_own_row_and_only_reply_gets_tail(self):
        window = self.make_window()
        self.assertEqual(window.speaker.text(), 'フブキ')
        self.assertLess(window.speaker.geometry().bottom(), window.bubble_provider.geometry().top())
        body = window.bubble.speech_body_rect()
        self.assertTrue(body.contains(window.transcript.geometry()))
        self.assertFalse(body.intersects(window.input.geometry()))
        self.assertFalse(body.intersects(window.speaker.geometry()))

    def test_provider_button_has_room_for_text_and_rounded_arrow(self):
        window = self.make_window()
        combo = window.bubble_provider
        required = combo.fontMetrics().horizontalAdvance('Gemini') + 38
        self.assertGreaterEqual(combo.width(), required)
        self.assertEqual(combo.objectName(), 'bubbleProvider')

if __name__ == '__main__':
    unittest.main()
