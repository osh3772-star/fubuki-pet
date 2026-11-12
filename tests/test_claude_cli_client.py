import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

from windows_pet.claude_cli_client import ClaudeCLIClient, _claude_env
from windows_pet.chatgpt_client import ChatGPTError, Cancelled


class ClaudeClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = ClaudeCLIClient(self.tmp.name)
        self.finder = patch('windows_pet.claude_cli_client._find_claude_command', return_value=['claude'])
        self.finder.start()
        self.addCleanup(self.finder.stop)

    def auth(self, method='claude.ai', logged=True):
        return subprocess.CompletedProcess([], 0, json.dumps({'loggedIn': logged, 'authMethod': method}), '')

    def test_subscription_auth_without_inference(self):
        with patch('windows_pet.claude_cli_client.subprocess.run', return_value=self.auth()) as run:
            self.assertTrue(self.client.sign_in()['connected'])
            self.assertEqual(run.call_args.args[0], ['claude', 'auth', 'status'])
            self.assertEqual(len(self.client.list_models()), 4)

    def test_api_key_token_and_logged_out_rejected(self):
        for method in ['api_key', 'api_key_helper', 'oauth_token', 'third_party', 'none']:
            with self.subTest(method=method), patch('windows_pet.claude_cli_client.subprocess.run', return_value=self.auth(method)):
                with self.assertRaises(ChatGPTError): self.client.sign_in()
                self.assertFalse(self.client.session_info()['connected'])

    def test_env_drops_billing_and_endpoint_overrides(self):
        values = {key: 'do-not-use' for key in ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CONFIG_DIR']}
        with patch.dict(os.environ, values):
            env = _claude_env()
        for key in values: self.assertNotIn(key, env)

    def test_safe_text_reply_and_nonstreaming_callback(self):
        self.client._connected = True
        proc = MagicMock()
        proc.communicate.return_value = (json.dumps({'type':'result', 'subtype':'success', 'is_error':False, 'result':'안녕!'}), '')
        proc.returncode = 0
        proc.poll.return_value = 0
        deltas = []
        with patch('windows_pet.claude_cli_client.subprocess.run', return_value=self.auth()), patch('windows_pet.claude_cli_client.subprocess.Popen', return_value=proc) as popen:
            self.assertEqual(self.client.stream_reply([{'role':'user','content':'hi'}], 'sonnet', deltas.append), '안녕!')
        cmd = popen.call_args.args[0]
        for flag in ['--safe-mode','--no-session-persistence','--strict-mcp-config','--disable-slash-commands','--no-chrome']: self.assertIn(flag,cmd)
        self.assertEqual(cmd[cmd.index('--tools')+1], '')
        self.assertEqual(cmd[cmd.index('--disallowedTools')+1], '*')
        self.assertNotIn('--dangerously-skip-permissions',cmd)
        self.assertNotIn('hi',cmd)
        self.assertEqual(deltas,['안녕!'])

    def test_failure_not_displayed_as_success(self):
        self.client._connected = True
        proc = MagicMock()
        proc.communicate.return_value = ('private raw error text', '')
        proc.returncode = 1
        proc.poll.return_value = 1
        with patch('windows_pet.claude_cli_client.subprocess.run', return_value=self.auth()), patch('windows_pet.claude_cli_client.subprocess.Popen', return_value=proc):
            with self.assertRaises(ChatGPTError) as error: self.client.stream_reply([{'role':'user','content':'hi'}], 'auto', lambda _: None)
        self.assertNotIn('private', str(error.exception))

    def test_cancel_before_auth(self):
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(Cancelled): self.client.sign_in(cancel)

    def test_cancel_quiet_child(self):
        self.client._connected = True
        cancel = threading.Event()
        proc = MagicMock()
        def wait(**kwargs):
            cancel.set()
            raise subprocess.TimeoutExpired('claude', 0.2)
        proc.communicate.side_effect = wait
        proc.poll.return_value = None
        with patch('windows_pet.claude_cli_client.subprocess.run', return_value=self.auth()), patch('windows_pet.claude_cli_client.subprocess.Popen', return_value=proc):
            with self.assertRaises(Cancelled): self.client.stream_reply([{'role':'user','content':'hi'}], 'auto', lambda _: None, cancel)
        proc.terminate.assert_called_once()

    def test_logout_does_not_revoke_cli_session(self):
        self.client._connected = True
        with patch('windows_pet.claude_cli_client.subprocess.run') as run:
            self.assertFalse(self.client.logout()['revoked'])
            run.assert_not_called()
        self.assertFalse(self.client.session_info()['connected'])

    def test_invalid_model_or_effort_does_not_invoke(self):
        self.client._connected = True
        with patch('windows_pet.claude_cli_client.subprocess.run') as run:
            for model, effort in [('gpt-5',None),('auto','minimal')]:
                with self.assertRaises(ChatGPTError): self.client.stream_reply([], model, lambda _:None, reasoning_effort=effort)
            run.assert_not_called()

if __name__ == '__main__': unittest.main()
