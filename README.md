# AstraPlusCar 设备端运行手册

本手册对应 `codex/camerafix-logicfix` 分支。先看[快速开始](#快速开始)，再按[功能入口](#功能入口与当前可用性)选择命令。实测设备是 Orange Pi AI Pro + Orbbec Astra+ + Slamtec 雷达，小车地址为 `root@192.168.8.204`。车载项目目录为：

```text
/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python
```

SSH 会提示输入密码；不要把密码写进命令或脚本。以下命令对应这台已调试过的小车，换设备时应重新确认路径与依赖。

## 快速开始

1. 在电脑终端执行 `ssh -tt root@192.168.8.204`，输入这台车的 SSH 密码。`-tt` 保留手动驾驶所需的交互终端。
2. 在小车终端复制执行[环境设置](#1-ssh-登录与环境设置)里的 `cd`、`source`、`export` 和两个 Python 变量命令。**每开一个新的 SSH 终端都要重新设置。**
3. 先运行不触碰底盘的 `$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg` 或 `$CAR_PY lidar_probe.py --seconds 12`，分别检查相机和雷达。
4. 准备让车轮运动时，先确认车轮已架空或场地安全，再运行 `$CAR_PY main.py --mode manual`。按 `w` 前进、空格停车、`Esc` 退出。此分支尚未做运动实测，方向、速度和 `z` 掉头角度需要现场校准。

**本次部署只复制代码、做静态与设备探针验证，不会运行会驱动车轮的 `main.py`。** 本手册的完整主程序命令供后续现场调试使用。

### 把本分支部署到这台车

如果代码还在电脑上，在电脑终端进入本仓库根目录，再执行：

```bash
rsync -rcv --exclude '.DS_Store' --exclude '__pycache__/' --exclude 'capture/' \
  --exclude 'logs/' --exclude 'Log/' --exclude 'weights/' \
  python/ root@192.168.8.204:/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python/
rsync -cv README.md root@192.168.8.204:/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/README.md
```

这只覆盖同名代码文件并保留车上额外文件、拍照结果和模型；不加 `--delete`。当前车上已有 `weights/yolo.om`。若部署到另一台没有模型的车，另行复制 `python/weights/yolo.om` 到车上 `python/weights/`。以下所有小车命令均以已部署当前分支为前提。若换另一台设备，先确认 Astra+ 的 Python binding、Ascend CANN、底盘 I²C、雷达 SDK 和对应模型文件已安装，路径与权限也与下文一致。

## 功能入口与当前可用性

| 功能 | 入口 | 模型 | 当前状态 |
| --- | --- | --- | --- |
| Astra+ USB 检查 | `lsusb` | 无 | 此前已识别 RGB `2bc5:0536` 和深度 `2bc5:0636`；实际项目只取彩色流 |
| 独立拍照与连续取帧 | `$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg` | 无 | 可运行；已拍到非黑色 1920×1080 JPG，10 分钟收到 17,920 帧 |
| 电脑浏览器实时监看 | `$CAMERA_PY camera_preview.py`，电脑另开 SSH 隧道 | 无 | 可运行；已验证 1280×720、15 fps 的网页画面和截图 |
| 主程序相机共享内存 | `src/utils/camera_broadcaster.py` | 无 | 已单独验证真实画面写入共享内存；尚未运行完整 `main.py` |
| 手动驾驶与按 `p` 拍照 | `$CAR_PY main.py --mode manual` | 无 | 入口与按键逻辑已修，尚未实车行驶验收 |
| 标识辅助转向 | `$CAR_PY main.py --mode easy` 或 `cmd` 中输入 `Helper` | `weights/yolo.om` | 模型已在车上加载，真实照片的推理和后处理已跑通；电机动作待实车验收 |
| 巡线 | `cmd` 中输入 `LF` | `weights/lfnet.om` | 已修正会报错的舵机和转向调用；仍缺模型，无法实车验证 |
| 目标跟踪 | `cmd` 中输入 `Tracking` | `weights/tracking.om` | 已修正会报错的舵机调用；仍缺模型，无法实车验证 |
| 雷达扫描 | `$CAR_PY lidar_probe.py --seconds 12` | 无 | 可运行；车上雷达健康状态正常，探针已读到有效点，不控制底盘 |
| 语音文字指令检查 | `$CAR_PY voice_control.py 前进` | 无 | 可运行；只输出手动按键映射，不监听麦克风或控制车 |
| 实际语音驾驶 | `$CAR_PY main.py --mode voice --voice-model /path/to/vosk-model` | 中文 Vosk 模型 | 软件入口已接入；车上未识别到麦克风/声卡，也没有语音模型，当前不能使用 |

`Helper` 当前只读取 `yolo.om`；旧文档提到的 `cls.om` 未在该场景中加载。`easy` 只启动 `Helper`。`cmd` 不能切换到 `Manual`。巡线和跟踪必须分别提供自己的 `.om`，不能拿 `yolo.om` 共用。

## 安全边界与环境

**不准备让车轮运动时，只运行 USB 检查、`camera_probe.py`、`camera_preview.py`、`lidar_probe.py` 和 `voice_control.py` 的文字映射检查。不要运行 `main.py`，也不要为了测试相机导入 `src.utils`。** 车控模块在导入时就实例化底盘控制器，并访问电机 I²C 设备。下文主程序命令仅供车轮架空或现场具备安全测试条件时使用；本分支尚未完成运动验收。

探针、网页预览和主程序都会打开 Astra+。同一时间只运行其中一个；启动下一个前先退出当前程序。`vi_l1_sample` 是 MIPI 摄像头样例，不是 Astra+ 的图像源。

车上已经安装适配 Astra+ 的 Orbbec SDK v1 Python 3.9 环境。其 binding 位于 `/home/HwHiAiUser/pyorbbecsdk/install/lib`，不要用系统 Python 3.10 直接运行这些相机脚本。主程序用另一套已有的 Python 3.9 环境；两套 Python 的依赖不同。下面的命令都从车上的 `Car/python` 目录运行，模型相对路径依赖当前目录。

### 1. SSH 登录与环境设置

在**电脑终端**登录；`-tt` 为后面的手动控制保留键盘终端：

```bash
ssh -tt root@192.168.8.204
```

以下命令均在**小车 SSH 终端**执行，除非特别标明“电脑终端”：

```bash
cd /home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python
source /usr/local/Ascend/ascend-toolkit/set_env.sh
export PYTHONPATH="/home/HwHiAiUser/pyorbbecsdk/install/lib${PYTHONPATH:+:$PYTHONPATH}"
CAMERA_PY=/home/HwHiAiUser/pyorbbecsdk/venv/bin/python
CAR_PY=/usr/local/miniconda3/bin/python
```

检查 USB、SDK 和模型文件；这些命令不会触碰电机：

```bash
lsusb | grep -E '2bc5:(0536|0636)'
$CAMERA_PY -c 'import cv2, pyorbbecsdk; print("Orbbec SDK ready")'
ls -lh weights/*.om
```

运行主程序前还须在同一环境中确认其依赖；`requirements.txt` 不包含全部当前运行依赖：

```bash
$CAR_PY -c 'import cv2, pyorbbecsdk, acl, ais_bench, yaml, serial, filelock, torch, torchvision, smbus2; print("main dependencies ready")'
```

车上的相机专用环境缺少若干主程序依赖，主程序应使用上面的 `CAR_PY`。如果导入检查失败，应在对应 Python 3.9 环境中安装缺少的包，或先检查 Ascend CANN 与 Orbbec SDK 的环境脚本和 binding 路径。不要在系统 Python 3.10 中直接安装后重试。依赖检查通过只表示模块可导入，不表示车控已经验收。

### 2. 独立拍照与 10 分钟取流（车轮着地可运行）

先退出网页预览或其他摄像头程序。短时拍照并验证图片是否为非黑画面：

```bash
$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg
ls -lh capture/astra_check.jpg
```

连续取帧验收：

```bash
$CAMERA_PY camera_probe.py --seconds 600 --output capture/astra_10min.jpg
```

探针会报告帧数、分辨率、亮度与保存结果；5 秒收不到彩色帧会报错。`capture/` 是小车上的截图目录。在**电脑终端**下载固定文件名的照片：

```bash
scp root@192.168.8.204:/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python/capture/astra_check.jpg .
```

### 3. 电脑浏览器实时监看（车轮着地可运行）

在**小车 SSH 终端 A**启动预览，并保持终端运行：

```bash
$CAMERA_PY camera_preview.py
```

在**电脑终端 B**建立 SSH 隧道，并保持终端运行：

```bash
ssh -N -L 8765:127.0.0.1:8765 root@192.168.8.204
```

在电脑浏览器打开 `http://127.0.0.1:8765/`；页面提供实时 MJPEG 画面和“Open current frame”单帧链接。也可在**电脑终端 C**保存当前帧：

```bash
curl -o astra_snapshot.jpg http://127.0.0.1:8765/snapshot.jpg
```

结束时先在终端 A、B 各按 `Ctrl+C`。若预览是此前放在后台运行的，在小车 SSH 终端查看并停止对应的预览进程：

```bash
ps -ef | grep '[c]amera_preview.py'
pkill -TERM -f '^/home/HwHiAiUser/pyorbbecsdk/venv/bin/python camera_preview.py( |$)'
```

预览默认 1280×720、15 fps。相机返回 MJPEG 时直接转发其 JPEG 数据，避免重复编码；这次局域网实测约 2.7 MB/s。需要降低带宽时，可在终端 A 改用支持的较低分辨率：

```bash
$CAMERA_PY camera_preview.py --width 640 --height 480 --fps 15
```

预览服务只监听小车的 `127.0.0.1`，通过 SSH 隧道访问。当前独立预览占用摄像头，不能与 `main.py` 同时运行；边运行小车边监看仍需实现同一取流源的画面分发。

### 4. 雷达扫描（不触碰底盘）

车上 `/dev/ttyUSB0` 对应的 Slamtec 雷达已通过 SDK 健康检查和扫描验证。独立运行探针：

```bash
$CAR_PY lidar_probe.py --seconds 12
```

输出是 JSON，正常应包含 `"health": "OK"`、大于 0 的 `"points"` 和毫米单位的 `"nearest_mm"`。它调用车上已有的 `/home/HwHiAiUser/rplidar_sdk/output/Linux/Release/ultra_simple`，通过稳定的 `/dev/serial/by-id/...` 设备路径连接，默认 115200 波特率，结束时通知 SDK 停止雷达自身的电机。它不需要 ROS2，也不会发底盘运动指令。找不到设备路径时，可用 `ls -l /dev/serial/by-id/` 检查接线，并用 `--port /dev/ttyUSB0` 覆盖。车上目前没有安装 ROS2，因此 `lidar_test/` 中的 ROS2 建图节点不能直接运行。

## 主程序操作指令总表

**以下 `main.py` 命令可能接触电机，只能在车轮架空或电机断电、车控准备妥当后使用。** 先按第 1 节登录、进入 `python` 目录、设置环境，并退出独立相机探针或网页预览。主程序使用第 1 节的 `$CAR_PY`。

| 启动命令（小车 SSH 终端） | 进入后如何操作 | 当前状态 |
| --- | --- | --- |
| `$CAR_PY main.py` 或 `$CAR_PY main.py --mode manual` | 直接按下方手动按键，不用回车 | 逻辑已修，尚未实车行驶验收 |
| `$CAR_PY main.py --mode cmd` | 输入下方场景命令，**每条都要回车** | 每次启动场景会先结束旧场景并停车 |
| `$CAR_PY main.py --mode easy` | 自动启动 `Helper`；按 `Esc` 退出，其他按键无作用 | 依赖 `weights/yolo.om`，尚未实车行驶验收 |
| `$CAR_PY main.py --mode voice --voice-model /path/to/vosk-model` | 说出下方语音指令 | 需额外安装麦克风、Vosk 和中文模型；当前车上不能使用 |

### manual：单键操作

SSH 登录须保留终端，例如 `ssh -tt root@192.168.8.204`。手动模式为单键输入，**不用按回车**；默认速度值为 `40`。动作键发出一次控制指令后，程序不会因松开按键自动停车，请用空格停车。字母大小写等效。当前手动模式没有终端预览窗口。

| 按键 | 代码中的操作 | 当前说明 |
| --- | --- | --- |
| `w` | 前进 | `Advance` |
| `s` | 后退 | `BackUp` |
| `a` | 左转 | `TurnLeft` |
| `d` | 右转 | `TurnRight` |
| `q` | 原地逆时针旋转 | `SpinAntiClockwise` |
| `e` | 原地顺时针旋转 | `SpinClockwise` |
| `←` / `→` | 左／右平移 | `ShiftLeft` / `ShiftRight` |
| `z` | 原地掉头 | 定时旋转约 180°，可用空格或其他运动键中断；实际角度需实车校准 |
| `Space`（空格） | 停车 | `Stop`，仍留在手动模式 |
| `Esc` | 停车并退出主程序 | 向手动场景发送退出消息 |
| `p` | 拍照 | 将共享内存中的当前彩色帧写入小车 `capture/`，文件名为时间戳 JPG |
| `↑` / `↓` | 速度 `+20` / `-20`，范围 `0–100` | 行驶时会立即重发新速度；静止时只更改下一次动作的速度 |

其他按键（包括 `c`、`g`、`t`、`r`、`x`）没有手动控制功能。`p` 的截图只表示当前共享帧已写盘；若要独立验证相机取帧，请使用第 2 节的 `camera_probe.py`。在小车 SSH 终端查看最新手动截图：

```bash
ls -lt capture/*.jpg | head
```

### cmd：逐行输入的场景命令

启动 `$CAR_PY main.py --mode cmd` 后，输入以下**大小写完全一致**的文本，再按回车。它不接受 `w`、`a` 等手动驾驶按键。

| 输入 | 作用 | 当前状态 |
| --- | --- | --- |
| `Helper` | 启动识别标识后执行转向的自动场景 | 读取现有 `weights/yolo.om`；推理及后处理已在真实照片上运行，电机动作尚未实车验收 |
| `LF` | 启动巡线场景 | 缺少 `weights/lfnet.om`；代码中的直接调用错误已修，模型运行仍待验收 |
| `Tracking` | 启动目标跟踪场景 | 缺少 `weights/tracking.om`；代码中的直接调用错误已修，模型运行仍待验收 |
| `clear` | 结束已启动的所有场景并发出停车指令 | 保持在 `cmd`，之后可输入其他场景命令 |
| `stop` | 退出 `cmd` 和主程序 | 退出清理时会发出停车指令 |
| `Manual` | 无法切换手动模式 | 只打印不支持的错误；须退出后用 `--mode manual` 启动 |

未知命令只打印错误。启动新的自动场景时会结束旧场景并先停车。`LF` 和 `Tracking` 缺模型，补齐前不能作为可运行功能；不要照搬旧文档中的 `Ascend310B1` 转换命令来推断当前板卡的模型兼容性。

### voice：可选离线语音入口

开发指南只把 6 路麦克风和扬声器列为可选部件，原语音控制仍标为规划中，没有规定模块协议。当前小车 `lsusb` 没有音频设备，`/proc/asound/cards` 和 `arecord -l` 均报告无声卡；**目前没有被系统识别的物理麦克风/声卡**，无法仅凭软件检查断言车壳内绝对没有安装模块。也没有找到可用的中文语音模型。因此这台车目前不能实际语音驾驶。代码使用 `arecord` 读取麦克风、Vosk 本地模型识别中文，并把完整短句交给现有手动场景。没有麦克风、模型或 Vosk 时会在打开相机及底盘之前报出原因。

不接硬件也可以先检查文字指令映射：

```bash
$CAR_PY voice_control.py 前进
$CAR_PY voice_control.py 左平移
```

支持前进、后退、左转、右转、左旋转、右旋转、左平移、右平移、加速、减速、掉头、拍照、停止和退出。语音的普通运动指令默认只执行 1 秒，随后自动停车；`z` 掉头由手动场景定时停车。接入可被 ALSA 识别的麦克风并准备兼容的中文 Vosk 模型目录后，在小车终端执行：

```bash
arecord -l
$CAR_PY -m pip install -r requirements-voice.txt
$CAR_PY main.py --mode voice --voice-model /path/to/vosk-model
```

模型路径要指向解压后的模型**目录**，不是 `.zip` 文件；使用特定 ALSA 输入设备时在启动命令末尾加 `--voice-device 设备名`。普通动作时长可用 `--voice-move-seconds 1.5` 调整，允许范围为大于 0 至 5 秒。上述语音驾驶仍需在安全测试条件下进行，目前没有实际语音识别验收。

## 相机链路与验证范围

```text
Astra+ USB → pyorbbecsdk v1 → camera_probe.py → capture/*.jpg
                         ↘ camera_preview.py → 本机 MJPEG 服务 → SSH 隧道 → 电脑浏览器
                         ↘ CameraBroadcaster → 共享内存 → Manual / Helper / LF / Tracking
```

已验证独立取流、非黑截图、10 分钟连续取帧、浏览器预览和广播器共享内存。主程序及所有可能驱动电机的场景尚未在车轮安全条件下实车测试。训练与标注工具分别见 `Lane-Follow-Train/README.md`、`auto_label_tool/README.md` 和 `det_label_split/README.md`；它们不属于上述车载 SSH 运行入口。
