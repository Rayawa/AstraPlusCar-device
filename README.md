# AstraPlusCar

AstraPlusCar 是运行在 Orange Pi AI Pro / Ascend 平台上的智能小车项目，支持 SSH 键盘驾驶、HarmonyOS 手机遥控、Astra+ 相机视频与截图、雷达距离监测，以及基于离线模型的标识识别、巡线和目标跟踪。项目还保留了语音控制、数据标注、模型训练与 ESP32 控制相关代码，供后续扩展。

整个产品由两个独立 Git 仓库组成：

| 仓库 | 职责 |
| --- | --- |
| `AstraPlusCar-device`（本仓库） | 设备端 Python 主程序、相机、雷达、AI 推理、底盘控制与 HTTP API。 |
| [AstraPlusCar-HarmonyOS](../AstraPlusCar-HarmonyOS/README.md) | ArkTS 手机应用，通过局域网 HTTP API 显示视频、雷达距离，发送驾驶指令并保存截图。 |

```text
HarmonyOS App ── LAN HTTP ── 设备端主程序
                                ├── Astra+ 相机：视频、截图、AI 输入
                                ├── Slamtec 雷达：扫描、距离与状态
                                └── 统一运动控制：底盘动作
```

手机负责界面和高层指令，设备端负责硬件与运动控制。当前 `Controller` 使用 `chassis_control_node.py` 的 I²C 麦轮底盘实现；仓库也保留了 ESP32 串口方案，接线和底层驱动须按实际车辆确认。

本文统一使用 `python3 main.py --mode 模式` 书写主程序命令。**仓库代码与车上已部署代码可能不同，启动前先核对目录和 `--help`。**

## 1. 快速开始

### 第一步：SSH 连接

在电脑终端执行：

```bash
ssh root@192.168.8.204
```

### 第二步：环境初始化

在小车 SSH 终端一次性执行以下命令，每次新开会话都重新初始化：

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
source /home/HwHiAiUser/pyorbbecsdk/env.sh
export PYTHONPATH="/home/HwHiAiUser/pyorbbecsdk/install/lib${PYTHONPATH:+:$PYTHONPATH}"
export PATH="/usr/local/miniconda3/bin:$PATH"
cd /home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python
CAMERA_PY=/home/HwHiAiUser/pyorbbecsdk/venv/bin/python
```

### 第三步：选择功能并启动

按下表选择一项启动。驾驶模式须先确认车轮架空或场地安全；先退出占用同一硬件的程序，已有手机服务运行时先用 `systemctl stop astra-phone` 停止。

| 功能 | 启动命令 | 启动后操作 / 条件 |
| --- | --- | --- |
| 键盘驾驶 | `python3 main.py --mode manual` | 单键输入，空格停车，`Esc` 退出。 |
| 场景调度 | `python3 main.py --mode cmd` | 输入场景名或管理命令后按回车。 |
| 标识辅助 | `python3 main.py --mode easy` | 自动启动 `Helper`，需要 `weights/yolo.om`。 |
| 巡线 | `python3 main.py --mode cmd` | 输入 `LF` 后回车，需要 `weights/lfnet.om`。 |
| 目标跟踪 | `python3 main.py --mode cmd` | 输入 `Tracking` 后回车，需要 `weights/tracking.om`。 |
| 手机控制 | `python3 main.py --mode phone` | App 连接 `http://192.168.8.204:8080`；前台运行，`Ctrl+C` 退出。 |
| 语音驾驶 | `python3 main.py --mode voice --voice-model /path/to/vosk-model` | 相当于手动加后台语音，需要麦克风、Vosk 和中文模型。 |
| 驾驶时网页看画面 | `python3 main.py --mode manual --camera` | 通过 SSH 隧道打开浏览器预览。 |
| 驾驶时查看雷达 | `python3 main.py --mode manual --camera --lidar` | 预览页同时显示雷达状态；不自动避障。 |
| 独立拍照 / 取帧检查 | `$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg` | 不打开底盘，检查彩色帧并保存照片。 |
| 独立网页预览 | `$CAMERA_PY camera_preview.py` | 不打开底盘，通过 SSH 隧道访问。 |
| 独立雷达检查 | `python3 lidar_probe.py --seconds 12` | 不打开底盘，结束后输出汇总 JSON。 |
| 持续雷达检查 | `python3 lidar_probe.py --follow` | 每秒输出 JSON，`Ctrl+C` 停止。 |
| 语音文字映射检查 | `python3 voice_control.py 前进` | 只输出 `w`，不录音、不驱动车辆。 |

