import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading,time,unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication,QMessageBox
from windows_pet.chat_window import ChatWindow

class FakeClient:
    def __init__(self): self.connected=False; self.slow=False; self.calls=0
    def session_info(self): return dict(connected=self.connected,sharing=self.connected,email='mock@example.test')
    def sign_in(self,cancel): self.connected=True; return self.session_info()
    def list_models(self,cancel): return [{'slug':'mock','display_name':'Mock model'}]
    def stream_reply(self,messages,model,on_delta,cancel):
        self.calls+=1
        for part in ['안녕! ', '오늘도 반가워.']:
            for i in range(20 if self.slow else 1):
                if cancel.is_set(): return ''
                time.sleep(.01)
            on_delta(part)
        return '안녕! 오늘도 반가워.'
    def logout(self): self.connected=False; return {'revoked':True,'message':'로그아웃했습니다.'}

class ChatUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def setUp(self): self.client=FakeClient(); self.window=ChatWindow(Path('.'),True,self.client)
    def wait(self):
        deadline=time.monotonic()+5
        while self.window.worker is not None and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.app.processEvents()
        self.assertIsNone(self.window.worker)
    def tearDown(self): self.window.shutdown();self.window.deleteLater();self.app.processEvents()
    def connect(self): self.window.connect_account();self.wait()
    def test_connect_models_reply_logout(self):
        self.assertFalse(self.window.send_button.isEnabled())
        self.connect();self.assertEqual(self.window.models.count(),1)
        self.window.input.setPlainText('안녕');self.window.send();self.window.send();self.wait()
        self.assertEqual(self.client.calls,1);self.assertEqual(len(self.window.history),2)
        self.assertIn('반가워',self.window.transcript.toPlainText())
        self.window.logout();self.wait();self.assertEqual(self.window.history,[])
        self.assertFalse(self.window.send_button.isEnabled())
    def test_cancel_not_committed(self):
        self.connect();self.client.slow=True
        self.window.input.setPlainText('취소 테스트');self.window.send();self.window.stop();self.wait()
        self.assertEqual(self.window.history,[])
        self.assertIn('완료되지 않음',self.window.transcript.toPlainText())
    def test_input_bound_and_plain_text(self):
        self.connect();self.window.input.setPlainText('x'*4001);self.window.send()
        self.assertIsNone(self.window.worker)
        self.window.history=[{'role':'assistant','content':'<img src="https://bad.test">'}]
        self.window.render();self.assertIn('<img',self.window.transcript.toPlainText())
    def test_new_chat(self):
        self.window.history=[{'role':'user','content':'old'}];self.window.new_chat()
        self.assertEqual(self.window.history,[])
    def test_close_during_request(self):
        self.connect();self.client.slow=True
        self.window.input.setPlainText('안녕');self.window.send();self.window.close();self.wait()
        self.assertEqual(self.window.history,[])

if __name__=='__main__':unittest.main()
