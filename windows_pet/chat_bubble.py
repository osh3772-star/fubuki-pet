"""Character-anchored chat. The existing ChatWindow owns all auth and workers."""
from PySide6.QtCore import Qt, QTimer, Signal, QRect, QEvent
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut, QPainter, QPainterPath, QColor, QPen, QFontDatabase
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit, QLabel, QComboBox
from .chat_window import ChatWindow

def load_chat_fonts():
    """App-private OFL fonts; never installs fonts or changes Windows settings."""
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/'assets'/'fonts'
    loaded=[]
    for name in ('NotoSansKR.ttf','NotoSansJP.ttf'):
        font_id=QFontDatabase.addApplicationFont(str(root/name))
        if font_id>=0:loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
    return loaded

# Original snow/sky palette. No artwork or font from reference games is bundled.
SKY_THEME = """
QWidget { font-family: 'Noto Sans KR', 'Noto Sans JP', 'Malgun Gothic', 'Yu Gothic UI'; font-size: 12px; color: #203E55; }
QWidget#fubukiBubble, QLabel { background: transparent; }
QLabel#speaker { color: #183E59; font-size: 14px; font-weight: 600; }
QLabel#status { color: #48677B; font-size: 11px; padding-bottom: 3px; }
QLabel#inputLabel { color: #42687D; font-size: 11px; font-weight: 600; }
QTextEdit { background: transparent; border: none; border-radius: 10px; padding: 4px; color: #203E55; font-size: 14px; selection-background-color: #C5E9FF; }
QPlainTextEdit { background: #EDF8FF; border: 1px solid #A6D4EC; border-radius: 14px; padding: 4px; color: #203E55; font-size: 14px; selection-background-color: #B0DDF5; }
QPlainTextEdit:focus { border: 2px solid #3685AE; }
QComboBox { background: #EAF5FC; border: 1px solid #CAE2F0; border-radius: 8px; padding: 1px 4px; color: #203E55; font-size: 11px; }
QComboBox:hover { background: #D6EEFC; border-color: #76B6D7; }
QComboBox:disabled { color: #758692; background: #EDF1F4; border-color: #DCE4E9; }
QPushButton { background: #EAF5FC; border: 1px solid #CAE2F0; border-radius: 10px; padding: 3px 6px; color: #31596E; }
QPushButton:hover { background: #D6EEFC; border-color: #76B6D7; }
QPushButton:focus { border: 2px solid #3685AE; }
QPushButton:pressed { background: #C0E3F6; }
QPushButton:disabled { color: #758692; background: #EDF1F4; border-color: #DCE4E9; }
QPushButton#send { background: #246E96; border-color: #246E96; color: white; font-weight: 700; }
QPushButton#send:hover { background: #195979; }
QPushButton#send:disabled { background: #D5E3EC; color: #657B89; border-color: #D5E3EC; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 2px; }
QScrollBar::handle:vertical { background: #A9CCDF; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

class SnowBubble(QWidget):
    def __init__(self):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.side='right'
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body=QPainterPath();body.addRoundedRect(12,3,self.width()-24,self.height()-7,22,22)
        tail=QPainterPath()
        if self.side=='right':
            tail.moveTo(13,55);tail.lineTo(2,65);tail.lineTo(13,75)
        else:
            tail.moveTo(self.width()-13,55);tail.lineTo(self.width()-2,65);tail.lineTo(self.width()-13,75)
        tail.closeSubpath();body=body.united(tail)
        p.setPen(QPen(QColor('#AFD7EC'),1.5));p.setBrush(QColor('#F8FCFF'));p.drawPath(body)


class BubbleInput(QPlainTextEdit):
    submit = Signal()
    def __init__(self):
        super().__init__()
        self.composing = False
        self.document().setDocumentMargin(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAccessibleName('Message to Fubuki')
        self.setPlaceholderText('후부키에게 말 걸기…')
        self.textChanged.connect(self.fit_height)
        self.fit_height()
    def fit_height(self):
        lines = max(1, min(2, int(self.document().size().height())))
        metrics=self.fontMetrics()
        # Reserve equal top/bottom padding plus the focused 2px frame.
        # Font height includes glyph ascent/descent; lineSpacing alone clips CJK.
        target=metrics.height()+metrics.lineSpacing()*(lines-1)+14
        if self.height()!=target:self.setFixedHeight(target)
    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange,QEvent.Type.StyleChange):
            QTimer.singleShot(0,self.fit_height)
    def inputMethodEvent(self, event):
        self.composing = bool(event.preeditString())
        super().inputMethodEvent(event)
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if not self.composing: self.submit.emit()
            event.accept(); return
        super().keyPressEvent(event)

def place_bubble(anchor, area, width, height, side='right'):
    """Logical-pixel placement; retain side unless it no longer fits."""
    width=min(width,area.width());height=min(height,area.height())
    right=anchor.right()+12;left=anchor.left()-12-width
    if side=='right' and right+width>area.right()+1: side='left'
    elif side=='left' and left<area.left(): side='right'
    x=right if side=='right' else left
    x=max(area.left(),min(x,area.right()-width+1))
    y=max(area.top(),min(anchor.top(),area.bottom()-height+1))
    return QRect(x,y,width,height),side

def anchor_head_rect(anchor, fallback):
    """Use the visible upper sprite mask, not transparent canvas or tail width."""
    if anchor is None or anchor.mask().isEmpty():return fallback
    from PySide6.QtGui import QRegion
    mask=anchor.mask()
    bounds=mask.boundingRect()
    upper=mask.intersected(QRegion(QRect(bounds.x(),bounds.y(),bounds.width(),max(1,int(bounds.height()*.4))))).boundingRect()
    return upper.translated(anchor.frameGeometry().topLeft()) if not upper.isEmpty() else fallback


def place_launcher(head,area,width=48,height=26):
    x=head.center().x()-width//2
    y=head.top()-height-6
    return QRect(max(area.left(),min(x,area.right()-width+1)),max(area.top(),min(y,area.bottom()-height+1)),width,height)


class BubbleChat(ChatWindow):
    def __init__(self,data_dir,mock=False,client=None,anchor=None,providers=None):
        self.loaded_font_families=load_chat_fonts()
        self.bubble_provider=None
        super().__init__(data_dir,mock,client,providers=providers)
        self.anchor=anchor;self.side='right'
        self.setWindowTitle('후부키 계정 · 모델 설정')
        self.bubble=SnowBubble()
        if mock:
            # Keep offline validation discoverable by native accessibility tools.
            self.bubble.setWindowFlags(Qt.WindowType.Window|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.bubble.setWindowTitle('후부키 말풍선')
        self.bubble.setObjectName('fubukiBubble')
        self.bubble.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.bubble.setStyleSheet(SKY_THEME)
        box=QVBoxLayout(self.bubble);box.setContentsMargins(22,10,22,10);box.setSpacing(5)
        head=QHBoxLayout();head.setSpacing(4)
        speaker=QLabel('후부키');speaker.setObjectName('speaker');head.addWidget(speaker)
        self.bubble_provider=QComboBox()
        self.bubble_provider.setAccessibleName('Bubble provider selector')
        self.bubble_provider.setToolTip('대화 공급자 선택 (ChatGPT · Gemini · Antigravity Gemini)')
        for label,code in (('ChatGPT','chatgpt'),('Gemini','gemini'),('Antigravity','antigravity_gemini')):
            self.bubble_provider.addItem(label,code)
        self.bubble_provider.setFixedSize(86,22)
        self.bubble_provider.currentIndexChanged.connect(self._on_bubble_provider_changed)
        self.provider_changed.connect(self._sync_bubble_provider)
        head.addWidget(self.bubble_provider)
        head.addStretch()
        self.new_button.setText('새 대화');self.new_button.setToolTip('새 대화 시작');head.addWidget(self.new_button)
        settings=QPushButton('⋯');settings.setFixedSize(24,24);settings.setAccessibleName('Chat settings');settings.clicked.connect(self.open_settings);head.addWidget(settings)
        close=QPushButton('−');close.setFixedSize(24,24);close.setAccessibleName('Fold Fubuki chat');close.clicked.connect(self.fold_bubble);head.addWidget(close);box.addLayout(head)
        self.status.setObjectName('status');self.status.setMaximumHeight(30);box.addWidget(self.status)
        box.addWidget(self.transcript)
        self.transcript.setAccessibleName('Fubuki conversation')
        self.transcript.setMinimumHeight(56);self.transcript.setMaximumHeight(96)
        self.transcript.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input.hide();self.input.deleteLater();self.input=BubbleInput();self.input.submit.connect(self.send)
        self.send_button.setObjectName('send');self.send_button.setText('↑');self.send_button.setAccessibleName('Send message');self.send_button.setFixedSize(28,30)
        self.stop_button.setText('■');self.stop_button.setAccessibleName('Stop response');self.stop_button.setFixedSize(26,30)
        row=QHBoxLayout();row.setSpacing(4)
        row.addWidget(self.input,1);row.addWidget(self.stop_button);row.addWidget(self.send_button);box.addLayout(row)
        QShortcut(QKeySequence('Escape'),self.bubble,activated=self.fold_bubble)
        self.launch_button=QPushButton('•••',None)
        self.launch_button.setStyleSheet(SKY_THEME)
        self.launch_button.setWindowFlags(Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.launch_button.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.launch_button.setAccessibleName('Open Fubuki chat')
        self.launch_button.clicked.connect(self.open_bubble)
        self.launch_button.setFixedSize(48,26);self.launch_button.show()
        self.timer=QTimer(self);self.timer.timeout.connect(self.follow_anchor);self.timer.start(40)
        self.refresh_controls()
    def _on_bubble_provider_changed(self):
        if self.bubble_provider is not None:
            code=self.bubble_provider.currentData()
            if code:self.select_provider(code)
    def _sync_bubble_provider(self,provider_code):
        if self.bubble_provider is not None:
            idx=self.bubble_provider.findData(provider_code)
            if idx>=0 and self.bubble_provider.currentIndex()!=idx:
                self.bubble_provider.blockSignals(True)
                self.bubble_provider.setCurrentIndex(idx)
                self.bubble_provider.blockSignals(False)
    def refresh_controls(self):
        super().refresh_controls()
        if getattr(self,'bubble_provider',None) is not None:
            self.bubble_provider.setEnabled(self.worker is None)
    def open_bubble(self):
        self.follow_anchor(force=True);self.bubble.show();self.launch_button.hide();self.bubble.raise_()
        # Only this explicit user action activates the editor, never streamed replies.
        self.bubble.activateWindow();self.input.setFocus()
    def fold_bubble(self):
        self.bubble.hide();self.follow_anchor();self.launch_button.show()
    def open_settings(self):
        self.showNormal();self.raise_();self.activateWindow()
    def follow_anchor(self,force=False):
        rect=self.anchor.frameGeometry() if self.anchor else QRect(500,400,160,180)
        screen=QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        if not screen:return
        area=screen.availableGeometry()
        head=anchor_head_rect(self.anchor,rect)
        self.launch_button.setGeometry(place_launcher(head,area,self.launch_button.width(),self.launch_button.height()))
        self.launch_button.setVisible(not self.bubble.isVisible())
        self.transcript.document().setTextWidth(max(1,self.transcript.viewport().width()))
        reply_height=max(56,min(96,int(self.transcript.document().size().height())+12))
        self.transcript.setFixedHeight(reply_height)
        height=self.bubble.sizeHint().height()
        bubble_anchor=QRect(head.x(),head.y()-40,head.width(),head.height())
        geometry,self.side=place_bubble(bubble_anchor,area,286,height,self.side)
        self.bubble.side=self.side;self.bubble.update()
        self.bubble.setGeometry(geometry)
    def shutdown(self):
        if not super().shutdown():return False
        self.timer.stop();self.bubble.hide();self.launch_button.hide();return True
