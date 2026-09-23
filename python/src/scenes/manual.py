import datetime
import os

import cv2
import numpy as np

from src.actions import Advance, Stop, SetServo, TurnLeft, TurnRight, SpinClockwise, SpinAntiClockwise, BackUp, \
    ShiftLeft, ShiftRight, CustomAction
from src.actions.complex_actions import ComplexAction, TurnAround
from src.scenes.base_scene import BaseScene
from src.utils import log


class Manual(BaseScene):
    def __init__(self, memory_name, camera_info, msg_queue):
        super().__init__(memory_name, camera_info, msg_queue)
        self.speed = 40
        self.save_dir = os.path.join(os.getcwd(), 'capture')
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir, exist_ok=True)

    def init_state(self):
        self.ctrl.execute(SetServo(servo=[90, 65]))


    def adjust_speed(self, increment):
        """
        调整速度的方法
        :param increment: 调整增量，可以为正数（增加速度）或负数（减少速度）
        """
        self.speed += increment
        self.speed = min(max(self.speed, 0), 100)  # 确保速度在 25 到 60 之间
        
    def loop(self):
        # ret = self.init_state()
        # if ret:
        #     log.error(f'{self.__class__.__name__} init failed.')
        #     return
        frame = np.ndarray((self.height, self.width, 3), dtype=np.uint8, buffer=self.broadcaster.buf)
        log.info(f'{self.__class__.__name__} loop start')
       # last_action = SetServo(servo=[90, 65])
        last_action = None

        while True:
            try:
                if not self.msg_queue.empty():
                    key = self.msg_queue.get()
                else:
                    continue
            except KeyboardInterrupt:
                self.ctrl.execute(Stop())
                break

            if key == 'up':
                 self.adjust_speed(1)
            elif key == 'down':
                 self.adjust_speed(-1)
            elif key == 'left':
                last_action = ShiftLeft(speed=self.speed)
            elif key == 'right':
                last_action = ShiftRight(speed=self.speed)
            elif key == 'w':
                last_action = Advance(speed=self.speed)
            elif key == 'a':
                last_action = TurnLeft(speed=self.speed)
            elif key == 'g':
                last_action =SetServo()
            elif key == 's':
                last_action = BackUp(speed=self.speed)
            elif key == 'd':
                last_action = TurnRight(speed=self.speed)
            elif key == 'q':
                last_action = SpinAntiClockwise(speed=self.speed)
            elif key == 'e':
                last_action = SpinClockwise(speed=self.speed)
            elif key == 'z':
                last_action = ShiftLeft(speed=self.speed)
            elif key == 'c':
                last_action = ShiftRight(speed=self.speed)
            elif key == 'space':
                last_action = Stop()
            elif key == 'esc':
                self.ctrl.execute(Stop())
                break
            elif key == 'p':
                save_img = frame.copy()
                cv2.imwrite(os.path.join(self.save_dir, f'{datetime.datetime.now()}.jpg'), save_img)
                log.info(f'image saved.')
                continue
            # elif key == 't':
            #     last_action = CustomAction(motor_setting=[-62, 50, 50, -50])
            # elif key == 'r':
            #     last_action = CustomAction(motor_setting=[55, -50, -50, 50])
            elif key == 'z':
                last_action = TurnAround()
            # elif key == 'x':
            #     from src.actions.complex_actions import Spin
            #     last_action = Spin()
            else:
                continue

            #if not isinstance(last_action, ComplexAction) and not isinstance(last_action, CustomAction):
                #last_action.update_speed = False
                #last_action.speed_setting = last_action.generate_speed_setting(speed=self.speed, degree=degree)
                #last_action.fix_speed()
            self.ctrl.execute(last_action)