2026-09-30 已将统一主程序部署到上述车载目录，手机模式与其他模式共用 `main.py --mode`。后台 `astra-phone.service` 运行时，先停止服务再启动任何前台驾驶或独立硬件工具。完整参数与后台服务管理见第 2 节。

## 2. 模式与参数使用教程

本节依据本仓库 `python/main.py` 和独立工具的实际代码编写。所有启动参数都写在命令后面；按键、场景名和 HTTP 字段是在程序启动后使用的输入。

### 2.1 主模式与通用参数

```bash
python3 main.py --mode manual
python3 main.py --mode manual --camera --lidar
python3 main.py --help
```

| 参数 | 默认值 | 用法 |
| --- | --- | --- |
| `--mode` | `manual` | 选择 `manual`、`cmd`、`easy`、`phone` 或 `voice`。 |
| `--manual` / `--cmd` / `--easy` / `--phone` | 无 | 对应模式的兼容简写；不能与另一个主模式参数同时使用。本文示例统一使用 `--mode`。 |
| `--camera` | 关闭网页预览 | 在非 `phone` 模式开启本机预览；关闭它仍会采集相机，供截图与 AI 使用。 |
| `--camera-port` | `8765` | 非 `phone` 预览端口，整数 1–65535。 |
| `--phone-port` | `8080` | `phone` HTTP 端口，整数 1–65535。 |
| `--capture-dir` | `capture` | 主程序截图目录；相对路径从启动目录计算。 |
| `--voice` | 关闭 | 附加后台语音；它是功能开关，`--mode voice` 则会映射为 `manual + --voice`。 |
| `--voice-model` | 自动查找 | Vosk 模型目录，详见语音教程。 |
| `--voice-device` | ALSA 默认设备 | 指定麦克风设备，例如 `plughw:1,0`，以 `arecord -l` 为准。 |
| `--voice-move-seconds` | `1.0` | 语音运动自动停车时间，必须大于 0 且不超过 5 秒。 |
| `--lidar` / `--radar` | 关闭 | 开启雷达，二者等价；`phone` 自动开启。 |
| `--lidar-sdk` | `/home/HwHiAiUser/rplidar_sdk/output/Linux/Release/ultra_simple` | 雷达 SDK 可执行文件路径。 |
| `--lidar-port` | `/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0` | 雷达串口路径。 |
| `--lidar-baudrate` | `115200` | 雷达波特率，正整数。 |
| `-h` / `--help` | 无 | 显示当前文件支持的参数后退出，不启动硬件。 |

主程序没有 `--speed`、`--model` 或 `--mode LF` 参数。速度由运行后的键盘或手机指令调整；AI 模型路径由各场景确定。

### 2.2 manual：键盘驾驶与调速

```bash
python3 main.py --mode manual
```

单键输入，不按回车；字母大小写等效。初始速度控制值为 40，范围 0–100；实际行驶速度与轮向须现场校准。

| 按键 | 动作 |
| --- | --- |
| `w` / `s` | 前进 / 后退。 |
| `a` / `d` | 左转 / 右转。 |
| `q` / `e` | 原地逆时针 / 顺时针旋转。 |
| `←` / `→` | 左 / 右平移。 |
| `↑` / `↓` | 速度加 / 减 20，限制在 0–100；行驶时更新当前动作，静止时设置下一次动作速度。 |
| `z` | 固定旋转速度 80 的定时掉头，当前计时约 3.31 秒；实际角度须现场校准。 |
| 空格 | 停车，留在程序中。 |
| `Esc` | 停车并退出。 |
| `p` | 后台保存截图，不改变当前运动。 |

键盘运动指令发出后，**松开键盘按键不会自动停车**，须按空格。定时掉头可用空格或其他运动键中断，掉头期间调速会先停车。其他字母没有手动驾驶功能。

