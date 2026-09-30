"""Read the connected Slamtec lidar without starting the car controller or ROS2.

The device image already contains Slamtec's ``ultra_simple`` SDK executable.
This small adapter turns its scan lines into a useful health and distance check.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import subprocess
from threading import Event, Lock, Thread
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


SECTORS = {'front_nearest_mm': 0, 'sector_90_mm': 90,
           'sector_180_mm': 180, 'sector_270_mm': 270}


def sector_distances(points):
    """Nearest millimeters within ±30° of each sensor-relative bearing."""
    ranges = {name: None for name in SECTORS}
    for point in points:
        for name, bearing in SECTORS.items():
            if abs((point.angle_degrees - bearing + 180) % 360 - 180) <= 30:
                previous = ranges[name]
                ranges[name] = min(previous, point.distance_mm) if previous is not None else point.distance_mm
    return ranges


def check_lidar_ready(sdk_path=DEFAULT_SDK, port=DEFAULT_PORT):
    errors = []
    if not Path(sdk_path).is_file() or not os.access(sdk_path, os.X_OK):
        errors.append(f'Slamtec SDK executable missing or not executable: {sdk_path}')
    if not Path(port).exists() or not os.access(port, os.R_OK | os.W_OK):
        errors.append(f'Lidar serial port missing or not accessible: {port}')
    if not shutil.which('stdbuf'):
        errors.append('stdbuf is required to read live SDK output')
    if errors:
        raise RuntimeError('; '.join(errors))


def collect_scan(sdk_path=DEFAULT_SDK, port=DEFAULT_PORT, baudrate=115200, seconds=8,
                 stop_event=None, report=None):
    """Read continuously when seconds=None; publish distance windows each second."""
    check_lidar_ready(sdk_path, port)
    command = ['stdbuf', '-oL', str(sdk_path), '--channel', '--serial', str(port), str(baudrate)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    summary = {'health': 'unknown', 'serial': None, 'raw_points': 0,
               'nonzero_distance_points': 0, 'points': 0,
               'nearest_mm': None, **{name: None for name in SECTORS}}
    output_tail, pending = [], b''
    started = last_report = time.monotonic()
    last_point = started
    deadline = started + seconds if seconds is not None else float('inf')
    window = []
    try:
        while time.monotonic() < deadline and not (stop_event and stop_event.is_set()):
            now = time.monotonic()
            if report and now - last_report >= 1:
                report(dict(observed_at=datetime.now().astimezone().isoformat(timespec='seconds'),
                            serial=summary['serial'], health=summary['health'],
                            status='scanning' if window else 'waiting',
                            points=len(window), nearest_mm=min((p.distance_mm for p in window), default=None),
                            **sector_distances(window)))
                window.clear()
                last_report = now
            if seconds is None and now - last_point > 5:
                raise RuntimeError('Lidar delivered no valid scan for 5 seconds: ' + ' | '.join(output_tail))
            readable, _, _ = select.select([process.stdout], [], [], 0.1)
            if not readable:
                if process.poll() is not None:
                    raise RuntimeError('Lidar SDK exited: ' + ' | '.join(output_tail))
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('Lidar SDK output closed: ' + ' | '.join(output_tail))
            pending += chunk
            lines = pending.split(b'\n')
            pending = lines.pop()[-8192:]
            for raw in lines:
                line = raw.decode(errors='replace').strip()
                output_tail = (output_tail + [line])[-8:]
                if line.startswith('SLAMTEC LIDAR S/N:'):
                    summary['serial'] = line.split(':', 1)[1].strip()
                elif 'Lidar health status' in line:
                    status = line.rsplit(':', 1)[-1].strip().split()[0]
                    summary['health'] = 'OK' if status in ('0', 'OK') else status
                    if summary['health'] != 'OK':
                        raise RuntimeError(f'Lidar unhealthy: {line}')
                match = POINT_PATTERN.search(line)
                if match:
                    summary['raw_points'] += 1
                    summary['nonzero_distance_points'] += float(match.group(2)) > 0
                point = parse_scan_point(line)
                if point is None:
                    continue
                last_point = time.monotonic()
                window.append(point)
                summary['points'] += 1
                nearest = summary['nearest_mm']
                summary['nearest_mm'] = min(nearest, point.distance_mm) if nearest else point.distance_mm
                for name, distance in sector_distances((point,)).items():
                    if distance is not None:
                        nearest = summary[name]
                        summary[name] = min(nearest, distance) if nearest is not None else distance
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        process.stdout.close()
    if not (stop_event and stop_event.is_set()) and (summary['health'] != 'OK' or summary['points'] == 0):
        raise RuntimeError(f'No healthy lidar scan received: {summary}; ' + ' | '.join(output_tail))
    return summary


class LidarService:
    def __init__(self, sdk, port, baudrate, report=print):
        self.sdk, self.port, self.baudrate, self.report = sdk, port, baudrate, report
        self.stopping = Event()
        self.error = None
        self.ready = Event()
        self.lock = Lock()
        self.latest = None
        self.updated_at = None
        self.thread = Thread(target=self.run, name='lidar-scan', daemon=True)

    def publish(self, summary):
        with self.lock:
            self.latest = dict(summary)
            self.updated_at = time.monotonic()
        if summary['health'] == 'OK' and summary['points']:
            self.ready.set()
        self.report('Lidar: ' + json.dumps(summary, ensure_ascii=False))

    def status(self):
        """Return the current one-second window without presenting stale ranges as live."""
        with self.lock:
            result = dict(self.latest) if self.latest is not None else {
                'observed_at': None, 'serial': None, 'health': 'unknown',
                'status': 'waiting', 'points': 0, 'nearest_mm': None,
                **{name: None for name in SECTORS}}
            updated = self.updated_at
        if self.error is not None:
            result.update(status='error', error=str(self.error), points=0,
                          nearest_mm=None, **{name: None for name in SECTORS})
        elif updated is not None:
            age = max(0, time.monotonic() - updated)
            result['age_seconds'] = round(age, 2)
            if age >= 2.5:
                result.update(status='stale', points=0,
                              nearest_mm=None, **{name: None for name in SECTORS})
        return result

    def run(self):
        try:
            collect_scan(self.sdk, self.port, self.baudrate, None, self.stopping, self.publish)
        except Exception as exc:
            self.error = exc
            self.report(f'Lidar failed: {exc}')

    def start(self):
        self.thread.start()
        deadline = time.monotonic() + 7
        while not self.ready.wait(0.1):
            if self.error or time.monotonic() >= deadline:
                raise RuntimeError(f'Lidar startup failed: {self.error or "no healthy scan"}')

    def close(self):
        self.stopping.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=5)


def main(argv=None):
    def stop_on_term(_signum, _frame):
        raise KeyboardInterrupt

    parser = argparse.ArgumentParser(description='Check the connected Slamtec lidar')
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--port', default=DEFAULT_PORT)
    parser.add_argument('--baudrate', type=int, default=115200)
    parser.add_argument('--seconds', type=float, default=8)
    parser.add_argument('--follow', '--continuous', action='store_true',
                        help='print one JSON scan window per second until Ctrl+C')
    args = parser.parse_args(argv)
    if args.seconds <= 0 or args.baudrate <= 0:
        parser.error('seconds and baudrate must be positive')
    if args.follow:
        previous = signal.signal(signal.SIGTERM, stop_on_term)
        try:
            collect_scan(args.sdk, args.port, args.baudrate, seconds=None,
                         report=lambda summary: print(json.dumps(summary, ensure_ascii=False), flush=True))
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGTERM, previous)
    else:
        print(json.dumps(collect_scan(args.sdk, args.port, args.baudrate, args.seconds),
                         ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
