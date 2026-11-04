"""Deterministic, GUI-independent interaction and physics state machine.

Coordinates and velocities are logical pixels, logical pixels/second.
This module never reads ChatGPT processes, transcripts, or private APIs.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import math
from typing import Iterable

JOB_STATES=frozenset({'working','thinking','waiting','success','failed','review','idle'})
DRAG_STATES=frozenset({'grab_start','grabbed_idle','drag_left','drag_right','drag_up','drag_down'})
PHYSICS_STATES=frozenset({'release','fall','landing','land','recover'})
REACTIONS=frozenset({'hover','click','double_click','pat','wave','return_greet'})
AMBIENT=frozenset({'idle','blink','look','look_away','walk_left','walk_right','run_left','run_right','jump','turn','sit','sleep','wake','stretch','yawn','ear_twitch','tail_wag','head_tilt','look_around','idle_sit'})
STATES=JOB_STATES|DRAG_STATES|PHYSICS_STATES|REACTIONS|AMBIENT

@dataclass(frozen=True)
class Rect:
    x:float; y:float; width:float; height:float
    @property
    def right(self)->float:return self.x+self.width
    @property
    def bottom(self)->float:return self.y+self.height
    def contains(self,x:float,y:float)->bool:return self.x<=x<=self.right and self.y<=y<=self.bottom

@dataclass
class Settings:
    gravity:float=1800.0
    terminal_velocity:float=1800.0
    restitution:float=0.10
    friction:float=7.0
    drag_inertia:float=0.30
    drag_threshold:float=8.0
    max_throw_speed:float=1200.0
    double_click_seconds:float=0.30
    sit_after:float=120.0
    sleep_after:float=300.0
    idle_fps:int=12
    active_fps:int=60
    scale:float=1.0
    always_on_top:bool=True
    event_inbox_enabled:bool=False
    def __post_init__(self):
        for name in ('always_on_top','event_inbox_enabled'):
            if type(getattr(self,name)) is not bool:
                raise ValueError(f'Invalid boolean setting {name}')
        limits={'gravity':(0,10000),'terminal_velocity':(10,10000),'restitution':(0,0.85),'friction':(0,40),'drag_inertia':(0,1.5),'drag_threshold':(2,50),'max_throw_speed':(0,5000),'double_click_seconds':(0.1,0.8),'sit_after':(10,86400),'sleep_after':(20,86400),'scale':(0.5,2.5)}
        for name,(lo,hi) in limits.items():
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError(f'Invalid setting {name}: {value!r}')
        if self.sleep_after<self.sit_after:raise ValueError('sleep_after must be >= sit_after')
        if not 4<=self.idle_fps<=30 or not 20<=self.active_fps<=120:raise ValueError('Invalid FPS')

@dataclass
class Job:
    state:str; origin:str; session:str; received_at:float

class PetEngine:
    """Motion priority: drag > physics > reactions > job status > ambient.

    Latest status per session is retained while a higher-priority action runs.
    Queue sizes and history are bounded. tick() uses a caller-supplied monotonic
    time; tests can advance time without sleeping.
    """
    def __init__(self,screens:Iterable[Rect],settings:Settings|None=None,now:float=0.0):
        self.settings=settings or Settings()
        self.screens=list(screens)
        if not self.screens:raise ValueError('At least one available screen is required')
        self.width=192*self.settings.scale;self.height=208*self.settings.scale
        self.pivot_y=196*self.settings.scale
        self.screen=self.screens[0]
        self.x=self.screen.x+min(100,max(0,self.screen.width-self.width))
        self.y=self.screen.bottom-self.pivot_y
        self.vx=self.vy=0.0
        self.state='idle';self.state_since=now;self.now=now;self.until=None
        self.last_activity=now;self.last_pointer=None;self.pointer_speed=(0.0,0.0)
        self.last_pointer_over_head=False
        self.pressed=False;self.dragging=False;self.press_at=None;self.grab_offset=(0.0,0.0)
        self.last_drag_time=now;self.drag_pose='grabbed_idle'
        self.drag_motion=deque(maxlen=128)
        self.click_due=None;self.click_pos=None
        self.jobs:dict[tuple[str,str],Job]={}
        self.seen_ids=deque(maxlen=256);self.history=deque(maxlen=200)
        self.gaze_angle=0.0;self.hovered=False;self.hover_cooldown_until=0.0
        self.pat_samples=deque(maxlen=60);self.pat_cooldown_until=0.0
        self.source_label='none';self.reduced_motion=False
        self.animation_durations_ms:dict[str,float]={}

    def configure_clip_timings(self, clips:dict)->None:
        """Use real non-looping clip lengths instead of prototype timeouts.

        No state transitions are added. Without a registry, legacy timings apply.
        A new drag/release can still interrupt an action, as before.
        """
        durations={}
        for state, clip in clips.items():
            if state not in STATES or clip.get('loop', False):
                continue
            values=clip.get('durations_ms', [])
            if not values or len(values)!=len(clip.get('frames', [])):
                raise ValueError(f'Invalid animation timing: {state}')
            if any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or v<=0 for v in values):
                raise ValueError(f'Invalid animation duration: {state}')
            durations[state]=sum(values)
        self.animation_durations_ms=durations

    @staticmethod
    def priority(state:str)->int:
        if state in DRAG_STATES:return 100
        if state in PHYSICS_STATES:return 80
        if state in REACTIONS or state in {'jump','wake'}:return 60
        if state in JOB_STATES and state!='idle':return 40
        return 10

    def _set(self,state:str,duration:float|None=None,reason:str='')->None:
        if state not in STATES:raise ValueError(f'Unknown state: {state}')
        if duration is not None and state in self.animation_durations_ms:
            duration=self.animation_durations_ms[state]/1000.0
        changed=state!=self.state
        if changed:
            self.history.append({'at':round(self.now,4),'from':self.state,'to':state,'reason':reason})
            self.state=state;self.state_since=self.now
        if changed or duration is not None:self.until=self.now+duration if duration is not None else None

    def _nearest_screen(self,px:float,py:float)->Rect:
        for s in self.screens:
            if s.contains(px,py):return s
        return min(self.screens,key=lambda s:(max(s.x-px,0,px-s.right)**2+max(s.y-py,0,py-s.bottom)**2))

    def clamp(self,pointer:tuple[float,float]|None=None)->None:
        # Do not clamp to one bounding rectangle: mixed-DPI screens can have gaps.
        px,py=pointer or (self.x+self.width/2,self.y+self.pivot_y/2)
        self.screen=self._nearest_screen(px,py)
        self.x=min(max(self.x,self.screen.x),max(self.screen.x,self.screen.right-self.width))
        self.y=min(max(self.y,self.screen.y),max(self.screen.y,self.screen.bottom-self.pivot_y))

    def set_screens(self,screens:Iterable[Rect])->None:
        screens=list(screens)
        if screens:
            changed=screens!=self.screens
            self.screens=screens;self.clamp()
            floor=max(self.screen.y,self.screen.bottom-self.pivot_y)
            # Removing a monitor or lowering its work-area floor can leave a
            # formerly grounded pet in midair. Preserve dragging and existing
            # release/fall timing, but resume gravity for unsupported actions.
            if changed and not self.dragging and self.state not in {'release','fall'} and self.y<floor:
                self.vx=self.vy=0
                self._set('fall',reason='screen layout removed floor support')

    def resize(self,scale:float)->None:
        if not .5<=scale<=2.5:raise ValueError('Scale must be between 0.5 and 2.5')
        was_dragging=self.dragging
        in_physics=self.state in PHYSICS_STATES
        foot=(self.x+self.width/2,self.y+self.pivot_y)
        self.settings.scale=scale;self.width=192*scale;self.height=208*scale;self.pivot_y=196*scale
        self.x=foot[0]-self.width/2;self.y=foot[1]-self.pivot_y;self.clamp()
        # Resizing invalidates the old capture offset, but must not cancel an
        # unfinished fall or restart/skip release, landing, and recovery clips.
        self.pressed=False;self.dragging=False;self.press_at=None
        if not in_physics:self.vx=self.vy=0
        self.drag_motion.clear();self.drag_pose='grabbed_idle'
        if was_dragging:self._set('release',.12,'resize ended drag')
        elif not in_physics:self._resume()

    def pointer_down(self,x:float,y:float,opaque:bool)->bool:
        if not opaque:return False
        self.pressed=True;self.dragging=False;self.press_at=(x,y)
        self.pat_samples.clear();self.last_pointer_over_head=False
        self.grab_offset=(x-self.x,y-self.y);self.last_activity=self.now
        self.last_pointer=(x,y,self.now);self.pointer_speed=(0,0)
        self.last_drag_time=self.now
        self.drag_motion.clear();self.drag_pose='grabbed_idle'
        return True

    def _update_drag_pose(self,dx:float,dy:float)->None:
        # Some native input streams deliver X and Y separately. Choose a pose
        # from recent displacement, not one axis-only event. Hysteresis keeps
        # near-diagonal motion on its current axis without restarting the clip.
        if self.now-self.last_drag_time>.1:
            self.drag_motion.clear();self.drag_pose='grabbed_idle'
        # Duplicated coordinates do not consume time from the next sample.
        dt=max(.001,self.now-self.last_drag_time)
        self.drag_motion.append((self.now,dx,dy,dt))
        while self.drag_motion and self.now-self.drag_motion[0][0]>.08:
            self.drag_motion.popleft()
        sx=sum(v[1] for v in self.drag_motion)
        sy=sum(v[2] for v in self.drag_motion)
        elapsed=sum(v[3] for v in self.drag_motion)
        ax,ay=abs(sx),abs(sy)
        if max(ax,ay)/elapsed<40:
            self.drag_pose='grabbed_idle';return
        horizontal=ax>=ay
        if self.drag_pose in {'drag_left','drag_right'} and ay<=2*ax:
            horizontal=True
        elif self.drag_pose in {'drag_up','drag_down'} and ax<=2*ay:
            horizontal=False
        self.drag_pose=(('drag_right' if sx>0 else 'drag_left') if horizontal
                        else ('drag_down' if sy>0 else 'drag_up'))

    def pointer_move(self,x:float,y:float,over_head:bool=False)->None:
        old=self.last_pointer
        was_over_head=self.last_pointer_over_head
        self.last_pointer_over_head=bool(over_head and not self.pressed)
        moved=0.0
        if old:
            dt=max(.001,self.now-old[2]);dx=x-old[0];dy=y-old[1];moved=math.hypot(dx,dy)
            self.pointer_speed=(dx/dt,dy/dt)
        # Sample velocity only between real coordinate changes. A repeated
        # coordinate must neither consume elapsed time nor damp a later throw.
        # Stationary holds are still handled by the existing drag timeout.
        if old is None or moved>0:self.last_pointer=(x,y,self.now)
        if moved>1:self.last_activity=self.now
        self.gaze_angle=math.degrees(math.atan2(y-(self.y+78*self.settings.scale),x-(self.x+self.width/2)))%360
        if self.pressed and self.press_at:
            if not self.dragging and math.hypot(x-self.press_at[0],y-self.press_at[1])>=self.settings.drag_threshold:
                self.dragging=True;self.click_due=None
                # A fresh drag samples the hand, not the previous fall/throw.
                # Wait for the threshold so a simple click still preserves fall.
                self.vx=self.vy=0.0
                self._set('grab_start',.14,'drag threshold crossed')
            if self.dragging:
                self.x=x-self.grab_offset[0];self.y=y-self.grab_offset[1];self.clamp((x,y))
                if moved>0:
                    speedx,speedy=self.pointer_speed
                    limit=self.settings.max_throw_speed
                    speedx=max(-limit,min(limit,speedx));speedy=max(-limit,min(limit,speedy))
                    self.vx=.5*self.vx+.5*speedx;self.vy=.5*self.vy+.5*speedy
                    self._update_drag_pose(dx,dy)
                    self.last_drag_time=self.now
                    if self.state!='grab_start':self._set(self.drag_pose,reason='recent pointer direction')
        elif over_head and was_over_head and moved>1 and self.now>=self.pat_cooldown_until:
            # Only count motion within the head, not the approach from outside.
            self.pat_samples.append((self.now,moved))
            while self.pat_samples and self.now-self.pat_samples[0][0]>.7:self.pat_samples.popleft()
            if sum(v for _,v in self.pat_samples)>=70 and self.priority(self.state)<60:
                self._set('pat',.8,'head strokes');self.pat_samples.clear();self.pat_cooldown_until=self.now+2.5
        elif not over_head or not was_over_head:self.pat_samples.clear()

    def pointer_up(self,x:float,y:float)->None:
        if not self.pressed:return
        # The release event can carry a newer position than the last move.
        # Consume that sample while still pressed, including threshold/bounds,
        # instead of dropping from a stale point or mistaking a drag for a click.
        if self.last_pointer is None or (x,y)!=self.last_pointer[:2]:
            self.pointer_move(x,y)
        self.pressed=False
        if self.dragging:
            self.dragging=False
            if self.now-self.last_drag_time>.12:self.vx=self.vy=0
            self.vx*=self.settings.drag_inertia;self.vy*=self.settings.drag_inertia
            self._set('release',.12,'mouse released')
        else:
            nearby=self.click_pos is not None and math.hypot(x-self.click_pos[0],y-self.click_pos[1])<16
            if self.click_due is not None and self.now<=self.click_due and nearby:
                self.click_due=None
                if self.priority(self.state)<80:self._set('double_click',1.0,'double click')
            else:self.click_due=self.now+self.settings.double_click_seconds;self.click_pos=(x,y)
        self.press_at=None;self.last_activity=self.now

    def cancel_pointer(self)->None:
        # Focus loss / capture loss cannot leave the pet permanently grabbed.
        if self.pressed:
            self.pressed=False;self.press_at=None
            if self.dragging:self.dragging=False;self.vx=self.vy=0;self._set('release',.1,'capture lost')

    def hover(self,inside:bool)->None:
        if inside and not self.hovered and self.now>=self.hover_cooldown_until and self.priority(self.state)<60:
            self._set('hover',.35,'pointer entered');self.hover_cooldown_until=self.now+5
        self.hovered=inside

    def job_event(self,state:str,origin:str='manual',session:str='default',event_id:str|None=None)->bool:
        if state not in JOB_STATES:raise ValueError(f'Invalid task state: {state}')
        if origin not in {'manual','local_app','codex_hook'}:raise ValueError('Unsupported event origin')
        if not isinstance(session,str) or len(session)>128:raise ValueError('Invalid session id')
        if event_id is not None:
            if event_id in self.seen_ids:return False
            self.seen_ids.append(event_id)
        key=(origin,session)
        if state=='idle':self.jobs.pop(key,None)
        else:
            if key not in self.jobs and len(self.jobs)>=64:
                oldest=min(self.jobs,key=lambda k:self.jobs[k].received_at);del self.jobs[oldest]
            self.jobs[key]=Job(state,origin,session,self.now)
        if not self.dragging and self.priority(self.state)<=40:self._resume()
        return True

    def _job_choice(self)->Job|None:
        if not self.jobs:return None
        rank={'waiting':6,'failed':5,'success':4,'review':3,'working':2,'thinking':1}
        return max(self.jobs.values(),key=lambda j:(rank[j.state],j.received_at))

    def _resume(self)->None:
        job=self._job_choice()
        if job:
            self.source_label=f'{job.origin}:{job.session}'
            self._set(job.state,reason='latest queued task status')
        else:
            self.source_label='none'
            quiet=self.now-self.last_activity
            if quiet>=self.settings.sleep_after:self._set('sleep',reason='long idle')
            elif quiet>=self.settings.sit_after:self._set('sit',reason='idle timeout')
            else:self._set('idle',reason='no active task')

    def debug_action(self,state:str)->bool:
        if state not in STATES:raise ValueError(f'Unknown state: {state}')
        if state in JOB_STATES:self.job_event(state);return True
        if state in DRAG_STATES or state in PHYSICS_STATES:return False
        if self.priority(self.state)>=80:return False
        self._set(state,1.0,'manual debug action');return True

    def _physics(self,dt:float)->None:
        # Small substeps avoid overshoot. Timer stalls discard excess elapsed time.
        step_max=1/120
        while dt>1e-9:
            step=min(dt,step_max);dt-=step
            self.vy=min(self.settings.terminal_velocity,self.vy+self.settings.gravity*step)
            self.x+=self.vx*step;self.y+=self.vy*step
            # Move into a real monitor only; never enter a virtual desktop gap.
            self.screen=self._nearest_screen(self.x+self.width/2,self.y+self.pivot_y/2)
            left=self.screen.x;right=max(left,self.screen.right-self.width)
            if self.x<left:self.x=left;self.vx=abs(self.vx)*self.settings.restitution
            elif self.x>right:self.x=right;self.vx=-abs(self.vx)*self.settings.restitution
            if self.y<self.screen.y:self.y=self.screen.y;self.vy=max(0,self.vy)
            floor=max(self.screen.y,self.screen.bottom-self.pivot_y)
            if self.y>=floor:
                self.y=floor
                if self.vy>260 and self.settings.restitution>0:
                    self.vy=-self.vy*self.settings.restitution
                    self.vx*=math.exp(-self.settings.friction*.08)
                else:
                    self.vx=self.vy=0.0;self._set('landing',.28,'floor contact');break

    def tick(self,now:float)->None:
        if not math.isfinite(now) or now<self.now:raise ValueError('Time must be finite and monotonic')
        dt=min(now-self.now,.05);self.now=now
        if self.click_due is not None and now>=self.click_due:
            self.click_due=None
            if not self.pressed and not self.dragging and self.priority(self.state)<80:self._set('click',.45,'single click confirmed')
        # Success is an explicitly supplied event, never inferred from a stopped turn.
        for job in self.jobs.values():
            if job.state=='success' and now-job.received_at>2.5:job.state='review'
        if self.dragging:
            if self.state=='grab_start' and self.until is not None and now>=self.until:self._set('grabbed_idle',reason='grab reaction finished')
            elif self.state!='grab_start' and now-self.last_drag_time>.1:
                self.vx=self.vy=0;self.drag_motion.clear();self.drag_pose='grabbed_idle'
                self._set('grabbed_idle',reason='pointer stopped')
            return
        if self.until is not None and now>=self.until:
            old=self.state;self.until=None
            if old=='release':self._set('fall',reason='release finished')
            elif old in {'landing','land'}:self._set('recover',.25,'impact absorbed')
            elif old=='recover':self._resume()
            elif old not in PHYSICS_STATES:self._resume()
        if self.state=='fall':self._physics(dt)
        elif self.priority(self.state)<=40 and self.until is None:self._resume()

    def snapshot(self)->dict:
        return {'state':self.state,'x':self.x,'y':self.y,'vx':self.vx,'vy':self.vy,'pressed':self.pressed,'dragging':self.dragging,'source':self.source_label,'pending_jobs':len(self.jobs),'gaze_angle':self.gaze_angle}
