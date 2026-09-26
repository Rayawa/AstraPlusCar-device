"""Browser preview backed by CameraBroadcaster, also usable without the chassis."""

import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import signal
from threading import Condition, Thread
import time

import cv2

from camera_tasks import SnapshotWriter


PAGE = '''<!doctype html><html lang="zh"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Astra+ camera</title>
<style>body{margin:0;background:#111;color:#eee;font:16px sans-serif}
main{max-width:1280px;margin:auto;padding:1rem}img{display:block;width:100%;height:auto}
a{color:#9df}.video{position:relative}.clock{position:absolute;top:.5rem;right:.5rem;
background:#000b;padding:.4rem .6rem;border-radius:.3rem}pre{white-space:pre-wrap;
overflow-wrap:anywhere;background:#222;padding:.8rem}</style>
<main><h1>Astra+ 实时预览</h1><div class="video">
<img src="/stream.mjpg" alt="Live camera"><div class="clock" id="server-time">读取时间中…</div></div>
<p id="frame-time">画面时间：读取中…</p>
<p><a href="/snapshot.jpg" target="_blank">保存当前画面</a></p>
<section id="radar" hidden><h2>雷达参数（最近一秒）</h2><pre id="radar-json"></pre></section></main>
<script>
async function refreshStatus() {
  try {
    const response = await fetch('/status.json', {cache: 'no-store'});
    if (!response.ok) throw new Error('状态接口 ' + response.status);
    const data = await response.json();
    document.getElementById('server-time').textContent = '服务端时间：' + data.server_time;
    document.getElementById('frame-time').textContent = data.camera.status === 'live'
      ? '画面时间：' + data.camera.frame_time + '（约 ' + data.camera.age_ms + ' ms 前）'
      : '画面状态：' + data.camera.status;
    const radar = document.getElementById('radar');
    radar.hidden = data.lidar === null;
    if (data.lidar !== null) {
      document.getElementById('radar-json').textContent = JSON.stringify(data.lidar, null, 2);
    }
  } catch (error) {
    document.getElementById('server-time').textContent = '状态更新失败：' + error.message;
    document.getElementById('frame-time').textContent = '画面状态未知';
  }
}
refreshStatus();
setInterval(refreshStatus, 1000);
</script></html>'''.encode('utf-8')


def preview_status(stream, lidar=None):
    """A short status read; never copies/encodes a frame or touches a device."""
    with stream.condition:
        stamp = stream.stamp
        stopped = stream.stopping
    monotonic_now, now = time.monotonic(), time.time()
    camera = {'status': 'waiting', 'frame_time': None, 'age_ms': None}
    if stopped:
        camera['status'] = 'unavailable'
    elif stamp:
        try:
            stream.camera.check_fresh()
            age = monotonic_now - stamp
            if 0 <= age < 2:
                camera = {'status': 'live',
                          'frame_time': datetime.fromtimestamp(now - age).astimezone().isoformat(timespec='seconds'),
                          'age_ms': round(age * 1000)}
            else:
                camera['status'] = 'stale'
        except RuntimeError:
            camera['status'] = 'unavailable'
    return {'server_time': datetime.fromtimestamp(now).astimezone().isoformat(timespec='seconds'),
            'camera': camera, 'lidar': lidar.status() if lidar is not None else None}


