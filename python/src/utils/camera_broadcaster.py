import time
from ctypes import c_bool
from multiprocessing import get_context, shared_memory

_context = get_context("spawn")
Event, Lock, Value = _context.Event, _context.Lock, _context.Value

import cv2
import numpy as np

from src.utils.logger import logger_instance as log


class CameraBroadcaster:
    """Publish Astra+ color frames as BGR images in shared memory."""

    def __init__(self, camera_info):
        self.height = camera_info.get('height', 480)
        self.width = camera_info.get('width', 640)
        self.fps = camera_info.get('fps', 30)
        self.stop_sign = Value(c_bool, False)
        self.frame_lock = Lock()
        self.ready = Event()
        self.failed = Event()
        self.last_frame_time = Value('d', 0.0, lock=False)
        self.frame = shared_memory.SharedMemory(create=True, size=self.height * self.width * 3)
        self.memory_name = self.frame.name

    def run(self):
        pipeline = None
        sender = None
        try:
            # Import in the child so startup failures reach the failed event.
            from astra_camera import frame_to_bgr_image, open_color_pipeline

            pipeline, profile = open_color_pipeline(self.width, self.height, self.fps)
            log.info(f'Astra+ color profile: {profile}')
            sender = np.ndarray((self.height, self.width, 3), dtype=np.uint8, buffer=self.frame.buf)
            last_frame = time.monotonic()

            while not self.stop_sign.value:
                frames = pipeline.wait_for_frames(200)
                color_frame = frames.get_color_frame() if frames is not None else None
                image = frame_to_bgr_image(color_frame) if color_frame is not None else None
                if image is None:
                    if time.monotonic() - last_frame > 5:
                        raise TimeoutError('Astra+ color stream produced no frames for 5 seconds')
                    continue
                if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
                    raise ValueError(f'Unexpected Astra+ color frame: {image.shape}, {image.dtype}')
                if image.shape[:2] != (self.height, self.width):
                    image = cv2.resize(image, (self.width, self.height))
                with self.frame_lock:
                    sender[:] = image
                    last_frame = time.monotonic()
                    self.last_frame_time.value = last_frame
                self.ready.set()
        except Exception:
            self.failed.set()
            log.exception('Astra+ color capture failed')
        finally:
            self.ready.clear()
            if pipeline is not None:
                try:
                    pipeline.stop()
                except Exception:
                    log.exception('Failed to stop Astra+ pipeline')
            del sender
            self.frame.close()

    def camera_info(self):
        return dict(height=self.height, width=self.width, fps=self.fps,
                    frame_lock=self.frame_lock, last_frame_time=self.last_frame_time,
                    camera_failed=self.failed, camera_ready=self.ready)

    def read(self):
        return read_frame(self.frame, self.camera_info())

    def check_fresh(self):
        check_fresh(self.camera_info())

    def close(self):
        """Release the shared memory after all scene processes have exited."""
        self.frame.close()
        self.frame.unlink()

    def wait_until_ready(self, process, timeout=10):
        deadline = time.monotonic() + timeout
        while not self.ready.wait(timeout=0.1):
            if self.failed.is_set() or not process.is_alive() or time.monotonic() >= deadline:
                return False
        return not self.failed.is_set() and process.is_alive()


def check_fresh(info, max_age=2):
    failed, ready = info.get('camera_failed'), info.get('camera_ready')
    stamp = info.get('last_frame_time')
    if ((failed is not None and failed.is_set()) or
            (ready is not None and not ready.is_set()) or
            stamp is None or not 0 <= time.monotonic() - stamp.value < max_age):
        raise RuntimeError('Camera unavailable or frame expired; refusing stale image')


def read_frame(memory, info):
    """Copy one complete frame, with a bounded wait if the producer dies."""
    lock = info['frame_lock']
    if not lock.acquire(timeout=0.2):
        raise RuntimeError('Camera frame lock timed out')
    try:
        check_fresh(info)
        frame = np.ndarray((info['height'], info['width'], 3), dtype=np.uint8,
                           buffer=memory.buf).copy()
        stamp = info['last_frame_time'].value
        return frame, stamp
    finally:
        lock.release()
