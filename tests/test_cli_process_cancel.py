"""Real, offline Python subprocess regressions for local CLI pipe handling."""
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from windows_pet import local_cli_clients as cli
from windows_pet.chatgpt_client import Cancelled, ChatGPTError


class CLIProcessCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.processes = []
        self.addCleanup(self.cleanup_processes)

    def cleanup_processes(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=3)

    def invoke(self, provider, script, *, cancel=None, timeout=3, text='hello', callback=None):
        cls = cli.GeminiCLIClient if provider == 'gemini' else cli.AntigravityGeminiClient
        client = cls(self.temp.name)
        client._connected = True
        real_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            self.processes.append(proc)
            return proc

        finder = '_find_gemini_cli_command' if provider == 'gemini' else '_find_antigravity_cli_command'
        with patch.object(cli, finder, return_value=[sys.executable, '-u', '-c', script]), \
                patch.object(cli, 'CLI_REPLY_TIMEOUT', timeout), \
                patch.object(cli.subprocess, 'Popen', side_effect=spawn):
            return client.stream_reply([{'role': 'user', 'content': text}],
                                       'auto' if provider == 'gemini' else 'gemini-test',
                                       callback or (lambda delta: None), cancel)

    def events(self, provider):
        if provider == 'gemini':
            return [{'type': 'message', 'role': 'assistant', 'content': '안녕'},
                    {'type': 'message', 'role': 'assistant', 'content': '하세요'},
                    {'type': 'result', 'status': 'success'}]
        return [{'event': 'step_update', 'step_update': {'step_type': 'agent_response', 'text_delta': '안녕'}},
                {'event': 'step_update', 'step_update': {'step_type': 'agent_response', 'text_delta': '하세요'}},
                {'event': 'result', 'result': {'status': 'SUCCESS'}}]

    def output_script(self, provider):
        lines = [json.dumps(event, ensure_ascii=False) for event in self.events(provider)]
        return 'import sys,time\n' + '\n'.join('print(' + repr(line) + ', flush=True); time.sleep(0.05)' for line in lines)

    def assert_clean(self):
        self.assertTrue(all(proc.poll() is not None for proc in self.processes))
        self.assertTrue(all(pipe is None or pipe.closed for proc in self.processes
                            for pipe in (proc.stdin, proc.stdout, proc.stderr)))

    def test_silent_process_stop_including_blocked_stdin(self):
        for provider in ('gemini', 'antigravity'):
            with self.subTest(provider=provider):
                cancel = threading.Event()
                timer = threading.Timer(0.2, cancel.set)
                timer.start()
                start = time.monotonic()
                try:
                    with self.assertRaises(Cancelled):
                        self.invoke(provider, 'import time; time.sleep(30)', cancel=cancel, text='x' * 59000)
                finally:
                    timer.cancel()
                    timer.join()
                self.assertLess(time.monotonic() - start, 3)
                self.assert_clean()

    def test_partial_line_and_silence_time_out(self):
        for provider in ('gemini', 'antigravity'):
            with self.subTest(provider=provider):
                start = time.monotonic()
                with self.assertRaisesRegex(ChatGPTError, '제한 시간'):
                    self.invoke(provider, "import sys,time; sys.stdout.write('{'); sys.stdout.flush(); time.sleep(30)", timeout=0.2)
                self.assertLess(time.monotonic() - start, 3)
                self.assert_clean()

    def test_stderr_flood_does_not_deadlock_or_reach_callback(self):
        for provider in ('gemini', 'antigravity'):
            with self.subTest(provider=provider):
                deltas = []
                script = "import sys; sys.stderr.write('PRIVATE_DIAGNOSTIC' * 150000); sys.stderr.flush()\n" + self.output_script(provider)
                self.assertEqual(self.invoke(provider, script, callback=deltas.append), '안녕하세요')
                self.assertEqual(deltas, ['안녕', '하세요'])
                self.assert_clean()

    def test_streaming_is_incremental_and_stop_after_delta_works(self):
        for provider in ('gemini', 'antigravity'):
            with self.subTest(provider=provider):
                cancel = threading.Event()
                deltas = []
                first = json.dumps(self.events(provider)[0])
                script = f'import time; print({first!r}, flush=True); time.sleep(30)'

                def on_delta(delta):
                    deltas.append(delta)
                    cancel.set()

                with self.assertRaises(Cancelled):
                    self.invoke(provider, script, cancel=cancel, callback=on_delta)
                self.assertEqual(deltas, ['안녕'])
                self.assert_clean()

    def test_stop_while_waiting_after_final_result_or_stdout_eof(self):
        for provider in ('gemini', 'antigravity'):
            for prefix in (self.output_script(provider), 'import os; os.close(1)'):
                with self.subTest(provider=provider, prefix=prefix):
                    cancel = threading.Event()
                    timer = threading.Timer(0.4, cancel.set)
                    timer.start()
                    try:
                        with self.assertRaises(Cancelled):
                            self.invoke(provider, prefix + '\nimport time; time.sleep(30)', cancel=cancel)
                    finally:
                        timer.cancel()
                        timer.join()
                    self.assert_clean()

    def test_oversized_unterminated_output_is_bounded(self):
        for provider in ('gemini', 'antigravity'):
            with self.subTest(provider=provider):
                with self.assertRaisesRegex(ChatGPTError, '너무 길어'):
                    self.invoke(provider, "import sys,time; sys.stdout.write('x' * 300000); sys.stdout.flush(); time.sleep(30)")
                self.assert_clean()


if __name__ == '__main__':
    unittest.main()
