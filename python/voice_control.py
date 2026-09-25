"""Offline speech input for the car's existing manual actions.

The optional USB microphone and speech model are checked before any chassis
module is imported. Vosk is loaded only when voice mode is selected.
"""

from contextlib import AbstractContextManager
import json
from pathlib import Path
import shutil
import subprocess


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


def check_voice_ready(model_path):
    """Fail before camera or chassis initialization when voice is unavailable."""
    if model_path is None or not Path(model_path).is_dir():
        raise RuntimeError('Voice model missing: pass --voice-model with a Vosk model directory')
    if shutil.which('arecord') is None:
        raise RuntimeError('ALSA arecord is not installed')
    cards = Path('/proc/asound/cards')
    if not cards.exists() or 'no soundcards' in cards.read_text().lower():
        raise RuntimeError('No microphone/sound card is detected by ALSA')
    try:
        import vosk  # noqa: F401
    except ImportError as exc:
        raise RuntimeError('Vosk is not installed in this Python environment') from exc


class VoiceRecognizer(AbstractContextManager):
    """Stream microphone audio into a local Vosk model and yield full phrases."""

    def __init__(self, model_path, device=None):
        self.model_path = Path(model_path)
        self.device = device
        self.process = None
        self.recognizer = None
        self.model = None

    def __enter__(self):
        from vosk import KaldiRecognizer, Model

        self.model = Model(str(self.model_path))
        self.recognizer = KaldiRecognizer(self.model, 16000)
        command = ['arecord', '-q']
        if self.device:
            command.extend(['-D', self.device])
        command.extend(['-f', 'S16_LE', '-r', '16000', '-c', '1', '-t', 'raw'])
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL)
        return self

    def __iter__(self):
        while True:
            audio = self.process.stdout.read(4000)
            if not audio:
                raise RuntimeError('Microphone stopped delivering audio')
            if self.recognizer.AcceptWaveform(audio):
                phrase = json.loads(self.recognizer.Result()).get('text', '').strip()
                if phrase:
                    yield phrase

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


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Test voice command text without starting the car')
    parser.add_argument('phrase')
    phrase = parser.parse_args().phrase
    print(command_to_key(phrase) or 'unknown')
