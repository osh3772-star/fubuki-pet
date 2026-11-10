"""Offline reasoning selection tests. No real login, credentials, or inference."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from windows_pet.chatgpt_client import (
    ChatGPTClient, MockChatGPTClient, ChatGPTError, DIRECT, REASONING_EFFORTS,
    REASONING_REJECTED,
)
from windows_pet.chat_window import ChatWindow
from test_chatgpt_client import Response
from test_chat_ui import FakeClient


class ReasoningPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        protection = patch('windows_pet.chatgpt_client._dpapi', lambda data, decrypt=False: data)
        protection.start()
        self.addCleanup(protection.stop)
        self.client = ChatGPTClient(self.temp.name)
        self.client._record.update(subject='offline-test', access_token='fake-offline-token',
                                   scopes=[DIRECT], expires_at=time.time() + 3600)
        self.client._save()
        network = patch.object(self.client._http, 'request', return_value=Response(events=[
            {'type': 'response.output_text.delta', 'delta': 'offline response'},
            {'type': 'response.completed'},
        ]))
        self.http = network.start()
        self.addCleanup(network.stop)

    def send(self, **options):
        return self.client.stream_reply([{'role': 'user', 'content': 'offline test'}],
                                        'account-model', lambda text: None, **options)

    def test_default_omits_reasoning_instead_of_guessing_medium(self):
        self.send()
        payload = self.http.call_args.kwargs['json']
        self.assertNotIn('reasoning', payload)
        self.assertFalse(payload['store'])
        self.assertTrue(payload['stream'])
        self.assertNotIn('tools', payload)

    def test_each_documented_value_is_passed_exactly(self):
        for effort in REASONING_EFFORTS:
            with self.subTest(effort=effort):
                self.assertEqual(self.send(reasoning_effort=effort), 'offline response')
                payload = self.http.call_args.kwargs['json']
                self.assertEqual(payload['reasoning'], {'effort': effort})
                self.assertEqual(payload['model'], 'account-model')

    def test_none_string_is_an_explicit_setting(self):
        self.send(reasoning_effort='none')
        self.assertEqual(self.http.call_args.kwargs['json']['reasoning'], {'effort': 'none'})

    def test_invalid_effort_rejected_before_auth_or_network(self):
        with patch.object(self.client, '_access') as access:
            for invalid in ('ultra', 'auto', 'HIGH', '', True, 1, {}, ['high']):
                with self.subTest(value=invalid), self.assertRaises(ChatGPTError):
                    self.send(reasoning_effort=invalid)
            access.assert_not_called()
            self.http.assert_not_called()

    def test_http_unsupported_setting_is_sanitized_and_never_retried(self):
        response = Response({'error': {'param': 'reasoning.effort',
                                      'message': 'Unsupported fake-private-server-text'}})
        response.status_code = 400
        self.http.return_value = response
        with self.assertRaises(ChatGPTError) as caught:
            self.send(reasoning_effort='max')
        self.assertEqual(str(caught.exception), REASONING_REJECTED)
        self.assertNotIn('fake-private', str(caught.exception))
        self.assertEqual(self.http.call_count, 1)

    def test_generic_rejection_does_not_claim_a_specific_parameter_cause(self):
        response = Response({'error': {'param': 'input', 'message': 'private details'}})
        response.status_code = 422
        self.http.return_value = response
        with self.assertRaises(ChatGPTError) as caught:
            self.send(reasoning_effort='high')
        self.assertIn('요청 설정을 거부', str(caught.exception))
        self.assertNotIn('private', str(caught.exception))
        self.assertEqual(self.http.call_count, 1)

    def test_malformed_error_body_keeps_safe_recovery(self):
        response = Response()
        response.status_code = 400
        self.http.return_value = response
        with patch.object(response, 'json', side_effect=ValueError('private body')):
            with self.assertRaises(ChatGPTError) as caught:
                self.send(reasoning_effort='high')
        self.assertIn('서버 기본값', str(caught.exception))
        self.assertNotIn('private', str(caught.exception))

    def test_401_and_429_keep_auth_and_usage_errors(self):
        for status, expected in ((401, '로그인'), (429, '사용량 한도')):
            with self.subTest(status=status):
                response = Response({'error': {'param': 'reasoning.effort'}})
                response.status_code = status
                self.http.return_value = response
                with self.assertRaises(ChatGPTError) as caught:
                    self.send(reasoning_effort='high')
                self.assertIn(expected, str(caught.exception))

    def test_stream_parameter_errors_are_sanitized(self):
        for event in (
            {'type': 'error', 'param': 'reasoning.effort', 'message': 'private'},
            {'type': 'response.failed', 'response': {'error': {
                'param': 'reasoning', 'message': 'private'}}},
            {'type': 'error', 'error': {'message': 'Unsupported reasoning effort. private'}},
        ):
            with self.subTest(event=event):
                self.http.return_value = Response(events=[event])
                with self.assertRaises(ChatGPTError) as caught:
                    self.send(reasoning_effort='high')
                self.assertEqual(str(caught.exception), REASONING_REJECTED)

    def test_catalog_does_not_fabricate_effort_support(self):
        self.http.return_value = Response({'models': [
            {'slug': 'future-model', 'display_name': 'Future', 'visibility': 'list'}]})
        self.assertEqual(self.client.list_models(), [{'slug': 'future-model', 'display_name': 'Future'}])

    def test_mock_accepts_effort_without_real_inference(self):
        client = MockChatGPTClient()
        client.sign_in()
        with patch('windows_pet.chatgpt_client.requests.Session.request', side_effect=AssertionError('network')):
            with patch('windows_pet.chatgpt_client.time.sleep'):
                self.assertIn('오프라인 데모', client.stream_reply([], 'offline-demo', lambda x: None,
                                                               reasoning_effort='xhigh'))


class RecordingClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.efforts = []
        self.fail_next = False

    def stream_reply(self, messages, model, on_delta, cancel, *, reasoning_effort=None):
        self.efforts.append(reasoning_effort)
        if self.fail_next:
            self.fail_next = False
            self.calls += 1
            raise ChatGPTError(REASONING_REJECTED)
        return super().stream_reply(messages, model, on_delta, cancel)


class ReasoningUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.client = RecordingClient()
        self.window = ChatWindow(Path('.'), True, self.client)

    def tearDown(self):
        self.window.shutdown()
        self.window.deleteLater()
        self.app.processEvents()

    def wait(self):
        deadline = time.monotonic() + 5
        while self.window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertIsNone(self.window.worker)

    def connect(self):
        self.window.connect_account()
        self.wait()

    def select(self, value):
        self.window.reasoning_effort.setCurrentIndex(self.window.reasoning_effort.findData(value))

    def test_starts_at_server_default_and_disabled_until_connected(self):
        self.assertIsNone(self.window.reasoning_effort.currentData())
        self.assertFalse(self.window.reasoning_effort.isEnabled())
        self.assertEqual(self.window.reasoning_effort.count(), len(REASONING_EFFORTS) + 1)
        self.assertIn('모델마다 지원 단계가 다릅니다', self.window.reasoning_note.text())
        self.connect()
        self.assertTrue(self.window.reasoning_effort.isEnabled())

    def test_selected_value_used_busy_controls_locked_and_repeat_send_ignored(self):
        self.connect()
        self.select('xhigh')
        self.client.slow = True
        self.window.input.setPlainText('안녕')
        self.window.send()
        self.assertFalse(self.window.reasoning_effort.isEnabled())
        self.assertFalse(self.window.models.isEnabled())
        self.window.send()
        self.wait()
        self.assertEqual(self.client.efforts, ['xhigh'])
        self.assertEqual(self.client.calls, 1)
        self.assertTrue(self.window.reasoning_effort.isEnabled())

    def test_default_is_not_an_explicit_medium(self):
        self.connect()
        self.window.input.setPlainText('안녕')
        self.window.send()
        self.wait()
        self.assertEqual(self.client.efforts, [None])

    def test_model_change_resets_to_server_default(self):
        self.connect()
        self.select('high')
        self.window.models.addItem('Other model', 'other')
        self.window.models.setCurrentIndex(1)
        self.assertIsNone(self.window.reasoning_effort.currentData())

    def test_refresh_of_same_model_preserves_effort(self):
        self.connect()
        self.select('high')
        self.window.refresh_models()
        self.wait()
        self.assertEqual(self.window.reasoning_effort.currentData(), 'high')

    def test_failed_setting_preserves_draft_no_retry_then_explicit_default_retry(self):
        self.connect()
        self.select('max')
        self.client.fail_next = True
        self.window.input.setPlainText('다시 보낼 문장')
        self.window.send()
        self.wait()
        self.assertEqual(self.client.calls, 1)
        self.assertEqual(self.window.input.toPlainText(), '다시 보낼 문장')
        self.assertEqual(self.window.history, [])
        self.assertIn('서버 기본값', self.window.status.text())
        self.assertEqual(self.window.reasoning_effort.currentData(), 'max')
        self.select(None)
        self.window.send()
        self.wait()
        self.assertEqual(self.client.efforts, ['max', None])
        self.assertEqual(len(self.window.history), 2)

    def test_logout_clears_selection_and_disables_effort(self):
        self.connect()
        self.select('high')
        self.window.logout()
        self.wait()
        self.assertIsNone(self.window.reasoning_effort.currentData())
        self.assertFalse(self.window.reasoning_effort.isEnabled())

    def test_close_and_cancel_restores_draft_without_committing(self):
        self.connect()
        self.select('high')
        self.client.slow = True
        self.window.input.setPlainText('취소한 문장')
        self.window.send()
        self.window.close()
        self.wait()
        self.assertEqual(self.window.input.toPlainText(), '취소한 문장')
        self.assertEqual(self.window.history, [])
        self.assertTrue(self.window.reasoning_effort.isEnabled())


if __name__ == '__main__':
    unittest.main()
