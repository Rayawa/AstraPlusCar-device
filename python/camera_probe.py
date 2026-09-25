"""Save and verify an Astra+ photo without importing the chassis controller."""

import argparse
from pathlib import Path
import time

import cv2
import numpy as np

from astra_camera import frame_to_bgr_image, open_color_pipeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=10)
    parser.add_argument('--output', type=Path,
                        default=Path('capture') / f'astra_probe_{int(time.time())}.jpg')
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('--seconds must be positive')

    pipeline = None
    try:
        pipeline, profile = open_color_pipeline(1920, 1080, 30)
        print(f'Astra+ color profile: {profile}', flush=True)
        start = last_frame = time.monotonic()
        frame_count = 0
        image = None
        while time.monotonic() - start < args.seconds:
            frames = pipeline.wait_for_frames(200)
            color_frame = frames.get_color_frame() if frames is not None else None
            if color_frame is None:
                if time.monotonic() - last_frame > 5:
                    raise TimeoutError('Astra+ produced no color frames for 5 seconds')
                continue
            image = frame_to_bgr_image(color_frame)
            if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
                raise ValueError(f'Unexpected color image: {image.shape}, {image.dtype}')
            last_frame = time.monotonic()
            frame_count += 1

        if image is None or time.monotonic() - last_frame > 2:
            raise RuntimeError('No fresh Astra+ color frame to save')
        mean = float(image.mean())
        bright_fraction = float(np.count_nonzero(image > 20) / image.size)
        if mean < 5 or bright_fraction < 0.01:
            raise RuntimeError(f'Color image is black: mean={mean:.1f}, bright={bright_fraction:.3f}')

        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.output), image):
            raise RuntimeError(f'Could not save {args.output}')
        saved = cv2.imread(str(args.output))
        if saved is None or saved.shape != image.shape or float(saved.mean()) < 5:
            raise RuntimeError(f'Saved photo could not be verified: {args.output}')
        print(f'Saved {args.output}: {image.shape[1]}x{image.shape[0]}, '
              f'frames={frame_count}, mean={mean:.1f}, bright={bright_fraction:.3f}', flush=True)
    finally:
        if pipeline is not None:
            pipeline.stop()


if __name__ == '__main__':
    main()
