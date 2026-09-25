"""Read the connected Slamtec lidar without starting the car controller or ROS2.

The device image already contains Slamtec's ``ultra_simple`` SDK executable.
This small adapter turns its scan lines into a useful health and distance check.
"""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import subprocess
import time


DEFAULT_SDK = Path('/home/HwHiAiUser/rplidar_sdk/output/Linux/Release/ultra_simple')
DEFAULT_PORT = '/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0'
POINT_PATTERN = re.compile(r'theta:\s*([\d.]+)\s+Dist:\s*([\d.]+)\s+Q:\s*(\d+)')


@dataclass(frozen=True)
class ScanPoint:
    angle_degrees: float
    distance_mm: float
    quality: int


def parse_scan_point(line):
    match = POINT_PATTERN.search(line)
    if not match:
        return None
    point = ScanPoint(float(match.group(1)), float(match.group(2)), int(match.group(3)))
    return point if point.distance_mm > 0 and point.quality > 0 else None


def collect_scan(sdk_path=DEFAULT_SDK, port=DEFAULT_PORT, baudrate=115200, seconds=8):
    """Return a summary of valid points; always ask the SDK to stop its motor."""
    if not Path(sdk_path).is_file():
        raise FileNotFoundError(f'Slamtec SDK executable not found: {sdk_path}')
    if not Path(port).exists():
        raise FileNotFoundError(f'Lidar serial port not found: {port}')
    if not shutil.which('stdbuf'):
        raise RuntimeError('stdbuf is required to read live SDK output')

    command = ['stdbuf', '-oL', str(sdk_path), '--channel', '--serial',
               str(port), str(baudrate)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               bufsize=1, start_new_session=True)
    summary = {'health': 'unknown', 'serial': None, 'raw_points': 0,
               'nonzero_distance_points': 0, 'points': 0,
               'nearest_mm': None, 'front_nearest_mm': None}
    output_tail = []
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select([process.stdout], [], [], 0.25)
            if not readable:
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue
            output_tail.append(line.strip())
            output_tail = output_tail[-8:]
            if line.startswith('SLAMTEC LIDAR S/N:'):
                summary['serial'] = line.split(':', 1)[1].strip()
            elif 'Lidar health status' in line:
                status = line.rsplit(':', 1)[-1].strip().split()[0]
                summary['health'] = 'OK' if status in ('0', 'OK') else status
            raw_point = POINT_PATTERN.search(line)
            if raw_point:
                summary['raw_points'] += 1
                if float(raw_point.group(2)) > 0:
                    summary['nonzero_distance_points'] += 1
            point = parse_scan_point(line)
            if point is None:
                continue
            summary['points'] += 1
            nearest = summary['nearest_mm']
            summary['nearest_mm'] = min(nearest, point.distance_mm) if nearest else point.distance_mm
            if point.angle_degrees <= 30 or point.angle_degrees >= 330:
                nearest = summary['front_nearest_mm']
                summary['front_nearest_mm'] = min(nearest, point.distance_mm) if nearest else point.distance_mm
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        process.stdout.close()

    if summary['health'] != 'OK' or summary['points'] == 0:
        raise RuntimeError(f'No healthy lidar scan received: {summary}; ' + ' | '.join(output_tail))
    return summary


def main():
    parser = argparse.ArgumentParser(description='Check the connected Slamtec lidar')
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--port', default=DEFAULT_PORT)
    parser.add_argument('--baudrate', type=int, default=115200)
    parser.add_argument('--seconds', type=float, default=8)
    args = parser.parse_args()
    if args.seconds <= 0 or args.baudrate <= 0:
        parser.error('seconds and baudrate must be positive')
    print(json.dumps(collect_scan(args.sdk, args.port, args.baudrate, args.seconds),
                     ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