### 2.3 cmd：场景命令与 AI 模型

```bash
python3 main.py --mode cmd
```

进入后输入以下文本并按回车，大小写须完全一致：

| 输入 | 效果 | 模型 |
| --- | --- | --- |
| `Helper` | 识别标识并执行左转、右转、掉头或停车动作。 | `weights/yolo.om` |
| `LF` | 运行巡线场景。 | `weights/lfnet.om` |
| `Tracking` | 运行目标跟踪场景。 | `weights/tracking.om` |
| `clear` | 停车并结束当前场景，保留命令模式。 | 无 |
| `stop` | 停车并退出主程序。 | 无 |
| `p` | 保存截图。 | 无 |
| `Manual` | 报告不支持切换；须退出后重新启动 `--mode manual`。 | 无 |

例如，进入 `cmd` 后输入 `LF` 回车，结束巡线时输入 `clear` 回车。启动新场景会先停车并结束旧场景；未知命令只打印错误。`cmd` 中的 `w/a/s/d` 不是键盘驾驶命令。

仓库目前提供 `yolo.om`，此前已在车上验证其加载与照片推理；`lfnet.om` 和 `tracking.om` 仍需另行提供并验收。三个模型用途不同，不能通过重命名 `yolo.om` 代替其他模型。`Helper` 当前没有加载 `cls.om`。

### 2.4 easy：自动进入标识辅助

```bash
python3 main.py --mode easy
```

`easy` 自动启动 `Helper`，不自动启动 `LF`。它依赖标识检测结果执行动作，不等同于巡线。键盘运动键或空格可接管并结束 AI 控制；要恢复 `Helper`，退出后重新启动 `easy`，或改用 `cmd` 显式启动场景。`Esc` 停车退出。

### 2.5 相机预览、截图与保存路径

驾驶与网页预览共用同一个相机广播器：

```bash
python3 main.py --mode manual --camera --camera-port 8765 --capture-dir capture
```

电脑另开终端建立隧道，并保持其运行：

```bash
ssh -N -L 8765:127.0.0.1:8765 root@192.168.8.204
```

浏览器访问 `http://127.0.0.1:8765/`。非 `phone` 预览仅监听小车的 `127.0.0.1`；改 `--camera-port` 时也要修改隧道右侧端口。页面提供 MJPEG、保存画面入口和 `/status.json`；状态包含服务端时间与画面时间。主程序预览默认限制为 10 fps，AI 和截图继续读取完整采集帧。

键盘 `p`、语音“拍照”、网页截图与手机截图共用最新完整帧。主程序默认保存到 `capture/`，可改为：

```bash
python3 main.py --mode manual --capture-dir /home/HwHiAiUser/astra-captures
```

看到 `Screenshot saved` 或 HTTP 截图成功响应才表示文件写入成功。帧过期、队列满或保存失败会明确报错；截图写盘在后台进行。查看照片：

```bash
ls -lt capture/*.jpg | head
```

电脑端下载原车载目录中的文件示例：

```bash
scp root@192.168.8.204:/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python/capture/astra_check.jpg .
```

使用联调目录或自定义截图目录时，相应修改下载路径。截图时间取决于车端时钟；此前车端时钟已校正，但网络自动校时未确认，重启后可检查 `timedatectl status`。

### 2.6 独立相机工具

独立工具不初始化底盘，使用相机专用 Python；运行前退出其他相机程序。

```bash
$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg
$CAMERA_PY camera_preview.py --port 8765 --width 640 --height 480 --fps 15 --quality 70
```

| 工具 | 参数 | 默认值与作用 |
| --- | --- | --- |
| `camera_probe.py` | `--seconds` | 10，正整数；取帧检查时长。用 600 可检查 10 分钟连续取流。 |
| `camera_probe.py` | `--output` | `capture/astra_probe_时间戳.jpg`；保存并校验最后一张新鲜彩色帧。 |
| `camera_preview.py` | `--port` | 8765，范围 1–65535；同样通过 SSH 隧道访问。 |
| `camera_preview.py` | `--width` / `--height` | 1280 / 720，正整数；请求的彩色流尺寸，实际以相机支持的配置为准。 |
| `camera_preview.py` | `--fps` | 15，正整数；请求采集帧率与预览编码帧率。 |
| `camera_preview.py` | `--quality` | 70，范围 1–100；JPEG 质量。 |

