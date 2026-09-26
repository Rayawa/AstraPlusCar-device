#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Primary mode plus independently enabled preview, speech and lidar services."""
from argparse import ArgumentParser
from contextlib import ExitStack
from multiprocessing import get_context
from queue import Empty
import os
from pathlib import Path
import select
import signal
import sys


def parse_args(argv=None):
    from lidar_probe import DEFAULT_PORT, DEFAULT_SDK
    parser = ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--mode', choices=['cmd', 'voice', 'manual', 'easy'])
    for mode in ('manual', 'cmd', 'easy'):
        modes.add_argument('--' + mode, dest='mode', action='store_const', const=mode)
    parser.add_argument('--camera', action='store_true', help='enable browser live preview')
    parser.add_argument('--voice', action='store_true', help='enable background speech commands')
    parser.add_argument('--lidar', '--radar', action='store_true', help='enable lidar status and distances')
    parser.add_argument('--camera-port', type=int, default=8765)
    parser.add_argument('--capture-dir', default='capture')
    parser.add_argument('--voice-model', help='directory containing an offline Vosk model')
    parser.add_argument('--voice-device', help='optional ALSA microphone device name')
    parser.add_argument('--voice-move-seconds', type=float, default=1.0)
    parser.add_argument('--lidar-sdk', default=str(DEFAULT_SDK))
    parser.add_argument('--lidar-port', default=DEFAULT_PORT)
    parser.add_argument('--lidar-baudrate', type=int, default=115200)
    args = parser.parse_args(argv)
    args.mode = args.mode or 'manual'
    if args.mode == 'voice':
        args.mode, args.voice = 'manual', True
    if args.voice and args.voice_model is None:
        candidate = os.environ.get('VOSK_MODEL_PATH')
        if candidate is None:
            candidate = Path(__file__).resolve().parent / 'weights' / 'vosk-model'
        if Path(candidate).is_dir():
            args.voice_model = str(candidate)
    if not 0 < args.voice_move_seconds <= 5:
        parser.error('--voice-move-seconds must be greater than 0 and at most 5')
    if not 1 <= args.camera_port <= 65535 or args.lidar_baudrate <= 0:
        parser.error('camera port must be 1..65535 and lidar baudrate must be positive')
    return args


def check_features(args):
    errors = []
    if args.voice:
        from voice_control import check_voice_ready
        try:
            check_voice_ready(args.voice_model, args.voice_device)
        except Exception as exc:
            errors.append(f'Voice: {exc}')
    if args.lidar:
        from lidar_probe import check_lidar_ready
        try:
            check_lidar_ready(args.lidar_sdk, args.lidar_port)
        except Exception as exc:
            errors.append(f'Lidar: {exc}')
    if errors:
        raise RuntimeError('Startup checks failed:\n' + '\n'.join(errors))


def stop_process(process, graceful=False):
    if process.pid is None:
        return
    if graceful and process.is_alive():
        process.join(timeout=2)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
    if process.is_alive():
        process.kill()
        process.join(timeout=2)
    process.close()


def stop_on_signal(_signum, _frame):
    raise KeyboardInterrupt


def run_scene(name, memory_name, camera_info, queue):
    signal.signal(signal.SIGTERM, stop_on_signal)
    from src.scenes import scene_initiator
    task = None
    try:
        task = scene_initiator(name)(memory_name, camera_info, queue)
        task.loop()
    except KeyboardInterrupt:
        pass
    finally:
        if task is not None:
            task.broadcaster.close()


