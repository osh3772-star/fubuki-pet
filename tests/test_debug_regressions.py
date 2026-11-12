"""Regression coverage for reported pet bugs; offline only."""
import ast
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import random
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from windows_pet.core import PetEngine,Rect,Settings,RUN_STATES
from windows_pet.chat_bubble import BubbleChat,PetContextBubble
from windows_pet.local_cli_clients import AntigravityGeminiClient
from test_chat_ui import FakeClient


class EngineDebugRegressions(unittest.TestCase):
    def make(self):
        return PetEngine([Rect(0,0,1920,1080)],Settings(dash_chance=1),rng=random.Random(1))

    def test_chat_success_expires_and_random_dash_resumes(self):
        e=self.make();e.chat_event('thinking');e.tick(1);e.chat_event('success')
        e.tick(3.6)
        self.assertFalse(e.jobs);self.assertEqual(e.state,'idle')
        e.tick(10);self.assertIn(e.state,RUN_STATES)
        x=e.x;e.tick(10.03);self.assertNotEqual(e.x,x)

    def test_chat_failure_expires(self):
        e=self.make();e.chat_event('failed');e.tick(2.6)
        self.assertFalse(e.jobs);self.assertEqual(e.state,'idle')

    def test_new_chat_turn_not_cleared_by_prior_terminal_deadline(self):
        e=self.make();e.chat_event('success');e.tick(1);e.chat_event('thinking');e.tick(4)
        self.assertEqual(e.state,'thinking');self.assertEqual(len(e.jobs),1)
        self.assertIsNone(e.chat_status_until)

    def test_different_providers_share_single_transient_chat_status(self):
        e=self.make();e.chat_event('success');e.tick(.1);e.chat_event('thinking')
        self.assertEqual(e.state,'thinking');self.assertEqual(len(e.jobs),1)
        self.assertEqual(e.source_label,'local_app:pet_chat')

    def test_chat_expiry_preserves_external_job(self):
        e=self.make();e.job_event('working','codex_hook','external');e.chat_event('success');e.tick(3)
        self.assertEqual(e.state,'working');self.assertEqual(set(e.jobs),{('codex_hook','external')})

    def test_manual_status_and_pose_idle_use_same_session(self):
        e=self.make();e.job_event('thinking','manual','debug');e.debug_action('idle')
        self.assertEqual(e.state,'idle');self.assertFalse(e.jobs)
        e.debug_action('failed');e.job_event('idle','manual','debug')
        self.assertEqual(e.state,'idle');self.assertFalse(e.jobs)

    def test_actual_context_pose_handler_returns_thinking_to_idle(self):
        e=self.make()
        class Combo:
            value='thinking'
            def currentData(self):return self.value
        class Stub:
            engine=e
            pose_combo=Combo()
            def sync_state(self):pass
        stub=Stub();PetContextBubble._play_selected_pose(stub)
        self.assertEqual(e.state,'thinking')
        stub.pose_combo.value='idle';PetContextBubble._play_selected_pose(stub)
        self.assertEqual(e.state,'idle');self.assertFalse(e.jobs)

    def test_same_nonloop_action_restarts_clip(self):
        e=self.make();e.configure_clip_timings({'wave':{'loop':False,'frames':['a','b'],'durations_ms':[500,500]}})
        e.debug_action('wave');e.tick(.8);e.debug_action('wave');e.tick(1.1)
        self.assertAlmostEqual(e.state_since,.8);self.assertAlmostEqual(e.until,1.8)
        self.assertLess(e.now-e.state_since,.5)
        e.tick(1.81);self.assertEqual(e.state,'idle')

    def test_idle_resume_does_not_restart_loop_clock(self):
        e=self.make();e.tick(.2);e.tick(.4)
        self.assertEqual(e.state_since,0)

    def test_terminal_chat_expiry_does_not_interrupt_drag(self):
        e=self.make();e.chat_event('success');e.pointer_down(e.x+10,e.y+10,True)
        e.pointer_move(e.x+40,e.y+10);e.tick(3)
        self.assertTrue(e.dragging);self.assertIn(e.state,{'grab_start','grabbed_idle'})
        self.assertFalse(e.jobs)


class UIDebugRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.w=BubbleChat(Path(self.tmp.name),True,FakeClient())

    def tearDown(self):
        self.w.shutdown();self.w.deleteLater();self.app.processEvents()

    def wait(self):
        end=time.monotonic()+3
        while self.w.worker is not None and time.monotonic()<end:
            self.app.processEvents();time.sleep(.005)
        self.assertIsNone(self.w.worker)

    def test_effort_choices_match_all_local_providers(self):
        allowed={'gemini':{None,'low','high'},'antigravity_gemini':{None,'low','medium','high','xhigh','max'},'claude':{None,'low','medium','high','xhigh','max'}}
        for provider,expected in allowed.items():
            self.w.select_provider(provider)
            actual={self.w.reasoning_effort.itemData(i) for i in range(self.w.reasoning_effort.count()) if self.w.reasoning_effort.model().item(i).isEnabled()}
            self.assertEqual(actual,expected)
        self.w.select_provider('chatgpt')
        self.assertTrue(all(self.w.reasoning_effort.model().item(i).isEnabled() for i in range(self.w.reasoning_effort.count())))

    def test_switching_resets_incompatible_selected_effort(self):
        self.w.reasoning_effort.setCurrentIndex(self.w.reasoning_effort.findData('medium'))
        self.w.select_provider('gemini')
        self.assertIsNone(self.w.reasoning_effort.currentData())

    def test_antigravity_refresh_fetches_new_catalog(self):
        client=AntigravityGeminiClient(self.tmp.name);client._connected=True
        client._cached_models=[{'slug':'gemini-old','display_name':'Old'}]
        self.w.providers['antigravity_gemini']=client
        self.w.select_provider('antigravity_gemini');self.wait()
        self.w.mock=False
        with patch.object(client,'_fetch_gemini_models',return_value=[{'slug':'gemini-new','display_name':'New'}]) as fetch:
            self.w.refresh_models();self.wait();fetch.assert_called_once()
        self.assertEqual(self.w.models.currentData(),'gemini-new')

    def test_tray_includes_claude_and_chat_uses_transient_event(self):
        source=(Path(__file__).parents[1]/'windows_pet/app.py').read_text()
        ast.parse(source)
        self.assertIn("providers_menu.addAction('Claude (로컬 Claude Code)',lambda:self.open_chat_provider('claude'))",source)
        self.assertIn('self.chat.state_changed.connect(engine.chat_event)',source)

if __name__=='__main__':unittest.main()
