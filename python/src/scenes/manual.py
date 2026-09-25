import datetime
import math
import os
from queue import Empty
import time

import cv2
import numpy as np

from src.actions import (Advance, BackUp, ShiftLeft, ShiftRight, SpinAntiClockwise,
                         SpinClockwise, Stop, TurnLeft, TurnRight)
from src.scenes.base_scene import BaseScene
from src.utils import log


class Manual(BaseScene):
    SPEED_STEP = 20
    TURN_SPEED = 80
    # Chassis angular rates are radians per second. A timed turn is only an
    # estimate until the actual wheel motion has been calibrated.
    TURN_DURATION = math.pi / (0.3 * TURN_SPEED / 40)
    MOTION_ACTIONS = {
        'w': Advance, 's': BackUp, 'a': TurnLeft, 'd': TurnRight,
        'q': SpinAntiClockwise, 'e': SpinClockwise,
        'left': ShiftLeft, 'right': ShiftRight,
    }

    def __init__(self, memory_name, camera_info, msg_queue):
        super().__init__(memory_name, camera_info, msg_queue)
        self.speed = 40
        self.save_dir = os.path.join(os.getcwd(), 'capture')
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir, exist_ok=True)

    def init_state(self):
        # The current chassis controller has no servo board attached.
        pass


    def adjust_speed(self, increment):
        self.speed = min(max(self.speed + increment, 0), 100)
        log.info(f'Manual speed: {self.speed}')

    def loop(self):
        frame = np.ndarray((self.height, self.width, 3), dtype=np.uint8, buffer=self.broadcaster.buf)
        log.info(f'{self.__class__.__name__} loop start')
        active_motion = None
        turn_deadline = None

        while True:
            try:
                if turn_deadline is None:
                    key = self.msg_queue.get()
                else:
                    key = self.msg_queue.get(timeout=max(0, turn_deadline - time.monotonic()))
            except Empty:
                self.ctrl.execute(Stop())
                turn_deadline = None
                continue
            except (KeyboardInterrupt, EOFError):
                self.ctrl.execute(Stop())
                break

            if isinstance(key, str):
                key = key.lower()
            if key == 'up':
                self.adjust_speed(self.SPEED_STEP)
            elif key == 'down':
                self.adjust_speed(-self.SPEED_STEP)
            elif key in self.MOTION_ACTIONS:
                turn_deadline = None
                active_motion = key
                action = Stop() if self.speed == 0 else self.MOTION_ACTIONS[key](speed=self.speed)
                self.ctrl.execute(action)
                continue
            elif key == 'space':
                turn_deadline = None
                active_motion = None
                self.ctrl.execute(Stop())
                continue
            elif key == 'esc':
                self.ctrl.execute(Stop())
                break
            elif key == 'p':
                save_img = frame.copy()
                cv2.imwrite(os.path.join(self.save_dir, f'{datetime.datetime.now()}.jpg'), save_img)
                log.info(f'image saved.')
                continue
            elif key == 'z':
                active_motion = None
                turn_deadline = time.monotonic() + self.TURN_DURATION
                self.ctrl.execute(SpinAntiClockwise(speed=self.TURN_SPEED))
                continue
            else:
                continue

            # An arrow key updates the current movement immediately. When
            # parked it only changes the speed for the next movement key.
            if active_motion is not None:
                action = Stop() if self.speed == 0 else self.MOTION_ACTIONS[active_motion](speed=self.speed)
                self.ctrl.execute(action)
