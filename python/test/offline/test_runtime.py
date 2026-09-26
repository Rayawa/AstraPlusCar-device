"""Hardware-free contracts for composable runtime services.

Run: PYTHONPATH=python python -m unittest discover -s python/test/offline -v
"""
from contextlib import ExitStack, redirect_stderr
import io
import itertools
import json
from pathlib import Path
from queue import Queue
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import urlopen

import cv2
import numpy as np

import main
from camera_preview import CameraStream, PreviewHandler, PreviewService, preview_status, PAGE
from camera_tasks import SnapshotWriter
from motion_control import Command, CommandInbox, MotionArbiter
from src.actions import Advance, BackUp, Stop, Sleep
from src.actions.complex_actions import ComplexAction
from src.utils.camera_broadcaster import CameraBroadcaster, read_frame
from voice_control import VoiceService, check_voice_ready


class ArgumentsTest(unittest.TestCase):
    def test_all_mode_feature_combinations(self):
        for mode, features in itertools.product(('manual', 'cmd', 'easy'), itertools.product((False, True), repeat=3)):
            flags = [flag for flag, enabled in zip(('--camera', '--voice', '--lidar'), features) if enabled]
            for selector in (['--' + mode], ['--mode', mode]):
                with self.subTest(mode=mode, flags=flags, selector=selector):
                    args = main.parse_args(selector + flags)
                    self.assertEqual(args.mode, mode)
                    self.assertEqual((args.camera, args.voice, args.lidar), features)
        self.assertTrue(main.parse_args(['--radar']).lidar)
        self.assertTrue(main.parse_args(['--mode', 'voice']).voice)
        self.assertEqual(main.parse_args(['--mode', 'voice']).mode, 'manual')
        self.assertFalse(main.parse_args(['--manual']).camera)

    def test_conflicting_modes_and_invalid_values(self):
        for flags in (['--manual', '--easy'], ['--manual', '--mode', 'cmd'],
                      ['--voice-move-seconds', '0'], ['--voice-move-seconds', 'nan'],
                      ['--camera-port', '65536'], ['--lidar-baudrate', '0']):
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main.parse_args(flags)

    def test_voice_model_can_be_configured_without_extra_flag(self):
        with tempfile.TemporaryDirectory() as model, patch.dict('os.environ', {'VOSK_MODEL_PATH': model}):
            args = main.parse_args(['--manual', '--camera', '--voice', '--lidar'])
            self.assertEqual(args.voice_model, model)

    def test_missing_features_reported_together(self):
        args = main.parse_args(['--voice', '--lidar'])
        with patch('voice_control.check_voice_ready', side_effect=RuntimeError('microphone/model missing')), \
                patch('lidar_probe.check_lidar_ready', side_effect=RuntimeError('device missing')):
            with self.assertRaisesRegex(RuntimeError, 'Voice:.*missing\nLidar:.*missing'):
                main.check_features(args)

    def test_probe_checks_capture_not_just_sound_card(self):
        result = types.SimpleNamespace(returncode=1, stderr=b'no capture device')
        with patch('voice_control.shutil.which', return_value='/usr/bin/arecord'), \
                patch('voice_control.subprocess.run', return_value=result) as run, \
                patch.dict('sys.modules', {'vosk': types.ModuleType('vosk')}):
            with self.assertRaisesRegex(RuntimeError, 'Voice model missing.*no capture device'):
                check_voice_ready(None, 'hw:2,0')
            self.assertIn('hw:2,0', run.call_args.args[0])


