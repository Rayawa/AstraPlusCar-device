"""Phone HTTP adapter. All chassis operations run in main.py's control loop."""
from concurrent.futures import Future, TimeoutError
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Lock
import json
import socket
import time
from uuid import uuid4

from camera_preview import PreviewHandler, PreviewService, preview_status
from motion_control import Command


class PhoneError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


class PhoneControl:
    KEYS = frozenset(('q', 'w', 'e', 'a', 's', 'd', 'z', 'up', 'down', 'left', 'right'))
    LEASE_SECONDS = 0.6

    def __init__(self, inbox):
        self.inbox = inbox
        self.queue = Queue(maxsize=32)
        self.urgent = Queue(maxsize=8)
        self.lock = Lock()
        self.session = None
        self.last_seq = -1
        self.seen = {}
        self.active_id = None
        self.lease_until = 0.0
        self.boot_id = uuid4().hex
        self.arbiter = None

    def open_session(self):
        with self.lock:
            if self.session is not None and self.active_id is not None:
                raise PhoneError(409, 'control_busy', 'Another active control session exists')
            self.session = uuid4().hex
            self.last_seq = -1
            self.seen = {}
            self.active_id = None
            return {'sessionId': self.session, 'bootId': self.boot_id,
                    'leaseMs': round(self.LEASE_SECONDS * 1000)}

    def submit(self, kind, data):
        future = Future()
        try:
            (self.urgent if kind == 'stop' else self.queue).put_nowait((kind, data, future, time.monotonic()))
        except Full:
            raise PhoneError(503, 'control_busy', 'Control queue is full')
        try:
            return future.result(timeout=2)
        except TimeoutError:
            future.cancel()
            raise PhoneError(503, 'control_timeout', 'Control loop did not respond')

    def _session(self, data):
        if not isinstance(data, dict) or not isinstance(data.get('sessionId'), str) or data['sessionId'] != self.session:
            raise PhoneError(409, 'session_expired', 'Start a new control session')

    def _process(self, kind, data, arbiter):
        with self.lock:
            self._session(data)
            now = time.monotonic()
            if kind == 'stop':
                self.session = None
                self.active_id = None
                self.lease_until = 0
                self.seen = {}
                arbiter.handle(Command('space', 'phone'))
                return {'accepted': True, 'speed': arbiter.speed}
            if kind == 'renew':
                if data.get('commandId') != self.active_id or now >= self.lease_until:
                    raise PhoneError(409, 'lease_expired', 'Movement lease expired')
                self.lease_until = now + self.LEASE_SECONDS
                return {'accepted': True, 'speed': arbiter.speed}
            seq = data.get('seq')
            command_id = data.get('commandId')
            if not isinstance(seq, int) or isinstance(seq, bool) or not isinstance(command_id, str) or not command_id or len(command_id) > 80:
                raise PhoneError(400, 'invalid_command', 'seq and commandId are required')
            if command_id in self.seen:
                return self.seen[command_id]
            if seq <= self.last_seq:
                raise PhoneError(409, 'stale_command', 'Command sequence is stale')
            if kind == 'command':
                key = data.get('key')
                if key not in self.KEYS:
                    raise PhoneError(400, 'invalid_command', 'Unknown control key')
                arbiter.handle(Command(key, 'phone'))
                if key in (*arbiter.MOTION_ACTIONS, 'z'):
                    self.active_id = command_id
                    self.lease_until = now + self.LEASE_SECONDS
                elif arbiter.active_motion is None:
                    self.active_id = None
                    self.lease_until = 0
            elif kind == 'speed':
                speed = data.get('speed')
                if not isinstance(speed, int) or isinstance(speed, bool) or not 0 <= speed <= 100:
                    raise PhoneError(400, 'invalid_speed', 'speed must be 0..100')
                arbiter.set_speed(speed)
                if arbiter.active_motion is None:
                    self.active_id = None
                    self.lease_until = 0
            else:
                raise PhoneError(404, 'unknown_route', 'Unknown control operation')
            self.last_seq = seq
            result = {'accepted': True, 'speed': arbiter.speed, 'commandId': command_id}
            self.seen[command_id] = result
            if len(self.seen) > 64:
                self.seen.pop(next(iter(self.seen)))
            return result

    def tick(self, arbiter):
        self.arbiter = arbiter
        for source in (self.urgent, self.queue):
            if source is self.queue:
                self._check_lease(arbiter)
            for _ in range(8):
                try:
                    kind, data, future, issued_at = source.get_nowait()
                except Empty:
                    break
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    if time.monotonic() - issued_at > 0.5:
                        raise PhoneError(503, 'stale_request', 'Control request waited too long')
                    future.set_result(self._process(kind, data, arbiter))
                except Exception as exc:
                    future.set_exception(exc)
        self._check_lease(arbiter)

    def _check_lease(self, arbiter):
        with self.lock:
            if self.active_id and (time.monotonic() >= self.lease_until or
                                   (arbiter.active_motion is None and arbiter.deadline is None)):
                arbiter.handle(Command('space', 'phone'))
                self.session = None
                self.active_id = None
                self.lease_until = 0

    def status(self):
        with self.lock:
            return {'bootId': self.boot_id, 'mode': 'phone',
                    'speed': self.arbiter.speed if self.arbiter else 40,
                    'moving': self.active_id is not None,
                    'controlBusy': self.active_id is not None}


