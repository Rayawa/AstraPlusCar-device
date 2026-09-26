"""Utilities loaded on demand: importing camera helpers never opens the chassis."""
from importlib import import_module

from src.utils.constant import *  # noqa: F401,F403

_LAZY = {
    'Controller': ('controller', 'Controller'),
    'CameraBroadcaster': ('camera_broadcaster', 'CameraBroadcaster'),
    'getkey': ('common_utils', 'getkey'),
    'load_yaml': ('common_utils', 'load_yaml'),
    'log': ('logger', 'logger_instance'),
    **{name: ('acl_utils', name) for name in (
        'copy_data_host_to_device', 'check_ret', 'init_acl', 'deinit_acl')},
}


def __getattr__(name):
    if name not in _LAZY:
        raise AttributeError(name)
    module, attribute = _LAZY[name]
    value = getattr(import_module(f'{__name__}.{module}'), attribute)
    globals()[name] = value
    return value
