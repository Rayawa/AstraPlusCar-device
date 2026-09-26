"""Compatibility scene using the same arbiter and asynchronous screenshot worker."""
from queue import Empty

from camera_tasks import SnapshotWriter
from motion_control import Command, MotionArbiter
from src.scenes.base_scene import BaseScene
from src.utils import log
from src.utils.camera_broadcaster import check_fresh, read_frame


class Manual(BaseScene):
    MOTION_ACTIONS = MotionArbiter.MOTION_ACTIONS
    SPEED_STEP = 20
    TURN_SPEED = MotionArbiter.TURN_SPEED
    TURN_DURATION = MotionArbiter.TURN_DURATION

    def init_state(self):
        pass

    def read(self):
        return read_frame(self.broadcaster, self.camera_info)

    def check_fresh(self):
        check_fresh(self.camera_info)

    def loop(self):
        snapshots = SnapshotWriter(self, report=log.info)
        driver = MotionArbiter(self.ctrl, snapshots.request)
        try:
            snapshots.start()
            while not self.stop_sign.value:
                self.check_fresh()
                try:
                    key = self.msg_queue.get(timeout=0.02)
                except Empty:
                    driver.tick()
                    continue
                if driver.handle(key if isinstance(key, Command) else Command(key)):
                    break
                driver.tick()
        finally:
            driver.stop()
            snapshots.close()
