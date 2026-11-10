import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import QRect,Qt
from PySide6.QtTest import QTest
from windows_pet.chat_bubble import BubbleChat,BubbleInput,place_bubble
import test_chat_ui
from test_chat_ui import FakeClient

class BubbleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_edges_and_negative_monitors(self):
        for area in [QRect(0,0,1920,1040),QRect(-1280,0,1280,984),QRect(0,0,800,560)]:
            for x in (area.left(),area.right()-100):
                for y in (area.top(),area.bottom()-100):
                    rect,side=place_bubble(QRect(x,y,100,100),area,320,300)
                    self.assertTrue(area.contains(rect))
    def test_enter_and_composition(self):
        editor=BubbleInput();events=[];editor.submit.connect(lambda:events.append(1))
        QTest.keyClick(editor,Qt.Key.Key_Return);self.assertEqual(len(events),1)
        editor.composing=True;QTest.keyClick(editor,Qt.Key.Key_Return);self.assertEqual(len(events),1)
        editor.composing=False;QTest.keyClick(editor,Qt.Key.Key_Return,Qt.KeyboardModifier.ShiftModifier)
        self.assertIn('\n',editor.toPlainText());editor.deleteLater()
    def test_anchor_draft_and_settings(self):
        anchor=QWidget();anchor.setGeometry(100,100,100,100)
        w=BubbleChat(Path(tempfile.mkdtemp()),True,FakeClient(),anchor)
        w.open_bubble();self.app.processEvents();w.input.setPlainText('draft')
        self.assertEqual(w.input.window(),w.bubble)
        self.assertEqual(w.transcript.window(),w.bubble)
        w.bubble.hide();w.open_bubble();self.assertEqual(w.input.toPlainText(),'draft')
        anchor.move(300,200);w.follow_anchor();self.assertGreater(w.bubble.x(),300)
        w.open_settings();self.assertTrue(w.isVisible());w.shutdown();w.hide();w.deleteLater();anchor.deleteLater()

class BubbleConversationTests(test_chat_ui.ChatUITests):
    def setUp(self):self.client=FakeClient();self.window=BubbleChat(Path('.'),True,self.client)

if __name__=='__main__':unittest.main()