拍照探针会输出帧数、分辨率、亮度与保存结果；5 秒收不到彩色帧会报错。预览可通过 `/snapshot.jpg` 获取并保存截图，通过 `/status.json` 查看状态。独立预览没有雷达采集，`Ctrl+C` 结束后再启动其他相机程序。

### 2.7 雷达采集与参数

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
| `--sdk` | 与主程序 `--lidar-sdk` 的默认路径相同。 |
| `--port` | 与主程序 `--lidar-port` 的默认串口相同。 |
| `--baudrate` | 115200，正整数。 |
| `--seconds` | 8，正数；单次采集时长，结束后输出一条汇总 JSON。 |
| `--follow` / `--continuous` | 持续模式，每秒一行 JSON；此时 `--seconds` 不限制总时长，`Ctrl+C` 停止。 |

JSON 中的 `points` 为有效点数，`nearest_mm` 为全扫描最近距离，`front_nearest_mm`、`sector_90_mm`、`sector_180_mm`、`sector_270_mm` 为对应方向 ±30° 扇区的最近距离，单位均为毫米。主程序持续采集使用最近一秒的窗口；超过 2.5 秒未更新标为 `stale`，没有有效或新鲜数据时距离为 `null`。

雷达只监测距离，当前没有自动避障。主程序已开雷达时不要再运行独立探针抢占同一串口；持续探针退出时会通知 SDK 停止雷达电机。

### 2.8 语音控制与模型配置

先检查 ALSA 麦克风并安装可选依赖：

```bash
arecord -l
python3 -m pip install -r requirements-voice.txt
python3 main.py --mode voice --voice-model /path/to/vosk-model \
  --voice-device plughw:1,0 --voice-move-seconds 1.5
```

将示例路径和设备名换成实际值。模型必须是解压后的目录，至少包含 `am/final.mdl` 和 `conf/mfcc.conf`。查找顺序为显式 `--voice-model`、设置的 `VOSK_MODEL_PATH`，以及未设置环境变量时的主入口旁 `weights/vosk-model/`。

例如，把模型配置为环境变量：

```bash
export VOSK_MODEL_PATH=/home/HwHiAiUser/models/vosk-chinese
python3 main.py --mode manual --voice
```

也可给 `cmd` 或 `easy` 附加 `--voice`。语音运动会接管 AI，之后须显式重启场景；键盘运动指令会取消旧语音动作。普通语音运动默认持续 1 秒，再自动停车；`--voice-move-seconds` 可调整到大于 0、不超过 5 秒，语音掉头也使用这个时长。

| 语音短句 | 对应动作 |
| --- | --- |
| 前进、后退、左转、右转 | `w`、`s`、`a`、`d`。 |
| 左旋转、右旋转、左平移、右平移 | `q`、`e`、`left`、`right`。 |
| 加速、减速、掉头 | `up`、`down`、`z`。 |
| 拍照、截图 | 保存截图。 |
| 停车、停止、停下 | 停车。 |
| 退出、结束 | 停车并退出。 |

无硬件时只验证文字映射：

```bash
python3 voice_control.py 前进
python3 voice_control.py 左平移
```

它只接收一条文本并输出按键，不监听麦克风或控制车辆。目前这台车此前检查未发现系统可识别的麦克风/声卡，也没有可用中文模型，语音驾驶仍需补齐依赖后验收。

### 2.9 phone：手机控制与 HTTP 参数

在快速开始的环境与统一目录中，先停止后台手机服务，再启动前台手机模式：

```bash
systemctl stop astra-phone
python3 main.py --mode phone --phone-port 8080 --capture-dir capture
```

`phone` 自动启用相机和雷达，相机使用 1280×720 @ 30 FPS 配置。相机 MJPEG 先写入共享的最新帧槽，驾驶预览使用 JPEG 半尺寸解码生成 640×360、质量 75 的视频，以降低无线带宽并保持 30 FPS；截图按需解码同一完整帧，保持 720p。其他模式的 1080p 相机配置保持原样。HTTP 监听 `0.0.0.0:8080`，无需 `--camera`。`--camera-port` 不改变手机服务端口；修改 `--phone-port` 后也要修改 App 地址。前台模式可用 `Ctrl+C` 停车退出，手机驾驶不通过 SSH 单键输入。

