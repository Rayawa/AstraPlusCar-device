# AstraPlusCar

AstraPlusCar 是一台以 **Orange Pi AI Pro（Ascend 平台）** 为主控的智能小车。设备端用一套 Python 统一主程序驱动麦轮底盘、Astra+ 相机与 Slamtec 雷达，并运行 Ascend 离线模型完成标识识别、巡线与目标跟踪；手机端用 HarmonyOS 应用通过局域网 HTTP 遥控小车、观看实时画面并把截图存入私有图库。

| 项目 | 内容 |
| --- | --- |
| 设备端入口 | `python3 main.py --mode manual`（另可选 `cmd` / `easy` / `phone` / `voice`） |
| 手机连接地址 | `http://<小车地址>:8080`（2026-09-30 实车联调为 `http://192.168.8.204:8080`） |
| 车端部署目录 | `/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python` |
| 硬件平台 | Orange Pi AI Pro / Ascend CANN / Python 3.9 / Linux |

本文统一使用 `python3 main.py --mode 模式` 书写主程序命令。**仓库代码与车上已部署代码可能不同，启动前先核对目录和 `--help`。**

## 1. 项目内容

### 1.1 双仓库结构

整个产品由两个独立 Git 仓库组成，分别管理、分别验证：

| 仓库 | 职责 |
| --- | --- |
| `AstraPlusCar-device`（本仓库） | 设备端 Python 主程序、底盘运动控制、相机与雷达采集、AI 推理、HTTP API、部署与服务配置，以及训练/标注等离线工具。 |
| [AstraPlusCar-HarmonyOS](../AstraPlusCar-HarmonyOS/README.md) | ArkTS 手机应用：显示视频与三向雷达、发送驾驶与调速指令、保存截图到应用私有图库。 |

工作区根目录不初始化 Git，两份历史不合并。部署更新时须保留模型、采集数据与车端已有改动。

### 1.2 系统架构

职责划分：**手机负责界面与高层指令，设备端负责硬件与运动控制**。二者之间只有一条局域网 HTTP 通道，没有云端依赖。

```text
┌──────────────────────────────────────────────┐
│              HarmonyOS 手机 App              │
│     视频预览 / 三向雷达 / 控制盘 / 图库      │
└───────────────────┬──────────────────────────┘
                    │ 局域网 HTTP :8080
┌───────────────────┴──────────────────────────┐
│          设备端 main.py 统一主程序           │
│  ┌────────────────────────────────────────┐  │
│  │ 主循环：输入 → 运动仲裁 → 底盘         │  │
│  │ （唯一底盘写者）                       │  │
│  ├────────────────────────────────────────┤  │
│  │ 相机进程：CameraBroadcaster            │  │
│  │ 场景进程：AI 推理 → 动作队列           │  │
│  │ 服务线程：预览 / 手机 / 语音 / 雷达    │  │
│  └────────────────────────────────────────┘  │
└──────┬──────────────┬──────────────┬─────────┘
  Astra+ 相机   Slamtec 雷达  麦轮底盘（I²C）
 彩色流 / 截图  扫描测距 / 扇区  四轮速度与转向
```

### 1.3 设备端运行架构

主程序是一个进程 + 若干子进程/线程的组合，几条关键约定保证硬件不被争用：

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| 主循环与参数 | `python/main.py` | 解析模式与参数，用 `/tmp/astrapluscar-main.lock` 文件锁保证**同一时刻只有一个主程序占用硬件**；启动相机、服务与场景，循环处理输入。 |
| 运动仲裁 | `python/motion_control.py` | `MotionArbiter` 是唯一的底盘写者：把键盘、手机、语音、AI 场景的动作统一成一条指令流，管理速度、定时动作（掉头）、优先级与停车。 |
| 相机广播 | `python/src/utils/camera_broadcaster.py` | 相机子进程把彩色帧写入共享内存，预览、截图与 AI 共用同一份最新帧，避免重复打开相机。 |
| 场景进程 | `python/src/scenes/` | 每个 AI 场景独立进程，只向动作队列提交动作，不直接打开底盘或相机。 |
| 硬件服务 | `python/phone_mode.py`、`camera_preview.py`、`voice_control.py`、`lidar_probe.py` | 手机 HTTP、网页预览、语音识别、雷达采集，均以线程/子进程形式挂载到主循环。 |
| 底盘驱动 | `python/src/utils/controller.py` + `chassis_control_node.py` | 当前 `Controller` 使用 I²C 麦轮底盘实现；仓库也保留 ESP32 串口方案，接线与底层驱动须按实际车辆确认。 |

主程序处理 `Ctrl+C`、`SIGTERM`、`SIGHUP` 与输入断开时**先停车再关闭后台任务**；相机、语音或雷达服务异常会停车退出。运行中的相机、截图、AI 共用唯一广播器，雷达适配器是串口的唯一读取者。

### 1.4 硬件组成

| 部件 | 说明与已知配置 |
| --- | --- |
| 主控 | Orange Pi AI Pro，Linux + Python 3.9（已见 3.9.2），Ascend CANN / ACL 提供 `.om` 模型推理。 |
| 相机 | Astra+ USB 相机（Orbbec，USB ID `2bc5:0536/0636`），Orbbec SDK v1 Python binding；当前只采集彩色流，未提供深度驾驶功能。 |
| 底盘 | 麦轮底盘 + 编码电机驱动板，I²C 总线 7、设备地址 `0x34`；轮向与行驶速度须现场校准。 |
| 雷达 | Slamtec 雷达到串口适配器（CP2102），通过 SDK 自带的 `ultra_simple` 可执行文件读取，独立扫描不要求 ROS2。 |
| 语音 | ALSA `arecord` 可用的麦克风 + Vosk 中文模型（可选，本车尚未验收）。 |

