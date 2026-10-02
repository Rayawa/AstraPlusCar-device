"""Composition and cleanup tests with fake hardware, real main-loop arbitration."""
from contextlib import ExitStack, redirect_stdout
import io
import os
from queue import Queue
import signal
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

import main
from src.actions import Stop
import src.utils as utils


class CloseableQueue(Queue):
    def cancel_join_thread(self):
        pass
    def close(self):
        pass


class LifecycleTest(unittest.TestCase):
    def test_main_preserves_failure_and_records_traceback(self):
        failure = RuntimeError('camera became stale')
        logger = Mock()
        with patch.object(main, 'parse_args', return_value=types.SimpleNamespace()), \
                patch.object(main, 'run', side_effect=failure), \
                patch.dict(utils.__dict__, log=logger), \
                patch.object(main.signal, 'signal', return_value=signal.SIG_DFL):
            with self.assertRaises(RuntimeError) as raised:
                main.main()
        self.assertIs(raised.exception, failure)
        logger.exception.assert_called_once()

    def test_logging_failure_does_not_replace_runtime_failure(self):
        failure = RuntimeError('camera process exited')
        logger = Mock()
        logger.exception.side_effect = OSError('log storage unavailable')
        with patch.object(main, 'parse_args', return_value=types.SimpleNamespace()), \
                patch.object(main, 'run', side_effect=failure), \
                patch.dict(utils.__dict__, log=logger), \
                patch.object(main.signal, 'signal', return_value=signal.SIG_DFL):
            with self.assertRaises(RuntimeError) as raised:
                main.main()
        self.assertIs(raised.exception, failure)

    def exercise(self, flags, failure=None, mode='manual', service_failure=False):
        events = []
        camera = Mock()
        camera.memory_name = 'test'
        camera.stop_sign = types.SimpleNamespace(value=False)
        camera.wait_until_ready.return_value = True
        camera.camera_info.return_value = {}
        camera.close.side_effect = lambda: events.append('camera-close')
        class Process:
            def __init__(self, target, args=(), name=None):
                self.target, self.name, self.pid, self.alive = target, name, None, False
            def start(self):
                self.pid, self.alive = 123, True
            def is_alive(self):
                return self.alive
            def join(self, timeout=None):
                if camera.stop_sign.value:
                    self.alive = False
            def terminate(self):
                self.alive = False
            kill = terminate
            def close(self):
                events.append('process-close')
        context = types.SimpleNamespace(Process=Process, Queue=CloseableQueue,
                                        Event=threading.Event,
                                        Value=lambda _, value: types.SimpleNamespace(value=value))
        class Service:
            error = None
            def __init__(self, *args, **kwargs):
                self.stream = self
                self.lidar = None
            def set_lidar(self, lidar):
                self.lidar = lidar
                events.append('radar-on-page')
            def start(self):
                events.append('service-start')
                if service_failure:
                    raise RuntimeError('startup failure')
            def close(self):
                events.append('service-close')
            def request(self):
                events.append('screenshot')
        controller = Mock()
        controller.execute.side_effect = lambda action: events.append('stop' if isinstance(action, Stop) else 'move')
        keys = iter(['w', 'p', 'p', 's', 'space', 'esc'])
        def getkey(timeout):
            key = next(keys)
            if failure and key == 's':
                raise failure('injected input failure')
            return key
        args = main.parse_args(['--' + mode] + flags)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(utils.__dict__, CameraBroadcaster=Mock(return_value=camera),
                                          Controller=Mock(return_value=controller), getkey=getkey,
                                          log=Mock()))
            stack.enter_context(patch.object(main, 'get_context', return_value=context))
            stack.enter_context(patch.object(main, 'check_features'))
            # Simulated hardware must not contend with a running vehicle service.
            stack.enter_context(patch('main.fcntl.flock'))
            stack.enter_context(patch('camera_tasks.SnapshotWriter', Service))
            stack.enter_context(patch('camera_preview.PreviewService', Service))
            stack.enter_context(patch('voice_control.VoiceService', Service))
            stack.enter_context(patch('lidar_probe.LidarService', Service))
            if mode == 'cmd':
                stack.enter_context(patch('main.sys.stdin', io.StringIO('p\nclear\nstop\n')))
                stack.enter_context(patch('main.select.select', return_value=([1], [], [])))
            if failure or service_failure:
                with self.assertRaises(failure or RuntimeError):
                    main.run(args)
            else:
                main.run(args)
            utils.CameraBroadcaster.assert_called_once()
            if not service_failure:
                utils.Controller.assert_called_once()
                self.assertEqual(events.count('radar-on-page'),
                                 int(args.camera and args.lidar))
                self.assertIsInstance(controller.execute.call_args.args[0], Stop)
                self.assertLess(max(i for i, event in enumerate(events) if event == 'stop'),
                                events.index('service-close'))
            else:
                utils.Controller.assert_not_called()
        self.assertTrue(camera.stop_sign.value)
        self.assertEqual(events[-1], 'camera-close')
        self.assertEqual(events.count('service-start'), events.count('service-close'))
        return events

    def test_all_primary_modes_and_feature_combinations_start_and_clean_up(self):
        import itertools
        for mode, switches in itertools.product(('manual', 'cmd', 'easy'), itertools.product((False, True), repeat=3)):
            flags = [flag for flag, enabled in zip(('--camera', '--voice', '--lidar'), switches) if enabled]
            with self.subTest(mode=mode, flags=flags):
                events = self.exercise(flags, mode=mode)
                if mode != 'cmd':
                    self.assertEqual(events.count('screenshot'), 2)

    def test_abnormal_exit_stops_before_releasing_services(self):
        for failure in (RuntimeError, KeyboardInterrupt, EOFError):
            with self.subTest(failure=failure):
                self.exercise(['--camera', '--voice', '--lidar'], failure)

    def test_partial_startup_is_cleaned_without_opening_chassis(self):
        self.exercise(['--camera', '--voice', '--lidar'], service_failure=True)

    def test_sigterm_runs_through_finally(self):
        with self.assertRaises(KeyboardInterrupt):
            main.stop_on_signal(signal.SIGTERM, None)


