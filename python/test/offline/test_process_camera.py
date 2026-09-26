"""Real spawn and shared memory lifetime with a simulated camera SDK."""
from multiprocessing import get_context, shared_memory
import sys
import tempfile
import time
import types
import unittest

import numpy as np

from camera_preview import CameraStream
from camera_tasks import SnapshotWriter
from src.utils.camera_broadcaster import CameraBroadcaster


def capture_worker(camera, opens, stopped, fail):
    class Pipeline:
        def wait_for_frames(self, timeout):
            time.sleep(.01)
            if fail:
                raise RuntimeError('injected camera disconnect')
            return self
        def get_color_frame(self):
            return self
        def stop(self):
            stopped.set()
    def open_pipeline(*args):
        opens.value += 1
        return Pipeline(), 'fake profile'
    sys.modules['astra_camera'] = types.SimpleNamespace(
        open_color_pipeline=open_pipeline,
        frame_to_bgr_image=lambda _: np.full((4, 4, 3), 73, np.uint8))
    camera.run()


class ProcessCameraTest(unittest.TestCase):
    def make_camera(self):
        try:
            return CameraBroadcaster(dict(height=4, width=4, fps=30))
        except PermissionError:
            self.skipTest('POSIX shared memory is unavailable in this sandbox')

    def test_shared_camera_survives_multiple_readers_then_unlinks(self):
        context = get_context('spawn')
        camera = self.make_camera()
        name = camera.memory_name
        opens, stopped = context.Value('i', 0), context.Event()
        process = context.Process(target=capture_worker, args=(camera, opens, stopped, False))
        preview, writer = None, None
        try:
            process.start()
            self.assertTrue(camera.wait_until_ready(process, timeout=5))
            preview = CameraStream(camera)
            preview.start()
            with tempfile.TemporaryDirectory() as directory:
                writer = SnapshotWriter(camera, directory, report=lambda _: None)
                writer.start()
                futures = [writer.request() for _ in range(4)]
                self.assertTrue(np.all(camera.read()[0] == 73))
                self.assertEqual(len({f.result(2)[0] for f in futures}), 4)
                self.assertEqual(opens.value, 1)
                writer.close()
                preview.close()
            camera.stop_sign.value = True
            process.join(3)
            self.assertFalse(process.is_alive())
            self.assertTrue(stopped.is_set())
        finally:
            if preview:
                preview.close()
            if writer:
                writer.close()
            if process.is_alive():
                process.terminate()
                process.join(3)
            process.close()
            camera.close()
        with self.assertRaises(FileNotFoundError):
            shared_memory.SharedMemory(name=name)

    def test_capture_process_reports_failure_and_releases_pipeline(self):
        context = get_context('spawn')
        camera = self.make_camera()
        stopped, opens = context.Event(), context.Value('i', 0)
        process = context.Process(target=capture_worker, args=(camera, opens, stopped, True))
        try:
            process.start()
            self.assertFalse(camera.wait_until_ready(process, timeout=5))
            process.join(3)
            self.assertTrue(camera.failed.is_set())
            self.assertTrue(stopped.is_set())
            with self.assertRaises(RuntimeError):
                camera.read()
        finally:
            if process.is_alive():
                process.terminate()
                process.join(3)
            process.close()
            camera.close()


if __name__ == '__main__':
    unittest.main()
