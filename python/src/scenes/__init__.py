"""Load AI dependencies only when their scene is selected."""
from importlib import import_module

_SCENES = {'Manual': 'manual', 'Tracking': 'tracking', 'Helper': 'helper', 'LF': 'lane_following'}
SCENE_NAMES = tuple(_SCENES)
__all__ = [*_SCENES, 'scene_initiator']


def __getattr__(name):
    if name not in _SCENES:
        raise AttributeError(name)
    return getattr(import_module(f'{__name__}.{_SCENES[name]}'), name)


def scene_initiator(name):
    if name in _SCENES:
        return __getattr__(name)
    from src.utils import log
    log.error(f'{name} is not a valid scene.')
    return None
