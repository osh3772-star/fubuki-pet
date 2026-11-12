import random
import unittest
from unittest.mock import Mock
from windows_pet.core import PetEngine, Settings, Rect, RUN_STATES


class DashTests(unittest.TestCase):
    def make(self, direction='run_right', chance=1, screen=None):
        rng=Mock()
        rng.random.return_value=0.1
        rng.choice.side_effect=lambda values:direction if direction in values else values[0]
        rng.uniform.return_value=1.2
        engine=PetEngine([screen or Rect(0,0,1920,1080)],Settings(dash_chance=chance),rng=rng)
        engine.x=800
        return engine,rng

    def test_random_right_has_actual_translation(self):
        e,r=self.make();e.tick(10)
        self.assertEqual(e.state,'run_right')
        start=e.x;e.tick(10.05)
        self.assertAlmostEqual(e.x-start,21)
        r.choice.assert_called_once_with(['run_left','run_right'])

    def test_random_left_has_actual_translation(self):
        e,_=self.make('run_left');e.tick(10);start=e.x;e.tick(10.05)
        self.assertLess(e.x,start)
        self.assertAlmostEqual(start-e.x,21)

    def test_no_dash_when_probability_misses(self):
        e,r=self.make(chance=.05);e.tick(10)
        self.assertEqual(e.state,'idle');r.choice.assert_not_called()

    def test_one_roll_per_interval_not_per_frame(self):
        e,r=self.make(chance=0)
        for i in range(1,501):e.tick(i/50)
        self.assertEqual(r.random.call_count,1)
        e.tick(100)
        self.assertEqual(r.random.call_count,2)

    def test_duration_stops_motion_and_cooldown_remains(self):
        e,_=self.make();e.tick(10);e.tick(10.05);e.tick(11.21)
        self.assertEqual(e.state,'idle');x=e.x;e.tick(11.26)
        self.assertEqual(e.x,x);self.assertEqual(e.next_dash_at,20)

    def test_edges_stop_without_overshoot(self):
        for direction in ('run_left','run_right'):
            e,_=self.make(direction);e.x=2 if direction=='run_left' else 1920-e.width-2
            e.tick(10);e.tick(10.05)
            self.assertEqual(e.state,'idle')
            self.assertGreaterEqual(e.x,0);self.assertLessEqual(e.x,1920-e.width)

    def test_edge_direction_is_inward(self):
        e,_=self.make('run_left');e.x=0;e.tick(10)
        self.assertEqual(e.state,'run_right')

    def test_tiny_monitor_does_not_run(self):
        e,_=self.make(screen=Rect(0,0,100,100));e.clamp();e.tick(10)
        self.assertEqual(e.state,'idle')

    def test_negative_monitor_and_gap_safe(self):
        e,_=self.make('run_right',screen=Rect(-1800,100,1280,800))
        e.screens.append(Rect(200,0,1920,1080));e.x=e.screen.right-e.width-3
        e.tick(10);e.tick(10.05)
        self.assertEqual(e.x,-520-e.width)
        self.assertEqual(e.screen.x,-1800)

    def test_pressed_dragged_reduced_motion_and_jobs_block(self):
        for block in ('pressed','dragging','reduced_motion','jobs','disabled'):
            e,_=self.make()
            if block=='jobs':e.job_event('thinking')
            elif block=='disabled':e.settings.dash_enabled=False
            else:setattr(e,block,True)
            e.tick(10)
            self.assertNotIn(e.state,RUN_STATES)

    def test_pointer_press_cancels_dash_without_throw_velocity(self):
        e,_=self.make();e.tick(10);e.tick(10.05)
        x=e.x;e.pointer_down(x+30,e.y+30,True);e.tick(10.1)
        self.assertEqual(e.x,x);self.assertNotIn(e.state,RUN_STATES)
        self.assertEqual(e.vx,0)

    def test_chat_job_interrupts_run(self):
        e,_=self.make();e.tick(10);e.tick(10.05);x=e.x
        e.job_event('thinking');e.tick(10.1)
        self.assertEqual(e.state,'thinking');self.assertEqual(e.x,x)

    def test_reduced_motion_stops_current_dash(self):
        e,_=self.make();e.tick(10);x=e.x;e.reduced_motion=True;e.tick(10.05)
        self.assertEqual(e.state,'idle');self.assertEqual(e.x,x)

    def test_no_dash_during_sleep_or_physics(self):
        e,_=self.make();e.tick(301);self.assertEqual(e.state,'sleep')
        e,_=self.make();e.y=100;e._set('fall');e.tick(10)
        self.assertNotIn(e.state,RUN_STATES)

    def test_looping_run_clip_preserves_random_duration(self):
        e,_=self.make()
        e.configure_clip_timings({'run_right':{'loop':True,'frames':['a','b'],'durations_ms':[100,100]}})
        e.tick(10)
        self.assertAlmostEqual(e.until,11.2)

    def test_settings_validation(self):
        for kwargs in ({'dash_chance':1.1},{'dash_interval':0},{'dash_speed':float('nan')},{'dash_enabled':1}):
            with self.assertRaises(ValueError):Settings(**kwargs)

    def test_seeded_direction_distribution(self):
        rng=random.Random(1234);counts={'run_left':0,'run_right':0}
        for _ in range(1000):
            e=PetEngine([Rect(0,0,1920,1080)],Settings(dash_chance=1),rng=rng)
            e.x=800;e.tick(10);counts[e.state]+=1
        self.assertTrue(430<counts['run_left']<570,counts)

if __name__=='__main__':unittest.main()