class MotionTest(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.ctrl = Mock()
        self.snapshot = Mock()
        self.driver = MotionArbiter(self.ctrl, self.snapshot, clock=lambda: self.now)

    def command(self, key, source='keyboard', issued=None, started=None):
        return self.driver.handle(Command(key, source, self.now if issued is None else issued, started))

    def test_keyboard_cancels_voice_timer(self):
        self.command('w', 'voice')
        self.now += .2
        self.command('s')
        calls = self.ctrl.execute.call_count
        self.now += 2
        self.driver.tick()
        self.assertEqual(self.ctrl.execute.call_count, calls)
        self.assertIsInstance(self.ctrl.execute.call_args.args[0], BackUp)

    def test_new_voice_action_replaces_old_timer(self):
        self.command('w', 'voice')
        self.now += .8
        self.command('s', 'voice')
        self.now += .3
        self.driver.tick()
        self.assertIsInstance(self.ctrl.execute.call_args.args[0], BackUp)
        self.now += .8
        self.driver.tick()
        self.assertIsInstance(self.ctrl.execute.call_args.args[0], Stop)

    def test_stale_and_pre_takeover_speech_cannot_move(self):
        self.command('w')
        self.now += .3
        self.command('s', 'voice', started=9)
        self.command('s', 'voice', issued=8)
        self.command('s', issued=7)
        self.assertEqual(self.ctrl.execute.call_count, 1)
        self.assertIsInstance(self.ctrl.execute.call_args.args[0], Advance)

    def test_stop_prioritized_and_discards_backlog(self):
        inbox = CommandInbox()
        for _ in range(100):
            inbox.put(Command('w', 'voice'))
        inbox.put(Command('space', 'voice', issued_at=1))
        inbox.put(Command('s'))
        commands = inbox.drain()
        self.assertEqual([c.key for c in commands], ['space'])
        self.driver.handle(commands[0])
        self.assertIsInstance(self.ctrl.execute.call_args.args[0], Stop)
        self.command('w', 'voice', issued=9.9)
        self.assertEqual(self.ctrl.execute.call_count, 1)

    def test_screenshot_does_not_cancel_motion_or_timer(self):
        self.command('w', 'voice')
        self.now += .2
        self.command('p')
        self.snapshot.assert_called_once()
        self.now += 1
        self.driver.tick()
        self.assertIsInstance(self.ctrl.execute.call_args.args[0], Stop)

    def test_speed_takeover_and_timed_turn(self):
        self.command('w', 'voice')
        self.now += .2
        self.command('up')
        self.assertEqual(self.ctrl.execute.call_args.args[0].speed, 60)
        self.now += 2
        self.driver.tick()
        self.assertIsInstance(self.ctrl.execute.call_args.args[0], Advance)
        self.now += .1
        self.command('z')
        self.now += self.driver.TURN_DURATION + .1
        self.driver.tick()
        self.assertIsInstance(self.ctrl.execute.call_args.args[0], Stop)

    def test_ai_sequence_sleep_is_interruptible(self):
        action = ComplexAction()
        action.action_seq = [Advance(40), Sleep(3), BackUp(30)]
        self.driver.scene_action(action, self.now)
        self.assertIsInstance(self.ctrl.execute.call_args.args[0], Advance)
        self.now += .1
        self.command('space')
        calls = self.ctrl.execute.call_count
        self.now += 4
        self.driver.tick()
        self.driver.scene_action(BackUp(30), self.now)
        self.assertEqual(self.ctrl.execute.call_count, calls)


class Memory:
    def __init__(self, create=True, size=12):
        self.buf = bytearray(size)
        self.name = 'offline-frame'
        self.closed = self.unlinked = False

    def close(self):
        self.closed = True

    def unlink(self):
        self.unlinked = True


class SharedCameraTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('src.utils.camera_broadcaster.shared_memory.SharedMemory', Memory))
        self.camera = CameraBroadcaster(dict(width=2, height=2, fps=30))
        self.addCleanup(self.camera.close)
        self.publish(90)

    def publish(self, value):
        with self.camera.frame_lock:
            self.camera.frame.buf[:] = bytes([value] * 12)
            self.camera.last_frame_time.value = time.monotonic()
            self.camera.ready.set()

    def test_copy_complete_and_not_aliasing(self):
        frame, _ = self.camera.read()
        self.publish(25)
        self.assertTrue(np.all(frame == 90))
        self.assertTrue(np.all(self.camera.read()[0] == 25))

    def test_torn_frame_is_never_read(self):
        self.camera.frame_lock.acquire()
        self.camera.frame.buf[:6] = bytes([12] * 6)
        result = []
        reader = threading.Thread(target=lambda: result.append(self.camera.read()[0]))
        reader.start()
        time.sleep(.03)
        self.assertEqual(result, [])
        self.camera.frame.buf[6:] = bytes([12] * 6)
        self.camera.frame_lock.release()
        reader.join(1)
        self.assertTrue(np.all(result[0] == 12))

    def test_dead_producer_lock_is_bounded(self):
        self.camera.frame_lock.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, 'lock timed out'):
                self.camera.read()
        finally:
            self.camera.frame_lock.release()

    def test_failure_or_stale_frame_rejected(self):
        self.camera.failed.set()
        with self.assertRaises(RuntimeError):
            self.camera.read()
        self.camera.failed.clear()
        self.camera.last_frame_time.value = time.monotonic() - 3
        with self.assertRaises(RuntimeError):
            self.camera.read()

    def test_page_status_displays_fresh_frame_and_optional_lidar(self):
        stream = types.SimpleNamespace(condition=threading.Condition(), stamp=time.monotonic(),
                                       stopping=False, camera=self.camera)
        lidar = types.SimpleNamespace(status=Mock(return_value={
            'status': 'scanning', 'points': 20, 'front_nearest_mm': 340}))
        self.assertIn(b'/status.json', PAGE)
        self.assertIn('服务端时间'.encode(), PAGE)
        live = preview_status(stream, lidar)
        self.assertEqual(live['camera']['status'], 'live')
        self.assertTrue(live['camera']['frame_time'])
        self.assertEqual(live['lidar']['front_nearest_mm'], 340)
        self.assertIsNone(preview_status(stream)['lidar'])
        stream.stamp = time.monotonic() - 3
        self.assertEqual(preview_status(stream, lidar)['camera']['status'], 'stale')
        stream.stamp = time.monotonic()
        self.camera.failed.set()
        self.assertEqual(preview_status(stream, lidar)['camera']['status'], 'unavailable')

    def test_status_endpoint_is_json_and_never_reads_camera_frame(self):
        stream = types.SimpleNamespace(condition=threading.Condition(), stamp=time.monotonic(),
                                       stopping=False, camera=self.camera)
        self.camera.read = Mock(side_effect=AssertionError('status copied a frame'))
        handler = PreviewHandler.__new__(PreviewHandler)
        handler.path = '/status.json'
        handler.connection = Mock()
        handler.server = types.SimpleNamespace(stream=stream, lidar=types.SimpleNamespace(
            status=lambda: {'status': 'scanning', 'nearest_mm': 250}))
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.do_GET()
        handler.send_response.assert_called_once_with(200)
        self.assertEqual(json.loads(handler.wfile.getvalue())['lidar']['nearest_mm'], 250)
        self.camera.read.assert_not_called()

    def writer(self, directory):
        writer = SnapshotWriter(self.camera, directory, report=lambda _: None)
        writer.start()
        self.addCleanup(writer.close)
        return writer

    def test_consecutive_screenshots_unique_real_jpegs(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = self.writer(directory)
            results = [f.result(2) for f in [writer.request() for _ in range(6)]]
            self.assertEqual(len({path for path, _ in results}), 6)
            for path, jpeg in results:
                self.assertEqual(path.read_bytes(), jpeg)
                image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                self.assertTrue(np.all(image == 90))
            self.camera.failed.set()
            with self.assertRaises(RuntimeError):
                writer.request().result(2)
            self.assertEqual(len(list(Path(directory).glob('*.jpg'))), 6)
            writer.close()

    def test_disk_error_reported_and_keyboard_not_blocked(self):
        entered, release = threading.Event(), threading.Event()
        def slow_write(path, data):
            entered.set()
            release.wait(2)
            raise OSError('disk full')
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'write_bytes', slow_write):
            writer = self.writer(directory)
            future = writer.request()
            self.assertTrue(entered.wait(1))
            ctrl = Mock()
            driver = MotionArbiter(ctrl, writer.request)
            driver.handle(Command('w'))
            driver.handle(Command('space'))
            self.assertIsInstance(ctrl.execute.call_args.args[0], Stop)
            release.set()
            with self.assertRaisesRegex(OSError, 'disk full'):
                future.result(2)
            writer.close()

    def test_preview_and_web_snapshot_share_camera_and_reject_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = self.writer(directory)
            try:
                preview = PreviewService(self.camera, writer, port=0)
            except PermissionError:
                self.skipTest('loopback sockets are unavailable in this sandbox')
            preview.start()
            self.addCleanup(preview.close)
            root = f'http://127.0.0.1:{preview.server.server_port}'
            with urlopen(root + '/snapshot.jpg', timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read().startswith(b'\xff\xd8'))
            self.assertEqual(len(list(Path(directory).glob('*.jpg'))), 1)
            self.camera.failed.set()
            with self.assertRaises(HTTPError) as error:
                urlopen(root + '/snapshot.jpg', timeout=2)
            self.assertEqual(error.exception.code, 503)
            preview.close()
            writer.close()

    def test_one_camera_pipeline_for_preview_and_snapshots(self):
        pipeline = Mock()
        pipeline.wait_for_frames.side_effect = lambda timeout: (time.sleep(.01) or pipeline)
        pipeline.get_color_frame.return_value = object()
        sdk = types.SimpleNamespace(open_color_pipeline=Mock(return_value=(pipeline, 'fake')),
                                    frame_to_bgr_image=lambda _: np.full((2, 2, 3), 90, np.uint8))
        with patch.dict('sys.modules', {'astra_camera': sdk}), tempfile.TemporaryDirectory() as directory:
            capture = threading.Thread(target=self.camera.run)
            capture.start()
            try:
                self.assertTrue(self.camera.ready.wait(1))
                writer = self.writer(directory)
                preview = CameraStream(self.camera)
                preview.start()
                try:
                    for _ in range(3):
                        writer.request().result(2)
                    self.camera.read()  # The AI reader uses the same copy contract.
                    sdk.open_color_pipeline.assert_called_once_with(2, 2, 30)
                finally:
                    preview.close()
                    writer.close()
            finally:
                self.camera.stop_sign.value = True
                capture.join(1)
            pipeline.stop.assert_called_once()


class VoiceTest(unittest.TestCase):
    def test_recognition_runs_in_background_and_closes(self):
        release = threading.Event()
        class Recognizer:
            phrase_started = time.monotonic()
            def __enter__(self):
                return self
            def __iter__(self):
                release.wait(2)
                yield '拍照'
            def __exit__(self, *args):
                release.set()
        inbox = CommandInbox()
        with patch('voice_control.VoiceRecognizer', return_value=Recognizer()):
            service = VoiceService(None, None, inbox, report=lambda _: None)
            service.start()
            inbox.put(Command('w'))
            self.assertEqual(inbox.drain()[0].key, 'w')
            service.close()
            self.assertFalse(service.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
