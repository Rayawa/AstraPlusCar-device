"""Phone movement and HTTP contract without hardware or loopback sockets."""
import time
import unittest
from concurrent.futures import Future
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import parse_args
from motion_control import CommandInbox, MotionArbiter
from phone_mode import PhoneControl, PhoneError, PhoneHandler
from src.actions import Advance, SpinAntiClockwise, Stop


class PhoneModeTest(unittest.TestCase):
    def setUp(self):
        self.chassis = Mock()
        self.arbiter = MotionArbiter(self.chassis, Mock())
        self.phone = PhoneControl(CommandInbox())
        self.session = self.phone.open_session()['sessionId']

    def request(self, kind, seq, command_id, **extra):
        return self.phone._process(kind,
                                   {'sessionId': self.session, 'seq': seq,
                                    'commandId': command_id, **extra}, self.arbiter)

    def test_phone_defaults_enable_camera_and_lidar(self):
        args = parse_args(['--phone'])
        self.assertEqual(args.mode, 'phone')
        self.assertTrue(args.camera)
        self.assertTrue(args.lidar)

    def test_motion_renewal_does_not_repeat_action_and_timeout_stops(self):
        self.request('command', 1, 'one', key='w')
        self.assertIsInstance(self.chassis.execute.call_args.args[0], Advance)
        calls = self.chassis.execute.call_count
        self.request('renew', 2, 'one')
        self.assertEqual(self.chassis.execute.call_count, calls)
        self.phone.lease_until = time.monotonic() - 0.01
        self.phone.tick(self.arbiter)
        self.assertIsInstance(self.chassis.execute.call_args.args[0], Stop)
        with self.assertRaises(PhoneError):
            self.request('command', 3, 'late', key='w')

    def test_duplicate_speed_and_old_sequence_cannot_override_stop(self):
        self.request('speed', 1, 'speed-one', speed=60)
        self.request('speed', 1, 'speed-one', speed=60)
        self.assertEqual(self.arbiter.speed, 60)
        self.request('command', 2, 'move', key='w')
        with self.assertRaises(PhoneError):
            self.request('command', 1, 'old', key='s')
        self.request('stop', 3, 'stop')
        self.assertIsInstance(self.chassis.execute.call_args.args[0], Stop)
        with self.assertRaises(PhoneError):
            self.request('command', 4, 'late', key='s')

    def test_turn_renewal_cannot_extend_timer_and_speed_stops_turn(self):
        self.request('command', 1, 'turn', key='z')
        self.assertIsInstance(self.chassis.execute.call_args.args[0], SpinAntiClockwise)
        deadline = self.arbiter.deadline
        self.request('renew', 2, 'turn')
        self.assertEqual(self.arbiter.deadline, deadline)
        self.request('speed', 2, 'speed-two', speed=30)
        self.assertIsNone(self.arbiter.deadline)
        self.assertIsInstance(self.chassis.execute.call_args.args[0], Stop)

    def test_queued_stop_blocks_a_late_motion_request(self):
        self.request('command', 1, 'move', key='w')
        stop = Future()
        late = Future()
        self.phone.queue.put(('command', {'sessionId': self.session, 'seq': 2,
                                          'commandId': 'late', 'key': 's'}, late, time.monotonic()))
        self.phone.urgent.put(('stop', {'sessionId': self.session}, stop, time.monotonic()))
        self.phone.tick(self.arbiter)
        self.assertTrue(stop.result()['accepted'])
        with self.assertRaises(PhoneError):
            late.result()
        self.assertIsInstance(self.chassis.execute.call_args.args[0], Stop)


class PhoneHttpTest(unittest.TestCase):
    def handler(self, path, body=b''):
        handler = PhoneHandler.__new__(PhoneHandler)
        handler.path = path
        handler.headers = {'Content-Length': str(len(body))}
        handler.rfile = BytesIO(body)
        handler.wfile = BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.server = SimpleNamespace(
            control=SimpleNamespace(status=lambda: {'bootId': 'test', 'speed': 40},
                                    submit=Mock(return_value={'accepted': True, 'speed': 40})),
            stream=object(), lidar=object(), snapshots=Mock())
        return handler

    def test_status_and_control_routes_match_contract(self):
        handler = self.handler('/api/v1/status')
        with patch('phone_mode.preview_status', return_value={'camera': {'status': 'live'}, 'lidar': {'points': 5}}):
            handler.do_GET()
        self.assertIn(b'"lidar": {"points": 5}', handler.wfile.getvalue())
        handler = self.handler('/api/v1/control/command',
                               b'{"sessionId":"s","seq":1,"commandId":"c","key":"w"}')
        handler.do_POST()
        handler.server.control.submit.assert_called_once()
        self.assertEqual(handler.server.control.submit.call_args.args[0], 'command')
        self.assertIn(b'"accepted": true', handler.wfile.getvalue())

    def test_capture_download_is_limited_to_saved_jpeg(self):
        with TemporaryDirectory() as directory:
            Path(directory, 'capture.jpg').write_bytes(b'jpeg-data')
            handler = self.handler('/api/v1/camera/captures/capture.jpg')
            handler.server.capture_dir = Path(directory)
            handler.do_GET()
            self.assertEqual(handler.wfile.getvalue(), b'jpeg-data')
            handler = self.handler('/api/v1/camera/captures/..')
            handler.server.capture_dir = Path(directory)
            handler.do_GET()
            handler.send_response.assert_called_with(400)


if __name__ == '__main__':
    unittest.main()
