"""Fubuki desktop pet. Manual and visual acceptance belongs to the user.

Existing illustration provenance is preserved; no ChatGPT installation is modified.
"""
from __future__ import annotations
import argparse,json,math,os,sys,time
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
from .core import PetEngine,Settings,Rect,JOB_STATES
from .events import data_directory,read_events

ROOT=Path(__file__).resolve().parents[1]

def forward_pointer_move(engine, x, y, opaque):
    """Preserve head-hit information for both timer and GUI mouse events."""
    overhead = bool(opaque and y < engine.y + 106 * engine.settings.scale)
    engine.pointer_move(x, y, over_head=overhead)

def read_reduced_motion(saved):
    """Old settings files have no flag; only a saved JSON true enables it."""
    return isinstance(saved,dict) and saved.get('reduced_motion') is True

def read_saved_settings(saved):
    """Load known settings or use defaults when their saved shape is invalid."""
    values=saved.get('settings',{}) if isinstance(saved,dict) else {}
    if not isinstance(values,dict):return Settings()
    valid={k:v for k,v in values.items() if k in Settings.__dataclass_fields__}
    try:return Settings(**valid)
    except (ValueError,TypeError,OverflowError):return Settings()

def restore_saved_position(engine, saved):
    """Restore bounded coordinates and settle an interrupted airborne session."""
    if not isinstance(saved,dict):return
    try:
        xx=float(saved.get('x',engine.x));yy=float(saved.get('y',engine.y))
        if not math.isfinite(xx) or not math.isfinite(yy):return
    except (ValueError,TypeError,OverflowError):return
    engine.x=xx;engine.y=yy;engine.clamp()
    floor=max(engine.screen.y,engine.screen.bottom-engine.pivot_y)
    if engine.y<floor:
        # Autosave, Quit, or a scale change may have saved a falling position.
        # Idle has no gravity, so restoring only coordinates would float forever.
        engine._set('fall',reason='restored airborne position')

