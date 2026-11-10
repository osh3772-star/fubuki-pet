import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from windows_pet.chat_bubble import SnowBubble,SKY_THEME

def luminance(h):
    rgb=[int(h[i:i+2],16)/255 for i in (0,2,4)]
    rgb=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    return sum(a*b for a,b in zip(rgb,(.2126,.7152,.0722)))
class SkyTests(unittest.TestCase):
    def test_readable_text_contrast(self):
        for fg,bg in [('203E55','FFFFFF'),('203E55','EDF8FF'),('FFFFFF','246E96'),('48677B','F8FCFF')]:
            a,b=sorted([luminance(fg),luminance(bg)])
            self.assertGreaterEqual((b+.05)/(a+.05),4.5)
    def test_transparent_directional_bubble(self):
        app=QApplication.instance() or QApplication([])
        w=SnowBubble();w.resize(360,350)
        self.assertTrue(w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        for side in ('left','right'):
            w.side=side;w.show();app.processEvents()
            self.assertFalse(w.grab().isNull())
        w.hide();w.deleteLater()
if __name__=='__main__':unittest.main()
