# AstraPlusCar-device

[English](README.md) | 简体中文

面向 Ascend 智能小车、结合 ESP32 的控制与计算机视觉示例。

## 项目概述

默认分支保留相机与推理驱动运动的示例及 ESP32 通信基线，包含手动和辅助运动场景、训练/标注工具及雷达实验。各模块的硬件条件不同，需要先配置 Ascend 开发板环境。

`codex/app` 分支包含后续服务和底盘整合，以及 HarmonyOS 手机接口；其命令和接线与默认分支不同，部署时应阅读对应分支文档。

## 技术栈与依赖

Python 3、NumPy、OpenCV、PySerial、filelock 和 PyTorch，见 `python/requirements.txt`。Ascend 推理另需兼容的 CANN/ACL 与 `.om` 模型；相机、底盘、雷达和 ESP32 流程需匹配的 SDK、驱动及硬件。

## 文件结构

- `python/` — 运行入口、运动场景、相机工具与推理模型。
- `ESP32/` — 微控制器相关资源。
- `Lane-Follow-Train/` — 巡线训练工具。
- `auto_label_tool/`、`det_label_split/` — 数据集与标注工具。
- `Lidar/`、`lidar_test/` — 雷达集成与实验。

## 快速上手

在已配置的 Linux 车端先核对硬件接线并安装平台 SDK，再从仓库根目录执行：

```bash
cd python
python3 -m pip install -r requirements.txt
python3 main.py --help
```

确认当前分支的模式和硬件配置后，可使用 `python3 main.py --mode manual` 进入手动控制。默认分支还包含 `cmd`、`easy`、`voice` 模式。模型、相机驱动及串口设备路径须与主机匹配，启用运动前先阅读源码。
