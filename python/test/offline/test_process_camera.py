"""Real spawn and shared memory lifetime with a simulated camera SDK."""
from multiprocessing import get_context, shared_memory
from unittest.mock import Mock, patch
import sys
import tempfile
import time
import types
import unittest

import numpy as np
import cv2

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
        prefer_color_frame_rate=lambda _: None,
        restore_color_exposure_priority=lambda *_: None,
        frame_to_bgr_image=lambda _: np.full((4, 4, 3), 73, np.uint8),
        frame_to_jpeg=lambda _: cv2.imencode('.jpg', np.full((32, 32, 3), 73, np.uint8))[1].tobytes())
    camera.run()


class ProcessCameraTest(unittest.TestCase):
    def test_driving_exposure_priority_is_restored_and_unsupported_devices_are_untouched(self):
        from astra_camera import prefer_color_frame_rate, restore_color_exposure_priority
        sdk = types.SimpleNamespace(OBPropertyID=types.SimpleNamespace(
            OB_PROP_COLOR_AUTO_EXPOSURE_PRIORITY_INT=2012),
            OBPermissionType=types.SimpleNamespace(PERMISSION_READ=1, PERMISSION_WRITE=2))
        pipeline = Mock()
        device = pipeline.get_device.return_value
        device.is_property_supported.return_value = True
        device.get_int_property.return_value = 1
        with patch.dict(sys.modules, pyorbbecsdk=sdk):
            previous = prefer_color_frame_rate(pipeline)
            device.set_int_property.assert_called_once_with(2012, 0)
            restore_color_exposure_priority(pipeline, previous)
            device.set_int_property.assert_called_with(2012, 1)
            device.reset_mock()
            device.is_property_supported.return_value = False
            self.assertIsNone(prefer_color_frame_rate(pipeline))
            restore_color_exposure_priority(pipeline, None)
            device.set_int_property.assert_not_called()

    def test_sensor_jpeg_padding_is_removed_without_reencoding(self):
        from astra_camera import frame_to_jpeg
        jpeg = cv2.imencode('.jpg', np.full((32, 32, 3), 73, np.uint8))[1].tobytes()
        frame = Mock()
        frame.get_format.return_value = 'mjpg'
        frame.get_data.return_value = np.frombuffer(jpeg + b'\0', dtype=np.uint8)
        with patch.dict(sys.modules, pyorbbecsdk=types.SimpleNamespace(
                OBFormat=types.SimpleNamespace(MJPG='mjpg'))):
            self.assertEqual(frame_to_jpeg(frame), jpeg)
            frame.get_data.return_value = np.frombuffer(jpeg[:-2], dtype=np.uint8)
            with self.assertRaises(ValueError):
                frame_to_jpeg(frame)

    def test_phone_jpeg_publication_preview_and_snapshot_share_one_capture(self):
        context = get_context('spawn')
        camera = CameraBroadcaster(dict(height=32, width=32, fps=30, jpeg_only=True))
        opens, stopped = context.Value('i', 0), context.Event()
        process = context.Process(target=capture_worker, args=(camera, opens, stopped, False))
        preview = CameraStream(camera, fps=30)
        try:
            process.start()
            self.assertTrue(camera.wait_until_ready(process, timeout=5))
            jpeg, stamp = camera.read_jpeg()
            self.assertTrue(jpeg.startswith(b'\xff\xd8'))
            self.assertTrue(np.all(camera.read()[0] == 73))
            camera.wait_for_frame(stamp)
            self.assertGreater(camera.read_jpeg()[1], stamp)
            # Streaming must copy the original compressed frame, never encode it again.
            with patch('camera_preview.cv2.imencode', side_effect=AssertionError('unexpected encode')):
                preview.start()
                with preview.condition:
                    preview.condition.wait_for(lambda: preview.sequence > 1 or preview.error, timeout=2)
                self.assertIsNone(preview.error)
                self.assertGreater(preview.sequence, 1)
                self.assertEqual(preview.jpeg, jpeg)
                preview.close()
            self.assertEqual(opens.value, 1)
            preview = CameraStream(camera, fps=30, quality=75)
            preview.jpeg_scale = 2
            preview.start()
            with preview.condition:
                preview.condition.wait_for(lambda: preview.sequence > 1 or preview.error, timeout=2)
            self.assertIsNone(preview.error)
            self.assertEqual(cv2.imdecode(np.frombuffer(preview.jpeg, dtype=np.uint8),
                                         cv2.IMREAD_COLOR).shape, (16, 16, 3))
            self.assertEqual(camera.read()[0].shape, (32, 32, 3))
            preview.close()
        finally:
            preview.close()
            camera.stop_sign.value = True
            process.join(3)
            if process.is_alive():
                process.terminate()
                process.join(3)
            process.close()
            camera.close()

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
