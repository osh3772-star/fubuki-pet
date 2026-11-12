"""Character-anchored chat. The existing ChatWindow owns all auth and workers."""
from PySide6.QtCore import Qt, QTimer, Signal, QRect, QEvent, QPoint, QRectF
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut, QPainter, QPainterPath, QColor, QPen, QFontDatabase, QTextCursor, QTextBlockFormat
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit, QLabel
from .ui_controls import RoundedComboBox as QComboBox
from .chat_window import ChatWindow

_LOADED_FONT_FAMILIES = None

def load_chat_fonts():
    """App-private OFL fonts; never installs fonts or changes Windows settings."""
    global _LOADED_FONT_FAMILIES
    if _LOADED_FONT_FAMILIES:
        return list(_LOADED_FONT_FAMILIES)
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/'assets'/'fonts'
    loaded=[]
    for name in ('NotoSansKR.ttf','NotoSansJP.ttf'):
        font_id=QFontDatabase.addApplicationFont(str(root/name))
        if font_id>=0:loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
    if loaded:
        _LOADED_FONT_FAMILIES=tuple(loaded)
    return loaded

# Original snow/sky palette. No artwork or font from reference games is bundled.
SKY_THEME = """
QWidget { font-family: 'Noto Sans KR', 'Noto Sans JP', 'Malgun Gothic', 'Yu Gothic UI'; font-size: 12px; color: #203E55; }
QWidget#fubukiBubble, QWidget#fubukiSettings, QLabel { background: transparent; }
QWidget#settingsCard { background: #EDF8FF; border: 1px solid #A6D4EC; border-radius: 14px; }
QLabel#speaker { color: #183E59; font-size: 14px; font-weight: 600; }
QLabel#status { color: #48677B; font-size: 11px; padding-bottom: 2px; }
QLabel#inputLabel { color: #42687D; font-size: 11px; font-weight: 600; }
QLabel#captionNote { color: #48677B; font-size: 11px; background: #F1F9FE; border: 1px solid #D5EAF7; border-radius: 10px; padding: 6px 8px; }
QTextEdit { background: #FFFFFF; border: 1.5px solid #C5E3F6; border-radius: 14px; padding: 6px 8px; color: #163247; font-size: 15px; font-weight: 500; selection-background-color: #C5E9FF; }
QPlainTextEdit { background: #EDF8FF; border: 1px solid #A6D4EC; border-radius: 14px; padding: 5px 7px; color: #163247; font-size: 14px; selection-background-color: #B0DDF5; }
QPlainTextEdit:focus { border: 2px solid #3685AE; background: #F7FCFF; }
QComboBox { background: #EAF5FC; border: 1px solid #CAE2F0; border-radius: 8px; padding: 2px 6px; color: #203E55; font-size: 11px; min-height: 20px; }
QComboBox:hover { background: #D6EEFC; border-color: #76B6D7; }
QComboBox:disabled { color: #758692; background: #EDF1F4; border-color: #DCE4E9; }
QComboBox#bubbleProvider { border-radius: 12px; padding: 2px 30px 2px 10px; min-height: 0px; }
QComboBox#bubbleProvider::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 25px; border: 0px; border-radius: 11px; background: #D9EFFB; margin: 1px; }
QComboBox#bubbleProvider::down-arrow { image: none; width: 0px; height: 0px; }
QTextEdit#bubbleTranscript { background: transparent; border: none; border-radius: 0px; padding: 8px 10px; }
QPushButton { background: #EAF5FC; border: 1px solid #CAE2F0; border-radius: 10px; padding: 3px 6px; color: #31596E; }
QPushButton:hover { background: #D6EEFC; border-color: #76B6D7; }
QPushButton:focus { border: 2px solid #3685AE; }
QPushButton:pressed { background: #C0E3F6; }
QPushButton:disabled { color: #758692; background: #EDF1F4; border-color: #DCE4E9; }
QPushButton#send { background: #246E96; border-color: #246E96; color: white; font-weight: 700; }
QPushButton#send:hover { background: #195979; }
QPushButton#send:disabled { background: #D5E3EC; color: #657B89; border-color: #D5E3EC; }
QPushButton#danger { background: #FDF2F4; border: 1px solid #F1C5CE; border-radius: 10px; color: #9C2B43; font-weight: 600; }
QPushButton#danger:hover { background: #FCE2E7; border-color: #E29AA9; }
QMenu { background: #F8FCFF; border: 1.5px solid #AFD7EC; border-radius: 12px; padding: 6px; color: #203E55; font-family: 'Noto Sans KR', 'Noto Sans JP', 'Malgun Gothic'; font-size: 12px; }
QMenu::item { padding: 5px 18px 5px 12px; border-radius: 7px; background: transparent; }
QMenu::item:selected { background: #D6EEFC; color: #183E59; font-weight: 600; }
QMenu::item:disabled { color: #758692; }
QMenu::separator { height: 1px; background: #D5EAF7; margin: 4px 6px; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 6px 3px; }
QScrollBar::handle:vertical { background: #A9CCDF; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

class SnowBubble(QWidget):
    def __init__(self, owner=None):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.side='right'
        self.owner=owner
        self._path_cache_key=None
        self._cached_path=None
        self._drag_start_global=None
        self._drag_start_pos=None
        self._resize_edges=''
        self._resize_start_global=None
        self._resize_start_geom=None
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    def _hit_resize_edges(self,pos:QPoint)->str:
        if self.owner is None:return ''
        w,h=self.width(),self.height()
        edges=''
        if pos.y()>=h-14:edges+='b'
        if pos.x()>=w-16 and pos.y()>36:edges+='r'
        elif pos.x()<=16 and pos.y()>36:edges+='l'
        return edges
    def speech_body_rect(self):
        if self.owner is not None and hasattr(self.owner, 'transcript'):
            return QRectF(self.owner.transcript.geometry()).adjusted(-3, -2, 3, 2)
        return QRectF(12, 3, self.width()-24, self.height()-7)
    def paintEvent(self,event):
        w,h,side=self.width(),self.height(),self.side
        rect=self.speech_body_rect()
        key=(w,h,side,rect.x(),rect.y(),rect.width(),rect.height())
        if self._path_cache_key!=key or self._cached_path is None:
            body=QPainterPath();body.addRoundedRect(rect,18,18)
            tail=QPainterPath()
            tail_y=min(rect.bottom()-18,rect.top()+28)
            if side=='right':
                tail.moveTo(rect.left()+1,tail_y-8);tail.lineTo(rect.left()-10,tail_y);tail.lineTo(rect.left()+1,tail_y+8)
            else:
                tail.moveTo(rect.right()-1,tail_y-8);tail.lineTo(rect.right()+10,tail_y);tail.lineTo(rect.right()-1,tail_y+8)
            tail.closeSubpath()
            self._cached_path=body.united(tail)
            self._path_cache_key=key
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#AFD7EC'),1.5));p.setBrush(QColor('#F8FCFF'));p.drawPath(self._cached_path)
        if self.owner is not None:
            # Subtle bottom-right resize grip lines so user knows bubble is resizable
            p.setPen(QPen(QColor('#8AC0DE'),1.4))
            p.drawLine(w-24,h-10,w-17,h-17)
            p.drawLine(w-20,h-10,w-17,h-13)
    def mousePressEvent(self,event):
        if self.owner is not None and event.button()==Qt.MouseButton.LeftButton:
            pos=event.position().toPoint() if hasattr(event,'position') else event.pos()
            gpos=event.globalPosition().toPoint() if hasattr(event,'globalPosition') else event.globalPos()
            edges=self._hit_resize_edges(pos)
            if edges:
                self._resize_edges=edges
                self._resize_start_global=gpos
                self._resize_start_geom=QRect(self.geometry())
                event.accept();return
            if pos.y()<=40:
                self._drag_start_global=gpos
                self._drag_start_pos=self.frameGeometry().topLeft()
                event.accept();return
        super().mousePressEvent(event)
    def mouseDoubleClickEvent(self,event):
        if self.owner is not None and event.button()==Qt.MouseButton.LeftButton:
            pos=event.position().toPoint() if hasattr(event,'position') else event.pos()
            if pos.y()<=40:
                self.owner.reset_window_adjustments()
                event.accept();return
        super().mouseDoubleClickEvent(event)
    def mouseMoveEvent(self,event):
        if self.owner is not None:
            pos=event.position().toPoint() if hasattr(event,'position') else event.pos()
            gpos=event.globalPosition().toPoint() if hasattr(event,'globalPosition') else event.globalPos()
            if self._resize_edges and (event.buttons()&Qt.MouseButton.LeftButton):
                dx=gpos.x()-self._resize_start_global.x()
                dy=gpos.y()-self._resize_start_global.y()
                g=self._resize_start_geom
                new_w=g.width()+(dx if 'r' in self._resize_edges else (-dx if 'l' in self._resize_edges else 0))
                new_h=g.height()+(dy if 'b' in self._resize_edges else 0)
                self.owner.apply_user_resize(new_w if ('r' in self._resize_edges or 'l' in self._resize_edges) else None,
                                             new_h if 'b' in self._resize_edges else None)
                event.accept();return
            if self._drag_start_global is not None and (event.buttons()&Qt.MouseButton.LeftButton):
                target=self._drag_start_pos+(gpos-self._drag_start_global)
                self.owner.apply_user_move(target)
                event.accept();return
            edges=self._hit_resize_edges(pos)
            if edges in ('rb','br'):self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif edges in ('lb','bl'):self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif edges in ('r','l'):self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif edges=='b':self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:self.unsetCursor()
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        self._drag_start_global=None
        self._drag_start_pos=None
        self._resize_edges=''
        self._resize_start_global=None
        self._resize_start_geom=None
        super().mouseReleaseEvent(event)


class BubbleInput(QPlainTextEdit):
    submit = Signal()
    def __init__(self):
        super().__init__()
        self.composing = False
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.document().setDocumentMargin(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAccessibleName('Message to Fubuki')
        self._idle_placeholder='フブキ에게 말 걸기…'
        self.setPlaceholderText(self._idle_placeholder)
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
        # Qt considers the document empty until IME commit. Hide its placeholder
        # during preedit too, otherwise it is painted underneath Korean input.
        self.setPlaceholderText('' if self.composing else self._idle_placeholder)
        super().inputMethodEvent(event)
        self.viewport().update()
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
    if anchor is None:return fallback
    mask=anchor.mask()
    if mask.isEmpty():return fallback
    bounds=mask.boundingRect()
    mask_sig=(bounds.x(),bounds.y(),bounds.width(),bounds.height(),mask.rectCount())
    cached=getattr(anchor,'_cached_head_upper',None)
    if cached is not None and cached[0]==mask_sig:
        upper=cached[1]
    else:
        from PySide6.QtGui import QRegion
        upper=mask.intersected(QRegion(QRect(bounds.x(),bounds.y(),bounds.width(),max(1,int(bounds.height()*.4))))).boundingRect()
        try:
            anchor._cached_head_upper=(mask_sig,upper)
        except Exception:
            pass
    return upper.translated(anchor.frameGeometry().topLeft()) if not upper.isEmpty() else fallback


def place_launcher(head,area,width=48,height=26):
    x=head.center().x()-width//2
    y=head.top()-height-6
    return QRect(max(area.left(),min(x,area.right()-width+1)),max(area.top(),min(y,area.bottom()-height+1)),width,height)


class ProviderComboBox(QComboBox):
    """Named subtype for the compact provider control."""


class BubbleChat(ChatWindow):
    def __init__(self,data_dir,mock=False,client=None,anchor=None,providers=None):
        self.loaded_font_families=load_chat_fonts()
        self.bubble_provider=None
        self.expanded=False
        self.expand_button=None
        self.font_down_button=None
        self.font_up_button=None
        self.chat_font_px=15
        self.custom_width=None
        self.custom_height=None
        self.custom_offset=None
        super().__init__(data_dir,mock,client,providers=providers)
        self.anchor=anchor;self.side='right';self._drag_offset=None
        self.setWindowTitle('フブキ 계정 · 모델 설정')
        settings_flags=(Qt.WindowType.Window if mock else Qt.WindowType.Tool)|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(settings_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(SKY_THEME)
        if hasattr(self,'standalone_chat_box'):
            self.standalone_chat_box.hide()
        QShortcut(QKeySequence('Escape'),self,activated=self.hide)
        self.bubble=SnowBubble(owner=self)
        if mock:
            # Keep offline validation discoverable by native accessibility tools.
            self.bubble.setWindowFlags(Qt.WindowType.Window|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.bubble.setWindowTitle('フブキ 말풍선')
        self.bubble.setObjectName('fubukiBubble')
        self.bubble.setStyleSheet(SKY_THEME)
        self._last_follow_state=None
        box=QVBoxLayout(self.bubble);box.setContentsMargins(18,8,18,10);box.setSpacing(7)
        title_row=QHBoxLayout();title_row.setContentsMargins(8,0,4,0)
        self.speaker=QLabel('フブキ');self.speaker.setObjectName('speaker')
        self.speaker.setStyleSheet('background: #F8FCFF; border-radius: 8px; padding: 2px 8px;')
        title_row.addWidget(self.speaker)
        title_row.addStretch()
        close=QPushButton('−');close.setFixedSize(24,24);close.setAccessibleName('Fold Fubuki chat');close.clicked.connect(self.fold_bubble);title_row.addWidget(close)
        box.addLayout(title_row)
        head=QHBoxLayout();head.setSpacing(5)
        self.bubble_provider=ProviderComboBox()
        self.bubble_provider.setObjectName('bubbleProvider')
        self.bubble_provider.setAccessibleName('Bubble provider selector')
        self.bubble_provider.setToolTip('대화 공급자 선택 (ChatGPT · Gemini · Antigravity Gemini · Claude)')
        for label,code in (('ChatGPT','chatgpt'),('Gemini','gemini'),('Antigravity','antigravity_gemini'),('Claude','claude')):
            self.bubble_provider.addItem(label,code)
        self.bubble_provider.setFixedSize(94,26)
        self.bubble_provider.view().setMinimumWidth(150)
        self._sync_bubble_provider(self.current_provider)
        self.bubble_provider.currentIndexChanged.connect(self._on_bubble_provider_changed)
        self.provider_changed.connect(self._sync_bubble_provider)
        head.addWidget(self.bubble_provider)
        self.font_down_button=QPushButton('가−')
        self.font_down_button.setAccessibleName('Decrease chat font size')
        self.font_down_button.setToolTip('글자 크기 작게 (창 상단 더블클릭 시 크기·위치 초기화)')
        self.font_down_button.setFixedSize(28,22)
        self.font_down_button.setStyleSheet('padding: 1px 2px; font-size: 11px;')
        self.font_down_button.clicked.connect(lambda:self.adjust_font_size(-1))
        head.addWidget(self.font_down_button)
        self.font_up_button=QPushButton('가+')
        self.font_up_button.setAccessibleName('Increase chat font size')
        self.font_up_button.setToolTip('글자 크기 크게 (우측·하단 모서리 드래그로 창 크기 조절 가능)')
        self.font_up_button.setFixedSize(28,22)
        self.font_up_button.setStyleSheet('padding: 1px 2px; font-size: 11px;')
        self.font_up_button.clicked.connect(lambda:self.adjust_font_size(1))
        head.addWidget(self.font_up_button)
        self.expand_button=QPushButton('펼치기')
        self.expand_button.setAccessibleName('Toggle full conversation')
        self.expand_button.setToolTip('전체 답변 및 큰 창으로 펼치기 / 접기')
        self.expand_button.setFixedSize(42,22)
        self.expand_button.setStyleSheet('padding: 1px 2px; font-size: 11px;')
        self.expand_button.clicked.connect(self.toggle_expand)
        head.addWidget(self.expand_button)
        self.new_button.setText('새 대화');self.new_button.setToolTip('새 대화 시작')
        self.new_button.setFixedSize(44,22)
        self.new_button.setStyleSheet('padding: 1px 2px; font-size: 11px;')
        head.addWidget(self.new_button)
        settings=QPushButton('⋯');settings.setFixedSize(22,22);settings.setAccessibleName('Chat settings');settings.clicked.connect(self.open_settings);head.addWidget(settings)
        head.addStretch();box.addLayout(head)
        self.status.setObjectName('status');self.status.setWordWrap(False);self.status.setMinimumWidth(40);self.status.setFixedHeight(20);box.addWidget(self.status)
        box.addWidget(self.transcript)
        self.transcript.setObjectName('bubbleTranscript')
        self.transcript.setAccessibleName('Fubuki conversation')
        self.transcript.document().setDocumentMargin(6)
        self.transcript.setMinimumHeight(68);self.transcript.setMaximumHeight(132)
        self.transcript.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Always reserve the gutter so the line width never changes under text.
        self.transcript.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.input.hide();self.input.deleteLater();self.input=BubbleInput();self.input.submit.connect(self.send)
        self.send_button.setObjectName('send');self.send_button.setText('↑');self.send_button.setAccessibleName('Send message');self.send_button.setFixedSize(30,32)
        self.stop_button.setText('■');self.stop_button.setAccessibleName('Stop response');self.stop_button.setFixedSize(28,32)
        row=QHBoxLayout();row.setSpacing(5)
        row.addWidget(self.input,1);row.addWidget(self.stop_button);row.addWidget(self.send_button);box.addLayout(row)
        QShortcut(QKeySequence('Escape'),self.bubble,activated=self.fold_bubble)
        self.launch_button=QPushButton('•••',None)
        self.launch_button.setStyleSheet(SKY_THEME)
        self.launch_button.setWindowFlags(Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.launch_button.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.launch_button.setAccessibleName('Open Fubuki chat')
        self.launch_button.clicked.connect(self.open_bubble)
        self.launch_button.setFixedSize(48,26);self.launch_button.show()
        self.bubble.ensurePolished();self.transcript.ensurePolished();self.input.ensurePolished()
        self._apply_font_size()
        _=self.input.fontMetrics().horizontalAdvance('한글 日本語 English')
        self.timer=QTimer(self);self.timer.timeout.connect(self.follow_anchor);self.timer.start(40)
        self.refresh_controls()
    def _apply_font_size(self):
        px=max(12,min(20,int(getattr(self,'chat_font_px',15))))
        self.chat_font_px=px
        self.transcript.setStyleSheet(f'font-size: {px}px; font-weight: 500;')
        font=self.transcript.font();font.setPixelSize(px)
        self.transcript.document().setDefaultFont(font)
        input_px=max(13,min(17,px-1))
        self.input.setStyleSheet(f'font-size: {input_px}px;')
        self.input.fit_height()
        self._apply_transcript_line_spacing()
    def _apply_transcript_line_spacing(self):
        doc=self.transcript.document()
        cursor=QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)
        fmt=QTextBlockFormat()
        fmt.setLineHeight(132,QTextBlockFormat.LineHeightTypes.ProportionalHeight.value if hasattr(QTextBlockFormat.LineHeightTypes.ProportionalHeight,'value') else 1)
        fmt.setBottomMargin(3)
        cursor.mergeBlockFormat(fmt)
    def adjust_font_size(self,delta:int):
        self.chat_font_px=max(12,min(20,int(getattr(self,'chat_font_px',15))+int(delta)))
        self._apply_font_size()
        self._transcript_rev=getattr(self,'_transcript_rev',0)+1
        self.follow_anchor(force=True)
    def apply_user_resize(self,new_w=None,new_h=None):
        if new_w is not None:
            self.custom_width=max(270,min(680,int(new_w)))
        if new_h is not None:
            self.custom_height=max(180,min(620,int(new_h)))
        self.follow_anchor(force=True)
    def apply_user_move(self,target_pos:QPoint):
        rect=self.anchor.frameGeometry() if self.anchor else QRect(500,400,160,180)
        head=anchor_head_rect(self.anchor,rect)
        self.custom_offset=target_pos-head.topLeft()
        self.follow_anchor(force=True)
    def reset_window_adjustments(self):
        self.custom_width=None
        self.custom_height=None
        self.custom_offset=None
        self.follow_anchor(force=True)
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
    def toggle_expand(self):
        self.expanded=not self.expanded
        self.custom_width=None
        self.custom_height=None
        if self.expand_button is not None:
            self.expand_button.setText('접기' if self.expanded else '펼치기')
        self.render()
        self.follow_anchor(force=True)
    def _compact_reply_text(self,text:str)->str:
        limit=getattr(self,'max_reply_chars',80) or 90
        if len(text)<=limit:
            return text
        return text[:limit].rstrip()+'… [펼치기에서 전체 보기]'
    def render(self,footer=''):
        is_expanded=bool(getattr(self,'expanded',False))
        assistant_turns=[m['content'] for m in self.history if m.get('role')=='assistant' and m.get('content')]
        lines=[]
        if is_expanded:
            if assistant_turns:
                lines.append('\n\n─────────────────\n\n'.join(assistant_turns))
            if self.pending_user:
                cursor='▍' if not footer else ''
                live=(self.current_text+cursor) if self.current_text else ('…' if not footer else '')
                if live:
                    lines.append(live)
        else:
            if self.pending_user:
                if self.current_text:
                    cursor='▍' if not footer else ''
                    lines.append(self._compact_reply_text(self.current_text)+cursor)
                elif not footer:
                    lines.append('…')
            elif assistant_turns:
                lines.append(self._compact_reply_text(assistant_turns[-1]))
        if footer:
            lines.append(footer)
        text='\n'.join(lines)
        if getattr(self,'_last_rendered_text',None)!=text:
            self._last_rendered_text=text
            self.transcript.setPlainText(text)
            self._apply_transcript_line_spacing()
            if is_expanded and self.pending_user:
                bar=self.transcript.verticalScrollBar();bar.setValue(bar.maximum())
            else:
                self.transcript.verticalScrollBar().setValue(0)
            self._transcript_rev=getattr(self,'_transcript_rev',0)+1
    def open_bubble(self):
        self.bubble.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating,False)
        self.follow_anchor(force=True);self.launch_button.hide();self.bubble.show();self.follow_anchor(force=True);self.bubble.raise_()
        # Only this explicit user action activates the editor, never streamed replies.
        self.bubble.activateWindow();self.input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    def fold_bubble(self):
        self.bubble.hide();self.follow_anchor(force=True);self.launch_button.show()
    def open_settings(self):
        self.ensurePolished();self.adjustSize()
        target_w=max(340,self.minimumSizeHint().width(),self.sizeHint().width());target_h=max(320,self.sizeHint().height())
        base=self.bubble.geometry() if self.bubble.isVisible() else (self.anchor.frameGeometry() if self.anchor else QRect(500,360,160,180))
        screen=QGuiApplication.screenAt(base.center()) or QGuiApplication.primaryScreen()
        if screen:
            area=screen.availableGeometry()
            geom,_=place_bubble(base,area,target_w,target_h,self.side)
            self.setGeometry(geom)
        else:
            self.resize(target_w,target_h)
        self.showNormal();self.raise_();self.activateWindow();self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body=QPainterPath();body.addRoundedRect(6,3,self.width()-12,self.height()-6,22,22)
        p.setPen(QPen(QColor('#AFD7EC'),1.5));p.setBrush(QColor('#F8FCFF'));p.drawPath(body)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            pos=event.position().toPoint() if hasattr(event,'position') else event.pos()
            if pos.y()<=42:
                gpos=event.globalPosition().toPoint() if hasattr(event,'globalPosition') else event.globalPos()
                self._drag_offset=gpos-self.frameGeometry().topLeft()
                event.accept();return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            gpos=event.globalPosition().toPoint() if hasattr(event,'globalPosition') else event.globalPos()
            self.move(gpos-self._drag_offset)
            event.accept();return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        self._drag_offset=None
        super().mouseReleaseEvent(event)
    def follow_anchor(self,force=False):
        rect=self.anchor.frameGeometry() if self.anchor else QRect(500,400,160,180)
        screen=QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        if not screen:return
        area=screen.availableGeometry()
        bubble_visible=self.bubble.isVisible()
        if not force and bubble_visible and getattr(self,'_last_anchor_rect',None)==rect and getattr(self,'_last_head_rect',None) is not None:
            head=self._last_head_rect
        else:
            head=anchor_head_rect(self.anchor,rect)
            self._last_anchor_rect=QRect(rect)
            self._last_head_rect=QRect(head)
        is_expanded=bool(getattr(self,'expanded',False))
        target_width=self.custom_width if self.custom_width is not None else (440 if is_expanded else 350)
        # QTextEdit owns document wrapping. Estimating a wider document than its
        # actual viewport clips the final glyphs behind the scroll bar.
        if self.bubble.width()!=target_width:
            self.bubble.resize(target_width,self.bubble.height())
        self.bubble.layout().activate()
        est_vp_width=self.transcript.viewport().width()
        doc_h=int(self.transcript.document().size().height())
        state_key=(
            head.x(),head.y(),head.width(),head.height(),
            area.x(),area.y(),area.width(),area.height(),
            bubble_visible,
            is_expanded,
            est_vp_width,
            doc_h,
            self.input.height(),
            getattr(self,'_transcript_rev',0),
            self.side,
            self.custom_width,
            self.custom_height,
            (self.custom_offset.x(),self.custom_offset.y()) if self.custom_offset is not None else None,
            getattr(self,'chat_font_px',15),
        )
        if not force and getattr(self,'_last_follow_state',None)==state_key:
            return
        self._last_follow_state=state_key
        launcher_geom=place_launcher(head,area,self.launch_button.width(),self.launch_button.height())
        if self.launch_button.geometry()!=launcher_geom:
            self.launch_button.setGeometry(launcher_geom)
        if self.launch_button.isVisible()==bubble_visible:
            self.launch_button.setVisible(not bubble_visible)
        if self.custom_height is not None:
            overhead=self.bubble.layout().sizeHint().height()-self.transcript.height()
            reply_height=max(56,min(480,self.custom_height-overhead))
            min_h,max_h=56,480
        else:
            min_h,max_h=(170,310) if is_expanded else (60,124)
            reply_height=max(min_h,min(max_h,doc_h+14))
        if self.transcript.minimumHeight()!=reply_height or self.transcript.maximumHeight()!=reply_height:
            self.transcript.setFixedHeight(reply_height)
            if self.bubble.layout() is not None:
                self.bubble.layout().activate()
        layout_sig=(reply_height,self.input.height(),is_expanded,self.status.text(),self.custom_height)
        if self.custom_height is not None:
            height=self.custom_height
            self._last_layout_sig=layout_sig
            self._last_bubble_h=height
        elif not force and getattr(self,'_last_layout_sig',None)==layout_sig and getattr(self,'_last_bubble_h',0)>0:
            height=self._last_bubble_h
        else:
            height=self.bubble.sizeHint().height()
            self._last_layout_sig=layout_sig
            self._last_bubble_h=height
        bubble_anchor=QRect(head.x(),head.y()-40,head.width(),head.height())
        geometry,new_side=place_bubble(bubble_anchor,area,target_width,height,self.side)
        if self.custom_offset is not None:
            cx=max(area.left(),min(head.x()+self.custom_offset.x(),area.right()-geometry.width()+1))
            cy=max(area.top(),min(head.y()+self.custom_offset.y(),area.bottom()-geometry.height()+1))
            geometry=QRect(cx,cy,geometry.width(),geometry.height())
            new_side='right' if geometry.center().x()>=head.center().x() else 'left'
        side_changed=(new_side!=self.side or self.bubble.side!=new_side)
        self.side=new_side;self.bubble.side=new_side
        if self.bubble.geometry()!=geometry:
            self.bubble.setGeometry(geometry)
        if side_changed or force:
            self.bubble.update()
    def shutdown(self):
        if not super().shutdown():return False
        self.timer.stop();self.bubble.hide();self.launch_button.hide();return True


class PetContextBubble(SnowBubble):
    """Snow-bubble styled right-click character settings & control card."""
    def __init__(self, overlay, engine, settings):
        super().__init__()
        load_chat_fonts()
        self.overlay = overlay
        self.engine = engine
        self.settings = settings
        self._drag_offset = None
        self.setWindowTitle('후부키 캐릭터 설정')
        self.setObjectName('fubukiBubble')
        self.setStyleSheet(SKY_THEME)
        QShortcut(QKeySequence('Escape'), self, activated=self.hide)

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 10, 18, 12)
        box.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(4)
        title = QLabel('후부키 메뉴')
        title.setObjectName('speaker')
        head.addWidget(title)
        self.state_label = QLabel('')
        self.state_label.setObjectName('status')
        head.addWidget(self.state_label)
        head.addStretch()
        close_btn = QPushButton('−')
        close_btn.setFixedSize(22, 22)
        close_btn.setToolTip('메뉴 닫기')
        close_btn.clicked.connect(self.hide)
        head.addWidget(close_btn)
        box.addLayout(head)

        # Card 1: Chat & AI Provider
        chat_card = QWidget()
        chat_card.setObjectName('settingsCard')
        chat_layout = QVBoxLayout(chat_card)
        chat_layout.setContentsMargins(9, 8, 9, 8)
        chat_layout.setSpacing(5)

        top_chat_row = QHBoxLayout()
        top_chat_row.setSpacing(4)
        open_chat_btn = QPushButton('💬 대화창 열기')
        open_chat_btn.setObjectName('send')
        open_chat_btn.clicked.connect(lambda: (self.hide(), self.overlay.open_chat()))
        open_cfg_btn = QPushButton('⚙️ AI · 모델 설정')
        open_cfg_btn.clicked.connect(lambda: (self.hide(), self.overlay.open_chat_settings()))
        top_chat_row.addWidget(open_chat_btn, 1)
        top_chat_row.addWidget(open_cfg_btn, 1)
        chat_layout.addLayout(top_chat_row)

        prov_label = QLabel('대화 공급자 바로 선택')
        prov_label.setObjectName('inputLabel')
        chat_layout.addWidget(prov_label)
        prov_row = QHBoxLayout()
        prov_row.setSpacing(4)
        self.provider_buttons = {}
        for label, code in (('ChatGPT', 'chatgpt'), ('Gemini', 'gemini'), ('Antigravity', 'antigravity_gemini'), ('Claude', 'claude')):
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked=False, c=code: (self.hide(), self.overlay.open_chat_provider(c)))
            prov_row.addWidget(btn, 1)
            self.provider_buttons[code] = btn
        chat_layout.addLayout(prov_row)
        box.addWidget(chat_card)

        # Card 2: Character Scale, Options & Actions
        pet_card = QWidget()
        pet_card.setObjectName('settingsCard')
        pet_layout = QVBoxLayout(pet_card)
        pet_layout.setContentsMargins(9, 8, 9, 8)
        pet_layout.setSpacing(5)

        scale_label = QLabel('캐릭터 크기')
        scale_label.setObjectName('inputLabel')
        pet_layout.addWidget(scale_label)
        scale_row = QHBoxLayout()
        scale_row.setSpacing(4)
        self.scale_buttons = {}
        for val in (0.75, 1.0, 1.5, 2.0):
            btn = QPushButton(f'{val:g}×')
            btn.clicked.connect(lambda checked=False, v=val: (self.overlay.resize_pet(v), self.sync_state()))
            scale_row.addWidget(btn, 1)
            self.scale_buttons[val] = btn
        pet_layout.addLayout(scale_row)

        opt_row1 = QHBoxLayout()
        opt_row1.setSpacing(4)
        self.top_btn = QPushButton('📌 항상 위에 표시')
        self.top_btn.clicked.connect(self._toggle_top)
        self.motion_btn = QPushButton('🍃 움직임 줄이기')
        self.motion_btn.clicked.connect(self._toggle_motion)
        opt_row1.addWidget(self.top_btn, 1)
        opt_row1.addWidget(self.motion_btn, 1)
        pet_layout.addLayout(opt_row1)

        opt_row2 = QHBoxLayout()
        opt_row2.setSpacing(4)
        self.inbox_btn = QPushButton('🔔 외부 이벤트 수신')
        self.inbox_btn.clicked.connect(self._toggle_inbox)
        self.startup_btn = QPushButton('🚀 자동 시작')
        self.startup_btn.clicked.connect(self._toggle_startup)
        opt_row2.addWidget(self.inbox_btn, 1)
        opt_row2.addWidget(self.startup_btn, 1)
        pet_layout.addLayout(opt_row2)

        pose_row = QHBoxLayout()
        pose_row.setSpacing(4)
        self.pose_combo = QComboBox()
        for label, code in (
            ('인사하기 (wave)', 'wave'),
            ('기본 대기 (idle)', 'idle'),
            ('오른쪽 걷기', 'walk_right'),
            ('왼쪽 걷기', 'walk_left'),
            ('점프 (jump)', 'jump'),
            ('생각 중 (thinking)', 'thinking'),
            ('작업 중 (working)', 'working'),
            ('성공 (success)', 'success'),
            ('실패 (failed)', 'failed'),
            ('검토 (review)', 'review'),
        ):
            self.pose_combo.addItem(label, code)
        play_btn = QPushButton('동작 재생')
        play_btn.clicked.connect(self._play_selected_pose)
        pose_row.addWidget(self.pose_combo, 1)
        pose_row.addWidget(play_btn)
        pet_layout.addLayout(pose_row)
        box.addWidget(pet_card)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)
        bring_btn = QPushButton('🏠 화면으로 데려오기')
        bring_btn.clicked.connect(lambda: (self.hide(), self.overlay.bring_back()))
        debug_btn = QPushButton('🎭 상태 패널')
        debug_btn.clicked.connect(lambda: (self.hide(), self.overlay.open_debug()))
        quit_btn = QPushButton('종료')
        quit_btn.setObjectName('danger')
        quit_btn.clicked.connect(lambda: (self.hide(), self.overlay.quit()))
        bottom_row.addWidget(bring_btn, 1)
        bottom_row.addWidget(debug_btn, 1)
        bottom_row.addWidget(quit_btn)
        box.addLayout(bottom_row)

    def _apply_active_style(self, btn: QPushButton, active: bool):
        btn.setObjectName('send' if active else '')
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _toggle_top(self):
        self.overlay.toggle_top(not self.settings.always_on_top)
        self.sync_state()

    def _toggle_motion(self):
        self.overlay.toggle_motion(not self.engine.reduced_motion)
        self.sync_state()

    def _toggle_inbox(self):
        self.overlay.toggle_inbox(not self.settings.event_inbox_enabled)
        self.sync_state()

    def _toggle_startup(self):
        self.overlay.toggle_startup(not self.overlay.startup_enabled())
        self.sync_state()

    def _play_selected_pose(self):
        code = self.pose_combo.currentData()
        if code in ('idle', 'walk_right', 'walk_left', 'wave', 'jump', 'failed', 'waiting', 'working', 'review'):
            self.engine.debug_action(code)
        else:
            self.engine.job_event(code, 'manual', 'debug')
        self.sync_state()

    def sync_state(self):
        state_txt = f"· {self.engine.state} ({'그림 없음' if self.overlay.missing_art else '재생 중'})"
        self.state_label.setText(state_txt)
        current_prov = getattr(self.overlay.chat, 'current_provider', 'gemini') if self.overlay.chat else 'gemini'
        for code, btn in self.provider_buttons.items():
            self._apply_active_style(btn, code == current_prov)
        for val, btn in self.scale_buttons.items():
            self._apply_active_style(btn, abs(float(self.settings.scale) - val) < 0.05)
        self._apply_active_style(self.top_btn, bool(self.settings.always_on_top))
        self._apply_active_style(self.motion_btn, bool(self.engine.reduced_motion))
        self._apply_active_style(self.inbox_btn, bool(self.settings.event_inbox_enabled))
        self._apply_active_style(self.startup_btn, bool(self.overlay.startup_enabled()))

    def popup_near_anchor(self):
        self.sync_state()
        self.ensurePolished()
        self.adjustSize()
        rect = self.overlay.frameGeometry()
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        target_w = 296
        target_h = max(290, self.sizeHint().height())
        if screen:
            area = screen.availableGeometry()
            head = anchor_head_rect(self.overlay, rect)
            bubble_anchor = QRect(head.x(), head.y() - 20, head.width(), head.height())
            geom, new_side = place_bubble(bubble_anchor, area, target_w, target_h, self.side)
            self.side = new_side
            self.setGeometry(geom)
        else:
            self.resize(target_w, target_h)
        self.show()
        self.raise_()
        self.activateWindow()
        self.update()

    def event(self, ev):
        if ev.type() == QEvent.Type.WindowDeactivate:
            from PySide6.QtWidgets import QApplication
            if QApplication.activePopupWidget() is None and not self.pose_combo.view().isVisible():
                self.hide()
        return super().event(ev)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
            if pos.y() <= 38:
                gpos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                self._drag_offset = gpos - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            gpos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
            self.move(gpos - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

