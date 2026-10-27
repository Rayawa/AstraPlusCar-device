# AstraPlusCar-device

English | [简体中文](README_zh.md)

Control and computer-vision examples for an Ascend-based robot car with ESP32 integration.

## Overview

This branch integrates a Python vehicle runtime, camera sharing, motion arbitration, lidar acquisition and local HTTP services for the HarmonyOS controller. AI scenes submit motion requests through the runtime rather than owning the chassis directly. The current chassis path is I²C-based; older ESP32 serial examples are retained separately. Voice control and individual model workflows have their own dependencies and validation status.

## Technology and Dependencies

Python 3, NumPy, OpenCV, PySerial, filelock and PyTorch as listed in `python/requirements.txt`. Ascend inference requires a compatible CANN/ACL installation and `.om` models. Camera, chassis, lidar and ESP32 workflows need their matching SDKs, drivers and hardware.

## Repository Structure

- `python/` — runtime, motion scenes, camera helpers and inference models.
- `ESP32/` — microcontroller resources.
- `Lane-Follow-Train/` — lane-following training tools.
- `auto_label_tool/` and `det_label_split/` — dataset and annotation tools.
- `Lidar/` and `lidar_test/` — lidar integration and experiments.
- `docs/` — service interfaces and operation notes.
- `deploy/` — host service configuration.

## Quick Start

On the configured Linux vehicle host, review the hardware connections and install the platform SDKs first. Then, from the repository root:

```bash
cd python
python3 -m pip install -r requirements.txt
python3 main.py --help
```

After checking the selected branch's mode options and hardware configuration, use `python3 main.py --mode manual` for its manual-control entry. For phone control, inspect `python3 main.py --mode phone --help` and the [phone API](docs/PHONE_API.md). The local HTTP address is `http://<vehicle-host>:8080`; use the actual host address rather than a recorded deployment IP. Model files, camera drivers and serial device paths must match the host. Read the source before enabling movement.
