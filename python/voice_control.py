"""Offline speech input for the car's existing manual actions.

The optional USB microphone and speech model are checked before any chassis
module is imported. Vosk is loaded only when voice mode is selected.
"""

from contextlib import AbstractContextManager
import json
from pathlib import Path
import shutil
import subprocess
from threading import Event, Thread
import time


COMMAND_KEYS = {
    '前进': 'w', '向前': 'w', '往前': 'w',
    '后退': 's', '向后': 's', '往后': 's',
    '左转': 'a', '向左转': 'a', '右转': 'd', '向右转': 'd',
    '左旋转': 'q', '左旋': 'q', '右旋转': 'e', '右旋': 'e',
    '左平移': 'left', '向左平移': 'left',
    '右平移': 'right', '向右平移': 'right',
    '加速': 'up', '减速': 'down',
    '掉头': 'z', '拍照': 'p', '截图': 'p',
    '停车': 'space', '停止': 'space', '停下': 'space',
    '退出': 'esc', '结束': 'esc',
}


def command_to_key(text):
    """Map a complete recognized phrase to one existing manual command."""
    normalized = ''.join(text.lower().split()).strip('，。！？,.!?')
    return COMMAND_KEYS.get(normalized)


def check_voice_ready(model_path, device=None):
    """Report missing dependencies and probe the selected capture device."""
    errors = []
    if model_path is None or not Path(model_path).is_dir():
        errors.append('Voice model missing: pass --voice-model, set VOSK_MODEL_PATH, '
                      'or install weights/vosk-model')
    elif not all((Path(model_path) / item).is_file()
                 for item in ('am/final.mdl', 'conf/mfcc.conf')):
        errors.append('Vosk model incomplete: expected am/final.mdl and conf/mfcc.conf')
    if shutil.which('arecord') is None:
        errors.append('ALSA arecord is not installed')
    else:
        command = ['arecord', '-q']
        if device:
            command += ['-D', device]
        command += ['-f', 'S16_LE', '-r', '16000', '-c', '1', '-t', 'raw', '-d', '1', '/dev/null']
        try:
            result = subprocess.run(command, capture_output=True, timeout=4)
            if result.returncode:
                errors.append('Microphone capture unavailable: ' + result.stderr.decode(errors='replace').strip())
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f'Microphone probe failed: {exc}')
    try:
        import vosk  # noqa: F401
    except ImportError:
        errors.append('Vosk is not installed in this Python environment')
    if errors:
        raise RuntimeError('; '.join(errors))


class VoiceRecognizer(AbstractContextManager):
    """Stream microphone audio into a local Vosk model and yield full phrases."""

    def __init__(self, model_path, device=None):
        self.model_path = Path(model_path)
        self.device = device
        self.process = None
        self.recognizer = None
        self.model = None
        self.phrase_started = None

    def __enter__(self):
        from vosk import KaldiRecognizer, Model

        self.model = Model(str(self.model_path))
        self.recognizer = KaldiRecognizer(self.model, 16000)
        self.recognizer.SetWords(True)
        command = ['arecord', '-q']
        if self.device:
            command.extend(['-D', self.device])
        command.extend(['-f', 'S16_LE', '-r', '16000', '-c', '1', '-t', 'raw'])
        self.audio_started = time.monotonic()
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL)
        return self

    def __iter__(self):
        started = None
        while True:
            received = time.monotonic()
            audio = self.process.stdout.read(4000)
            if not audio:
                raise RuntimeError('Microphone stopped delivering audio')
            if self.recognizer.AcceptWaveform(audio):
                result = json.loads(self.recognizer.Result())
                phrase = result.get('text', '').strip()
                if phrase:
                    words = result.get("result", [])
                    self.phrase_started = (self.audio_started + words[0]["start"] if words and "start" in words[0]
                                           else started if started is not None else received)
                    yield phrase
                started = None
            elif json.loads(self.recognizer.PartialResult()).get('partial') and started is None:
                started = received

    def __exit__(self, exc_type, exc_value, traceback):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process.stdout.close()
        return False


class VoiceService:
    def __init__(self, model_path, device, inbox, report=print):
        self.recognizer = VoiceRecognizer(model_path, device)
        self.inbox, self.report = inbox, report
        self.stopping = Event()
        self.error = None
        self.thread = Thread(target=self.run, name='voice-recognition', daemon=True)

    def start(self):
        self.recognizer.__enter__()
        self.thread.start()

    def run(self):
        from motion_control import Command
        try:
            for phrase in self.recognizer:
                if self.stopping.is_set():
                    break
                key = command_to_key(phrase)
                self.report(f'Voice phrase: {phrase}; command: {key or "unknown"}')
                if key:
                    self.inbox.put(Command(key, 'voice', started_at=self.recognizer.phrase_started))
        except Exception as exc:
            if not self.stopping.is_set():
                self.error = exc
                self.report(f'Voice failed: {exc}')

    def close(self):
        self.stopping.set()
        self.recognizer.__exit__(None, None, None)
        if self.thread.ident is not None:
            self.thread.join(timeout=3)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Test voice command text without starting the car')
    parser.add_argument('phrase')
    phrase = parser.parse_args().phrase
    print(command_to_key(phrase) or 'unknown')
