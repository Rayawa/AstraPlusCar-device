"""Watch Astra+ color video in a browser through an SSH port forward.

This standalone process does not import the chassis controller. It owns the
camera while running, so stop it before starting the car application.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import signal
from threading import Condition, Thread
import time

import cv2

from astra_camera import frame_to_bgr_image, open_color_pipeline


PAGE = b'''<!doctype html><html lang="zh"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Astra+ camera</title>
<style>body{margin:0;background:#111;color:#eee;font:16px sans-serif}
main{max-width:1280px;margin:auto;padding:1rem}img{display:block;width:100%;height:auto}
a{color:#9df}</style>
<main><h1>Astra+ live view</h1><img src="/stream.mjpg" alt="Live camera">
<p><a href="/snapshot.jpg" target="_blank">Open current frame</a></p></main></html>'''


class CameraStream:
    def __init__(self, width, height, fps, quality):
        self.width, self.height, self.fps, self.quality = width, height, fps, quality
        self.condition = Condition()
        self.jpeg = None
        self.sequence = 0
        self.stopping = False
        self.error = None
        self.thread = Thread(target=self.capture, name='astra-capture')

    def start(self):
        self.thread.start()
        deadline = time.monotonic() + 15
        with self.condition:
            while self.jpeg is None and self.error is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)
            if self.jpeg is None:
                raise RuntimeError(f'Astra+ did not deliver a frame: {self.error or "timeout"}')

    def capture(self):
        pipeline = None
        try:
            from pyorbbecsdk import OBFormat

            pipeline, profile = open_color_pipeline(self.width, self.height, self.fps)
            print(f'Astra+ color profile: {profile}', flush=True)
            last_frame = time.monotonic()
            native_mjpg_logged = False
            while True:
                with self.condition:
                    if self.stopping:
                        break
                frames = pipeline.wait_for_frames(200)
                frame = frames.get_color_frame() if frames is not None else None
                if frame is None:
                    if time.monotonic() - last_frame > 5:
                        raise TimeoutError('Astra+ color stream stopped for 5 seconds')
                    continue
                if (frame.get_format() == OBFormat.MJPG and
                        frame.get_width() == self.width and
                        frame.get_height() == self.height):
                    jpeg = bytes(frame.get_data())
                    if not jpeg.startswith(b'\xff\xd8'):
                        raise ValueError('Astra+ MJPG frame is missing its JPEG header')
                    if not native_mjpg_logged:
                        print('Streaming Astra+ native MJPG without re-encoding', flush=True)
                        native_mjpg_logged = True
                else:
                    image = frame_to_bgr_image(frame)
                    if image.shape[:2] != (self.height, self.width):
                        image = cv2.resize(image, (self.width, self.height))
                    ok, encoded = cv2.imencode('.jpg', image,
                                               [cv2.IMWRITE_JPEG_QUALITY, self.quality])
                    if not ok:
                        raise RuntimeError('Could not encode Astra+ frame as JPEG')
                    jpeg = encoded.tobytes()
                last_frame = time.monotonic()
                with self.condition:
                    self.jpeg = jpeg
                    self.sequence += 1
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.error = exc
                self.stopping = True
                self.condition.notify_all()
        finally:
            if pipeline is not None:
                pipeline.stop()

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        if self.thread.is_alive():
            self.thread.join(timeout=5)


class PreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)
            return
        if self.path == '/snapshot.jpg':
            with self.server.stream.condition:
                jpeg = self.server.stream.jpeg
            if jpeg is None:
                self.send_error(503, 'No camera frame')
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
                self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n')
                self.wfile.write(f'Content-Length: {len(jpeg)}\r\n\r\n'.encode())
                self.wfile.write(jpeg)
                self.wfile.write(b'\r\n')
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True


def main():
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

    stream = CameraStream(args.width, args.height, args.fps, args.quality)
    try:
        stream.start()
        with PreviewServer(('127.0.0.1', args.port), PreviewHandler) as server:
            server.stream = stream
            server.timeout = 0.5
            print(f'Preview ready on 127.0.0.1:{args.port}', flush=True)
            while not stream.stopping:
                server.handle_request()
        if stream.error is not None:
            raise RuntimeError('Astra+ preview stopped') from stream.error
    except KeyboardInterrupt:
        pass
    finally:
        stream.close()


if __name__ == '__main__':
    main()