手机模式在支持的相机上关闭“曝光优先”，保持自动曝光但优先维持帧率；退出后恢复原值，避免影响其他模式。暗光下画面亮度可能降低。实测相机源从约 19.4 FPS 恢复到 29.99 FPS，手机解码约 29–31 FPS。

#### 视频卡顿与断流排查

原 180 ms 单图轮询限制了显示帧率，现已改为持续 MJPEG，并使用 640×360 驾驶预览降低带宽。2026-09-30 捕获的断流是车端 TCP 视频发送 `timed out`：手机和电脑曾在同一时刻断流，手机日志显示停止收包，未卡在解码。车端相机仍正常采集。当前证据定位到传输链路阻塞，尚不能确定是无线信号、路由器还是接收端调度造成。

视频发送超时由 1 秒调整为 1.5 秒，并保留有界发送缓冲区和最新帧策略；App 在连接前绑定局域网，预览期间保持亮屏。较长的网络停顿仍会断流，需检查接收设备的无线信号、路由器负载与链路丢包；本次仍观察到超过 2 秒的停顿，持续稳定性尚未通过。车端本机连续 60 秒接收 1795 帧，测得 29.88 FPS、零跳帧，状态与截图下载检查通过，说明绕开无线链路后的采集和服务可持续工作。App 超过 2 秒无新画面即停止控制，车端 600 ms 控制续期看门狗保持不变，恢复网络后需重新连接并重新按下方向，不能自动恢复旧动作。

车端 `logs/` 中的 `MJPEG stream closed` 记录发送异常；手机 `AstraCamera` 日志中的 `dataAge` 表示最近一次收包距今的毫秒数，`decoding` 表示是否有解码任务进行。配置为 30 FPS 不等于实际达到 30 FPS，应同时检查界面 FPS 和相机采集。

| API | 参数 / 用途 |
| --- | --- |
| `GET /api/v1/status` | 查看模式、速度、运动状态、相机、雷达与服务端时间。 |
| `GET /api/v1/camera/frame.jpg` | 获取当前 JPEG，不写盘。 |
| `GET /api/v1/camera/stream.mjpg` | 获取连续 MJPEG。 |
| `POST /api/v1/camera/captures` | 请求体 `{}`；保存截图，返回 `captureId` 和下载 `url`。 |
| `GET /api/v1/camera/captures/{captureId}` | 下载已保存的 JPEG。 |
| `POST /api/v1/control/session` | 请求体 `{}`；取得 `sessionId`、`bootId` 和 `leaseMs=600`，本操作不运动。 |
| `POST /api/v1/control/command` | `sessionId`、递增整数 `seq`、唯一 `commandId`、`key`。支持 `q/w/e/a/s/d/z/up/down/left/right`。 |
| `POST /api/v1/control/speed` | 同样带会话、序号和命令 ID；`speed` 为 0–100 的整数。 |
| `POST /api/v1/control/renew` | `sessionId` 与当前运动的 `commandId`；运动期间约每 150 ms 续期。 |
| `POST /api/v1/control/stop` | `sessionId`；停车并使会话失效，下次运动重新建会话。 |

速度初始值为 40，`up/down` 每次调 20。停止后旧会话不能恢复运动；未续期超过 600 ms 会自动停车。`seq` 在会话内递增，同一个 `commandId` 的重复请求不会执行两次；续期不会重新发运动指令或重启掉头计时。

在电脑或小车上查看状态、保存截图：

```bash
curl -fsS http://192.168.8.204:8080/api/v1/status
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{}' http://192.168.8.204:8080/api/v1/camera/captures
```

第二条会在车上创建截图。手机 App 按住动作时持续续期，松手或取消时发停车；后台、断联等场景还有客户端释放动作和设备端看门狗。雷达界面显示左/前/右，分别对应 270°/0°/90° 扇区，数值单位为毫米。