class LidarTest(unittest.TestCase):
    def test_sensor_relative_sectors_keep_all_directions_distinct(self):
        import lidar_probe
        points = [lidar_probe.ScanPoint(angle, distance, 10) for angle, distance in
                  ((359, 450), (28, 380), (91, 700), (179, 920), (271, 610), (45, 100))]
        self.assertEqual(lidar_probe.sector_distances(points), {
            'front_nearest_mm': 380, 'sector_90_mm': 700,
            'sector_180_mm': 920, 'sector_270_mm': 610})

    def test_status_clears_expired_ranges(self):
        import lidar_probe
        service = lidar_probe.LidarService('sdk', 'port', 115200, report=lambda _: None)
        self.assertEqual(service.status()['status'], 'waiting')
        service.publish(dict(observed_at='2026-09-26T12:00:00+08:00', serial='ABC',
                             health='OK', status='scanning', points=10,
                             nearest_mm=200, front_nearest_mm=300,
                             sector_90_mm=400, sector_180_mm=500, sector_270_mm=600))
        self.assertEqual(service.status()['front_nearest_mm'], 300)
        service.updated_at = time.monotonic() - 3
        stale = service.status()
        self.assertEqual(stale['status'], 'stale')
        self.assertIsNone(stale['nearest_mm'])
        self.assertIsNone(stale['sector_90_mm'])
        self.assertIsNone(stale['sector_180_mm'])
        self.assertIsNone(stale['sector_270_mm'])
        service.error = RuntimeError('disconnected')
        self.assertEqual(service.status()['status'], 'error')

    def test_follow_emits_json_lines_and_stops_on_interrupt(self):
        import json
        import lidar_probe
        def fake_scan(*args, **kwargs):
            self.assertIsNone(kwargs['seconds'])
            for distance in (120, 180):
                kwargs['report']({'status': 'scanning', 'front_nearest_mm': distance})
            raise KeyboardInterrupt
        output = io.StringIO()
        with patch.object(lidar_probe, 'collect_scan', side_effect=fake_scan), \
                patch.object(lidar_probe.signal, 'signal') as signal_mock, \
                redirect_stdout(output):
            lidar_probe.main(['--follow'])
        self.assertEqual([json.loads(line)['front_nearest_mm']
                          for line in output.getvalue().splitlines()], [120, 180])
        self.assertEqual(signal_mock.call_count, 2)

    def test_single_probe_keeps_one_summary_json(self):
        import json
        import lidar_probe
        output = io.StringIO()
        with patch.object(lidar_probe, 'collect_scan', return_value={'health': 'OK', 'points': 42}) as scan, \
                redirect_stdout(output):
            lidar_probe.main(['--seconds', '2'])
        self.assertEqual(json.loads(output.getvalue()), {'health': 'OK', 'points': 42})
        self.assertEqual(scan.call_args.args[-1], 2)

    def test_continuous_status_and_motor_shutdown(self):
        import lidar_probe
        read_fd, write_fd = os.pipe()
        reader = os.fdopen(read_fd, 'rb', buffering=0)
        process = Mock(pid=123, stdout=reader)
        process.poll.return_value = None
        stopping = threading.Event()
        reports = []
        def report(summary):
            reports.append(summary)
            stopping.set()
        os.write(write_fd, b'Lidar health status : 0\ntheta: 5.00 Dist: 321.00 Q: 10\n')
        try:
            with patch.object(lidar_probe, 'check_lidar_ready'), \
                    patch.object(lidar_probe.subprocess, 'Popen', return_value=process), \
                    patch.object(lidar_probe.os, 'killpg') as kill:
                lidar_probe.collect_scan(seconds=None, stop_event=stopping, report=report)
                kill.assert_called_once_with(123, signal.SIGINT)
                process.wait.assert_called_once()
            self.assertTrue(reader.closed)
            self.assertEqual(reports[0]['status'], 'scanning')
            self.assertEqual(reports[0]['nearest_mm'], 321)
            self.assertEqual(reports[0]['front_nearest_mm'], 321)
            self.assertIsNone(reports[0]['sector_180_mm'])
        finally:
            reader.close()
            os.close(write_fd)

    def test_sdk_failure_still_stops_motor(self):
        import lidar_probe
        read_fd, write_fd = os.pipe()
        reader = os.fdopen(read_fd, 'rb', buffering=0)
        process = Mock(pid=123, stdout=reader)
        process.poll.return_value = None
        os.close(write_fd)
        try:
            with patch.object(lidar_probe, 'check_lidar_ready'), \
                    patch.object(lidar_probe.subprocess, 'Popen', return_value=process), \
                    patch.object(lidar_probe.os, 'killpg') as kill:
                with self.assertRaisesRegex(RuntimeError, 'output closed'):
                    lidar_probe.collect_scan(seconds=None)
                kill.assert_called_once_with(123, signal.SIGINT)
            self.assertTrue(reader.closed)
        finally:
            reader.close()

    def test_follow_interrupt_stops_lidar_motor(self):
        import lidar_probe
        read_fd, write_fd = os.pipe()
        reader = os.fdopen(read_fd, 'rb', buffering=0)
        process = Mock(pid=123, stdout=reader)
        process.poll.return_value = None
        try:
            with patch.object(lidar_probe, 'check_lidar_ready'), \
                    patch.object(lidar_probe.subprocess, 'Popen', return_value=process), \
                    patch.object(lidar_probe.select, 'select', side_effect=KeyboardInterrupt), \
                    patch.object(lidar_probe.os, 'killpg') as kill:
                with self.assertRaises(KeyboardInterrupt):
                    lidar_probe.collect_scan(seconds=None, report=lambda _: None)
                kill.assert_called_once_with(123, signal.SIGINT)
                process.wait.assert_called_once()
            self.assertTrue(reader.closed)
        finally:
            reader.close()
            os.close(write_fd)


if __name__ == '__main__':
    unittest.main()
