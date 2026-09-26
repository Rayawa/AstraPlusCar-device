#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod
from ctypes import c_bool
from multiprocessing import shared_memory, Value
import time



class BaseScene(ABC):
    def __init__(self, memory_name, camera_info, msg_queue):
        self.pause_sign = Value(c_bool, False)
        self.stop_sign = Value(c_bool, False)
        if 'action_queue' in camera_info:
            from motion_control import SceneController
            self.ctrl = SceneController(camera_info['action_queue'], camera_info['scene_stop'],
                                        camera_info['generation'], camera_info['action_completed'])
            self.stop_sign = camera_info['scene_stop_sign']
        else:
            from src.utils import Controller
            self.ctrl = Controller()
        self.msg_queue = msg_queue
        self.broadcaster = shared_memory.SharedMemory(name=memory_name)
        self.camera_info = camera_info
        self.height = self.camera_info.get('height', 720)
        self.width = self.camera_info.get('width', 1280)
        self.fps = self.camera_info.get('fps', 30)
        self.last_frame_time = self.camera_info.get('last_frame_time')

    def read_camera(self):
        from src.utils.camera_broadcaster import read_frame
        return read_frame(self.broadcaster, self.camera_info)[0]

    def camera_is_fresh(self):
        from src.utils.camera_broadcaster import check_fresh
        try:
            check_fresh(self.camera_info)
            return True
        except RuntimeError:
            return False

    @abstractmethod
    def init_state(self):
        pass

    @abstractmethod
    def loop(self):
        pass