成功响应包含 `ok: true`；错误包含 `ok: false`、`code` 和 `message`，常见状态码为 400（参数错误）、404（不存在）、409（会话或序号失效）和 503（服务暂不可用）。完整请求与响应见 [Phone API](docs/PHONE_API.md)。API 当前没有身份认证，应在受信任局域网使用。

#### 正式手机服务管理

正式目录为 `/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python`。`astra-phone.service` 已安装，启动脚本加载 Ascend 和 Orbbec 环境后运行 `/usr/local/miniconda3/bin/python main.py --mode phone`。服务未设置开机自启；重启后手动启动即可。

```bash
systemctl start astra-phone
systemctl status astra-phone
systemctl stop astra-phone
```

运行日志由程序写入正式目录的 `logs/`。原联调目录保留作历史参考，临时联调服务已停止，不再作为默认入口。被替换的正式目录文件备份在 `/home/HwHiAiUser/astra-backups/phone-20260930`，模型权重和已有截图没有覆盖。

手机、电脑和小车接入同一 WLAN，App 连接 `http://192.168.8.204:8080`。服务运行后可以退出 SSH；切回其他模式前先执行 `systemctl stop astra-phone`，然后在统一目录使用 `python3 main.py --mode manual/cmd/easy/voice` 对应的命令。

### 2.10 退出与常见启动问题

| 情况 | 处理方式 |
| --- | --- |
| `invalid choice: 'phone'` | 检查 `pwd` 和 `python3 main.py --help`，确认进入上述正式目录并运行新版统一主程序。 |
| `Another AstraPlusCar main program owns the hardware` | 先退出占用硬件的主程序或停止对应服务。 |
| 缺少 `pyorbbecsdk` / `acl` | 重新加载环境，并检查 Python 版本、SDK binding 路径；单纯导入成功不代表所有硬件就绪。 |
| 找不到 `.om` 模型 | 检查启动目录与 `weights/`；补齐场景对应模型。 |
| `Voice` / `Lidar` 启动检查失败 | 按错误检查模型、麦克风、SDK、串口路径和权限。 |
| 相机无新鲜帧 / HTTP 503 | 确认其他相机程序已退出，先用相机探针检查 USB 与取流。 |

本仓库主程序处理 `Ctrl+C`、`SIGTERM`、`SIGHUP` 及输入断开时先停车，再关闭后台任务；运行中的相机、语音或雷达服务异常会停车退出。截图单次保存失败会报告错误，通常不结束驾驶。键盘模式须主动停车，手机模式依赖动作释放与续期保护；这些路径仍需在实际设备上分别验收。

## 3. 项目依赖

### 3.1 设备与系统环境

| 依赖 | 用途与已知配置 |
| --- | --- |
| Orange Pi AI Pro、Linux、Python 3.9 | 当前车端运行平台；已见 Python 3.9.2。主程序使用 POSIX 终端、进程与文件锁。 |
| Ascend CANN / ACL | `.om` 模型推理；环境脚本 `/usr/local/Ascend/ascend-toolkit/set_env.sh`。 |
| Orbbec SDK v1 Python binding | Astra+ 彩色流；本车 binding 在 `/home/HwHiAiUser/pyorbbecsdk/install/lib`，相机专用 Python 在 `pyorbbecsdk/venv/`。 |
| Astra+ USB 相机 | 主程序各模式都需要相机；当前采集彩色流，未提供深度驾驶功能。 |
| 麦轮底盘 / 电机驱动板 | 当前代码使用 I²C 总线 7、设备地址 `0x34`；具体硬件与轮向须现场确认。 |
| Slamtec 雷达及 SDK、`stdbuf` | `--lidar` 与 `phone` 必需；适配器通过 `stdbuf` 读取 SDK 输出，独立扫描不要求 ROS2。 |
| ALSA `arecord`、麦克风 | 语音可选依赖；使用单声道 16 kHz 录音。 |
| HarmonyOS 手机、DevEco Studio / SDK | 手机应用与构建环境，见 [HarmonyOS README](../AstraPlusCar-HarmonyOS/README.md)。 |

### 3.2 Python 包与模型

