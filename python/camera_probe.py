"""Check Astra+ color capture without starting the chassis controller."""

import argparse
import time
from multiprocessing import Process

import cv2
import numpy as np

from src.utils import CAMERA_INFO, CameraBroadcaster


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=10)
    parser.add_argument('--output', default='/tmp/astra_probe.jpg')
    args = parser.parse_args()

    camera = CameraBroadcaster(CAMERA_INFO)
    process = Process(target=camera.run)
    try:
        process.start()
        if not camera.wait_until_ready(process):
            raise RuntimeError('Astra+ did not deliver a color frame; check the camera log')

        start = time.monotonic()
        updates = 0
        previous = 0.0
        while time.monotonic() - start < args.seconds:
            frame_time = camera.last_frame_time.value
            if camera.failed.is_set() or not process.is_alive() or time.monotonic() - frame_time > 2:
                raise RuntimeError('Astra+ color stream stopped or became stale')
            if frame_time != previous:
                updates += 1
                previous = frame_time
            time.sleep(0.03)

        frame = np.ndarray((CAMERA_INFO['height'], CAMERA_INFO['width'], 3),
                           dtype=np.uint8, buffer=camera.frame.buf).copy()
        if not cv2.imwrite(args.output, frame):
            raise RuntimeError(f'Could not save {args.output}')
        print(f'Color stream healthy for {args.seconds}s; observed {updates} frame updates; saved {args.output}')
    finally:
        camera.stop_sign.value = True
        if process.pid is not None:
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join()
        camera.close()


if __name__ == '__main__':
    main()