## 2. 小车功能

### 2.1 功能总览

| 功能 | 入口 | 操作方式 | 依赖 |
| --- | --- | --- | --- |
| 键盘驾驶 | `--mode manual` | SSH 单键输入 | 底盘 |
| 网页实时预览 | `--camera`（manual / cmd / easy） | 浏览器 + SSH 隧道 | 相机 |
| 标识辅助 Helper | `--mode easy`，或 `cmd` 中输入 `Helper` | AI 自动执行左转/右转/掉头/停车 | `weights/yolo.om`（仓库已提供） |
| 巡线 LF | `cmd` 中输入 `LF` | AI 自动巡线 | `weights/lfnet.om`（需自备） |
| 目标跟踪 Tracking | `cmd` 中输入 `Tracking` | AI 自动跟踪目标 | `weights/tracking.om`（需自备） |
| 手机遥控 | `--mode phone` | HarmonyOS App | 手机 + 同一 WLAN |
| 语音驾驶 | `--mode voice` 或 `--voice` | 中文短句 | Vosk + 麦克风 + 中文模型 |
| 截图 | 键盘 `p`、语音“拍照”、网页、手机 | 保存最新完整帧 | 相机 |
| 雷达距离监测 | `--lidar` / `--radar`；`phone` 自动开启 | 网页或 API 只读显示 | Slamtec 雷达 |
| 独立硬件检查 | `camera_probe.py`、`camera_preview.py`、`lidar_probe.py` | 命令行 | 对应硬件 |

各功能的完整按键、参数与限制见第 4 节；启动步骤见第 3 节。

### 2.2 键盘驾驶（manual）

SSH 终端里单键输入、不按回车，初始速度控制值 40（范围 0–100）：

| 按键 | 动作 |
| --- | --- |
| `w` / `s` | 前进 / 后退 |
| `a` / `d` | 左转 / 右转 |
| `q` / `e` | 原地逆时针 / 顺时针旋转 |
| `←` / `→` | 左 / 右平移 |
| `↑` / `↓` | 速度加 / 减 20，限制在 0–100 |
| `z` | 固定旋转速度 80 的定时掉头，当前计时约 3.31 秒（按实测 280–290° 校准，须现场复核） |
| 空格 | 停车，留在程序中 |
| `Esc` | 停车并退出 |
| `p` | 后台保存截图，不改变当前运动 |

**松开键盘按键不会自动停车，须按空格。** 定时掉头可用空格或其他运动键中断，掉头期间调速会先停车。

### 2.3 场景命令与 AI 推理（cmd / easy）

`cmd` 模式下按回车提交场景名，大小写须完全一致：

| 输入 | 效果 | 模型 |
| --- | --- | --- |
| `Helper` | 识别标识并执行左转、右转、掉头或停车动作 | `weights/yolo.om` |
| `LF` | 运行巡线场景 | `weights/lfnet.om` |
| `Tracking` | 运行目标跟踪场景 | `weights/tracking.om` |
| `clear` | 停车并结束当前场景，保留命令模式 | 无 |
| `stop` | 停车并退出主程序 | 无 |
| `p` | 保存截图 | 无 |
| `Manual` | 报告不支持切换；须退出后重新启动 `--mode manual` | 无 |

`easy` 模式等价于启动后自动进入 `Helper`，不自动启动 `LF`。键盘运动键或空格可随时接管并结束 AI 控制；要恢复 AI 须退出后重启 `easy`，或在 `cmd` 中重新输入场景名。启动新场景会先停车并结束旧场景。

模型状态：仓库目前提供 `yolo.om`，已在车上验证加载与照片推理；`lfnet.om` 与 `tracking.om` 仍需另行提供并验收。三者用途不同，不能靠重命名 `yolo.om` 代替。`Helper` 当前没有加载辅助分类模型 `cls.om`。

### 2.4 手机遥控（phone）

`--mode phone` 启动后自动开启相机与雷达，并监听 `0.0.0.0:8080`。手机与小车接入同一 WLAN，App 连接 `http://<小车地址>:8080` 即可看到视频、三向雷达与截图图库。

关键设计：

- **相机**：1280×720 @ 30 FPS 采集，并以 MJPEG 原始数据发布到共享最新帧槽；驾驶预览用半尺寸解码生成 640×360、质量 75 的 JPEG 以降低无线带宽，截图仍解码完整 720p。
- **控制安全**：运动指令带会话（`sessionId`）、递增序号（`seq`）与唯一命令 ID；按住动作时 App 约每 150 ms 续期，**超过 600 ms 未续期车端自动停车并使会话失效**；停止后旧会话不能恢复运动，重复命令不会执行两次。
- **看门狗**：App 侧视频超过 2 秒无新帧即停止控制并断开，前台按退避策略自动重连，重连后不会重放旧动作。

完整 API 契约见 [docs/PHONE_API.md](docs/PHONE_API.md)，参数与排查见 4.9 节。

### 2.5 相机预览与截图

预览与驾驶共用同一个相机广播器：驾驶模式加 `--camera` 会在小车 `127.0.0.1:8765` 打开网页预览，电脑建立 SSH 隧道后即可在浏览器观看 MJPEG、查看状态或保存当前画面。主程序预览默认限制为 10 fps（可通过 `?fps=1..30` 按客户端限速），AI 与截图继续读取完整采集帧。

