"""Bounded asynchronous screenshots shared by keyboard, speech and HTTP."""
from concurrent.futures import Future
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Event, Thread
import time
from uuid import uuid4

import cv2


class SnapshotWriter:
    def __init__(self, camera, directory='capture', report=print):
        self.camera, self.directory, self.report = camera, Path(directory), report
        self.queue = Queue(maxsize=8)
        self.stopping = Event()
        self.thread = Thread(target=self.run, name='snapshot-writer', daemon=True)

    def start(self):
        self.thread.start()

    def request(self):
        future = Future()
        try:
            if self.stopping.is_set():
                raise RuntimeError('Screenshot worker is stopping')
            self.queue.put_nowait((time.monotonic(), future))
        except (Full, RuntimeError) as exc:
            future.set_exception(RuntimeError(f'Screenshot rejected: {exc or "queue full"}'))
            self.report('Screenshot rejected: worker stopped or queue full')
        return future

    def run(self):
        while not self.stopping.is_set():
            try:
                requested, future = self.queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                if time.monotonic() - requested > 2:
                    raise RuntimeError('Screenshot request expired')
                frame, stamp = self.camera.read()
                ok, encoded = cv2.imencode('.jpg', frame)
                if not ok:
                    raise RuntimeError('JPEG encoding failed')
                self.camera.check_fresh()
                if time.monotonic() - stamp >= 2:
                    raise RuntimeError('Screenshot frame expired during encoding')
                self.directory.mkdir(parents=True, exist_ok=True)
                path = self.directory / f'{time.time_ns()}-{uuid4().hex[:8]}.jpg'
                jpeg = encoded.tobytes()
                temporary = path.with_suffix('.tmp')
                try:
                    temporary.write_bytes(jpeg)
                    self.camera.check_fresh()
                    if self.stopping.is_set() or time.monotonic() - stamp >= 2:
                        raise RuntimeError('Screenshot expired or cancelled before save completed')
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
                future.set_result((path, jpeg))
                self.report(f'Screenshot saved: {path}')
            except Exception as exc:
                future.set_exception(exc)
                self.report(f'Screenshot failed: {exc}')
        while True:
            try:
                _, future = self.queue.get_nowait()
                future.set_exception(RuntimeError('Screenshot cancelled on shutdown'))
            except Empty:
                break

    def close(self):
        self.stopping.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=3)
        if self.thread.is_alive():
            self.report('Screenshot worker did not finish within 3 seconds')
