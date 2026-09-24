"""Camera capture contract tests using a simulated Orbbec SDK."""

import importlib.util
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

import numpy as np


class FakePipeline:
    instances = []
    image = np.full((2, 2, 3), 37, dtype=np.uint8)
    fail = False

    def __init__(self):
        self.stopped = False
        self.__class__.instances.append(self)

    def get_stream_profile_list(self, sensor):
        return self

    def get_video_stream_profile(self, width, height, color_format, fps):
        return 'color-profile'

    def start(self, config):
        pass

    def wait_for_frames(self, timeout):
        if self.fail:
            raise RuntimeError('device disconnected')
        time.sleep(0.01)
        return self

    def get_color_frame(self):
        return self

    def stop(self):
        self.stopped = True


class FakeSharedMemory:
    def __init__(self, create, size):
        self.buf = bytearray(size)
        self.name = 'test-camera-frame'

    def close(self):
        pass

    def unlink(self):
        pass


class CameraBroadcasterTest(unittest.TestCase):
    def setUp(self):
        FakePipeline.instances.clear()
        FakePipeline.fail = False
        FakePipeline.image = np.full((2, 2, 3), 37, dtype=np.uint8)

        logger = types.ModuleType('src.utils.logger')
        logger.logger_instance = types.SimpleNamespace(info=lambda *args: None,
                                                       exception=lambda *args: None)
        converter = types.ModuleType('src.utils.utils')
        converter.frame_to_bgr_image = lambda frame: FakePipeline.image
        sdk = types.ModuleType('pyorbbecsdk')
        sdk.Config = type('Config', (), {'enable_stream': lambda self, profile: None})
        sdk.OBFormat = types.SimpleNamespace(MJPG=1, YUYV=2, RGB=3)
        sdk.OBSensorType = types.SimpleNamespace(COLOR_SENSOR=1)
        sdk.Pipeline = FakePipeline
        cv2 = types.ModuleType('cv2')
        cv2.resize = lambda image, size: np.tile(image, (size[1], size[0], 1))
        modules = {
            'src': types.ModuleType('src'),
            'src.utils': types.ModuleType('src.utils'),
            'src.utils.logger': logger,
            'src.utils.utils': converter,
            'pyorbbecsdk': sdk,
            'cv2': cv2,
        }
        self.patcher = patch.dict(sys.modules, modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        path = Path(__file__).resolve().parents[2] / 'src/utils/camera_broadcaster.py'
        spec = importlib.util.spec_from_file_location('camera_broadcaster_test_module', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.Value = lambda kind, value: types.SimpleNamespace(value=value)
        module.Event = threading.Event
        module.shared_memory = types.SimpleNamespace(SharedMemory=FakeSharedMemory)
        self.CameraBroadcaster = module.CameraBroadcaster

    def start_camera(self):
        camera = self.CameraBroadcaster({'height': 2, 'width': 2, 'fps': 30})
        thread = threading.Thread(target=camera.run)
        thread.start()

        def cleanup():
            camera.stop_sign.value = True
            thread.join(timeout=1)
            camera.close()

        self.addCleanup(cleanup)
        return camera, thread

    def test_first_frame_reaches_shared_memory_and_stops(self):
        camera, thread = self.start_camera()
        self.assertTrue(camera.ready.wait(timeout=1))
        image = np.ndarray((2, 2, 3), dtype=np.uint8, buffer=camera.frame.buf)
        self.assertTrue(np.all(image == 37))
        self.assertGreater(camera.last_frame_time.value, 0)
        camera.stop_sign.value = True
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(FakePipeline.instances[0].stopped)

    def test_sdk_failure_is_reported(self):
        FakePipeline.fail = True
        camera, thread = self.start_camera()
        self.assertTrue(camera.failed.wait(timeout=1))
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertFalse(camera.ready.is_set())
        self.assertTrue(FakePipeline.instances[0].stopped)

    def test_default_profile_size_is_resized_to_shared_memory(self):
        FakePipeline.image = np.full((1, 1, 3), 92, dtype=np.uint8)
        camera, _ = self.start_camera()
        self.assertTrue(camera.ready.wait(timeout=1))
        image = np.ndarray((2, 2, 3), dtype=np.uint8, buffer=camera.frame.buf)
        self.assertTrue(np.all(image == 92))


if __name__ == '__main__':
    unittest.main()