截图入口有四个，共用最新完整帧：键盘 `p`、语音“拍照”、网页 `/snapshot.jpg`、手机 `POST /api/v1/camera/captures`。默认写入 `capture/`，文件名由纳秒时间戳与随机串组成。

### 2.6 雷达距离监测

雷达每秒更新一次扫描摘要，输出全扫描最近距离与四个方向 ±30° 扇区的最近距离：

| 字段 | 方向 |
| --- | --- |
| `front_nearest_mm` | 0°（前） |
| `sector_90_mm` | 90°（右） |
| `sector_180_mm` | 180°（后） |
| `sector_270_mm` | 270°（左） |

单位均为毫米；超过 2.5 秒未更新标为 `stale`，没有有效或新鲜数据时距离为 `null`。**雷达只监测距离，当前没有自动避障。** 手机界面显示左/前/右三向。

### 2.7 语音控制（可选）

用 Vosk 离线中文模型识别短句并映射为按键：前进/后退/左转/右转/左旋转/右旋转/左平移/右平移/加速/减速/掉头/拍照/停车/退出。语音运动默认持续 1 秒后自动停车，可用 `--voice-move-seconds` 调整（大于 0、不超过 5 秒）；键盘运动指令会取消旧语音动作。

本车此前检查未发现系统可识别的麦克风/声卡，也没有可用中文模型，**语音驾驶仍需补齐依赖后验收**。无硬件时可用 `python3 voice_control.py 前进` 只验证文字映射。

## 3. 上手指南

### 3.1 第一步：SSH 连接小车

```bash
ssh root@192.168.8.204
```

手机、电脑与小车须接入同一网络。车端 `192.168.8.204` 实际位于 `eth0`，`wlan0` 保留 `192.168.149.1`；换网络后以小车实际地址为准。

### 3.2 第二步：初始化环境

每次新开 SSH 会话都要重新执行；这些变量不会自动保留：

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
source /home/HwHiAiUser/pyorbbecsdk/env.sh
export PYTHONPATH="/home/HwHiAiUser/pyorbbecsdk/install/lib${PYTHONPATH:+:$PYTHONPATH}"
export PATH="/usr/local/miniconda3/bin:$PATH"
cd /home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python
CAMERA_PY=/home/HwHiAiUser/pyorbbecsdk/venv/bin/python
```

`CAMERA_PY` 是相机专用解释器（独立相机工具使用）；主程序用 `python3` 或 `/usr/local/miniconda3/bin/python`。

### 3.3 第三步：选择功能并启动

按下表选择一项启动。**驾驶模式须先确认车轮架空或场地安全**；先退出占用同一硬件的程序，已有手机服务运行时先用 `systemctl stop astra-phone` 停止。

| 功能 | 启动命令 | 启动后操作 / 条件 |
| --- | --- | --- |
| 键盘驾驶 | `python3 main.py --mode manual` | 单键输入，空格停车，`Esc` 退出 |
| 场景调度 | `python3 main.py --mode cmd` | 输入场景名或管理命令后按回车 |
| 标识辅助 | `python3 main.py --mode easy` | 自动启动 `Helper`，需要 `weights/yolo.om` |
| 巡线 | `python3 main.py --mode cmd` | 输入 `LF` 后回车，需要 `weights/lfnet.om` |
| 目标跟踪 | `python3 main.py --mode cmd` | 输入 `Tracking` 后回车，需要 `weights/tracking.om` |
| 手机控制 | `python3 main.py --mode phone` | App 连接 `http://192.168.8.204:8080`；前台运行，`Ctrl+C` 退出 |
| 语音驾驶 | `python3 main.py --mode voice --voice-model /path/to/vosk-model` | 相当于手动加后台语音，需要麦克风、Vosk 和中文模型 |
| 驾驶时网页看画面 | `python3 main.py --mode manual --camera` | 通过 SSH 隧道打开浏览器预览 |
| 驾驶时查看雷达 | `python3 main.py --mode manual --camera --lidar` | 预览页同时显示雷达状态；不自动避障 |
| 独立拍照 / 取帧检查 | `$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg` | 不打开底盘，检查彩色帧并保存照片 |
| 独立网页预览 | `$CAMERA_PY camera_preview.py` | 不打开底盘，通过 SSH 隧道访问 |
| 独立雷达检查 | `python3 lidar_probe.py --seconds 12` | 不打开底盘，结束后输出汇总 JSON |
| 持续雷达检查 | `python3 lidar_probe.py --follow` | 每秒输出 JSON，`Ctrl+C` 停止 |
| 语音文字映射检查 | `python3 voice_control.py 前进` | 只输出 `w`，不录音、不驱动车辆 |

不带任何参数运行 `python3 main.py` 等同 `--mode manual`。2026-09-30 已将统一主程序部署到上述车载目录，所有模式共用同一入口。

### 3.4 第四步：验证运行

启动后按顺序确认，能在早期发现大部分问题：