def main()->int:
    ap=argparse.ArgumentParser(description='Fubuki desktop pet')
    ap.add_argument('--candidate-art',action='store_true',help=argparse.SUPPRESS)
    ap.add_argument('--debug',action='store_true',help='Open the state and animation panel')
    args=ap.parse_args()
    try:
        from PySide6.QtCore import Qt,QTimer,QPoint,QLockFile
        from PySide6.QtGui import QPainter,QPixmap,QRegion,QCursor,QAction,QIcon
        from PySide6.QtWidgets import QApplication,QWidget,QMenu,QSystemTrayIcon,QMessageBox,QVBoxLayout,QLabel,QPushButton,QHBoxLayout,QComboBox
    except ImportError:
        if sys.platform != 'linux':
            print('PySide6 is not installed. Run setup_windows.cmd first.',file=sys.stderr);return 3
        try:
            from PyQt5.QtCore import Qt,QTimer,QPoint,QLockFile
            from PyQt5.QtGui import QPainter,QPixmap,QRegion,QCursor,QIcon
            from PyQt5.QtWidgets import QAction,QApplication,QWidget,QMenu,QSystemTrayIcon,QMessageBox,QVBoxLayout,QLabel,QPushButton,QHBoxLayout,QComboBox
        except ImportError:
            print('Install PySide6 or PyQt5 to run Fubuki Pet.',file=sys.stderr);return 3
    app=QApplication(sys.argv[:1]);app.setApplicationName('FubukiPet');app.setQuitOnLastWindowClosed(False)
    store=data_directory();store.mkdir(parents=True,exist_ok=True)
    instance_lock=QLockFile(str(store/'instance.lock'))
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(100):
        QMessageBox.information(None,'Fubuki Pet','후부키가 이미 실행 중이거나 설정 폴더를 사용할 수 없습니다.\n작업 표시줄의 숨겨진 아이콘에서 후부키 메뉴를 열어 주세요.')
        return 0
    saved={}
    try:saved=json.loads((ROOT/'config/default-settings.json').read_text(encoding='utf-8'))
    except (ValueError,OSError):pass
    try:
        user_saved=json.loads((store/'settings.json').read_text(encoding='utf-8'))
        if isinstance(user_saved,dict):saved=user_saved
    except (ValueError,OSError):pass
    settings=read_saved_settings(saved)
    def screens():
        return [Rect(r.x(),r.y(),r.width(),r.height()) for s in app.screens() for r in [s.availableGeometry()]]
    engine=PetEngine(screens(),settings,time.monotonic())
    restore_saved_position(engine,saved)
    engine.reduced_motion=read_reduced_motion(saved)
    registry=json.loads((ROOT/'assets/runtime_candidate.json').read_text(encoding='utf-8'))
    clips=registry['clips'];default_path=ROOT/registry['placeholder']
    engine.configure_clip_timings(clips)

    class Overlay(QWidget):
        def __init__(self):
            super().__init__();self.setWindowTitle('Fubuki Pet')
            flags=Qt.WindowType.FramelessWindowHint|Qt.WindowType.Tool
            if settings.always_on_top:flags|=Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags);self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.setMouseTracking(True)
            self.cache=OrderedDict();self.pixmap=None;self.current_key=None
            self.displayed='';self.missing_art=True;self.last_cursor=None;self.last_inbox=0.;self.last_save=0.;self.last_screens=0.
            self.trace_previous=None;self.trace_path=os.environ.get('FUBUKI_FRAME_TRACE')
            self.last_state='';self.timer=QTimer(self);self.timer.timeout.connect(self.tick)
            self.menu=QMenu(self);self.debug=None
            # Popups take mouse events, including a held button's release.
            self.menu.aboutToShow.connect(engine.cancel_pointer)
            self.tray=QSystemTrayIcon(QIcon(str(default_path)),app);self.tray.setToolTip('Fubuki Pet')
            self.tray.setContextMenu(self.menu);self.tray.show()
            self.build_menu();self.render_current();self.move(round(engine.x),round(engine.y));self.show();self.timer.start(30)
        def build_menu(self):
            self.menu.clear()
            title=self.menu.addAction('Fubuki Pet');title.setEnabled(False)
            self.status_action=self.menu.addAction('');self.status_action.setEnabled(False)
            self.menu.addSeparator();self.menu.addAction('동작 패널 / 상태 보기',self.open_debug)
            actions=self.menu.addMenu('수동 작업 상태 (실제 ChatGPT 상태 아님)')
            for name in ['working','thinking','waiting','success','failed','review','idle']:
                actions.addAction(name,lambda checked=False,n=name:engine.job_event(n,'manual','debug'))
            size=self.menu.addMenu('크기')
            for value in [.75,1.,1.5,2.]:size.addAction(f'{value:g}×',lambda checked=False,v=value:self.resize_pet(v))
            top=self.menu.addAction('항상 위에 표시');top.setCheckable(True);top.setChecked(settings.always_on_top);top.triggered.connect(self.toggle_top)
            inbox=self.menu.addAction('로컬 앱 / 공식 Codex hook 이벤트 수신');inbox.setCheckable(True);inbox.setChecked(settings.event_inbox_enabled);inbox.triggered.connect(self.toggle_inbox)
            motion=self.menu.addAction('움직임 줄이기');motion.setCheckable(True);motion.setChecked(engine.reduced_motion);motion.triggered.connect(self.toggle_motion)
            startup=self.menu.addAction('Windows 로그인 시 자동 시작');startup.setCheckable(True);startup.setChecked(self.startup_enabled());startup.setEnabled(sys.platform=='win32');startup.triggered.connect(self.toggle_startup)
            self.menu.addAction('화면으로 다시 데려오기',self.bring_back)
            self.menu.addSeparator();self.menu.addAction('종료',self.quit)
        def bring_back(self):
            engine.cancel_pointer()
            engine.set_screens(screens())
            screen=engine.screen
            engine.x=screen.x+(screen.width-engine.width)/2
            engine.y=max(screen.y,screen.bottom-engine.pivot_y)
            engine.vx=engine.vy=0.
            engine._set('idle',reason='return to screen')
            engine.clamp();self.move(round(engine.x),round(engine.y));self.render_current();self.show();self.save()
        def startup_enabled(self):
            if sys.platform!='win32':return False
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:return bool(winreg.QueryValueEx(key,'FubukiPet')[0])
            except OSError:return False
        def toggle_startup(self,enabled):
            if sys.platform!='win32':return
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run',0,winreg.KEY_SET_VALUE) as key:
                    if enabled:
                        executable=Path(sys.executable).with_name('pythonw.exe')
                        if not executable.exists():executable=Path(sys.executable)
                        command=(f'"{sys.executable}" --candidate-art' if getattr(sys,"frozen",False) else f'"{executable}" "{ROOT / "launcher.py"}" --candidate-art')
                        winreg.SetValueEx(key,'FubukiPet',0,winreg.REG_SZ,command)
                    else:
                        try:winreg.DeleteValue(key,'FubukiPet')
                        except FileNotFoundError:pass
            except OSError as exc:QMessageBox.warning(self,'자동 시작 설정 실패',str(exc))
        def toggle_top(self,value):
            engine.cancel_pointer();settings.always_on_top=value
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,value);self.show();self.save()
        def toggle_inbox(self,value):settings.event_inbox_enabled=value;self.save()
        def toggle_motion(self,value):
            engine.reduced_motion=value;self.render_current();self.save()
        def resize_pet(self,value):
            engine.resize(value);self.move(round(engine.x),round(engine.y))
            self.cache.clear();self.current_key=None;self.render_current();self.save()
        def select_frame(self):
            clip=clips.get(engine.state)
            self.missing_art=clip is None
            if clip is None:
                self.displayed='STATIC PLACEHOLDER — '+engine.state+' art missing';return default_path
            self.displayed=clip['label']
            if engine.reduced_motion:return ROOT/clip['frames'][0]
            elapsed=max(0,(engine.now-engine.state_since)*1000)
            durations=clip['durations_ms'];total=sum(durations)
            t=elapsed%total if clip.get('loop',False) else min(elapsed,total-1)
            for path,d in zip(clip['frames'],durations):
                if t<d:return ROOT/path
                t-=d
            return ROOT/clip['frames'][-1]
        def render_current(self):
            path=self.select_frame();key=(str(path),settings.scale)
            trace_key=(engine.state,str(path))
            if self.trace_path and trace_key!=self.trace_previous:
                with open(self.trace_path,'a',encoding='utf-8') as trace:
                    trace.write(json.dumps({'time':time.monotonic(),'state':engine.state,'frame':str(path.relative_to(ROOT)),'dragging':engine.dragging})+'\n')
                self.trace_previous=trace_key
            if key==self.current_key:return
            if key not in self.cache:
                original=QPixmap(str(path))
                if original.isNull():raise RuntimeError(f'Cannot load frame: {path}')
                pm=original.scaled(round(engine.width),round(engine.height),Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.FastTransformation)
                # Qt derives the hit mask from alpha. Artwork alpha is not modified.
                region=QRegion(pm.mask())
                self.cache[key]=(pm,region)
                if len(self.cache)>64:self.cache.popitem(last=False)
            else:self.cache.move_to_end(key)
            self.pixmap,region=self.cache[key];self.current_key=key
            self.setFixedSize(self.pixmap.size());self.setMask(region);self.update()
        def is_opaque(self,gx,gy):
            if self.pixmap is None:return False
            # Hit the frame currently displayed, not an unpainted physics step.
            local=self.mapFromGlobal(QPoint(round(gx),round(gy)))
            return self.mask().contains(local)
        def tick(self):
            now=time.monotonic();engine.tick(now)
            cur=QCursor.pos();xy=(cur.x(),cur.y())
            if xy!=self.last_cursor:
                # During a press, the native mouse events own motion. A second
                # polling stream can be out of order and reset the drag pose.
                if not engine.pressed:
                    opaque=self.is_opaque(*xy)
                    forward_pointer_move(engine,*xy,opaque);engine.hover(opaque)
                self.last_cursor=xy
            if now-self.last_inbox>.25 and settings.event_inbox_enabled:
                for event in read_events(store):engine.job_event(event['state'],event['origin'],event['session'],event['id'])
                self.last_inbox=now
            if now-self.last_screens>2:engine.set_screens(screens());self.last_screens=now
            self.move(round(engine.x),round(engine.y));self.render_current()
            self.setToolTip(f'Fubuki Pet\nState: {engine.state}\nArt: {self.displayed}\nSource: {engine.source_label}')
            self.status_action.setText(f'{engine.state} | '+('그림 없음' if self.missing_art else '재생 중'))
            if self.debug is not None and self.debug.isVisible():self.debug.refresh()
            active=engine.dragging or engine.state in {'release','fall','landing','recover'}
            interval=round(1000/(settings.active_fps if active else settings.idle_fps))
            if self.timer.interval()!=interval:self.timer.setInterval(interval)
            if now-self.last_save>5 and not engine.dragging:self.save();self.last_save=now
        def paintEvent(self,event):
            if self.pixmap is not None:
                painter=QPainter(self);painter.drawPixmap(0,0,self.pixmap)
        def mousePressEvent(self,event):
            if event.button()==Qt.MouseButton.LeftButton:
                p=event.globalPosition() if hasattr(event, "globalPosition") else event.globalPos();engine.tick(time.monotonic())
                if engine.pointer_down(p.x(),p.y(),self.is_opaque(p.x(),p.y())):event.accept()
            else:super().mousePressEvent(event)
        def mouseDoubleClickEvent(self,event):
            # Engine disambiguates clicks on release; do not play single click first.
            self.mousePressEvent(event)
        def mouseMoveEvent(self,event):
            p=event.globalPosition() if hasattr(event, "globalPosition") else event.globalPos();engine.tick(time.monotonic())
            opaque=self.is_opaque(p.x(),p.y())
            forward_pointer_move(engine,p.x(),p.y(),opaque)
            # The timer polls QCursor too. Mark this position as already handled
            # so the same point is not delivered again as a zero-speed move.
            self.last_cursor=(p.x(),p.y());engine.hover(opaque)
            self.move(round(engine.x),round(engine.y));self.render_current()
        def mouseReleaseEvent(self,event):
            if event.button()==Qt.MouseButton.LeftButton:
                p=event.globalPosition() if hasattr(event, "globalPosition") else event.globalPos();engine.tick(time.monotonic());engine.pointer_up(p.x(),p.y())
                self.last_cursor=(p.x(),p.y())
                self.move(round(engine.x),round(engine.y));self.render_current();event.accept()
        def contextMenuEvent(self,event):self.menu.exec(event.globalPos())
        def hideEvent(self,event):engine.cancel_pointer();super().hideEvent(event)
        def save(self):
            obj={'settings':asdict(settings),'x':engine.x,'y':engine.y,'candidate_art':True,'reduced_motion':engine.reduced_motion}
            try:
                p=store/'settings.json';tmp=store/'settings.json.tmp';tmp.write_text(json.dumps(obj,indent=2),encoding='utf-8');tmp.replace(p)
            except OSError:pass
        def open_debug(self):
            if self.debug is None:self.debug=DebugPanel()
            self.debug.show();self.debug.raise_();self.debug.refresh()
        def quit(self):self.save();self.tray.hide();app.quit()

    class DebugPanel(QWidget):
        def __init__(self):
            super().__init__();self.setWindowTitle('Fubuki Pet 동작 패널');self.resize(520,420)
            layout=QVBoxLayout(self)
            warning=QLabel('아래 버튼으로 동작과 작업 상태를 직접 바꿀 수 있습니다.\nChatGPT 웹의 작업 상태를 자동으로 읽지는 않습니다.\n기존 그림을 통합했으며 그림과 사용감은 직접 확인해 주세요.')
            warning.setWordWrap(True);layout.addWidget(warning)
            self.details=QLabel();self.details.setWordWrap(True);layout.addWidget(self.details)
            combo=QComboBox();combo.addItems(['working','thinking','waiting','success','failed','review','idle']);layout.addWidget(combo)
            send=QPushButton('수동 작업 상태 보내기');send.clicked.connect(lambda:engine.job_event(combo.currentText(),'manual','debug'));layout.addWidget(send)
            wave=QPushButton('인사하기');wave.clicked.connect(lambda:engine.debug_action('wave'));layout.addWidget(wave)
            shared=QComboBox();shared.addItems(['idle','walk_right','walk_left','wave','jump','failed','waiting','working','review']);layout.addWidget(shared)
            play_shared=QPushButton('선택한 동작 재생');play_shared.clicked.connect(lambda:engine.debug_action(shared.currentText()));layout.addWidget(play_shared)
            self.trace=QLabel();self.trace.setWordWrap(True);layout.addWidget(self.trace)
            self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose,False)
        def refresh(self):
            self.details.setText(json.dumps(engine.snapshot(),ensure_ascii=False,indent=2)+'\nDISPLAY: '+overlay.displayed)
            self.trace.setText('최근 전환: '+' → '.join(x['to'] for x in list(engine.history)[-8:]))
    overlay=Overlay()
    if args.debug:overlay.open_debug()
    app.aboutToQuit.connect(overlay.save)
    return app.exec()

if __name__=='__main__':raise SystemExit(main())
