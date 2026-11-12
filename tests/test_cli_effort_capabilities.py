"""Mocked capability discovery and safe local effort settings regressions."""
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from windows_pet import claude_cli_client as claude
from windows_pet import local_cli_clients as cli
from windows_pet.chatgpt_client import Cancelled, ChatGPTError, REASONING_EFFORTS


class RecordedInput(io.StringIO):
    def close(self):
        self.sent = self.getvalue()
        super().close()


class BlockingOutput:
    def __init__(self, stop):
        self.stop = stop
        self.closed = False

    def readline(self, limit):
        self.stop.wait(5)
        return ''

    def close(self):
        self.closed = True


class ProbeProcess:
    def __init__(self, events=(), *, silent=False):
        self.pid = 99999
        self.returncode = None
        self.stopped = threading.Event()
        self.stdin = RecordedInput()
        self.stdout = (BlockingOutput(self.stopped) if silent else
                       io.StringIO('\n'.join(json.dumps(event) for event in events) + '\n'))
        self.stderr = io.StringIO('private diagnostics' * 10000)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self.stopped.set()

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        return self.returncode


def control_response(models, request_id='probe-id', subtype='success'):
    return {'type': 'control_response', 'response': {
        'subtype': subtype, 'request_id': request_id, 'response': {'models': models}}}


class ClaudeCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = claude.ClaudeCLIClient(self.temp.name)
        self.client._connected = True
        self.finder = patch.object(claude, '_find_claude_command', return_value=['claude'])
        self.finder.start()
        self.addCleanup(self.finder.stop)
        self.request_id = patch.object(claude.uuid, 'uuid4', return_value=SimpleNamespace(hex='probe-id'))
        self.request_id.start()
        self.addCleanup(self.request_id.stop)

    def test_probe_sends_only_initialize_and_uses_official_per_alias_metadata(self):
        rows = [{'value': 'sonnet', 'resolvedModel': 'claude-sonnet-4-6',
                 'supportsEffort': True, 'supportedEffortLevels': ['high', 'low']},
                {'value': 'haiku', 'supportsEffort': False},
                {'value': 'opus', 'supportsEffort': True,
                 'supportedEffortLevels': ['low', 'medium', 'high', 'xhigh', 'max']}]
        proc = ProbeProcess([control_response([], request_id='unrelated'), control_response(rows)])
        with patch.object(claude.subprocess, 'Popen', return_value=proc) as popen:
            result = self.client._probe_model_efforts()
        self.assertEqual(result, {'sonnet': ('low', 'high'), 'haiku': (),
                                  'opus': ('low', 'medium', 'high', 'xhigh', 'max')})
        sent = [json.loads(line) for line in proc.stdin.sent.splitlines()]
        self.assertEqual(sent, [{'type': 'control_request', 'request_id': 'probe-id',
                                 'request': {'subtype': 'initialize', 'hooks': None}}])
        cmd = popen.call_args.args[0]
        for flag in ('--safe-mode', '--strict-mcp-config', '--disable-slash-commands',
                     '--no-chrome', '--no-session-persistence', '--verbose'):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index('--tools') + 1], '')
        self.assertEqual(cmd[cmd.index('--disallowedTools') + 1], '*')
        self.assertEqual(cmd[cmd.index('--input-format') + 1], 'stream-json')
        self.assertEqual(cmd[cmd.index('--output-format') + 1], 'stream-json')
        self.assertTrue(proc.stopped.is_set())
        self.assertTrue(all(pipe.closed for pipe in (proc.stdin, proc.stdout, proc.stderr)))

    def test_untrusted_or_incomplete_capabilities_never_infer_support(self):
        rows = [{'value': 'sonnet', 'supportedEffortLevels': ['high']},
                {'value': 'opus', 'supportsEffort': True, 'supportedEffortLevels': ['surprise']},
                {'value': 'haiku', 'supportsEffort': True, 'supportedEffortLevels': 'high'},
                {'value': 'auto', 'supportsEffort': True, 'supportedEffortLevels': ['high']},
                {'value': 'claude-opus-5-5', 'supportsEffort': True, 'supportedEffortLevels': ['max']}]
        self.assertEqual(claude._parse_claude_model_efforts(rows), {})
        self.assertEqual(claude._parse_claude_model_efforts({'value': 'sonnet'}), {})
        self.assertEqual(claude._parse_claude_model_efforts([
            {'value': 'sonnet', 'supportsEffort': True, 'supportedEffortLevels': ['high']},
            {'value': 'sonnet', 'supportsEffort': True, 'supportedEffortLevels': ['low']}]), {})

    def test_protocol_failure_and_eof_fall_back_without_disconnect(self):
        for events in ([], [control_response([], subtype='error')],
                       [{'type': 'result', 'result': 'not control metadata'}]):
            with self.subTest(events=events):
                proc = ProbeProcess(events)
                with patch.object(claude.subprocess, 'Popen', return_value=proc):
                    self.assertEqual(self.client._probe_model_efforts(), {})
                self.assertTrue(self.client.session_info()['connected'])
                self.assertTrue(proc.stopped.is_set())

    def test_silent_probe_timeout_is_bounded(self):
        proc = ProbeProcess(silent=True)
        start = time.monotonic()
        with patch.object(claude, '_CLAUDE_CAPABILITY_TIMEOUT', 0.03), \
                patch.object(claude.subprocess, 'Popen', return_value=proc):
            self.assertEqual(self.client._probe_model_efforts(), {})
        self.assertLess(time.monotonic() - start, 2)
        self.assertTrue(proc.stopped.is_set())

    def test_silent_probe_stop_cleans_child(self):
        proc = ProbeProcess(silent=True)
        cancel = threading.Event()
        timer = threading.Timer(0.03, cancel.set)
        timer.start()
        try:
            with patch.object(claude.subprocess, 'Popen', return_value=proc):
                with self.assertRaises(Cancelled):
                    self.client._probe_model_efforts(cancel)
        finally:
            timer.cancel()
            timer.join()
        self.assertTrue(proc.stopped.is_set())

    def test_refresh_invalidates_old_capabilities_and_default_remains_unknown(self):
        self.client._model_efforts = {'sonnet': ('high',), 'auto': ('high',)}
        self.assertEqual(self.client.supported_reasoning_efforts('sonnet'), ('high',))
        self.assertIsNone(self.client.supported_reasoning_efforts('auto'))
        with patch.object(self.client, '_auth_status'), \
                patch.object(self.client, '_probe_model_efforts', return_value={}):
            self.client.list_models(force_refresh=True)
        self.assertIsNone(self.client.supported_reasoning_efforts('sonnet'))
        self.client._model_efforts = {'sonnet': ('high',)}
        self.client.logout()
        self.assertEqual(self.client._model_efforts, {})
        self.assertIsNone(self.client.supported_reasoning_efforts('sonnet'))

    def test_metadata_failure_does_not_undo_successful_subscription_auth(self):
        with patch.object(self.client, '_auth_status'), \
                patch.object(self.client, '_probe_model_efforts', return_value={}):
            self.assertTrue(self.client.sign_in()['connected'])
        self.assertIsNone(self.client.supported_reasoning_efforts('sonnet'))


class LocalEffortConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = cli.GeminiCLIClient(self.temp.name)
        self.client._connected = True
        self.settings_file = self.client.workspace_dir / '.gemini' / 'settings.json'

    def write_settings(self, settings):
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text(json.dumps(settings), encoding='utf-8')

    def read_settings(self):
        return json.loads(self.settings_file.read_text(encoding='utf-8'))

    def test_unknown_runtime_config_and_model_names_are_default_only(self):
        clients = [self.client, cli.AntigravityGeminiClient(self.temp.name),
                   *[cli.MockLocalCLIClient(provider) for provider in
                     ('gemini', 'antigravity_gemini', 'claude')]]
        with patch.object(cli.subprocess, 'Popen') as popen, patch.object(cli.subprocess, 'run') as run:
            for client in clients:
                for model in ('auto', 'gemini-3.1-pro-preview', 'gemini-4-argon-high', 'sonnet'):
                    with self.subTest(client=type(client).__name__, model=model):
                        self.assertIsNone(client.supported_reasoning_efforts(model))
                        for effort in REASONING_EFFORTS:
                            with self.assertRaises(ChatGPTError):
                                client.stream_reply([], model, lambda _: None, reasoning_effort=effort)
            popen.assert_not_called()
            run.assert_not_called()

    def test_exact_models_use_documented_level_or_budget_not_global_aliases(self):
        for model in cli._GEMINI_THINKING_LEVEL_MODELS | cli._GEMINI_THINKING_BUDGET_MODELS:
            for effort in ('low', 'high'):
                with self.subTest(model=model, effort=effort):
                    self.client._configure_workspace_effort(model, effort)
                    config = self.read_settings()['modelConfigs']
                    override = config['customOverrides'][0]
                    self.assertEqual(override['match'], {'model': model})
                    thinking = override['modelConfig']['generateContentConfig']['thinkingConfig']
                    expected = ({'thinkingBudget': 1024 if effort == 'low' else 24576}
                                if model == 'gemini-2.5-pro' else {'thinkingLevel': effort.upper()})
                    self.assertEqual(thinking, expected)
                    self.assertNotIn('customAliases', config)
        self.assertIsNone(cli._gemini_reasoning_efforts('auto'))
        self.assertIsNone(cli._gemini_reasoning_efforts('gemini-99-future'))
        with self.assertRaises(ValueError):
            cli._gemini_effort_config('gemini-99-future', 'low')

    def test_default_removes_only_owned_override_and_keeps_unrelated_settings(self):
        original = {'ui': {'theme': 'custom'}, 'other': {'value': [1, 2]}}
        self.write_settings(original)
        self.client._configure_workspace_effort('gemini-3.1-pro-preview', 'low')
        self.client._configure_workspace_effort('auto', None)
        self.assertEqual(self.read_settings(), original)

    def test_unknown_model_config_preserved_and_explicit_effort_rejected(self):
        original = {'ui': {'theme': 'custom'}, 'modelConfigs': {'customOverrides': [
            {'match': {'model': 'my-model'}, 'modelConfig': {'temperature': 0.5}}]}}
        self.write_settings(original)
        before = self.settings_file.read_bytes()
        with self.assertRaisesRegex(ChatGPTError, '충돌'):
            self.client._configure_workspace_effort('gemini-3.1-pro-preview', 'low')
        self.client._configure_workspace_effort('auto', None)
        self.assertEqual(self.settings_file.read_bytes(), before)

    def test_known_legacy_payload_migrates_without_removing_other_settings(self):
        legacy = {'customAliases': {
            'chat-base-3': {'extends': 'chat-base', 'modelConfig': {
                'generateContentConfig': {'thinkingConfig': {'thinkingLevel': 'LOW'}}}},
            'chat-base-2.5': {'extends': 'chat-base', 'modelConfig': {
                'generateContentConfig': {'thinkingConfig': {'thinkingBudget': 1024}}}}}}
        self.write_settings({'ui': {'theme': 'custom'}, 'modelConfigs': legacy})
        self.client._configure_workspace_effort('gemini-2.5-pro', 'high')
        self.assertEqual(self.read_settings()['ui'], {'theme': 'custom'})
        self.assertIn('customOverrides', self.read_settings()['modelConfigs'])

    def test_write_failure_does_not_cache_success_or_skip_next_attempt(self):
        self.write_settings({'ui': {'theme': 'custom'}})
        before = self.settings_file.read_bytes()
        with patch.object(cli.os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(ChatGPTError):
                self.client._configure_workspace_effort('gemini-3.1-pro-preview', 'low')
        self.assertEqual(self.settings_file.read_bytes(), before)
        self.assertEqual(list(self.settings_file.parent.glob('.settings-*.tmp')), [])
        self.client._configure_workspace_effort('gemini-3.1-pro-preview', 'low')
        self.assertEqual(self.read_settings()['modelConfigs'],
                         cli._gemini_effort_config('gemini-3.1-pro-preview', 'low'))

    def test_malformed_config_preserved_without_cli_invocation(self):
        self.settings_file.parent.mkdir(parents=True)
        self.settings_file.write_text('{broken', encoding='utf-8')
        with patch.object(self.client, 'supported_reasoning_efforts', return_value=('low',)), \
                patch.object(cli.subprocess, 'Popen') as popen:
            with self.assertRaises(ChatGPTError):
                self.client.stream_reply([], 'gemini-3.1-pro-preview', lambda _: None,
                                         reasoning_effort='low')
        self.assertEqual(self.settings_file.read_text(encoding='utf-8'), '{broken')
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
