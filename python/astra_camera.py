"""Color-only Astra+ capture through Orbbec SDK v1, without chassis imports."""

from pathlib import Path

import cv2
import numpy as np


def open_color_pipeline(width, height, fps):
    usb_devices = Path('/sys/bus/usb/devices')
    if usb_devices.is_dir():
        found = False
        for device in usb_devices.iterdir():
            try:
                vendor = (device / 'idVendor').read_text().strip().lower()
                product = (device / 'idProduct').read_text().strip().lower()
            except (OSError, FileNotFoundError):
                continue
            if vendor == '2bc5' and product in {'0536', '0636'}:
                found = True
                break
        if not found:
            raise RuntimeError('Astra+ USB device (2bc5:0536/0636) is not enumerated; check its data cable and hub')

    from pyorbbecsdk import Config, OBFormat, OBSensorType, Pipeline

    pipeline = Pipeline()
    profiles = pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
    profile = None
    for color_format in (OBFormat.MJPG, OBFormat.YUYV, OBFormat.RGB):
        try:
            profile = profiles.get_video_stream_profile(width, height, color_format, fps)
            break
        except Exception:
            continue
    if profile is None:
        profile = profiles.get_default_video_stream_profile()

    config = Config()
    config.enable_stream(profile)
    try:
        pipeline.start(config)
    except Exception:
        try:
            pipeline.stop()
        except Exception:
            pass
        raise
    return pipeline, profile


def frame_to_bgr_image(frame):
    from pyorbbecsdk import OBFormat

    width, height = frame.get_width(), frame.get_height()
    data = np.asanyarray(frame.get_data())
    color_format = frame.get_format()
    if color_format == OBFormat.MJPG:
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Could not decode Astra+ MJPG frame')
        return image
    if color_format == OBFormat.RGB:
        return cv2.cvtColor(data.reshape(height, width, 3), cv2.COLOR_RGB2BGR)
    if color_format == OBFormat.BGR:
        return data.reshape(height, width, 3).copy()
    if color_format == OBFormat.YUYV:
        return cv2.cvtColor(data.reshape(height, width, 2), cv2.COLOR_YUV2BGR_YUY2)
    if color_format == OBFormat.UYVY:
        return cv2.cvtColor(data.reshape(height, width, 2), cv2.COLOR_YUV2BGR_UYVY)
    yuv420_formats = {
        OBFormat.I420: cv2.COLOR_YUV2BGR_I420,
        OBFormat.NV12: cv2.COLOR_YUV2BGR_NV12,
        OBFormat.NV21: cv2.COLOR_YUV2BGR_NV21,
    }
    if color_format in yuv420_formats:
        return cv2.cvtColor(data.reshape(height * 3 // 2, width), yuv420_formats[color_format])
    raise ValueError(f'Unsupported Astra+ color format: {color_format}')
