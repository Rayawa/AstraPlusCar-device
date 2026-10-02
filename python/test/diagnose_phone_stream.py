"""Read-only LAN/loopback diagnosis; sends GET requests only, never control commands."""
import argparse
import json
from threading import Event, Thread
import time
from urllib.request import urlopen


def diagnose(base, seconds, fps=30):
    stopping = Event()
    states, frames, gaps, failures = [], [], [], []

    def poll():
        while not stopping.is_set():
            started = time.monotonic()
            try:
                with urlopen(base + '/api/v1/status', timeout=4) as response:
                    state = json.load(response)
                states.append({'ms': round((time.monotonic() - started) * 1000),
                               'camera': state['camera']['status'],
                               'moving': state['moving']})
            except Exception as exc:
                states.append({'error': str(exc)})
            stopping.wait(max(0, 1 - (time.monotonic() - started)))

    worker = Thread(target=poll, daemon=True)
    worker.start()
    deadline = time.monotonic() + seconds
    previous = time.monotonic()
    connections = 0
    try:
        while time.monotonic() < deadline:
            try:
                with urlopen(base + f'/api/v1/camera/stream.mjpg?fps={fps}', timeout=4) as stream:
                    connections += 1
                    while time.monotonic() < deadline:
                        line = stream.readline()
                        if not line:
                            raise RuntimeError('stream ended')
                        if not line.startswith(b'--frame'):
                            continue
                        headers = {}
                        while True:
                            line = stream.readline()
                            if not line:
                                raise RuntimeError('incomplete multipart header')
                            if line == b'\r\n':
                                break
                            name, value = line.decode('ascii').split(':', 1)
                            headers[name.lower()] = value.strip()
                        size = int(headers['content-length'])
                        if not 0 < size <= 1024 * 1024:
                            raise RuntimeError('invalid JPEG length')
                        jpeg = stream.read(size)
                        if len(jpeg) != size or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
                            raise RuntimeError('incomplete JPEG')
                        now = time.monotonic()
                        gap = now - previous
                        gaps.append(gap)
                        if gap >= 2:
                            print(f'frame gap {gap:.3f}s', flush=True)
                        frames.append((now, size))
                        previous = now
            except Exception as exc:
                failures.append(str(exc))
                print(f'stream failure: {exc}', flush=True)
                stopping.wait(0.5)
    finally:
        stopping.set()
        worker.join(timeout=5)
    latencies = [state['ms'] for state in states if 'ms' in state]
    result = {'frames': len(frames), 'connections': connections, 'stream_failures': failures,
              'fps': round((len(frames) - 1) / (frames[-1][0] - frames[0][0]), 2) if len(frames) > 1 else 0,
              'max_frame_gap_ms': round(max(gaps, default=0) * 1000),
              'gaps_over_2s': sum(gap >= 2 for gap in gaps),
              'average_jpeg_bytes': round(sum(frame[1] for frame in frames) / len(frames)) if frames else 0,
              'status_requests': len(states), 'status_failures': sum('error' in state for state in states),
              'max_status_ms': max(latencies, default=0),
              'camera_states': sorted(set(state['camera'] for state in states if 'camera' in state))}
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--fps', type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('--seconds must be between 1 and 600')
    if not 1 <= args.fps <= 30:
        parser.error('--fps must be between 1 and 30')
    diagnose(args.base_url.rstrip('/'), args.seconds, args.fps)