class PhoneHandler(PreviewHandler):
    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc):
        if isinstance(exc, PhoneError):
            self._json(exc.status, {'ok': False, 'code': exc.code, 'message': exc.message})
        else:
            self._json(503, {'ok': False, 'code': 'service_unavailable', 'message': str(exc)})

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/v1/status':
            payload = preview_status(self.server.stream, self.server.lidar)
            payload.update(self.server.control.status())
            self._json(200, payload)
        elif path == '/api/v1/camera/frame.jpg':
            # Headers and JPEG are written separately; disable Nagle as on the
            # MJPEG path so delayed ACKs do not hold a small JPEG tail.
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.connection.settimeout(1.5)
            with self.server.stream.condition:
                jpeg, stamp = self.server.stream.jpeg, self.server.stream.stamp
                sequence = self.server.stream.sequence
            if jpeg is None or time.monotonic() - stamp >= 2:
                self._json(503, {'ok': False, 'code': 'camera_not_ready', 'message': 'No fresh frame'})
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(jpeg)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Frame-Sequence', str(sequence))
            self.end_headers()
            self.wfile.write(jpeg)
        elif path.startswith('/api/v1/camera/captures/'):
            name = path.rsplit('/', 1)[-1]
            if not name.endswith('.jpg') or '/' in name or '..' in name or len(name) > 90:
                self._json(400, {'ok': False, 'code': 'invalid_capture', 'message': 'Invalid capture ID'})
                return
            try:
                jpeg = (self.server.capture_dir / name).read_bytes()
            except OSError:
                self._json(404, {'ok': False, 'code': 'capture_missing', 'message': 'Capture not found'})
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(jpeg)))
            self.end_headers()
            self.wfile.write(jpeg)
        elif path == '/api/v1/camera/stream.mjpg':
            # Preserve the optional per-client video rate; controls and camera
            # capture cadence are independent of this transport setting.
            query = self.path.partition('?')[2]
            self.path = '/stream.mjpg' + ('?' + query if query else '')
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        routes = {'/api/v1/control/session': 'session',
                  '/api/v1/control/command': 'command',
                  '/api/v1/control/renew': 'renew',
                  '/api/v1/control/stop': 'stop',
                  '/api/v1/control/speed': 'speed',
                  '/api/v1/camera/captures': 'capture'}
        kind = routes.get(self.path)
        if kind is None:
            self._json(404, {'ok': False, 'code': 'unknown_route', 'message': 'Unknown route'})
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 0 or size > 4096:
                raise PhoneError(400, 'invalid_body', 'Request body too large')
            data = json.loads(self.rfile.read(size)) if size else {}
            if not isinstance(data, dict):
                raise PhoneError(400, 'invalid_body', 'Expected JSON object')
            if kind == 'session':
                result = self.server.control.open_session()
            elif kind == 'capture':
                path, _ = self.server.snapshots.request().result(timeout=5)
                result = {'captureId': path.name, 'url': '/api/v1/camera/captures/' + path.name}
            else:
                result = self.server.control.submit(kind, data)
            self._json(200, {'ok': True, **result})
        except (ValueError, json.JSONDecodeError):
            self._error(PhoneError(400, 'invalid_body', 'Invalid JSON'))
        except Exception as exc:
            self._error(exc)


class PhoneService(PreviewService):
    def __init__(self, camera, snapshots, lidar, control, port=8080, host='0.0.0.0'):
        super().__init__(camera, snapshots, port=port, host=host, handler=PhoneHandler)
        self.stream.fps = 30
        self.stream.jpeg_scale = 2
        self.stream.quality = 75
        self.server.lidar = lidar
        self.server.control = control
        self.server.capture_dir = Path(snapshots.directory)
