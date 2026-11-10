"""Subscription & local official CLI Qt chat; no API keys or unauthorized scraping."""
from __future__ import annotations
import threading
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QTextEdit, QPlainTextEdit, QMessageBox


PROVIDER_CONNECT_LABELS = {
    'chatgpt': 'Continue with ChatGPT',
    'gemini': '로컬 Gemini CLI 연결',
    'antigravity_gemini': '로컬 Antigravity 연결',
}

PROVIDER_NOTICES = {
    'chatgpt': (
        'ChatGPT 구독 연결만 사용합니다. API 키·자동 유료 전환은 없습니다.\n'
        '대화는 이 창의 메모리에만 보관되며 기존 ChatGPT 대화를 가져오지 않습니다.\n'
        '계정에서 설정한 크레딧 사용 정책은 OpenAI 설정에서 확인해 주세요.'
    ),
    'gemini': (
        '이 PC의 공식 Gemini CLI(gemini) 로그인 세션만 사용합니다. API 키는 사용하지 않으며 환경변수에서도 제거됩니다.\n'
        '브라우저 쿠키나 로컬 인증 토큰 파일을 직접 읽지 않고 공식 CLI를 통해 응답을 받아옵니다.\n'
        '대화는 이 창의 메모리에만 보관됩니다.'
    ),
    'antigravity_gemini': (
        '이 PC의 공식 Antigravity CLI(agy) 로그인 세션만 사용합니다. API 키는 사용하지 않으며 환경변수에서도 제거됩니다.\n'
        'Claude 모델은 제외하고 Antigravity의 Gemini 모델만 구분하여 표시·호출합니다.\n'
        '대화는 이 창의 메모리에만 보관됩니다.'
    ),
}


class Operation(QThread):
    delta = Signal(str)
    result = Signal(object)
    failed = Signal(str)
    def __init__(self, action):
        super().__init__()
        self.action = action
        self.cancel = threading.Event()
    def run(self):
        try:
            value = self.action(self.cancel, self.delta.emit)
            if self.cancel.is_set(): self.failed.emit('요청을 중지했습니다.')
            else: self.result.emit(value)
        except Exception as exc:
            # Client exceptions are sanitized; never display arbitrary HTTP bodies.
            from .chatgpt_client import ChatGPTError, Cancelled
            self.failed.emit(str(exc) if isinstance(exc, (ChatGPTError, Cancelled)) else '연결 작업을 완료하지 못했습니다. 다시 시도해 주세요.')


