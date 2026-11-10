import os,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import QRect,Qt
from PySide6.QtGui import QRegion
from windows_pet.chat_bubble import BubbleChat,place_launcher,anchor_head_rect
from test_chat_ui import FakeClient
class CompactBubbleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.anchor=QWidget();self.anchor.setGeometry(100,180,165,198)
        self.anchor.setMask(QRegion(QRect(50,40,70,100)).united(QRegion(QRect(100,120,60,50))))
        self.w=BubbleChat(Path(self.tmp.name),True,FakeClient(),self.anchor)
    def tearDown(self):self.w.shutdown();self.w.deleteLater();self.anchor.deleteLater();self.app.processEvents()
    def test_head_ignores_transparent_canvas_and_tail(self):
        r=anchor_head_rect(self.anchor,self.anchor.frameGeometry())
        self.assertEqual(r.top(),220);self.assertEqual(r.center().x(),184)
    def test_folded_button_above_head_and_draft_preserved(self):
        self.w.input.setPlainText('draft');self.w.open_bubble();self.app.processEvents()
        self.assertFalse(self.w.launch_button.isVisible())
        self.w.fold_bubble();self.app.processEvents();head=anchor_head_rect(self.anchor,self.anchor.frameGeometry())
        self.assertLessEqual(abs(self.w.launch_button.geometry().center().x()-head.center().x()),1)
        self.assertEqual(head.top()-self.w.launch_button.geometry().bottom(),7)
        self.assertTrue(self.w.launch_button.isVisible());self.assertFalse(self.w.bubble.isVisible())
        self.w.open_bubble();self.assertEqual(self.w.input.toPlainText(),'draft')
    def test_launcher_clamps_screen_edges(self):
        area=QRect(-1280,0,1280,720)
        for x in (-1280,-20):
            for y in (0,700):self.assertTrue(area.contains(place_launcher(QRect(x,y,80,70),area)))
    def test_compact_short_reply_dimensions(self):
        self.w.history=[{'role':'assistant','content':'Short reply.'}];self.w.render();self.w.open_bubble();self.app.processEvents();self.w.follow_anchor()
        self.assertEqual(self.w.bubble.width(),350);self.assertLessEqual(self.w.bubble.height(),240)
        self.assertEqual(self.w.transcript.horizontalScrollBarPolicy(),Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    def test_long_reply_keeps_bounded_bubble(self):
        self.w.history=[{'role':'assistant','content':'A long reply. '*400}];self.w.render();self.w.open_bubble();self.app.processEvents();self.w.follow_anchor()
        self.assertLessEqual(self.w.transcript.height(),132);self.assertLessEqual(self.w.bubble.height(),280)
    def test_launcher_follows_anchor_movement(self):
        self.w.fold_bubble();before=self.w.launch_button.pos();self.anchor.move(200,280);self.w.follow_anchor()
        self.assertEqual(self.w.launch_button.pos().x()-before.x(),100)
        self.assertEqual(self.w.launch_button.pos().y()-before.y(),100)