| 检查项 | 方法 | 期望结果 |
| --- | --- | --- |
| 程序就绪 | 观察启动日志 | 出现 `Ready: mode=...`，无 `Startup checks failed` |
| 画面正常 | 加 `--camera` 后建立隧道：`ssh -N -L 8765:127.0.0.1:8765 root@192.168.8.204`，浏览器打开 `http://127.0.0.1:8765/` | 画面实时刷新，`/status.json` 中 `camera.status` 为 `live` |
| 相机独立验证 | `$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg` | 输出帧数、分辨率、亮度，并保存非黑彩色照片 |
| 截图落盘 | 按 `p`，然后执行 `ls -lt capture/*.jpg`（最新在前） | 打印 `Screenshot saved: ...` 且文件存在 |
| 雷达正常 | `python3 lidar_probe.py --seconds 12` | JSON 中 `points` 大于 0，各方向距离有数值 |
| 手机联通 | `curl -fsS http://192.168.8.204:8080/api/v1/status` | 返回 `ok`、相机状态与雷达距离 |

从电脑下载车上文件：

```bash
scp root@192.168.8.204:/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python/capture/astra_check.jpg .
```

截图时间取决于车端时钟；车端日历时钟此前不正确（曾观察到回到 2024-12-26），NTP 自动校时未验证，重启后可检查 `timedatectl status`。

### 3.5 第五步：退出与常见问题

正常退出：驾驶模式按 `Esc`；`cmd` 模式输入 `stop`；前台 `phone` 模式按 `Ctrl+C`。程序会先停车再释放硬件。后台服务用 `systemctl stop astra-phone`。

| 情况 | 处理方式 |
| --- | --- |
| `invalid choice: 'phone'` | 检查 `pwd` 和 `python3 main.py --help`，确认进入正式目录并运行新版统一主程序 |
| `Another AstraPlusCar main program owns the hardware` | 先退出占用硬件的主程序或停止对应服务 |
| 缺少 `pyorbbecsdk` / `acl` | 重新加载环境，并检查 Python 版本与 SDK binding 路径；单纯导入成功不代表所有硬件就绪 |
| 找不到 `.om` 模型 | 检查启动目录与 `weights/`；补齐场景对应模型 |
| `Voice` / `Lidar` 启动检查失败 | 按错误检查模型、麦克风、SDK、串口路径和权限 |
| 相机无新鲜帧 / HTTP 503 | 确认其他相机程序已退出，先用相机探针检查 USB 与取流 |
| 手机视频卡顿或断流 | 见 4.9 节排查步骤；车端 `logs/` 中的 `MJPEG stream closed` 记录发送异常 |

## 4. 模式与参数详解

本节依据本仓库 `python/main.py` 和独立工具的实际代码编写。所有启动参数都写在命令后面；按键、场景名和 HTTP 字段是在程序启动后使用的输入。

### 4.1 主模式与通用参数

```bash
python3 main.py --mode manual
python3 main.py --mode manual --camera --lidar
python3 main.py --help
```

| 参数 | 默认值 | 用法 |
| --- | --- | --- |
| `--mode` | `manual` | 选择 `manual`、`cmd`、`easy`、`phone` 或 `voice` |
| `--manual` / `--cmd` / `--easy` / `--phone` | 无 | 对应模式的兼容简写；不能与另一个主模式参数同时使用。本文示例统一使用 `--mode` |
| `--camera` | 关闭网页预览 | 在非 `phone` 模式开启本机预览；关闭它仍会采集相机，供截图与 AI 使用 |
| `--camera-port` | `8765` | 非 `phone` 预览端口，整数 1–65535 |
| `--phone-port` | `8080` | `phone` HTTP 端口，整数 1–65535 |
| `--capture-dir` | `capture` | 主程序截图目录；相对路径从启动目录计算 |
| `--voice` | 关闭 | 附加后台语音；它是功能开关，`--mode voice` 则会映射为 `manual + --voice` |
| `--voice-model` | 自动查找 | Vosk 模型目录，详见 4.8 节 |
| `--voice-device` | ALSA 默认设备 | 指定麦克风设备，例如 `plughw:1,0`，以 `arecord -l` 为准 |
| `--voice-move-seconds` | `1.0` | 语音运动自动停车时间，必须大于 0 且不超过 5 秒 |
| `--lidar` / `--radar` | 关闭 | 开启雷达，二者等价；`phone` 自动开启 |
| `--lidar-sdk` | `/home/HwHiAiUser/rplidar_sdk/output/Linux/Release/ultra_simple` | 雷达 SDK 可执行文件路径 |
| `--lidar-port` | `/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0` | 雷达串口路径 |
| `--lidar-baudrate` | `115200` | 雷达波特率，正整数 |
| `-h` / `--help` | 无 | 显示当前文件支持的参数后退出，不启动硬件 |

主程序没有 `--speed`、`--model` 或 `--mode LF` 参数。速度由运行后的键盘或手机指令调整；AI 模型路径由各场景确定。

### 4.2 manual：键盘驾驶与调速

按键与行为见 2.2 节。补充说明：

- 键盘运动指令发出后**松开按键不会自动停车**，须按空格。
- 运动指令在 1 秒内有效；停车与退出指令会清空待执行的积压动作。
- 速度键在行驶时立即更新当前动作，静止时设置下一次动作的速度；在定时掉头期间调速会先停车。

### 4.3 cmd：场景命令与 AI 模型

场景名、管理命令与模型依赖见 2.3 节。补充说明：`cmd` 中的 `w/a/s/d` 不是键盘驾驶命令；未知命令只打印错误。

### 4.4 easy：自动进入标识辅助

```bash
python3 main.py --mode easy
```

`easy` 自动启动 `Helper`，不自动启动 `LF`。它依赖标识检测结果执行动作，不等同于巡线。键盘运动键或空格可接管并结束 AI 控制；要恢复 `Helper`，退出后重新启动 `easy`，或改用 `cmd` 显式启动场景。`Esc` 停车退出；`Helper` 场景异常退出时主程序会停车报错。

