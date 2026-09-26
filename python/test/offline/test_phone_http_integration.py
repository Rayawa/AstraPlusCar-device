"""Exercise the real phone HTTP server with fake hardware on loopback."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import json
import time
import unittest
from urllib.request import Request, urlopen

import numpy as np

from camera_tasks import SnapshotWriter
from motion_control import CommandInbox, MotionArbiter
from phone_mode import PhoneControl, PhoneService
from src.actions import Advance, Stop


class FakeCamera:
    def read(self):
        return np.full((64, 96, 3), 127, dtype=np.uint8), time.monotonic()

    def check_fresh(self):
        pass


class FakeLidar:
    def status(self):
        return {'status': 'live', 'health': 'OK', 'points': 10,
                'nearest_mm': 500, 'front_nearest_mm': 600}


class FakeController:
    def __init__(self):
        self.actions = []

    def execute(self, action):
        self.actions.append(action)


class PhoneHttpIntegrationTest(unittest.TestCase):
    def test_control_preview_lidar_and_capture_over_http(self):
        with TemporaryDirectory() as directory:
            camera = FakeCamera()
            snapshots = SnapshotWriter(camera, directory, lambda _message: None)
            snapshots.start()
            controller = FakeController()
            arbiter = MotionArbiter(controller, snapshots.request)
            phone = PhoneControl(CommandInbox())
            try:
                service = PhoneService(camera, snapshots, FakeLidar(), phone, port=0, host='127.0.0.1')
            except OSError as exc:
                snapshots.close()
                self.skipTest(f'loopback unavailable: {exc}')
            stopping = Event()

            def pump():
                while not stopping.is_set():
                    phone.tick(arbiter)
                    arbiter.tick()
                    time.sleep(0.02)

            worker = Thread(target=pump, daemon=True)
            worker.start()
            service.start()
            base = f'http://127.0.0.1:{service.server.server_port}'

            def request(path, body=None):
                data = None if body is None else json.dumps(body).encode('utf-8')
                result = urlopen(Request(base + path, data=data,
                                         headers={'Content-Type': 'application/json'}), timeout=3)
                return result.read()

            try:
                status = json.loads(request('/api/v1/status'))
                self.assertEqual(status['lidar']['front_nearest_mm'], 600)
                deadline = time.monotonic() + 2
                while service.stream.sequence == 0 and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(request('/api/v1/camera/frame.jpg').startswith(b'\xff\xd8'))
                stream_response = urlopen(base + '/api/v1/camera/stream.mjpg', timeout=3)
                try:
                    self.assertIn('multipart/x-mixed-replace', stream_response.headers['Content-Type'])
                    self.assertIn(b'Content-Type: image/jpeg', stream_response.read(256))
                finally:
                    stream_response.close()
                capture = json.loads(request('/api/v1/camera/captures', {}))
                capture_id = capture['captureId']
                self.assertTrue(Path(directory, capture_id).is_file())
                self.assertEqual(request('/api/v1/camera/captures/' + capture_id),
                                 Path(directory, capture_id).read_bytes())
                session = json.loads(request('/api/v1/control/session', {}))['sessionId']
                speed = {'sessionId': session, 'seq': 1, 'commandId': 'speed-1', 'speed': 60}
                self.assertEqual(json.loads(request('/api/v1/control/speed', speed))['speed'], 60)
                move = {'sessionId': session, 'seq': 2, 'commandId': 'move-1', 'key': 'w'}
                self.assertTrue(json.loads(request('/api/v1/control/command', move))['accepted'])
                self.assertIsInstance(controller.actions[-1], Advance)
                self.assertEqual(controller.actions[-1].speed, 60)
                request('/api/v1/control/renew', {'sessionId': session, 'commandId': 'move-1'})
                request('/api/v1/control/stop', {'sessionId': session})
                self.assertIsInstance(controller.actions[-1], Stop)
            finally:
                stopping.set()
                worker.join(timeout=2)
                service.close()
                snapshots.close()
