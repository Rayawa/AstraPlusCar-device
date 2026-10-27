# AstraPlusCar-device

English | [简体中文](README_zh.md)

Control and computer-vision examples for an Ascend-based robot car with ESP32 integration.

## Overview

The default branch retains the camera/inference-to-motion examples and ESP32 communication baseline. It includes manual and assisted motion scenes, training/annotation utilities and lidar experiments. Hardware support varies by module and requires a prepared Ascend development-board environment.

The `codex/app` branch contains later service and chassis integration, including the HarmonyOS phone interface; its commands and wiring differ from the default branch. Read the documentation for the branch being deployed.

## Technology and Dependencies

Python 3, NumPy, OpenCV, PySerial, filelock and PyTorch as listed in `python/requirements.txt`. Ascend inference requires a compatible CANN/ACL installation and `.om` models. Camera, chassis, lidar and ESP32 workflows need their matching SDKs, drivers and hardware.

## Repository Structure

- `python/` — runtime, motion scenes, camera helpers and inference models.
- `ESP32/` — microcontroller resources.
- `Lane-Follow-Train/` — lane-following training tools.
- `auto_label_tool/` and `det_label_split/` — dataset and annotation tools.
- `Lidar/` and `lidar_test/` — lidar integration and experiments.

## Quick Start

On the configured Linux vehicle host, review the hardware connections and install the platform SDKs first. Then, from the repository root:

```bash
cd python
python3 -m pip install -r requirements.txt
python3 main.py --help
```

After checking the selected branch's mode options and hardware configuration, use `python3 main.py --mode manual` for its manual-control entry. The default branch also includes `cmd`, `easy` and `voice` modes. Model files, camera drivers and serial device paths must match the host. Read the source before enabling movement.