### 4.5 相机预览、截图与保存路径

驾驶与网页预览共用同一个相机广播器：

```bash
python3 main.py --mode manual --camera --camera-port 8765 --capture-dir capture
```

电脑另开终端建立隧道，并保持其运行：

```bash
ssh -N -L 8765:127.0.0.1:8765 root@192.168.8.204
```

浏览器访问 `http://127.0.0.1:8765/`。非 `phone` 预览仅监听小车的 `127.0.0.1`；改 `--camera-port` 时也要修改隧道右侧端口。页面提供 MJPEG、保存画面入口和 `/status.json`；状态包含服务端时间与画面时间。`/stream.mjpg?fps=1..30` 可按客户端单独限速，超出范围返回 400。

键盘 `p`、语音“拍照”、网页截图与手机截图共用最新完整帧。主程序默认保存到 `capture/`，可改为：

```bash
python3 main.py --mode manual --capture-dir /home/HwHiAiUser/astra-captures
```

看到 `Screenshot saved` 或 HTTP 截图成功响应才表示文件写入成功。帧过期、队列满或保存失败会明确报错；截图写盘在后台进行，不阻塞驾驶。

### 4.6 独立相机工具

独立工具不初始化底盘，使用相机专用 Python；运行前退出其他相机程序。

```bash
$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg
$CAMERA_PY camera_preview.py --port 8765 --width 640 --height 480 --fps 15 --quality 70
```

| 工具 | 参数 | 默认值与作用 |
| --- | --- | --- |
| `camera_probe.py` | `--seconds` | 10，正整数；取帧检查时长。用 600 可检查 10 分钟连续取流 |
| `camera_probe.py` | `--output` | `capture/astra_probe_时间戳.jpg`；保存并校验最后一张新鲜彩色帧 |
| `camera_preview.py` | `--port` | 8765，范围 1–65535；同样通过 SSH 隧道访问 |
| `camera_preview.py` | `--width` / `--height` | 1280 / 720，正整数；请求的彩色流尺寸，实际以相机支持的配置为准 |
| `camera_preview.py` | `--fps` | 15，正整数；请求采集帧率与预览编码帧率 |
| `camera_preview.py` | `--quality` | 70，范围 1–100；JPEG 质量 |

拍照探针会输出帧数、分辨率、亮度与保存结果；5 秒收不到彩色帧会报错。预览可通过 `/snapshot.jpg` 获取并保存截图，通过 `/status.json` 查看状态。独立预览没有雷达采集，`Ctrl+C` 结束后再启动其他相机程序。

### 4.7 雷达采集与参数

在驾驶主程序中附加雷达：

```bash
python3 main.py --mode manual --camera --lidar \
  --lidar-port /dev/ttyUSB0 --lidar-baudrate 115200
```

串口示例须按实际设备修改，优先使用 `/dev/serial/by-id/` 的稳定路径。`--lidar-sdk` 可指定其他兼容的 `ultra_simple` 可执行文件。雷达每秒更新扫描摘要；预览页和 `/status.json` 可读取它。

只检查雷达时使用独立工具：

```bash
python3 lidar_probe.py --seconds 12
python3 lidar_probe.py --follow
python3 lidar_probe.py --port /dev/ttyUSB0 --baudrate 115200 --seconds 12
```

| 独立工具参数 | 默认值与作用 |
| --- | --- |
| `--sdk` | 与主程序 `--lidar-sdk` 的默认路径相同 |
| `--port` | 与主程序 `--lidar-port` 的默认串口相同 |
| `--baudrate` | 115200，正整数 |
| `--seconds` | 8，正数；单次采集时长，结束后输出一条汇总 JSON |
| `--follow` / `--continuous` | 持续模式，每秒一行 JSON；此时 `--seconds` 不限制总时长，`Ctrl+C` 停止 |

JSON 字段含义见 2.6 节。主程序持续采集使用最近一秒的窗口。主程序已开雷达时不要再运行独立探针抢占同一串口；持续探针退出时会通知 SDK 停止雷达电机。

### 4.8 语音控制与模型配置

先检查 ALSA 麦克风并安装可选依赖：

```bash
arecord -l
python3 -m pip install -r requirements-voice.txt
python3 main.py --mode voice --voice-model /path/to/vosk-model \
  --voice-device plughw:1,0 --voice-move-seconds 1.5
```

将示例路径和设备名换成实际值。模型必须是解压后的目录，至少包含 `am/final.mdl` 和 `conf/mfcc.conf`。查找顺序为显式 `--voice-model`、环境变量 `VOSK_MODEL_PATH`，以及未设置环境变量时主入口旁 `weights/vosk-model/`。

也可给 `cmd` 或 `easy` 附加 `--voice`：

```bash
export VOSK_MODEL_PATH=/home/HwHiAiUser/models/vosk-chinese
python3 main.py --mode manual --voice
```

语音运动会接管 AI，之后须显式重启场景；键盘运动指令会取消旧语音动作。短句映射见 2.7 节。无硬件时只验证文字映射：

```bash
python3 voice_control.py 前进
python3 voice_control.py 左平移
```

它只接收一条文本并输出按键，不监听麦克风或控制车辆。

### 4.9 phone：手机控制与 HTTP 参数

先停止后台手机服务，再启动前台手机模式：

```bash
systemctl stop astra-phone
python3 main.py --mode phone --phone-port 8080 --capture-dir capture
```