class CameraStream:
    """Encode the broadcaster's frames; this class never opens a camera."""
    def __init__(self, camera, fps=10, quality=70):
        self.camera, self.fps, self.quality = camera, fps, quality
        self.condition = Condition()
        self.jpeg = None
        self.sequence = 0
        self.stamp = 0
        self.stopping = False
        self.error = None
        self.thread = Thread(target=self.capture, name='preview-encoder', daemon=True)

    def start(self):
        self.thread.start()

    def capture(self):
        try:
            while not self.stopping:
                started = time.monotonic()
                image, stamp = self.camera.read()
                if stamp != self.stamp:
                    ok, encoded = cv2.imencode('.jpg', image,
                                               [cv2.IMWRITE_JPEG_QUALITY, self.quality])
                    if not ok:
                        raise RuntimeError('Could not encode camera frame as JPEG')
                    self.camera.check_fresh()
                    with self.condition:
                        self.jpeg, self.stamp = encoded.tobytes(), stamp
                        self.sequence += 1
                        self.condition.notify_all()
                with self.condition:
                    self.condition.wait_for(lambda: self.stopping,
                                            timeout=max(0, 1 / self.fps - (time.monotonic() - started)))
        except Exception as exc:
            with self.condition:
                self.error, self.stopping = exc, True
                self.jpeg = None
                self.condition.notify_all()

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        if self.thread.ident is not None:
            self.thread.join(timeout=3)


class PreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.connection.settimeout(3)
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)
            return
        if self.path == '/status.json':
            payload = json.dumps(preview_status(self.server.stream, self.server.lidar),
                                 ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == '/snapshot.jpg':
            try:
                _, jpeg = self.server.snapshots.request().result(timeout=5)
            except Exception as exc:
                self.send_error(503, f'Screenshot failed: {exc}')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(jpeg)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(jpeg)
            return
        if self.path != '/stream.mjpg':
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        sequence = 0
        try:
            while True:
                with self.server.stream.condition:
                    stream = self.server.stream
                    stream.condition.wait_for(
                        lambda: stream.sequence > sequence or stream.stopping, timeout=5)
                    if stream.stopping or stream.sequence == sequence:
                        return
                    sequence, jpeg = stream.sequence, stream.jpeg
                    stream.camera.check_fresh()
                    if time.monotonic() - stream.stamp >= 2:
                        return
                self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n')
                self.wfile.write(f'Content-Length: {len(jpeg)}\r\n\r\n'.encode())
                self.wfile.write(jpeg)
                self.wfile.write(b'\r\n')
                self.wfile.flush()
        except (OSError, RuntimeError):
            return


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True


class PreviewService:
    def __init__(self, camera, snapshots, port=8765):
        self.stream = CameraStream(camera)
        self.server = PreviewServer(('127.0.0.1', port), PreviewHandler)
        self.server.stream, self.server.snapshots = self.stream, snapshots
        self.server.lidar = None
        self.thread = Thread(target=self.server.serve_forever, name='preview-http', daemon=True)

    def set_lidar(self, lidar):
        self.server.lidar = lidar

    def start(self):
        self.stream.start()
        self.thread.start()
        print(f'Preview ready on 127.0.0.1:{self.server.server_port}', flush=True)

    def close(self):
        self.stream.close()
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=3)
        self.server.server_close()


def main():
    from multiprocessing import get_context
    from src.utils.camera_broadcaster import CameraBroadcaster
    from main import stop_process

    def stop_on_term(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_term)
    parser = argparse.ArgumentParser(description='Standalone Astra+ browser preview')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--fps', type=int, default=15)
    parser.add_argument('--quality', type=int, default=70)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or min(args.width, args.height, args.fps) <= 0:
        parser.error('port, image size and fps must be positive')
    if not 1 <= args.quality <= 100:
        parser.error('quality must be from 1 to 100')
    camera = CameraBroadcaster(vars(args))
    process = get_context('spawn').Process(target=camera.run)
    snapshots = SnapshotWriter(camera)
    preview = None
    try:
        process.start()
        if not camera.wait_until_ready(process):
            raise RuntimeError('Astra+ failed to start')
        snapshots.start()
        preview = PreviewService(camera, snapshots, args.port)
        preview.stream.fps, preview.stream.quality = args.fps, args.quality
        preview.start()
        while process.is_alive():
            camera.check_fresh()
            if preview.stream.error:
                raise RuntimeError('Preview failed') from preview.stream.error
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        if preview is not None:
            preview.close()
        snapshots.close()
        camera.stop_sign.value = True
        if process.pid is not None:
            stop_process(process, graceful=True)
        camera.close()


if __name__ == '__main__':
    main()