`python/requirements.txt` 列出了 `pyserial`、`filelock`、`numpy`、`opencv-python` 和 `torch`；它没有覆盖全部系统 SDK 与运行依赖。

| 功能 | 主要额外依赖 |
| --- | --- |
| 相机与截图 | `pyorbbecsdk`、OpenCV、NumPy；binding 须与 Python 和板端 SDK 匹配。 |
| 当前底盘控制 | `smbus2`；控制器模块也引用串口与文件锁相关包。 |
| AI 场景 | `acl`、`ais_bench`、`torch`、`torchvision`，以及对应 `.om`。模型包导入可能同时加载多个 AI 类。 |
| YAML 工具 | `PyYAML`。 |
| 后台语音 | `requirements-voice.txt` 中的 `vosk`、中文模型和可用录音设备。 |

在另行准备的开发环境中安装 Python 包的示例；车端已有环境先核对已装依赖：

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install smbus2 PyYAML
# 需要语音时再安装
python3 -m pip install -r requirements-voice.txt
```

CANN、ACL、Orbbec binding、`ais_bench` 以及板端 `torch` / `torchvision` 环境按已有 SDK 与平台版本配套配置，不能仅靠上述通用包列表补齐。设备上已有工作环境时先检查，避免更换不兼容版本。用于 AI 场景的完整导入检查示例：

```bash
python3 -c 'import cv2, numpy, pyorbbecsdk, acl, ais_bench, yaml, serial, filelock, torch, torchvision, smbus2; print("dependencies ready")'
```

若当前 `python3` 缺少主程序依赖，可核对已安装的 `/usr/local/miniconda3/bin/python` 环境，再将同一条启动命令的解释器换为该绝对路径。相机专用环境与主程序环境的包并不完全相同。

## 4. 文件结构

```text
AstraPlusCar/                         # 工作区根目录，不是 Git 仓库
├── AstraPlusCar-device/              # 本仓库
│   ├── README.md
│   ├── docs/PHONE_API.md             # 手机 HTTP 协议
│   ├── deploy/astra-phone.service    # 正式服务配置模板
│   ├── python/
│   │   ├── main.py                   # 当前统一主入口
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
│   │   │   ├── scenes/               # Helper、LF、Tracking 等场景
│   │   │   ├── models/               # Ascend 模型封装与后处理
│   │   │   └── utils/                # 底盘、相机广播、日志与 ACL 工具
│   │   ├── weights/                  # yolo.om；其他模型另行配置
│   │   ├── capture/                  # 默认截图输出
│   │   └── test/                     # 离线测试、历史测试与实车 API 检查
│   ├── ESP32/                        # ESP32 电机 / 舵机固件
│   ├── 基于ESP32的智能小车控制/      # 接线与控制方案资料
│   ├── Lane-Follow-Train/            # 巡线模型训练
│   ├── auto_label_tool/             # 车道线 HSV 标注工具
│   ├── det_label_split/             # 检测数据转分类数据与训练工具
│   ├── lidar_test/                  # 雷达 SDK、ROS2 示例与配置
│   └── notebook/                    # 历史交互控制示例
└── AstraPlusCar-HarmonyOS/           # 独立的 ArkTS 应用仓库
    ├── entry/src/main/ets/           # 页面、组件、API、图库与模型
    └── README.md
