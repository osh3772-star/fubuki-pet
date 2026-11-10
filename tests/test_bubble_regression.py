"""Offline regression coverage; never calls a provider or changes system settings."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from windows_pet.chat_bubble import BubbleChat, BubbleInput, place_bubble
from test_chat_ui import FakeClient

class BubbleRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_actual_ime_preedit_and_commit_events(self):
        editor = BubbleInput()
        calls = []
        editor.submit.connect(lambda: calls.append(1))
        QApplication.sendEvent(editor, QInputMethodEvent('\u314e', []))
        self.assertTrue(editor.composing)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(calls, [])
        commit = QInputMethodEvent()
        commit.setCommitString('\ud55c')
        QApplication.sendEvent(editor, commit)
        self.assertFalse(editor.composing)
        self.assertEqual(editor.toPlainText(), '\ud55c')
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(calls, [1])
        editor.deleteLater()

    def test_multiline_draft_survives_repeated_hide(self):
        anchor = QWidget()
        w = BubbleChat(Path(tempfile.mkdtemp()), True, FakeClient(), anchor)
        try:
            w.input.setPlainText('first\nsecond\n\ud55c\uae00 / \u65e5\u672c\u8a9e')
            original = w.input.toPlainText()
            for _ in range(5):
                w.open_bubble()
                self.app.processEvents()
                w.bubble.hide()
            self.assertEqual(w.input.toPlainText(), original)
        finally:
            w.shutdown(); w.deleteLater(); anchor.deleteLater()

    def test_placement_exhaustive_logical_screens(self):
        for area in (QRect(0, 0, 1920, 1040), QRect(-1920, -200, 1920, 1080),
                     QRect(0, 0, 1280, 680), QRect(0, 0, 280, 240)):
            for x in (area.left()-80, area.left(), area.center().x(), area.right()-50):
                for y in (area.top()-80, area.top(), area.center().y(), area.bottom()-50):
                    for side in ('left', 'right'):
                        rect, _ = place_bubble(QRect(x, y, 160, 180), area, 360, 400, side)
                        self.assertTrue(area.contains(rect), (area, rect))

    def test_side_is_stable_when_both_fit(self):
        area = QRect(0, 0, 1920, 1080)
        anchor = QRect(800, 400, 160, 180)
        for side in ('left', 'right'):
            _, result = place_bubble(anchor, area, 360, 350, side)
            self.assertEqual(result, side)

    def test_shutdown_hides_bubble_and_launcher(self):
        w = BubbleChat(Path(tempfile.mkdtemp()), True, FakeClient())
        w.open_bubble()
        self.app.processEvents()
        self.assertTrue(w.bubble.isVisible())
        self.assertTrue(w.shutdown())
        self.assertFalse(w.bubble.isVisible())
        self.assertFalse(w.launch_button.isVisible())
        self.assertFalse(w.timer.isActive())
        w.deleteLater()

if __name__ == '__main__':
    unittest.main()
