import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont,QRawFont
from windows_pet.chat_bubble import load_chat_fonts
class FontTests(unittest.TestCase):
    def test_bundled_fonts_and_glyphs(self):
        app=QApplication.instance() or QApplication([])
        families=load_chat_fonts()
        self.assertIn('Noto Sans KR',families);self.assertIn('Noto Sans JP',families)
        for family,text in [('Noto Sans KR','후부키 안녕하세요'),('Noto Sans JP','こんにちは休憩')]:
            font=QRawFont.fromFont(QFont(family,14))
            for ch in text:self.assertTrue(font.supportsCharacter(ch),(family,ch))
if __name__=='__main__':unittest.main()