class ChatWindow(QWidget):
    state_changed = Signal(str)
    provider_changed = Signal(str)
    def __init__(self, data_dir, mock=False, client=None, providers=None):
        super().__init__()
        from .chatgpt_client import ChatGPTClient, MockChatGPTClient, DEFAULT_MAX_REPLY_CHARS, REPLY_CHAR_LIMIT_OPTIONS
        from .local_cli_clients import PROVIDERS, GeminiCLIClient, AntigravityGeminiClient, MockLocalCLIClient
        default_chatgpt = client or (MockChatGPTClient(data_dir) if mock else ChatGPTClient(data_dir))
        self.providers = {
            'chatgpt': default_chatgpt,
            'gemini': MockLocalCLIClient('gemini', data_dir) if mock else GeminiCLIClient(data_dir),
            'antigravity_gemini': MockLocalCLIClient('antigravity_gemini', data_dir) if mock else AntigravityGeminiClient(data_dir),
        }
        if isinstance(providers, dict):
            self.providers.update(providers)
        self.max_reply_chars = DEFAULT_MAX_REPLY_CHARS
        for p in self.providers.values():
            p.max_reply_chars = self.max_reply_chars
        self.current_provider = 'chatgpt'
        self.client = self.providers[self.current_provider]
        self._provider_models = {k: [] for k in self.providers}
        self._provider_selected_model = {k: None for k in self.providers}
        self._transcript_rev = 0
        self.mock = mock
        if not mock and client is None and providers is None:
            for code in ('gemini', 'antigravity_gemini'):
                fast_fn = getattr(self.providers.get(code), 'try_fast_connect', None)
                if callable(fast_fn) and fast_fn():
                    try:
                        self._provider_models[code] = list(self.providers[code].list_models())
                    except Exception:
                        pass
            if not self.providers['chatgpt'].session_info().get('connected'):
                for fallback_code in ('gemini', 'antigravity_gemini'):
                    if self.providers[fallback_code].session_info().get('connected'):
                        self.current_provider = fallback_code
                        self.client = self.providers[fallback_code]
                        break
        self.worker = None
        self.history = []
        self.current_text = ''
        self.pending_user = ''
        self.operation = ''
        self._effort_model = None
        self.setWindowTitle('후부키 · 구독 및 로컬 CLI 채팅' + (' [모의 테스트]' if mock else ' [시험본]'))
        self.resize(480, 590)
        layout = QVBoxLayout(self)
        provider_row = QHBoxLayout()
        provider_label = QLabel('대화 공급자')
        self.provider_selector = QComboBox()
        self.provider_selector.setAccessibleName('대화 공급자')
        provider_label.setBuddy(self.provider_selector)
        for code, label in PROVIDERS:
            self.provider_selector.addItem(label, code)
        provider_row.addWidget(provider_label)
        provider_row.addWidget(self.provider_selector, 1)
        layout.addLayout(provider_row)
        self.status = QLabel('연결 안 됨')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.connect_button = QPushButton(PROVIDER_CONNECT_LABELS['chatgpt'])
        self.cli_login_button = QPushButton('CLI 로그인 창 열기')
        self.cli_login_button.setVisible(False)
        self.refresh_button = QPushButton('모델 새로고침')
        self.logout_button = QPushButton('로그아웃')
        for button in (self.connect_button, self.cli_login_button, self.refresh_button, self.logout_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.models = QComboBox()
        layout.addWidget(self.models)
        effort_row = QHBoxLayout()
        effort_label = QLabel('추론 강도')
        self.reasoning_effort = QComboBox()
        self.reasoning_effort.setAccessibleName('추론 강도')
        effort_label.setBuddy(self.reasoning_effort)
        for label, value in (
                ('서버 기본값 (권장)', None), ('없음 · none', 'none'),
                ('최소 · minimal', 'minimal'), ('낮음 · low', 'low'),
                ('보통 · medium', 'medium'), ('높음 · high', 'high'),
                ('매우 높음 · xhigh', 'xhigh'), ('최대 · max', 'max')):
            self.reasoning_effort.addItem(label, value)
        effort_row.addWidget(effort_label)
        effort_row.addWidget(self.reasoning_effort, 1)
        layout.addLayout(effort_row)
        self.reasoning_note = QLabel('모델마다 지원 단계가 다릅니다. 계정 목록에 지원 정보가 없어 직접 선택은 서버에서 확인됩니다.\n높은 강도는 응답 시간과 구독 사용량이 늘 수 있습니다. 기본값은 강도를 지정하지 않습니다.')
        self.reasoning_note.setWordWrap(True)
        layout.addWidget(self.reasoning_note)
        self.reasoning_effort.setToolTip(self.reasoning_note.text())
        limit_row = QHBoxLayout()
        limit_label = QLabel('답변 길이 제한')
        self.reply_limit_selector = QComboBox()
        self.reply_limit_selector.setAccessibleName('답변 길이 제한')
        limit_label.setBuddy(self.reply_limit_selector)
        for label, value in REPLY_CHAR_LIMIT_OPTIONS:
            self.reply_limit_selector.addItem(label, value)
        self.reply_limit_selector.currentIndexChanged.connect(self._on_reply_limit_changed)
        limit_row.addWidget(limit_label)
        limit_row.addWidget(self.reply_limit_selector, 1)
        layout.addLayout(limit_row)
        self.models.currentIndexChanged.connect(self.on_model_changed)
        self.notice = QLabel(PROVIDER_NOTICES['chatgpt'])
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        layout.addWidget(self.transcript, 1)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText('후부키에게 짧게 말해 주세요…')
        self.input.setMaximumHeight(85)
        layout.addWidget(self.input)
        row = QHBoxLayout()
        self.new_button = QPushButton('새 대화')
        self.stop_button = QPushButton('중지')
        self.send_button = QPushButton('보내기')
        for button in (self.new_button, self.stop_button, self.send_button): row.addWidget(button)
        layout.addLayout(row)
        self.provider_selector.currentIndexChanged.connect(self._on_provider_combo_changed)
        self.connect_button.clicked.connect(self.connect_account)
        self.cli_login_button.clicked.connect(self.open_cli_login)
        self.refresh_button.clicked.connect(self.refresh_models)
        self.logout_button.clicked.connect(self.logout)
        self.send_button.clicked.connect(self.send)
        self.stop_button.clicked.connect(self.stop)
        self.new_button.clicked.connect(self.new_chat)
        if self.current_provider != 'chatgpt':
            idx = self.provider_selector.findData(self.current_provider)
            if idx >= 0:
                self.provider_selector.blockSignals(True)
                self.provider_selector.setCurrentIndex(idx)
                self.provider_selector.blockSignals(False)
            self.connect_button.setText(PROVIDER_CONNECT_LABELS.get(self.current_provider, '연결'))
            self.cli_login_button.setVisible(self.current_provider in ('gemini', 'antigravity_gemini'))
            self.notice.setText(PROVIDER_NOTICES.get(self.current_provider, PROVIDER_NOTICES['chatgpt']))
            self._restore_provider_models(self.current_provider)
            self._effort_model = self.models.currentData()
        self.refresh_controls()
    def select_provider(self, provider_code: str):
        if self.worker is not None or provider_code not in self.providers:
            return
        idx = self.provider_selector.findData(provider_code)
        if idx >= 0 and self.provider_selector.currentIndex() != idx:
            self.provider_selector.setCurrentIndex(idx)
            return
        if self.current_provider == provider_code:
            return
        self._provider_selected_model[self.current_provider] = self.models.currentData()
        self.current_provider = provider_code
        self.client = self.providers[provider_code]
        self.connect_button.setText(PROVIDER_CONNECT_LABELS.get(provider_code, '연결'))
        self.cli_login_button.setVisible(provider_code in ('gemini', 'antigravity_gemini'))
        self.notice.setText(PROVIDER_NOTICES.get(provider_code, PROVIDER_NOTICES['chatgpt']))
        self._restore_provider_models(provider_code)
        self.reasoning_effort.setCurrentIndex(0)
        self._effort_model = self.models.currentData()
        self.refresh_controls()
        self.provider_changed.emit(provider_code)
    def _on_provider_combo_changed(self):
        code = self.provider_selector.currentData()
        if code:
            self.select_provider(code)
    def _on_reply_limit_changed(self):
        self.max_reply_chars = self.reply_limit_selector.currentData()
        for p in self.providers.values():
            p.max_reply_chars = self.max_reply_chars
        self.render()
    def _restore_provider_models(self, provider_code: str):
        saved_models = self._provider_models.get(provider_code, [])
        selected = self._provider_selected_model.get(provider_code)
        self.models.blockSignals(True)
        self.models.clear()
        for model in saved_models:
            self.models.addItem(model['display_name'], model['slug'])
        if selected is not None:
            idx = self.models.findData(selected)
            if idx >= 0:
                self.models.setCurrentIndex(idx)
        self.models.blockSignals(False)
    def open_cli_login(self):
        opener = getattr(self.client, 'open_cli_login', None)
        if callable(opener):
            try:
                opener()
                self.status.setText('공식 CLI 로그인 창을 열었습니다. 로그인 완료 후 연결 버튼을 눌러 주세요.')
            except Exception as exc:
                from .chatgpt_client import ChatGPTError
                self.status.setText(str(exc) if isinstance(exc, ChatGPTError) else 'CLI 로그인 창을 열지 못했습니다.')
    def refresh_controls(self):
        info = self.client.session_info()
        busy = self.worker is not None
        connected = bool(info.get('connected') and info.get('sharing'))
        self.provider_selector.setEnabled(not busy)
        self.connect_button.setEnabled(not busy)
        self.cli_login_button.setEnabled(not busy)
        self.cli_login_button.setVisible(self.current_provider in ('gemini', 'antigravity_gemini'))
        self.refresh_button.setEnabled(connected and not busy)
        self.logout_button.setEnabled(bool(info.get('connected')) and not busy)
        self.models.setEnabled(not busy)
        if hasattr(self, 'reply_limit_selector'):
            self.reply_limit_selector.setEnabled(not busy)
        self.reasoning_effort.setEnabled(connected and self.models.count() > 0 and not busy)
        self.send_button.setEnabled(connected and self.models.count() > 0 and not busy)
        self.input.setEnabled(True)
        self.new_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        if not busy:
            if connected:
                if self.mock:
                    self.status.setText('모의 테스트 · 네트워크 사용 없음')
                elif self.current_provider == 'gemini':
                    self.status.setText('Gemini (로컬 CLI) · ' + (info.get('email') or '연결됨'))
                elif self.current_provider == 'antigravity_gemini':
                    self.status.setText('Antigravity Gemini · ' + (info.get('email') or '연결됨'))
                else:
                    self.status.setText('ChatGPT 구독 · ' + (info.get('email') or '연결됨'))
            else:
                if self.current_provider == 'gemini':
                    self.status.setText('연결 안 됨 · 로컬 Gemini CLI 연결 확인이 필요합니다.')
                elif self.current_provider == 'antigravity_gemini':
                    self.status.setText('연결 안 됨 · 로컬 Antigravity 연결 확인이 필요합니다.')
                else:
                    self.status.setText('연결 안 됨 · 구독 사용 권한이 필요합니다.')
    def start(self, name, action):
        if self.worker is not None: return
        self.operation = name
        self.worker = Operation(action)
        self.worker.delta.connect(self.on_delta)
        self.worker.result.connect(self.on_result)
        self.worker.failed.connect(self.on_failure)
        self.worker.finished.connect(self.on_finished)
        self.refresh_controls()
        signin_text = (
            '로컬 CLI 상태 확인 중…'
            if self.current_provider in ('gemini', 'antigravity_gemini')
            else '브라우저 로그인 대기 중…'
        )
        self.status.setText({'signin':signin_text, 'models':'사용 가능한 모델 확인 중…', 'chat':'후부키가 생각 중…', 'logout':'연결 해제 중…'}[name])
        self.worker.start()
    def connect_account(self):
        if not self.mock:
            if self.current_provider == 'chatgpt':
                answer = QMessageBox.question(self, 'ChatGPT 계정 연결', 'OpenAI의 공식 로그인 화면을 엽니다.\n이 앱이 계정 식별 정보와 ChatGPT 구독 사용 권한을 요청하고, 로그인 토큰을 이 PC에 암호화해 저장합니다.\n권한은 OpenAI 화면에서 직접 검토하고 승인하세요.\n\n계속할까요?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes: return
            elif self.current_provider == 'gemini':
                answer = QMessageBox.question(self, '로컬 Gemini CLI 연결', '이 PC에 설치된 공식 Gemini CLI(gemini)의 연결 상태를 확인합니다.\nAPI 키를 사용하지 않으며, 로컬 인증 파일이나 쿠키를 직접 추출하지 않습니다.\n\n계속할까요?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
                if answer != QMessageBox.StandardButton.Yes: return
            elif self.current_provider == 'antigravity_gemini':
                answer = QMessageBox.question(self, '로컬 Antigravity (Gemini) 연결', '이 PC에 설치된 공식 Antigravity CLI(agy)에서 Gemini 모델 목록과 연결 상태를 확인합니다.\nClaude 모델과 API 키는 사용하지 않습니다.\n\n계속할까요?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
                if answer != QMessageBox.StandardButton.Yes: return
        self.start('signin', lambda cancel, delta:self.client.sign_in(cancel))
    def refresh_models(self):
        self.start('models', lambda cancel, delta:self.client.list_models(cancel))
    def on_model_changed(self):
        model = self.models.currentData()
        self._provider_selected_model[self.current_provider] = model
        if model != self._effort_model:
            # An effort selected for one model is not evidence of another's support.
            self.reasoning_effort.setCurrentIndex(0)
            self._effort_model = model
        self.refresh_controls()
    def logout(self):
        self.start('logout', lambda cancel, delta:self.client.logout())
    def send(self):
        if self.worker is not None or not self.send_button.isEnabled(): return
        text = self.input.toPlainText().strip()
        if not text: return
        if len(text) > 4000:
            self.status.setText('한 번에 4,000자 이하로 입력해 주세요.'); return
        self.pending_user = text
        self.current_text = ''
        self.input.clear()
        self.render()
        messages = self.history[-12:] + [{'role':'user', 'content':text}]
        model = self.models.currentData()
        effort = self.reasoning_effort.currentData()
        self.state_changed.emit('thinking')
        options = {} if effort is None else {'reasoning_effort': effort}
        self.start('chat', lambda cancel, delta:self.client.stream_reply(messages, model, delta, cancel, **options))
    def on_delta(self, text):
        if self.worker is None or self.worker.cancel.is_set(): return
        self.current_text += text
        self.render()
    def render(self, footer=''):
        # Plain text rendering prevents model-supplied HTML and links from executing.
        lines=[]
        for item in self.history:
            lines.append(('나: ' if item['role']=='user' else '후부키: ') + item['content'])
        if self.pending_user:
            lines += ['나: '+self.pending_user, '후부키: '+self.current_text]
        if footer: lines.append(footer)
        self.transcript.setPlainText('\n\n'.join(lines))
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())
        self._transcript_rev = getattr(self, '_transcript_rev', 0) + 1
    def on_result(self, value):
        if self.operation == 'models':
            self._provider_models[self.current_provider] = list(value)
            previous_model = self.models.currentData()
            self.models.blockSignals(True)
            self.models.clear()
            for model in value: self.models.addItem(model['display_name'], model['slug'])
            previous_index = self.models.findData(previous_model)
            if previous_index >= 0: self.models.setCurrentIndex(previous_index)
            self.models.blockSignals(False)
            self.on_model_changed()
        elif self.operation == 'chat':
            self.history += [{'role':'user','content':self.pending_user}, {'role':'assistant','content':value}]
            self.history = self.history[-40:]
            self.pending_user = self.current_text = ''
            self.render()
            self.state_changed.emit('success')
        elif self.operation == 'logout':
            self._provider_models[self.current_provider] = []
            self._provider_selected_model[self.current_provider] = None
            self.models.clear(); self.history=[]; self.pending_user=self.current_text=''; self.render()
            self.status.setText(value.get('message','로그아웃했습니다.'))
    def on_failure(self, message):
        if self.operation == 'chat':
            self.render('\n[완료되지 않음] '+message)
            # Keep a failed/cancelled draft available for an explicit retry.
            if not self.input.toPlainText(): self.input.setPlainText(self.pending_user)
            self.pending_user = self.current_text = ''
            self.state_changed.emit('failed')
        self.status.setText(message)
        self.last_error = message
    def on_finished(self):
        operation = self.operation
        previous = self.status.text()
        worker = self.worker
        self.worker = None
        worker.deleteLater()
        self.refresh_controls()
        if hasattr(self, 'last_error'):
            self.status.setText(self.last_error); del self.last_error
        elif operation == 'logout': self.status.setText(previous)
        elif operation == 'models' and not self.models.count(): self.status.setText('사용 가능한 모델이 없습니다. 계정 권한을 확인해 주세요.')
        elif operation == 'signin' and self.client.session_info().get('sharing'): self.refresh_models()
    def stop(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.setText('중지 요청 중…')
    def new_chat(self):
        if self.worker is not None: return
        self.history=[]; self.pending_user=self.current_text=''; self.render()
    def closeEvent(self, event):
        self.stop()
        # Hide without destroying an in-flight worker; parent owns window lifetime.
        event.ignore(); self.hide()
    def shutdown(self):
        if self.worker:
            self.worker.cancel.set()
            return self.worker.wait(35000)
        return True
