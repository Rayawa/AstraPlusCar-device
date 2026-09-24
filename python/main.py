#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
from argparse import ArgumentParser
from multiprocessing import Process, Queue
from queue import Full

from src.actions import Stop
from src.scenes import Manual, scene_initiator
from src.utils import CAMERA_INFO, CameraBroadcaster, Controller, getkey, log


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('--mode', default='manual', choices=['cmd', 'voice', 'manual', 'easy'])
    return parser.parse_args()


def stop_process(process, graceful=False):
    if graceful and process.is_alive():
        process.join(timeout=2)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
    if process.is_alive():
        process.kill()
        process.join()


def main():
    args = parse_args()
    if args.mode == 'voice':
        raise NotImplementedError('voice control is not currently supported.')

    log.info('start')
    camera = CameraBroadcaster(CAMERA_INFO)
    camera_process = Process(target=camera.run)
    msg_queue = Queue(maxsize=1)
    processes = []
    ctrl = None
    try:
        camera_process.start()
        if not camera.wait_until_ready(camera_process):
            raise RuntimeError('Astra+ did not deliver a color frame; check the camera log')

        camera_info = dict(CAMERA_INFO, last_frame_time=camera.last_frame_time)
        ctrl = Controller()
        if args.mode == 'manual':
            task = Manual(camera.memory_name, camera_info, msg_queue)
            process = Process(target=task.loop)
            process.start()
            processes.append(process)
            while True:
                key = getkey()
                if key == 'esc':
                    try:
                        msg_queue.put('esc', timeout=1)
                    except Full:
                        pass
                    break
                msg_queue.put(key)

        elif args.mode == 'cmd':
            while True:
                command = input().strip()
                if command == 'stop':
                    break
                if command == 'clear':
                    for process in processes:
                        stop_process(process)
                    processes.clear()
                    ctrl.execute(Stop())
                    continue
                if command == 'Manual':
                    log.error('Does not support switching from cmd mode to manual mode')
                    continue
                scene = scene_initiator(command)
                if scene is not None:
                    task = scene(camera.memory_name, camera_info, msg_queue)
                    process = Process(target=task.loop)
                    process.start()
                    processes.append(process)

        elif args.mode == 'easy':
            task = scene_initiator('Helper')(camera.memory_name, camera_info, msg_queue)
            process = Process(target=task.loop)
            process.start()
            processes.append(process)
            while getkey() != 'esc':
                pass
    finally:
        for process in processes:
            stop_process(process)
        if ctrl is not None:
            try:
                ctrl.execute(Stop())
            except Exception:
                log.exception('Failed to stop the chassis')
        camera.stop_sign.value = True
        if camera_process.pid is not None:
            stop_process(camera_process, graceful=True)
        camera.close()
        os.system('stty sane')
        log.info('stopping.')


if __name__ == '__main__':
    main()
