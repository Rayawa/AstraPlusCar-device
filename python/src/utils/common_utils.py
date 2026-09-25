#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import select
import sys
import threading
import tty

import termios
from yaml import safe_load


# 单例类
class SingleTonType(type):
    _instance_lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if not hasattr(cls, '_instance'):
            with SingleTonType._instance_lock:
                if not hasattr(cls, '_instance'):
                    cls._instance = super(SingleTonType, cls).__call__(*args, **kwargs)
        return cls._instance


def path_check(path: str):
    base_name = os.path.basename(path)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f'{base_name} does not exist.')
    if not os.access(path, mode=os.R_OK):
        raise PermissionError(f'{base_name} is unreadable')


def load_yaml(config_path: str):
    path_check(config_path)
    with open(config_path, 'r') as f:
        config = safe_load(f.read())
    return config


def getkey():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        key = os.read(fd, 1)
        if not key:
            return None
        if key == b'\x1b':
            # Escape is also the first byte of an arrow-key sequence. Only
            # consume the following bytes when they actually arrive.
            if not select.select([fd], [], [], 0.05)[0]:
                return 'esc'
            prefix = os.read(fd, 1)
            if prefix in (b'[', b'O') and select.select([fd], [], [], 0.05)[0]:
                direction = os.read(fd, 1)
                return {
                    b'A': 'up', b'B': 'down', b'C': 'right', b'D': 'left'
                }.get(direction)
            return None

        mapping = {
            b'\x7f': 'backspace', b'\n': 'return', b'\r': 'return',
            b' ': 'space', b'\t': 'tab'
        }
        if key in mapping:
            return mapping[key]
        char = key.decode('ascii', errors='ignore')
        return char.lower() if char.isalpha() else char or None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