`phone` 自动启用相机和雷达，相机使用 1280×720 @ 30 FPS 配置并只发布 JPEG。HTTP 监听 `0.0.0.0:8080`，无需 `--camera`；`--camera-port` 不改变手机服务端口，修改 `--phone-port` 后也要修改 App 地址。前台模式可用 `Ctrl+C` 停车退出，手机驾驶不通过 SSH 单键输入。

手机模式在支持的相机上关闭“曝光优先”，保持自动曝光但优先维持帧率；退出后恢复原值，避免影响其他模式。暗光下画面亮度可能降低。实测相机源从约 19.4 FPS 恢复到 29.99 FPS。

| API | 参数 / 用途 |
| --- | --- |
| `GET /api/v1/status` | 查看模式、速度、运动状态、相机、雷达与服务端时间 |
| `GET /api/v1/camera/frame.jpg` | 获取当前 JPEG，不写盘 |
| `GET /api/v1/camera/stream.mjpg` | 获取连续 MJPEG，支持 `?fps=1..30` 按客户端限速 |
| `POST /api/v1/camera/captures` | 请求体 `{}`；保存截图，返回 `captureId` 和下载 `url` |
| `GET /api/v1/camera/captures/{captureId}` | 下载已保存的 JPEG |
| `POST /api/v1/control/session` | 请求体 `{}`；取得 `sessionId`、`bootId` 和 `leaseMs=600`，本操作不运动 |
| `POST /api/v1/control/command` | `sessionId`、递增整数 `seq`、唯一 `commandId`、`key`。支持 `q/w/e/a/s/d/z/up/down/left/right` |
| `POST /api/v1/control/speed` | 同样带会话、序号和命令 ID；`speed` 为 0–100 的整数 |
| `POST /api/v1/control/renew` | `sessionId` 与当前运动的 `commandId`；运动期间约每 150 ms 续期 |
| `POST /api/v1/control/stop` | `sessionId`；停车并使会话失效，下次运动重新建会话 |

速度初始值为 40，`up/down` 每次调 20。停止后旧会话不能恢复运动；未续期超过 600 ms 会自动停车。`seq` 在会话内递增，同一个 `commandId` 的重复请求不会执行两次；续期不会重新发运动指令或重启掉头计时。

在电脑或小车上查看状态、保存截图：

```bash
curl -fsS http://192.168.8.204:8080/api/v1/status
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{}' http://192.168.8.204:8080/api/v1/camera/captures
```

第二条会在车上创建截图。成功响应包含 `ok: true`；错误包含 `ok: false`、`code` 和 `message`，常见状态码为 400（参数错误）、404（不存在）、409（会话或序号失效）和 503（服务暂不可用）。完整请求与响应见 [docs/PHONE_API.md](docs/PHONE_API.md)。**API 当前没有身份认证，应在受信任局域网使用，不要把 8080 端口转发到其他网络。**

#### 视频卡顿与断流排查

原 180 ms 单图轮询限制了显示帧率，现已改为持续 MJPEG，并使用 640×360 驾驶预览降低带宽。视频发送超时由 1 秒调整为 1.5 秒，并保留有界发送缓冲区和最新帧策略。

2026-10-02 的只读诊断（[docs/STREAM_DIAGNOSIS_2026-10-02.md](docs/STREAM_DIAGNOSIS_2026-10-02.md)）对比了两条路径：

| 测试路径 | 时间 | 帧数 / FPS | 视频断流 | 最大帧间隔 | 状态失败 / 最大耗时 |
| --- | --- | --- | --- | --- | --- |
| 电脑 → 局域网 → 车端 | 180 s | 4674 / 25.96 | 6 次，共 7 个连接 | 4531 ms | 0 / 2042 ms |
| 车端 127.0.0.1 回环 | 180 s | 5379 / 29.88 | 0 次，单连接 | 110 ms | 0 / 50 ms |

证据指向局域网传输停顿，而非相机停止出帧；具体原因（路由器、无线拥塞或终端）尚未确定，**不能宣称无线断流已完全消除**。App 已实现前台自动退避重连，仍保留 2 秒视频看门狗与独立的设备 600 ms 运动租约；断流时清除按键、会话与续期，重连后不会重放旧动作。复测命令：

```bash
python3 python/test/diagnose_phone_stream.py --base-url http://192.168.8.204:8080 --seconds 180
```

该脚本只发 GET 请求，同时读取视频与每秒状态，默认不写截图；回环测试在车端把地址换成 `http://127.0.0.1:8080`。配置为 30 FPS 不等于实际达到 30 FPS，应同时检查界面 FPS 与相机采集。

#### 正式手机服务管理

正式目录为 `/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python`。`astra-phone.service` 已安装，`python/start_phone.sh` 加载 Ascend 和 Orbbec 环境后运行 `/usr/local/miniconda3/bin/python main.py --mode phone`。**服务未设置开机自启**，重启后手动启动即可。

```bash
systemctl start astra-phone
systemctl status astra-phone
systemctl stop astra-phone
```

运行日志由程序写入正式目录的 `logs/`，服务管理日志可用 `journalctl -u astra-phone -f` 查看。被替换的正式目录文件备份在 `/home/HwHiAiUser/astra-backups/phone-20260930`，模型权重和已有截图没有覆盖。切回其他模式前先执行 `systemctl stop astra-phone`。

### 4.10 退出与运行保护

