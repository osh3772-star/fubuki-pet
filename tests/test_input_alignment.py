import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from windows_pet.chat_bubble import BubbleInput,SKY_THEME,load_chat_fonts
class InputAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);load_chat_fonts()
    def setUp(self):
        self.w=BubbleInput();self.w.setStyleSheet(SKY_THEME);self.w.resize(180,self.w.height());self.w.show();self.w.setFocus();self.app.processEvents();self.w.fit_height();self.app.processEvents()
    def tearDown(self):self.w.hide();self.w.deleteLater();self.app.processEvents()
    def assert_centered(self):
        cursor=self.w.cursorRect();p=self.w.viewport().mapTo(self.w,cursor.center())
        self.assertLessEqual(abs(p.y()-(self.w.height()-1)/2),3)
        self.assertGreaterEqual(self.w.viewport().height(),self.w.fontMetrics().height())
    def test_empty_placeholder_line_centered(self):self.assert_centered()
    def test_korean_text_line_centered(self):
        self.w.setPlainText('\ud6c4\ubd80\ud0a4 \uc548\ub155');self.app.processEvents();self.assert_centered()
    def test_two_lines_have_glyph_space(self):
        self.w.setPlainText('\ud55c\uae00\n\u65e5\u672c\u8a9e');self.app.processEvents()
        fm=self.w.fontMetrics();self.assertGreaterEqual(self.w.viewport().height(),fm.height()+fm.lineSpacing())
    def test_ime_commit_and_enter(self):
        calls=[];self.w.submit.connect(lambda:calls.append(1))
        QApplication.sendEvent(self.w,QInputMethodEvent('\u314e',[]));QTest.keyClick(self.w,Qt.Key.Key_Return);self.assertEqual(calls,[])
        event=QInputMethodEvent();event.setCommitString('\ud55c');QApplication.sendEvent(self.w,event);self.app.processEvents()
        self.assertEqual(self.w.toPlainText(),'\ud55c');self.assert_centered();QTest.keyClick(self.w,Qt.Key.Key_Return);self.assertEqual(calls,[1])