```

`python/src/utils/main.py` 是遗留入口，不是本手册对应的主程序。车辆应从 `python/main.py` 启动。临时联调目录和脚本位于车上，不属于此树中的正式部署文件。

## 5. 扩展与验证

### 5.1 新增场景与硬件能力

新增 AI 场景可参考 `src/scenes/base_scene.py`，在 `src/scenes/__init__.py` 注册场景名，通过 `cmd` 启动。场景读取主程序的共享帧，并向统一运动控制入口提交动作；相机预览、截图和 AI 复用唯一广播器，避免重复打开相机或让多个进程直接写底盘。

新增手机能力时同时检查设备端 API 与 HarmonyOS 客户端；运动、续期、急停、错误响应和数据单位须保持一致。电机、ESP32 引脚与底层串口行为放在设备端，客户端只发高层命令。

仓库保留了舵机动作与 ESP32 代码，但当前主程序没有独立舵机控制参数或手机舵机 API；不要把历史固件能力当作现有遥控入口。替换底盘驱动时须重新核对停车行为和轮向。

### 5.2 数据采集、标注与训练

| 扩展工具 | 使用入口与说明 |
| --- | --- |
| 巡线标注 | [auto_label_tool](auto_label_tool/README.md)：在该目录配置 `config/` 中的图片路径，使用 `python3 check_hsv.py` 提取色域，再运行 `python3 main.py` 标注。这里的 `main.py` 是标注工具。 |
| 巡线训练 | [Lane-Follow-Train](Lane-Follow-Train/README.md)：在该目录准备数据与 `config.yaml`，运行 `python3 train.py`，再将模型转换为与目标 Ascend 平台匹配的 `.om`。 |
| 检测辅助分类 | [det_label_split](det_label_split/README.md)：数据转换、分类训练和模型转换工具；当前 `Helper` 未启用辅助分类模型。 |
| ESP32 控制 | [控制方案说明](基于ESP32的智能小车控制/基于ESP32的智能小车控制.md) 与 `ESP32/` 固件。 |
| ROS2 雷达 / 建图 | `lidar_test/` 中的示例；此前车端未安装 ROS2，需要另行配置与验收。 |

训练文档中的 ATC 芯片型号和输入格式只是各自样例配置，转换时须按实际板卡、模型与 CANN 版本核对。训练与标注应在各自目录和依赖环境运行，不属于车辆驾驶主模式。

### 5.3 正式部署与服务

2026-09-30 已部署到原车载目录并安装正式 `astra-phone.service`，原 `astra-phone-integration` 临时服务已停止。`python/start_phone.sh` 进入正式目录、加载 CANN 与 Orbbec binding，然后运行 `/usr/local/miniconda3/bin/python main.py --mode phone`；`deploy/astra-phone.service` 使用该脚本。手机模式与 `manual`、`cmd`、`easy`、`voice` 共用统一入口。

用 `systemctl start astra-phone` 启动、`systemctl status astra-phone` 查看状态、`systemctl stop astra-phone` 停止。程序日志位于正式目录的 `logs/`，服务管理日志可用 `journalctl -u astra-phone -f` 查看。服务当前未启用开机自启，重启车辆后需手动启动。切换其他模式前先停止该服务，避免争用底盘、相机和雷达。

后续部署先备份并比较原目录，确认 Python 代码、SDK 依赖与模型相互匹配；更新服务模板后执行 `systemctl daemon-reload`。本次被替换文件的备份位于 `/home/HwHiAiUser/astra-backups/phone-20260930`，模型与已有截图保留。

两个仓库分别验证和管理 Git，工作区根目录不初始化 Git，也不合并两份历史。部署更新须保留模型、采集数据及车端已有改动。

### 5.4 离线与实车验证

设备端离线测试在本仓库根目录运行，开发环境需要 NumPy 和 OpenCV：

```bash
PYTHONPATH=python python3 -m unittest discover -s python/test/offline -v
PYTHONPATH=python python3 -m unittest discover -s python/test/utils -p test_camera_broadcaster.py -v
```

覆盖模式参数、共享帧、截图、HTTP、语音与键盘接管、计时、停车和资源清理。沙箱不支持回环端口或 POSIX 共享内存时，相应测试可能跳过；`python/test/` 其他历史用例包含旧接口和硬件依赖，不能与这套离线检查混为一谈。

HTTP 实车检查入口：

```bash
python3 python/test/live_phone_api.py --base-url http://192.168.8.204:8080
```

该命令在仓库根目录执行，默认检查状态、视频、截图创建和下载，不发送运动指令；它会在车端创建一张截图。仅在车轮安全架空后加 `--motion`，检查短时运动、速度、续期、停车和失联保护。

此前实车记录确认了 Astra+ 彩色取流、非黑截图、10 分钟连续采集，以及手机同 WLAN 下的视频、雷达、截图和图库。Phone API 的运动检查仅在车轮悬空时短时进行，已确认接口接受、停车和 600 ms 失联保护。实际轮向、落地行驶、各 AI 场景、语音驾驶及 App 后台停车仍需现场分别验证；离线测试不能代替这些验收。