程序在以下情况均先停车再释放资源：`Ctrl+C`、`SIGTERM`、`SIGHUP`、SSH 输入断开、运行中的相机/语音/雷达服务异常退出。截图单次保存失败只报告错误，通常不结束驾驶。

| 模式 | 停车方式 |
| --- | --- |
| `manual` / `easy` | 主动按空格；`Esc` 停车退出 |
| `cmd` | 输入 `clear` 停场景，`stop` 停车退出 |
| `voice` | 说“停车”，或按空格；语音动作本身也会在设定时长后自动停车 |
| `phone` | 松手即停车；断联、退后台、视频看门狗触发都会停车；车端 600 ms 租约独立兜底 |

键盘模式须主动停车，手机模式依赖动作释放与续期保护；这些路径仍需在实际设备上分别验收。

## 5. 项目依赖

### 5.1 设备与系统环境

| 依赖 | 用途与已知配置 |
| --- | --- |
| Orange Pi AI Pro、Linux、Python 3.9 | 当前车端运行平台；已见 Python 3.9.2。主程序使用 POSIX 终端、进程与文件锁 |
| Ascend CANN / ACL | `.om` 模型推理；环境脚本 `/usr/local/Ascend/ascend-toolkit/set_env.sh` |
| Orbbec SDK v1 Python binding | Astra+ 彩色流；本车 binding 在 `/home/HwHiAiUser/pyorbbecsdk/install/lib`，相机专用 Python 在 `pyorbbecsdk/venv/` |
| Astra+ USB 相机 | 主程序各模式都需要相机；当前采集彩色流，未提供深度驾驶功能 |
| 麦轮底盘 / 电机驱动板 | 当前代码使用 I²C 总线 7、设备地址 `0x34`；具体硬件与轮向须现场确认 |
| Slamtec 雷达及 SDK、`stdbuf` | `--lidar` 与 `phone` 必需；适配器通过 `stdbuf` 读取 SDK 输出，独立扫描不要求 ROS2 |
| ALSA `arecord`、麦克风 | 语音可选依赖；使用单声道 16 kHz 录音 |
| HarmonyOS 手机、DevEco Studio / SDK | 手机应用与构建环境，见 [HarmonyOS README](../AstraPlusCar-HarmonyOS/README.md) |

### 5.2 Python 包与模型

`python/requirements.txt` 列出了 `pyserial`、`filelock`、`numpy`、`opencv-python` 和 `torch`；它没有覆盖全部系统 SDK 与运行依赖。

| 功能 | 主要额外依赖 |
| --- | --- |
| 相机与截图 | `pyorbbecsdk`、OpenCV、NumPy；binding 须与 Python 和板端 SDK 匹配 |
| 当前底盘控制 | `smbus2`；控制器模块也引用串口与文件锁相关包 |
| AI 场景 | `acl`、`ais_bench`、`torch`、`torchvision`，以及对应 `.om` |
| YAML 工具 | `PyYAML` |
| 后台语音 | `requirements-voice.txt` 中的 `vosk`、中文模型和可用录音设备 |

在另行准备的开发环境中安装 Python 包的示例；车端已有环境先核对已装依赖：

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install smbus2 PyYAML
# 需要语音时再安装
python3 -m pip install -r requirements-voice.txt
```

CANN、ACL、Orbbec binding、`ais_bench` 以及板端 `torch` / `torchvision` 环境按已有 SDK 与平台版本配套配置，不能仅靠上述通用包列表补齐。设备上已有工作环境时先检查，避免更换不兼容版本。完整导入检查：

```bash
python3 -c 'import cv2, numpy, pyorbbecsdk, acl, ais_bench, yaml, serial, filelock, torch, torchvision, smbus2; print("dependencies ready")'
```

若当前 `python3` 缺少主程序依赖，可核对已安装的 `/usr/local/miniconda3/bin/python` 环境，再将启动命令的解释器换为该绝对路径。相机专用环境与主程序环境的包并不完全相同。

## 6. 文件结构

```text
AstraPlusCar/                         # 工作区根目录，不是 Git 仓库
├── AstraPlusCar-device/              # 本仓库
│   ├── README.md
│   ├── docs/
│   │   ├── PHONE_API.md              # 手机 HTTP 协议
│   │   └── STREAM_DIAGNOSIS_2026-10-02.md  # 断流诊断记录
│   ├── deploy/astra-phone.service    # 正式服务配置模板
│   ├── python/
│   │   ├── main.py                   # 统一主入口
│   │   ├── start_phone.sh            # 正式 phone 服务启动脚本
│   │   ├── motion_control.py         # 指令仲裁、速度、定时动作、停车
│   │   ├── phone_mode.py             # HTTP 会话、续期与 API
│   │   ├── astra_camera.py           # Astra+ 取流与图像转换
│   │   ├── camera_tasks.py           # 后台截图任务
│   │   ├── camera_probe.py           # 独立取帧 / 拍照检查
│   │   ├── camera_preview.py         # 共享预览服务与独立预览入口
│   │   ├── lidar_probe.py            # 雷达扫描工具与后台服务
│   │   ├── voice_control.py          # Vosk 服务与文字映射工具
│   │   ├── requirements*.txt
│   │   ├── src/
│   │   │   ├── actions/              # 基础动作与组合动作
│   │   │   ├── scenes/               # Manual、Helper、LF、Tracking 场景
│   │   │   ├── models/               # Ascend 模型封装与后处理
│   │   │   └── utils/                # 底盘、相机广播、日志与 ACL 工具
│   │   ├── weights/                  # yolo.om；其他模型另行配置
│   │   ├── capture/                  # 默认截图输出
│   │   ├── logs/                     # 运行日志
│   │   └── test/
│   │       ├── offline/              # 离线回归用例
│   │       ├── live_phone_api.py     # 实车 Phone API 检查
│   │       └── diagnose_phone_stream.py  # 只读视频/状态诊断
│   ├── ESP32/                        # ESP32 电机 / 舵机固件
│   ├── 基于ESP32的智能小车控制/      # 接线与控制方案资料
│   ├── Lane-Follow-Train/            # 巡线模型训练
│   ├── auto_label_tool/              # 车道线 HSV 标注工具
│   ├── det_label_split/              # 检测数据转分类数据与训练工具
│   ├── lidar_test/                   # 雷达 SDK、ROS2 示例与配置
│   └── notebook/                     # 历史交互控制示例
└── AstraPlusCar-HarmonyOS/           # 独立的 ArkTS 应用仓库
    ├── entry/src/main/ets/           # 页面、组件、API、图库与模型
    └── README.md
