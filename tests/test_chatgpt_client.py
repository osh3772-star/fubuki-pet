"""Offline tests. All HTTP/browser access is stubbed; no real OAuth grants."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from windows_pet.chatgpt_client import (ChatGPTClient, MockChatGPTClient,
    ChatGPTError, Cancelled, DIRECT, ISSUER, _dpapi)


class Response:
    status_code = 200
    def __init__(self, data=None, events=None):
        self.data = data
        self.events = events or []
    def json(self):
        return self.data
    def close(self):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()
    def iter_lines(self, **kwargs):
        for e in self.events:
            yield ('data: ' + json.dumps(e)).encode()
            yield b''


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.protect = patch('windows_pet.chatgpt_client._dpapi', lambda d, decrypt=False: d)
        self.protect.start()
        self.client = ChatGPTClient(self.temp.name)
        self.network = patch.object(self.client._http, 'request', side_effect=AssertionError('Unexpected network'))
        self.http = self.network.start()
    def tearDown(self):
        self.network.stop()
        self.protect.stop()
        self.temp.cleanup()
    def connect(self, expires=3600):
        self.client._record.update(subject='user-1', client_id='oaiapp_test',
            access_token='secret-access', refresh_token='secret-refresh', id_token='secret-id',
            scopes=[DIRECT], expires_at=time.time()+expires, email='a@example.invalid')
        self.client._save()
    def test_session_info_never_exposes_credentials(self):
        self.connect()
        info = self.client.session_info()
        self.assertTrue(info['connected'])
        self.assertTrue(info['sharing'])
        self.assertNotIn('secret', json.dumps(info))
    def test_models_uses_account_catalog(self):
        self.connect()
        self.http.side_effect = None
        self.http.return_value = Response({'models': [
            {'slug':'b','display_name':'B','visibility':'list'},
            {'slug':'hidden','visibility':'hide'}, {'slug':'a','visibility':'list'}]})
        self.assertEqual(self.client.list_models(), [
            {'slug':'b','display_name':'B'}, {'slug':'a','display_name':'a'}])
    def test_refresh_rotates_and_persists(self):
        self.connect(-1)
        self.http.side_effect = None
        self.http.return_value = Response({'access_token':'new-access','refresh_token':'new-refresh',
            'scope':DIRECT, 'token_type':'Bearer','expires_in':3600})
        self.assertEqual(self.client._access(None), 'new-access')
        self.assertEqual(self.client._record['refresh_token'], 'new-refresh')
        sent = self.http.call_args.kwargs['data']
        self.assertNotIn('scope', sent)
        self.assertEqual(sent['client_id'], 'oaiapp_test')
        self.assertEqual(ChatGPTClient(self.temp.name)._record['refresh_token'], 'new-refresh')
    def test_cancel_during_refresh_keeps_rotated_credentials(self):
        self.connect(-1)
        cancel = threading.Event()
        def refreshed(*args, **kwargs):
            cancel.set()
            return Response({'access_token':'rotated','refresh_token':'replacement',
                'scope':DIRECT,'token_type':'Bearer','expires_in':3600})
        self.http.side_effect = refreshed
        with self.assertRaises(Cancelled):
            self.client.list_models(cancel)
        self.assertEqual(ChatGPTClient(self.temp.name)._record['refresh_token'], 'replacement')
    def test_stream_requires_completed(self):
        self.connect()
        self.http.side_effect = None
        self.http.return_value = Response(events=[{'type':'response.output_text.delta','delta':'안녕'}])
        with self.assertRaises(ChatGPTError):
            self.client.stream_reply([{'role':'user','content':'hello'}], 'test', lambda d: None)
    def test_stream_success_and_safe_payload(self):
        self.connect()
        self.http.side_effect = None
        self.http.return_value = Response(events=[{'type':'response.output_text.delta','delta':'hello'},
                                                 {'type':'response.completed'}])
        out = []
        self.assertEqual(self.client.stream_reply([{'role':'user','content':'hey'}], 'test', out.append), 'hello')
        payload = self.http.call_args.kwargs['json']
        self.assertFalse(payload['store'])
        self.assertTrue(payload['stream'])
        self.assertNotIn('tools', payload)
        self.assertIn('한국어', payload['instructions'])
        self.assertEqual(out, ['hello'])
    def test_system_message_rejected(self):
        self.connect()
        with self.assertRaises(ChatGPTError):
            self.client.stream_reply([{'role':'system','content':'test'}], 'test', lambda d: None)
        self.http.assert_not_called()
    def test_oversized_history_rejected(self):
        self.connect()
        with self.assertRaises(ChatGPTError):
            self.client.stream_reply([{'role':'user','content':'x'*60001}], 'test', lambda d: None)
        self.http.assert_not_called()
    def test_oversized_reply_rejected(self):
        self.connect()
        self.http.side_effect = None
        self.http.return_value = Response(events=[{'type':'response.output_text.delta','delta':'x'*20001},
                                                 {'type':'response.completed'}])
        with self.assertRaises(ChatGPTError):
            self.client.stream_reply([], 'test', lambda d: None)
    def test_midstream_failure_is_not_success(self):
        self.connect()
        self.http.side_effect = None
        self.http.return_value = Response(events=[{'type':'response.output_text.delta','delta':'partial'},
                                                 {'type':'response.failed'}])
        with self.assertRaises(ChatGPTError):
            self.client.stream_reply([], 'test', lambda d: None)
    def test_cancel_no_network(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            self.client.sign_in(event)
        self.http.assert_not_called()
    def test_no_permission_no_inference(self):
        self.connect()
        self.client._record['scopes'] = []
        self.client._save()
        with self.assertRaises(ChatGPTError):
            self.client.stream_reply([], 'test', lambda d: None)
        self.http.assert_not_called()
    def test_logout_clears_tokens_preserves_registration(self):
        self.connect()
        self.http.side_effect = None
        self.http.return_value = Response()
        self.assertTrue(self.client.logout()['revoked'])
        self.assertEqual(self.client._record['client_id'], 'oaiapp_test')
        self.assertNotIn('access_token', self.client._record)
        self.assertNotIn('id_token', self.client._record)
        self.assertFalse(self.client.session_info()['connected'])
    def test_id_token_signature_and_nonce(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk['kid'] = 'test-key'
        now = int(time.time())
        claims = dict(iss=ISSUER, aud='oaiapp_test', sub='u', exp=now+100, iat=now, nonce='expected')
        token = jwt.encode(claims, key, algorithm='RS256', headers={'kid':'test-key'})
        self.http.side_effect = None
        self.http.return_value = Response({'keys':[jwk]})
        self.assertEqual(self.client._verify_identity(token, 'oaiapp_test', 'expected', None)['sub'], 'u')
        for audience, nonce in [('wrong', 'expected'), ('oaiapp_test', 'wrong')]:
            with self.assertRaises(ChatGPTError):
                self.client._verify_identity(token, audience, nonce, None)
    def test_mock_never_uses_network(self):
        mock = MockChatGPTClient()
        self.assertTrue(mock.sign_in()['mock'])
        self.assertTrue(mock.list_models())
        parts = []
        with patch('windows_pet.chatgpt_client.time.sleep'):
            text = mock.stream_reply([], 'offline-demo', parts.append)
        self.assertEqual(text, ''.join(parts))
        mock.logout()
        self.assertFalse(mock.session_info()['connected'])


class DPAPITests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_real_dpapi_roundtrip_no_plaintext(self):
        plaintext = b'offline-test-not-a-real-credential'
        encrypted = _dpapi(plaintext)
        self.assertNotIn(plaintext, encrypted)
        self.assertEqual(_dpapi(encrypted, True), plaintext)


if __name__ == '__main__':
    unittest.main()
