"""One chassis writer; cancellable timers and timestamped input arbitration."""
from collections import deque
from dataclasses import dataclass, field
import math
from threading import Lock
import time

from src.actions import (Advance, BackUp, ShiftLeft, ShiftRight, SpinAntiClockwise,
                         SpinClockwise, Stop, TurnLeft, TurnRight, Sleep)
from src.actions.complex_actions import ComplexAction


@dataclass(frozen=True)
class Command:
    key: str
    source: str = 'keyboard'
    issued_at: float = field(default_factory=time.monotonic)
    started_at: float = None


class CommandInbox:
    """Bounded input buffer; stop/exit bypass pending movements."""
    def __init__(self):
        self.lock = Lock()
        self.items = deque(maxlen=32)
        self.urgent = None

    def put(self, command):
        with self.lock:
            if command.key in ('space', 'esc'):
                self.items.clear()
                if self.urgent is None or self.urgent.key != 'esc':
                    self.urgent = command
            else:
                self.items.append(command)

    def drain(self):
        with self.lock:
            if self.urgent is not None:
                result = [self.urgent]
                self.urgent = None
                self.items.clear()
                return result
            result = sorted(self.items, key=lambda c: c.source != 'keyboard')
            self.items.clear()
            return result


class MotionArbiter:
    MOTION_ACTIONS = {
        'w': Advance, 's': BackUp, 'a': TurnLeft, 'd': TurnRight,
        'q': SpinAntiClockwise, 'e': SpinClockwise,
        'left': ShiftLeft, 'right': ShiftRight,
    }
    TURN_SPEED = 80
    # At this fixed spin command, the old 5.24 s timer turned the real car
    # about 280-290 degrees. Scale its nominal 180-degree time by 180/285.
    TURN_DURATION = math.pi / (0.3 * TURN_SPEED / 40) * (180 / 285)

    def __init__(self, controller, snapshot, voice_seconds=1, clock=time.monotonic):
        self.ctrl, self.snapshot = controller, snapshot
        self.voice_seconds, self.clock = voice_seconds, clock
        self.speed = 40
        self.active_motion = None
        self.deadline = None
        self.owner = None
        self.cutoff = 0
        self.last_command = 0
        self.scene_enabled = True
        self.sequence = deque()
        self.sequence_deadline = None

    def stop(self):
        self.active_motion = self.deadline = self.owner = None
        self.sequence.clear()
        self.sequence_deadline = None
        self.ctrl.execute(Stop())

    def handle(self, command):
        now = self.clock()
        key = command.key
        if key in ('space', 'esc'):
            self.cutoff = now
            self.scene_enabled = False
            self.stop()
            return key == 'esc'
        if not 0 <= now - command.issued_at <= 1:
            return False
        start = command.started_at if command.started_at is not None else command.issued_at
        if command.issued_at <= self.cutoff:
            return False
        if command.source == 'voice' and (start <= self.cutoff or command.issued_at < self.last_command):
            return False
        if key == 'p':
            self.snapshot()
            return False
        if key not in (*self.MOTION_ACTIONS, 'up', 'down', 'z'):
            return False
        self.last_command = command.issued_at
        self.scene_enabled = False
        self.sequence.clear()
        self.sequence_deadline = None
        if command.source == 'keyboard':
            self.cutoff = command.issued_at
            # A speed key during a timed spin must not leave an unbounded spin.
            if self.deadline is not None and self.active_motion is None:
                self.stop()
            self.deadline = None
        self.owner = command.source
        if key in ('up', 'down'):
            self.speed = min(100, max(0, self.speed + (20 if key == 'up' else -20)))
            if self.active_motion is not None:
                self._move(self.active_motion)
        elif key == 'z':
            self.active_motion = None
            self.ctrl.execute(SpinAntiClockwise(speed=self.TURN_SPEED))
            self.deadline = now + self.TURN_DURATION
        else:
            self.active_motion = key
            self._move(key)
            self.deadline = None
        if command.source == 'voice':
            self.deadline = now + self.voice_seconds
        return False

    def _move(self, key):
        self.ctrl.execute(Stop() if self.speed == 0 else self.MOTION_ACTIONS[key](speed=self.speed))

    def scene_action(self, action, issued_at):
        if not self.scene_enabled or not 0 <= self.clock() - issued_at <= 1:
            return
        # Complex actions are expanded here so their sleeps never block input.
        self.sequence.clear()
        self.sequence_deadline = None
        self.sequence.extend(action.action_seq if isinstance(action, ComplexAction) else [action])
        self.tick()

    def tick(self):
        now = self.clock()
        if self.deadline is not None and now >= self.deadline:
            self.stop()
        if self.sequence_deadline is not None and now < self.sequence_deadline:
            return
        self.sequence_deadline = None
        while self.sequence:
            action = self.sequence.popleft()
            if isinstance(action, Sleep):
                self.sequence_deadline = now + action.sleep_time
                return
            self.ctrl.execute(action)


class SceneController:
    """AI workers publish actions without opening or writing the chassis."""
    def __init__(self, queue, stop_event, generation, completed):
        self.queue, self.stop_event, self.generation = queue, stop_event, generation
        self.completed = completed

    def execute(self, action):
        from queue import Full
        self.completed.clear()
        while not self.stop_event.is_set():
            try:
                self.queue.put((self.generation, time.monotonic(), action), timeout=0.1)
                while not self.stop_event.is_set() and not self.completed.wait(0.1):
                    pass
                return
            except Full:
                continue