```

`python/src/utils/main.py` 是遗留入口，不是本文对应的主程序；车辆应从 `python/main.py` 启动。临时联调目录和脚本位于车上，不属于此树中的正式部署文件。

## 7. 扩展与验证

### 7.1 新增场景与硬件能力

新增 AI 场景可参考 `src/scenes/base_scene.py`，在 `src/scenes/__init__.py` 注册场景名，通过 `cmd` 启动。场景读取主程序的共享帧，并向统一运动控制入口提交动作；相机预览、截图和 AI 复用唯一广播器，避免重复打开相机或让多个进程直接写底盘。

新增手机能力时同时检查设备端 API 与 HarmonyOS 客户端；运动、续期、急停、错误响应和数据单位须保持一致。电机、ESP32 引脚与底层串口行为放在设备端，客户端只发高层命令。

仓库保留了舵机动作与 ESP32 代码，但当前主程序没有独立舵机控制参数或手机舵机 API；不要把历史固件能力当作现有遥控入口。替换底盘驱动时须重新核对停车行为和轮向。

### 7.2 数据采集、标注与训练

| 扩展工具 | 使用入口与说明 |
| --- | --- |
| 巡线标注 | [auto_label_tool](auto_label_tool/README.md)：在该目录配置 `config/` 中的图片路径，用 `python3 check_hsv.py` 提取色域，再运行 `python3 main.py` 标注。这里的 `main.py` 是标注工具 |
| 巡线训练 | [Lane-Follow-Train](Lane-Follow-Train/README.md)：在该目录准备数据与 `config.yaml`，运行 `python3 train.py`，再将模型转换为与目标 Ascend 平台匹配的 `.om` |
| 检测辅助分类 | [det_label_split](det_label_split/README.md)：数据转换、分类训练和模型转换工具；当前 `Helper` 未启用辅助分类模型 |
| ESP32 控制 | [控制方案说明](基于ESP32的智能小车控制/基于ESP32的智能小车控制.md) 与 `ESP32/` 固件 |
| ROS2 雷达 / 建图 | `lidar_test/` 中的示例；此前车端未安装 ROS2，需要另行配置与验收 |

训练文档中的 ATC 芯片型号和输入格式只是各自样例配置，转换时须按实际板卡、模型与 CANN 版本核对。训练与标注应在各自目录和依赖环境运行，不属于车辆驾驶主模式。

### 7.3 正式部署与服务

2026-09-30 已部署到原车载目录并安装正式 `astra-phone.service`，原 `astra-phone-integration` 临时服务已停止。`python/start_phone.sh` 进入正式目录、加载 CANN 与 Orbbec binding，然后运行 `/usr/local/miniconda3/bin/python main.py --mode phone`；`deploy/astra-phone.service` 使用该脚本。

后续部署先备份并比较原目录，确认 Python 代码、SDK 依赖与模型相互匹配；更新服务模板后执行 `systemctl daemon-reload`。本次被替换文件的备份位于 `/home/HwHiAiUser/astra-backups/phone-20260930`。

### 7.4 离线与实车验证

设备端离线测试在本仓库根目录运行，开发环境需要 NumPy 和 OpenCV：

```bash
PYTHONPATH=python python3 -m unittest discover -s python/test/offline -v
PYTHONPATH=python python3 -m unittest discover -s python/test/utils -p test_camera_broadcaster.py -v
```

覆盖模式参数、共享帧、截图、HTTP、语音与键盘接管、计时、停车和资源清理。沙箱不支持回环端口或 POSIX 共享内存时，相应测试可能跳过；`python/test/` 其他历史用例包含旧接口和硬件依赖，不能与这套离线检查混为一谈。

HTTP 实车检查入口（在仓库根目录执行）：

```bash
python3 python/test/live_phone_api.py --base-url http://192.168.8.204:8080
```

默认检查状态、视频、截图创建和下载，不发送运动指令；它会在车端创建一张截图。**仅在车轮安全架空后**加 `--motion`，检查短时运动、速度、续期、停车和失联保护。

此前实车记录确认了 Astra+ 彩色取流、非黑截图、10 分钟连续采集，以及手机同 WLAN 下的视频、雷达、截图和图库。Phone API 的运动检查仅在车轮悬空时短时进行，已确认接口接受、停车和 600 ms 失联保护。**实际轮向、落地行驶、各 AI 场景、语音驾驶及 App 后台停车仍需现场分别验证；离线测试不能代替这些验收。**
