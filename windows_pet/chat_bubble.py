"""Character-anchored chat. The existing ChatWindow owns all auth and workers."""
from PySide6.QtCore import Qt, QTimer, Signal, QRect, QEvent
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut, QPainter, QPainterPath, QColor, QPen, QFontDatabase
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit, QLabel, QComboBox
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
QLabel#status { color: #48677B; font-size: 11px; padding-bottom: 3px; }
QLabel#inputLabel { color: #42687D; font-size: 11px; font-weight: 600; }
QLabel#captionNote { color: #48677B; font-size: 11px; background: #F1F9FE; border: 1px solid #D5EAF7; border-radius: 10px; padding: 6px 8px; }
QTextEdit { background: transparent; border: none; border-radius: 10px; padding: 4px; color: #203E55; font-size: 14px; selection-background-color: #C5E9FF; }
QPlainTextEdit { background: #EDF8FF; border: 1px solid #A6D4EC; border-radius: 14px; padding: 4px; color: #203E55; font-size: 14px; selection-background-color: #B0DDF5; }
QPlainTextEdit:focus { border: 2px solid #3685AE; }
QComboBox { background: #EAF5FC; border: 1px solid #CAE2F0; border-radius: 8px; padding: 2px 6px; color: #203E55; font-size: 11px; min-height: 20px; }
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
QPushButton#danger { background: #FDF2F4; border: 1px solid #F1C5CE; border-radius: 10px; color: #9C2B43; font-weight: 600; }
QPushButton#danger:hover { background: #FCE2E7; border-color: #E29AA9; }
QMenu { background: #F8FCFF; border: 1.5px solid #AFD7EC; border-radius: 12px; padding: 6px; color: #203E55; font-family: 'Noto Sans KR', 'Noto Sans JP', 'Malgun Gothic'; font-size: 12px; }
QMenu::item { padding: 5px 18px 5px 12px; border-radius: 7px; background: transparent; }
QMenu::item:selected { background: #D6EEFC; color: #183E59; font-weight: 600; }
QMenu::item:disabled { color: #758692; }
QMenu::separator { height: 1px; background: #D5EAF7; margin: 4px 6px; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 2px; }
QScrollBar::handle:vertical { background: #A9CCDF; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

class SnowBubble(QWidget):
    def __init__(self):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.side='right'
        self._path_cache_key=None
        self._cached_path=None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    def paintEvent(self,event):
        w,h,side=self.width(),self.height(),self.side
        key=(w,h,side)
        if self._path_cache_key!=key or self._cached_path is None:
            body=QPainterPath();body.addRoundedRect(12,3,w-24,h-7,22,22)
            tail=QPainterPath()
            if side=='right':
                tail.moveTo(13,55);tail.lineTo(2,65);tail.lineTo(13,75)
            else:
                tail.moveTo(w-13,55);tail.lineTo(w-2,65);tail.lineTo(w-13,75)
            tail.closeSubpath()
            self._cached_path=body.united(tail)
            self._path_cache_key=key
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#AFD7EC'),1.5));p.setBrush(QColor('#F8FCFF'));p.drawPath(self._cached_path)


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


class BubbleChat(ChatWindow):
    def __init__(self,data_dir,mock=False,client=None,anchor=None,providers=None):
        self.loaded_font_families=load_chat_fonts()
        self.bubble_provider=None
        self.expanded=False
        self.expand_button=None
        super().__init__(data_dir,mock,client,providers=providers)
        self.anchor=anchor;self.side='right';self._drag_offset=None
        self.setWindowTitle('후부키 계정 · 모델 설정')
        settings_flags=(Qt.WindowType.Window if mock else Qt.WindowType.Tool)|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(settings_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(SKY_THEME)
        if hasattr(self,'standalone_chat_box'):
            self.standalone_chat_box.hide()
        QShortcut(QKeySequence('Escape'),self,activated=self.hide)
        self.bubble=SnowBubble()
        if mock:
            # Keep offline validation discoverable by native accessibility tools.
            self.bubble.setWindowFlags(Qt.WindowType.Window|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.bubble.setWindowTitle('후부키 말풍선')
        self.bubble.setObjectName('fubukiBubble')
        self.bubble.setStyleSheet(SKY_THEME)
        self._last_follow_state=None
        box=QVBoxLayout(self.bubble);box.setContentsMargins(16,10,16,10);box.setSpacing(5)
        head=QHBoxLayout();head.setSpacing(2)
        speaker=QLabel('후부키');speaker.setObjectName('speaker');head.addWidget(speaker)
        self.bubble_provider=QComboBox()
        self.bubble_provider.setAccessibleName('Bubble provider selector')
        self.bubble_provider.setToolTip('대화 공급자 선택 (ChatGPT · Gemini · Antigravity Gemini)')
        for label,code in (('ChatGPT','chatgpt'),('Gemini','gemini'),('Antigravity','antigravity_gemini')):
            self.bubble_provider.addItem(label,code)
        self.bubble_provider.setFixedSize(64,22)
        self._sync_bubble_provider(self.current_provider)
        self.bubble_provider.currentIndexChanged.connect(self._on_bubble_provider_changed)
        self.provider_changed.connect(self._sync_bubble_provider)
        head.addWidget(self.bubble_provider)
        head.addStretch()
        self.expand_button=QPushButton('펼치기')
        self.expand_button.setAccessibleName('Toggle full conversation')
        self.expand_button.setToolTip('전체 대화 내용 펼치기 / 접기')
        self.expand_button.setFixedSize(40,22)
        self.expand_button.setStyleSheet('padding: 1px 2px; font-size: 11px;')
        self.expand_button.clicked.connect(self.toggle_expand)
        head.addWidget(self.expand_button)
        self.new_button.setText('새 대화');self.new_button.setToolTip('새 대화 시작')
        self.new_button.setFixedSize(44,22)
        self.new_button.setStyleSheet('padding: 1px 2px; font-size: 11px;')
        head.addWidget(self.new_button)
        settings=QPushButton('⋯');settings.setFixedSize(22,22);settings.setAccessibleName('Chat settings');settings.clicked.connect(self.open_settings);head.addWidget(settings)
        close=QPushButton('−');close.setFixedSize(22,22);close.setAccessibleName('Fold Fubuki chat');close.clicked.connect(self.fold_bubble);head.addWidget(close);box.addLayout(head)
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
        self.bubble.ensurePolished();self.input.ensurePolished()
        _=self.input.fontMetrics().horizontalAdvance('한글 日本語 English')
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
    def toggle_expand(self):
        self.expanded=not self.expanded
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
        if getattr(self,'expanded',False):
            super().render(footer)
            return
        lines=[]
        if self.pending_user:
            lines.append('💬 나: '+self.pending_user)
            if self.current_text:
                cursor='▍' if not footer else ''
                lines.append('후부키: '+self._compact_reply_text(self.current_text)+cursor)
            else:
                lines.append('후부키: '+('…' if not footer else ''))
        elif self.history:
            last=self.history[-1]
            if last['role']=='assistant':
                if len(self.history)>=2 and self.history[-2]['role']=='user':
                    lines.append('💬 나: '+self.history[-2]['content'])
                lines.append('후부키: '+self._compact_reply_text(last['content']))
            else:
                lines.append('💬 나: '+last['content'])
        if footer:
            lines.append(footer)
        text='\n'.join(lines)
        if getattr(self,'_last_rendered_text',None)!=text:
            self._last_rendered_text=text
            self.transcript.setPlainText(text)
            # Keep the user's own utterance visible at the top of the compact speech bubble.
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
        target_w=340;target_h=max(320,self.sizeHint().height())
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
        vp_width=max(1,self.transcript.viewport().width())
        state_key=(
            head.x(),head.y(),head.width(),head.height(),
            area.x(),area.y(),area.width(),area.height(),
            bubble_visible,
            is_expanded,
            vp_width,
            self.input.height(),
            getattr(self,'_transcript_rev',0),
            self.side,
        )
        if not force and getattr(self,'_last_follow_state',None)==state_key:
            return
        self._last_follow_state=state_key
        launcher_geom=place_launcher(head,area,self.launch_button.width(),self.launch_button.height())
        if self.launch_button.geometry()!=launcher_geom:
            self.launch_button.setGeometry(launcher_geom)
        if self.launch_button.isVisible()==bubble_visible:
            self.launch_button.setVisible(not bubble_visible)
        if int(self.transcript.document().textWidth())!=vp_width:
            self.transcript.document().setTextWidth(vp_width)
        min_h,max_h=(140,240) if is_expanded else (56,96)
        if self.transcript.minimumHeight()!=min_h or self.transcript.maximumHeight()!=max_h:
            self.transcript.setMinimumHeight(min_h);self.transcript.setMaximumHeight(max_h)
        reply_height=max(min_h,min(max_h,int(self.transcript.document().size().height())+12))
        if self.transcript.height()!=reply_height:
            self.transcript.setFixedHeight(reply_height)
        layout_sig=(reply_height,self.input.height(),is_expanded,self.status.text())
        if not force and getattr(self,'_last_layout_sig',None)==layout_sig and getattr(self,'_last_bubble_h',0)>0:
            height=self._last_bubble_h
        else:
            height=self.bubble.sizeHint().height()
            self._last_layout_sig=layout_sig
            self._last_bubble_h=height
        target_width=360 if is_expanded else 286
        bubble_anchor=QRect(head.x(),head.y()-40,head.width(),head.height())
        geometry,new_side=place_bubble(bubble_anchor,area,target_width,height,self.side)
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
        for label, code in (('ChatGPT', 'chatgpt'), ('Gemini', 'gemini'), ('Antigravity', 'antigravity_gemini')):
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
