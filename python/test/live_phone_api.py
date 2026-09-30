"""Short, explicit live check of the phone API on a wheel-raised vehicle.

Read-only camera checks run by default. Pass --motion only when the vehicle is
secured; every movement is followed by an explicit stop and the 600 ms device
watchdog remains the fallback.
"""
import argparse
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--motion', action='store_true')
    parser.add_argument('--stream-seconds', type=float, default=10,
                        help='read-only MJPEG receive-rate measurement duration')
    args = parser.parse_args()
    if not 0 < args.stream_seconds <= 60:
        parser.error('--stream-seconds must be greater than 0 and at most 60')
    base = args.base_url.rstrip('/')

    def request(path, body=None, binary=False):
        data = None if body is None else json.dumps(body).encode('utf-8')
        req = Request(base + path, data=data,
                      headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=4) as response:
                payload = response.read() if binary else json.load(response)
                return response.status, payload
        except HTTPError as exc:
            return exc.code, json.load(exc)

    status, state = request('/api/v1/status')
    assert status == 200 and state['mode'] == 'phone', (status, state)
    assert state['camera']['status'] == 'live', state['camera']
    assert state['lidar']['status'] == 'scanning', state['lidar']
    status, frame = request('/api/v1/camera/frame.jpg', binary=True)
    assert status == 200 and frame.startswith(b'\xff\xd8'), status
    with urlopen(base + '/api/v1/camera/stream.mjpg', timeout=4) as stream:
        assert stream.status == 200
        assert 'multipart/x-mixed-replace' in stream.headers['Content-Type']
        times, sizes, sequences = [], [], []
        deadline = time.monotonic() + args.stream_seconds
        while time.monotonic() < deadline or len(times) < 2:
            line = stream.readline()
            if not line:
                raise RuntimeError('MJPEG ended before measurement completed')
            if not line.startswith(b'--frame'):
                continue
            headers = {}
            while True:
                line = stream.readline()
                if not line:
                    raise RuntimeError('MJPEG header ended unexpectedly')
                if line == b'\r\n':
                    break
                name, value = line.decode('ascii').split(':', 1)
                headers[name.lower()] = value.strip()
            assert headers['content-type'] == 'image/jpeg'
            size = int(headers['content-length'])
            jpeg = stream.read(size)
            assert len(jpeg) == size and jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')
            sizes.append(size)
            times.append(time.monotonic())
            if 'x-frame-sequence' in headers:
                sequences.append(int(headers['x-frame-sequence']))
        fps = (len(times) - 1) / (times[-1] - times[0])
        skipped = sequences[-1] - sequences[0] + 1 - len(sequences) if sequences else None
        print(f'MJPEG: {len(times)} frames, {fps:.2f} FPS, '
              f'{sum(sizes) / len(sizes):.0f} bytes/frame, skipped={skipped}')
    status, capture = request('/api/v1/camera/captures', {})
    assert status == 200 and capture['ok'] and capture['captureId'].endswith('.jpg')
    status, saved = request(capture['url'], binary=True)
    assert status == 200 and saved.startswith(b'\xff\xd8'), status
    print('status, frame, MJPEG stream, capture and download: OK')

    if not args.motion:
        return

    def session():
        code, result = request('/api/v1/control/session', {})
        assert code == 200 and result['ok'] and result['leaseMs'] == 600, result
        return result['sessionId']

    def stop(sid):
        code, result = request('/api/v1/control/stop', {'sessionId': sid})
        assert code == 200 and result['accepted'], (code, result)
        code, state = request('/api/v1/status')
        assert code == 200 and state['moving'] is False, state

    sid = session()
    try:
        code, result = request('/api/v1/control/speed',
                               {'sessionId': sid, 'seq': 1,
                                'commandId': 'live-speed-25', 'speed': 25})
        assert code == 200 and result['speed'] == 25, (code, result)
    finally:
        stop(sid)
    print('session, absolute speed and stop: OK')

    for key in ('w', 's', 'a', 'd', 'q', 'e', 'left', 'right', 'z', 'up', 'down'):
        sid = session()
        try:
            command_id = 'live-' + key
            code, result = request('/api/v1/control/command',
                                   {'sessionId': sid, 'seq': 1,
                                    'commandId': command_id, 'key': key})
            assert code == 200 and result['accepted'], (key, code, result)
            if key == 'w':
                code, result = request('/api/v1/control/renew',
                                       {'sessionId': sid, 'commandId': command_id})
                assert code == 200 and result['accepted'], (code, result)
                time.sleep(0.08)
        finally:
            stop(sid)
        print(key + ': accepted and stopped')

    code, result = request('/api/v1/control/command',
                           {'sessionId': sid, 'seq': 2,
                            'commandId': 'late-after-stop', 'key': 'w'})
    assert code == 409 and result['code'] == 'session_expired', (code, result)
    print('stale command after stop: rejected')

    sid = session()
    try:
        code, result = request('/api/v1/control/command',
                               {'sessionId': sid, 'seq': 1,
                                'commandId': 'live-watchdog', 'key': 'w'})
        assert code == 200 and result['accepted'], (code, result)
        time.sleep(0.9)
        code, state = request('/api/v1/status')
        assert code == 200 and state['moving'] is False, state
        code, result = request('/api/v1/control/renew',
                               {'sessionId': sid, 'commandId': 'live-watchdog'})
        assert code == 409 and result['code'] in ('session_expired', 'lease_expired'), (code, result)
    finally:
        request('/api/v1/control/stop', {'sessionId': sid})
    print('600 ms control-loss watchdog: stopped and stale renewal rejected')


if __name__ == '__main__':
    main()