def run(args):
    check_features(args)
    from camera_tasks import SnapshotWriter
    from motion_control import Command, CommandInbox, MotionArbiter
    from src.actions import Stop
    from src.utils import CAMERA_INFO, CameraBroadcaster, getkey, log

    context = get_context('spawn')
    inbox = CommandInbox()
    ctrl = None
    scene_process = None
    scene_info = None
    generation = 0
    scene_pending = False
    arbiter = None
    services = []

    def stop_scene():
        nonlocal scene_process, scene_info
        if scene_process is not None:
            scene_info['scene_stop'].set()
            scene_info['scene_stop_sign'].value = True
            try:
                stop_process(scene_process, graceful=True)
            finally:
                scene_process = None

    def safe_stop():
        if ctrl is not None:
            try:
                ctrl.execute(Stop())
            except Exception:
                log.exception('Failed to stop the chassis')

    with ExitStack() as cleanup:
        camera = CameraBroadcaster(CAMERA_INFO)
        cleanup.callback(camera.close)
        camera_process = context.Process(target=camera.run, name='camera-capture')

        def close_camera():
            camera.stop_sign.value = True
            stop_process(camera_process, graceful=True)

        cleanup.callback(close_camera)
        camera_process.start()
        if not camera.wait_until_ready(camera_process):
            raise RuntimeError('Astra+ did not deliver a color frame; check the camera log')
        snapshots = SnapshotWriter(camera, args.capture_dir, log.info)
        cleanup.callback(snapshots.close)
        snapshots.start()
        if args.camera:
            from camera_preview import PreviewService
            preview = PreviewService(camera, snapshots, args.camera_port)
            cleanup.callback(preview.close)
            preview.start()
            services.append(preview.stream)
        if args.voice:
            from voice_control import VoiceService
            voice = VoiceService(args.voice_model, args.voice_device, inbox, log.info)
            cleanup.callback(voice.close)
            voice.start()
            services.append(voice)
        if args.lidar:
            from lidar_probe import LidarService
            lidar = LidarService(args.lidar_sdk, args.lidar_port, args.lidar_baudrate, log.info)
            cleanup.callback(lidar.close)
            lidar.start()
            services.append(lidar)
            if args.camera:
                preview.set_lidar(lidar)

        # Only this process opens the chassis, after optional services are ready.
        from src.utils import Controller
        ctrl = Controller()
        cleanup.callback(stop_scene)
        cleanup.callback(safe_stop)  # LIFO: stop motors before waiting for any worker.
        safe_stop()
        arbiter = MotionArbiter(ctrl, snapshots.request, args.voice_move_seconds)
        action_queue, scene_queue = context.Queue(maxsize=8), context.Queue(maxsize=1)
        # Queues are consumed before closing; no parent feeder is left waiting.
        def close_queues():
            for queue in (action_queue, scene_queue):
                queue.cancel_join_thread()
                queue.close()
        cleanup.callback(close_queues)

        def start_scene(name):
            nonlocal scene_process, scene_info, generation, scene_pending
            arbiter.stop()
            stop_scene()
            generation += 1
            scene_pending = False
            arbiter.scene_enabled = True
            scene_info = dict(camera.camera_info(), action_queue=action_queue,
                              scene_stop=context.Event(), scene_stop_sign=context.Value('b', False),
                              generation=generation, action_completed=context.Event())
            scene_process = context.Process(target=run_scene,
                                            args=(name, camera.memory_name, scene_info, scene_queue))
            scene_process.start()

        if args.mode == 'easy':
            start_scene('Helper')
        log.info(f'Ready: mode={args.mode}, camera={args.camera}, voice={args.voice}, lidar={args.lidar}')
        while True:
            camera.check_fresh()
            if not camera_process.is_alive():
                raise RuntimeError('Camera process exited')
            for service in services:
                if service.error is not None:
                    raise RuntimeError(f'{type(service).__name__} failed: {service.error}')
            if scene_process is not None and not scene_process.is_alive():
                autonomous = arbiter.scene_enabled
                if autonomous:
                    arbiter.stop()
                stop_scene()
                if autonomous and args.mode == 'easy':
                    raise RuntimeError('Helper scene exited')
                log.info('Scene exited' + ('; chassis stopped' if autonomous else '; human control active'))
            if args.mode == 'cmd':
                if select.select([sys.stdin], [], [], 0.02)[0]:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    name = line.strip()
                    if name == 'stop':
                        break
                    if name == 'clear':
                        arbiter.stop()
                        stop_scene()
                    elif name == 'p':
                        snapshots.request()
                    elif name == 'Manual':
                        log.error('Use --manual to select keyboard driving')
                    else:
                        from src.scenes import SCENE_NAMES
                        if name in SCENE_NAMES:
                            start_scene(name)
                        else:
                            log.error(f'{name} is not a valid scene.')
            else:
                key = getkey(timeout=0.02)
                if key is not None:
                    inbox.put(Command(key))
            quitting = False
            for command in inbox.drain():
                quitting = arbiter.handle(command) or quitting
            if quitting:
                break
            # A human motion/stop command takes over an AI scene until explicitly restarted.
            if not arbiter.scene_enabled and scene_process is not None:
                scene_info['scene_stop'].set()
                scene_info['scene_stop_sign'].value = True
            arbiter.tick()
            if scene_pending and not arbiter.sequence and arbiter.sequence_deadline is None:
                scene_info['action_completed'].set()
                scene_pending = False
            try:
                for _ in range(8):
                    version, issued, action = action_queue.get_nowait()
                    if version == generation and scene_process is not None:
                        scene_info['action_completed'].clear()
                        scene_pending = True
                        arbiter.scene_action(action, issued)
                        if not arbiter.sequence and arbiter.sequence_deadline is None:
                            scene_info['action_completed'].set()
                            scene_pending = False
            except Empty:
                pass


def main():
    args = parse_args()
    previous = {signum: signal.signal(signum, stop_on_signal)
                for signum in (signal.SIGTERM, signal.SIGHUP)}
    try:
        run(args)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    main()
