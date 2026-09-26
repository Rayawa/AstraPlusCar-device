# AstraPlusCar 设备端运行手册

## 手机 phone 模式

当前分支新增 `main.py --phone`：默认启动唯一相机、雷达和 HTTP 手动控制接口（端口 8080）。手机连小车 WLAN 后使用 `http://192.168.149.1:8080`；车端地址须以实际设备为准。按键、速度、掉头、截图、断联停车和完整接口见 [Phone API](docs/PHONE_API.md)。

完成部署后，SSH 中执行 `systemctl start astra-phone` 即可退出终端，服务仍运行。首次安装须将 `python/` 部署到下文车载目录、将 `deploy/astra-phone.service` 放到 `/etc/systemd/system/` 并执行 `systemctl daemon-reload`。本服务默认不随开机自动启动。使用 `systemctl stop astra-phone` 后才能运行原 SSH manual；两者不可同时控制硬件。phone 模式需相机和雷达均就绪才能进入驾驶界面。

下文原有 SSH 操作手册继续描述 manual/cmd/easy 模式。

下文原 SSH 手册基于 `codex/camerafix-logicfix` 的功能整理；当前 `codex/app` 分支新增了上面的 phone 模式。先看[快速开始](#快速开始)，再按[功能入口](#功能入口与当前可用性)选择命令。实测设备是 Orange Pi AI Pro + Orbbec Astra+ + Slamtec 雷达，小车地址为 `root@192.168.8.204`。车载项目目录为：

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
| 电脑浏览器实时监看 | `$CAR_PY main.py --manual --camera`；独立检查仍可用 `camera_preview.py` | 无 | 已接入共享取流，组合功能通过离线验证，实车负载待验收 |
| 主程序相机共享内存 | `src/utils/camera_broadcaster.py` | 无 | 已单独验证真实画面写入共享内存；尚未运行完整 `main.py` |
| 手动驾驶与按 `p` 拍照 | `$CAR_PY main.py --manual` | 无 | 后台截图，无需网页预览；尚未实车行驶验收 |
| 标识辅助转向 | `$CAR_PY main.py --mode easy` 或 `cmd` 中输入 `Helper` | `weights/yolo.om` | 模型已在车上加载，真实照片的推理和后处理已跑通；电机动作待实车验收 |
| 巡线 | `cmd` 中输入 `LF` | `weights/lfnet.om` | 已修正会报错的舵机和转向调用；仍缺模型，无法实车验证 |
| 目标跟踪 | `cmd` 中输入 `Tracking` | `weights/tracking.om` | 已修正会报错的舵机调用；仍缺模型，无法实车验证 |
| 雷达扫描与持续 JSON | `$CAR_PY lidar_probe.py --seconds 12` 或 `$CAR_PY lidar_probe.py --follow` | 无 | 单次汇总或每秒一行 JSON；不控制底盘 |
| 语音文字指令检查 | `$CAR_PY voice_control.py 前进` | 无 | 可运行；只输出手动按键映射，不监听麦克风或控制车 |
| 语音附加功能 | `$CAR_PY main.py --manual --voice --voice-model /path/to/vosk-model` | 中文 Vosk 模型 | 后台识别，键盘保持响应；实车仍需麦克风和模型 |

`Helper` 当前只读取 `yolo.om`；旧文档提到的 `cls.om` 未在该场景中加载。`easy` 只启动 `Helper`。`cmd` 不能切换到 `Manual`。巡线和跟踪必须分别提供自己的 `.om`，不能拿 `yolo.om` 共用。

## 安全边界与环境

**不准备让车轮运动时，只运行 USB 检查、`camera_probe.py`、`camera_preview.py`、`lidar_probe.py` 和 `voice_control.py` 的文字映射检查。不要运行 `main.py`。** 通用工具改为按需加载；运行主程序创建底盘控制器时才访问电机 I²C 设备。下文主程序命令仅供车轮架空或现场具备安全测试条件时使用；本分支尚未完成运动验收。

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

在电脑浏览器打开 `http://127.0.0.1:8765/`；页面提供实时 MJPEG 画面、每秒刷新的服务端时间与画面时间，以及“保存当前画面”截图链接（同时保存到小车 `capture/`）。也可在**电脑终端 C**保存当前帧：

```bash
curl -o astra_snapshot.jpg http://127.0.0.1:8765/snapshot.jpg
```

结束时先在终端 A、B 各按 `Ctrl+C`。若预览是此前放在后台运行的，在小车 SSH 终端查看并停止对应的预览进程：

```bash
ps -ef | grep '[c]amera_preview.py'
pkill -TERM -f '^/home/HwHiAiUser/pyorbbecsdk/venv/bin/python camera_preview.py( |$)'
```

独立预览默认 1280×720、15 fps。预览和截图读取 `CameraBroadcaster` 发布的完整 BGR 帧，JPEG 编码在后台执行。主程序预览默认限制为 10 fps，相机与 AI 保持原采集分辨率。需要降低独立预览带宽时，可在终端 A 改用较低分辨率：

```bash
$CAMERA_PY camera_preview.py --width 640 --height 480 --fps 15
```

预览服务只监听小车的 `127.0.0.1`，通过 SSH 隧道访问。页面每秒查询 `GET /status.json`；其中 `camera.status` 为 `live`、`waiting`、`stale` 或 `unavailable`，失效画面不会显示为实时。单独运行 `camera_preview.py` 时不会打开雷达，页面也不会显示雷达参数。独立 `camera_preview.py` 自己启动一个广播器，不要另开它与 `main.py` 争用相机。边驾驶边监看请使用 `main.py --manual --camera`，其预览、截图和 AI 共用主程序唯一的广播器。

### 4. 雷达扫描（不触碰底盘）

车上 `/dev/ttyUSB0` 对应的 Slamtec 雷达已通过 SDK 健康检查和扫描验证。独立运行探针：

```bash
$CAR_PY lidar_probe.py --seconds 12
```

上述 `--seconds` 命令结束后只输出一条汇总 JSON，正常应包含 `"health": "OK"`、大于 0 的 `"points"` 和毫米单位的 `"nearest_mm"`。需要持续观察最近一秒扫描窗口时，在**没有运行主程序 `--lidar`** 的另一个独立调试会话中执行：

```bash
$CAR_PY lidar_probe.py --follow
# 等价：$CAR_PY lidar_probe.py --continuous
```

每秒输出一行 JSON（便于 `jq`、日志采集或脚本解析），包含 `observed_at`、`serial`、`health`、`status`、`points`、`nearest_mm`、`front_nearest_mm`。距离单位是毫米，无有效点时为 `null`。按 `Ctrl+C` 或发送 `SIGTERM` 会通知 SDK 停止雷达电机。持续模式会一直运行，`--seconds` 只控制默认的单次汇总模式。探针调用车上已有的 `/home/HwHiAiUser/rplidar_sdk/output/Linux/Release/ultra_simple`，通过稳定的 `/dev/serial/by-id/...` 设备路径连接，默认 115200 波特率。它不需要 ROS2，也不会发底盘运动指令。找不到设备路径时，可用 `ls -l /dev/serial/by-id/` 检查接线，并用 `--port /dev/ttyUSB0` 覆盖。车上目前没有安装 ROS2，因此 `lidar_test/` 中的 ROS2 建图节点不能直接运行。

## 主程序操作指令总表

**以下 `main.py` 命令可能接触电机，只能在车轮架空或电机断电、车控准备妥当后使用。** 先按第 1 节登录、进入 `python` 目录、设置环境，并退出独立相机探针或网页预览。主程序使用第 1 节的 `$CAR_PY`。

| 启动命令（小车 SSH 终端） | 进入后如何操作 | 当前状态 |
| --- | --- | --- |
| `$CAR_PY main.py --manual`（默认；兼容 `--mode manual`） | 直接按下方手动按键，不用回车 | 逻辑已修，尚未实车行驶验收 |
| `$CAR_PY main.py --cmd`（兼容 `--mode cmd`） | 输入下方场景命令，**每条都要回车** | 每次启动场景会先结束旧场景并停车 |
| `$CAR_PY main.py --easy`（兼容 `--mode easy`） | 自动启动 `Helper`；按 `Esc` 退出，手动运动键可接管 | 依赖 `weights/yolo.om`，尚未实车行驶验收 |
| `$CAR_PY main.py --manual --voice --voice-model /path/to/vosk-model` | 键盘驾驶和后台语音同时运行 | 需额外安装麦克风、Vosk 和中文模型；当前车上不能使用 |

### 主模式＋附加功能

每次选择一个主模式：`--manual`、`--cmd` 或 `--easy`；默认 `manual`，兼容 `--mode manual/cmd/easy`。不同主模式不能同时指定。附加功能可任意叠加，`--radar` 是 `--lidar` 的别名：

| 参数 | 功能 |
| --- | --- |
| `--manual` | 键盘驾驶，按 `p` 后台截图 |
| `--manual --camera` | 键盘驾驶＋网页实时画面＋截图 |
| `--manual --voice --voice-model /path/to/vosk-model` | 键盘驾驶＋后台语音＋截图 |
| `--manual --camera --voice --lidar --voice-model /path/to/vosk-model` | 开启全部附加功能 |

`--camera` 只控制是否启动网页预览。没有它也会采集相机画面，供 `p`、语音“拍照”和 AI 使用。网页截图与其他截图使用同一个最新完整帧读取入口，都保存到 `capture/`；用 `--capture-dir 路径` 修改目录。截图有界排队，保存成功才输出 `Screenshot saved`；相机失败、画面超过 2 秒、队列满或写盘失败均明确报错，网页返回 HTTP 503。实时显示、截图写盘与运动控制分开运行。

网页默认监听 `127.0.0.1:8765`，通过上文 SSH 隧道访问；`--camera-port` 可改端口。预览页每秒显示服务端当前时间和最近一帧的时间/帧龄。若同时开启 `--lidar`（或 `--radar`），页面还打印最近一次雷达扫描参数 JSON；可直接访问 `/status.json` 调试。主程序已开启 `--camera --lidar` 时，在另一终端持续读取状态（其中 `lidar` 字段就是雷达 JSON），不需要重复打开串口：

```bash
while :; do curl -fsS http://127.0.0.1:8765/status.json; printf "\n"; sleep 1; done
```

`--lidar` 启动持续采集，每秒输出 `health`、`status`、有效点数、最近距离和前方 ±30° 最近距离（毫米）；距离来自最近一秒；超过 2.5 秒未更新会标记为 `stale` 并清空距离，空窗口的距离为 `null`。用 `--lidar-sdk`、`--lidar-port`、`--lidar-baudrate` 覆盖设备参数。雷达只监测，不执行自动避障。

启动会检查语音模型结构、Vosk、ALSA 实际录音，以及雷达 SDK、串口访问权限和有效扫描。缺失项会明确报告。运行中相机、语音或雷达异常会停车退出。`Esc`、`Ctrl+C`、`SIGTERM` 和输入断开都会进入清理，先停车，再结束识别/录音、雷达 SDK、预览和相机，释放共享内存。

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
| `z` | 原地掉头 | 固定旋转速度 80，按实测 280–290° 校准为约 3.31 秒；可用空格或其他运动键中断，180° 效果需实车复测 |
| `Space`（空格） | 停车 | `Stop`，仍留在手动模式 |
| `Esc` | 停车并退出主程序 | 急停优先，清理后台服务 |
| `p` | 拍照 | 将共享内存中的当前彩色帧写入小车 `capture/`，文件名含时间戳和唯一标识的 JPG |
| `↑` / `↓` | 速度 `+20` / `-20`，范围 `0–100` | 行驶时会立即重发新速度；静止时只更改下一次动作的速度 |

其他按键（包括 `c`、`g`、`t`、`r`、`x`）没有手动控制功能。`p` 异步保存当前完整且新鲜的共享帧，看到 `Screenshot saved` 才表示写盘成功；若要独立验证相机取帧，请使用第 2 节的 `camera_probe.py`。在小车 SSH 终端查看最新手动截图：

```bash
ls -lt capture/*.jpg | head
```

### cmd：逐行输入的场景命令

启动 `$CAR_PY main.py --mode cmd` 后，输入以下**大小写完全一致**的文本，再按回车。它不接受 `w`、`a` 等手动驾驶按键；`p` 加回车可截图。附加 `--voice` 后也可用语音接管，接管后原 AI 场景结束，需显式输入场景名重新启动。

| 输入 | 作用 | 当前状态 |
| --- | --- | --- |
| `Helper` | 启动识别标识后执行转向的自动场景 | 读取现有 `weights/yolo.om`；推理及后处理已在真实照片上运行，电机动作尚未实车验收 |
| `LF` | 启动巡线场景 | 缺少 `weights/lfnet.om`；代码中的直接调用错误已修，模型运行仍待验收 |
| `Tracking` | 启动目标跟踪场景 | 缺少 `weights/tracking.om`；代码中的直接调用错误已修，模型运行仍待验收 |
| `clear` | 结束已启动的所有场景并发出停车指令 | 保持在 `cmd`，之后可输入其他场景命令 |
| `stop` | 退出 `cmd` 和主程序 | 退出清理时会发出停车指令 |
| `Manual` | 无法切换手动模式 | 只打印不支持的错误；须退出后用 `--mode manual` 启动 |

未知命令只打印错误。启动新的自动场景时会结束旧场景并先停车。`LF` 和 `Tracking` 缺模型，补齐前不能作为可运行功能；不要照搬旧文档中的 `Ascend310B1` 转换命令来推断当前板卡的模型兼容性。

### voice：可选后台语音功能

开发指南只把 6 路麦克风和扬声器列为可选部件，原语音控制仍标为规划中，没有规定模块协议。当前小车 `lsusb` 没有音频设备，`/proc/asound/cards` 和 `arecord -l` 均报告无声卡；**目前没有被系统识别的物理麦克风/声卡**，无法仅凭软件检查断言车壳内绝对没有安装模块。也没有找到可用的中文语音模型。因此这台车目前不能实际语音驾驶。代码使用 `arecord` 读取麦克风、Vosk 本地模型识别中文，并把完整短句交给统一运动控制入口。没有麦克风、模型或 Vosk 时会在打开相机及底盘之前报出原因。

不接硬件也可以先检查文字指令映射：

```bash
$CAR_PY voice_control.py 前进
$CAR_PY voice_control.py 左平移
```

支持前进、后退、左转、右转、左旋转、右旋转、左平移、右平移、加速、减速、掉头、拍照、停止和退出。语音运动（含掉头）默认只执行 1 秒，随后自动停车。键盘运动/调速会接管并取消旧语音动作及其计时；接管前已开始识别的旧语音运动不会在稍后执行。空格和语音“停止”优先，清除待执行动作；按 `p` 不改变正在执行的运动。超过 1 秒尚未处理的普通指令会被丢弃。键盘 `z` 仍按约 180° 的计时旋转，运动键可中断，旋转时按调速键会停车。接入可被 ALSA 识别的麦克风并准备兼容的中文 Vosk 模型目录后，在小车终端执行：

```bash
arecord -l
$CAR_PY -m pip install -r requirements-voice.txt
$CAR_PY main.py --manual --voice --voice-model /path/to/vosk-model
```

旧的 `--mode voice` 兼容映射到 `--manual --voice`，键盘仍可使用。模型路径要指向解压后的模型**目录**，不是 `.zip` 文件；可通过 `--voice-model`、环境变量 `VOSK_MODEL_PATH` 或 `python/weights/vosk-model/` 配置。后两种配置好后可直接运行 `--manual --camera --voice --lidar`。使用特定 ALSA 输入设备时在启动命令末尾加 `--voice-device 设备名`。普通动作时长可用 `--voice-move-seconds 1.5` 调整，允许范围为大于 0 至 5 秒。上述语音驾驶仍需在安全测试条件下进行，目前没有实际语音识别验收。

## 相机链路与验证范围

```text
Astra+ USB → 唯一 CameraBroadcaster → 带锁的完整共享帧
                                     ├→ 后台 JPEG 编码 → MJPEG 网页
                                     ├→ 后台截图任务 ← 键盘 p / 语音拍照 / 网页截图
                                     └→ Helper / LF / Tracking
键盘 / 后台语音 / AI 动作 → 统一运动控制入口 → 底盘
雷达 SDK → 后台采集 → 每秒扫描状态与距离（不控制底盘）
```

已验证独立取流、非黑截图、10 分钟连续取帧、浏览器预览和广播器共享内存。主程序及所有可能驱动电机的场景尚未在车轮安全条件下实车测试。训练与标注工具分别见 `Lane-Follow-Train/README.md`、`auto_label_tool/README.md` 和 `det_label_split/README.md`；它们不属于上述车载 SSH 运行入口。


## 组合功能验证

离线测试不需要相机、麦克风、雷达、Ascend 或电机硬件。安装 `numpy` 和 `opencv-python-headless` 后，在仓库根目录运行（已有 GUI OpenCV 环境可使用 `opencv-python`）：

```bash
PYTHONPATH=python python3 -m unittest discover -s python/test/offline -v
PYTHONPATH=python python3 -m unittest discover -s python/test/utils -p test_camera_broadcaster.py -v
```

覆盖全部主模式/附加参数组合、唯一相机实例、共享帧完整性、连续截图和真实 JPEG、网页截图及失效 503、预览状态 JSON 与帧时间、可选雷达参数及过期清除、雷达持续 JSON、慢写盘期间驾驶、键盘/语音抢占、过期指令、优先停车、可取消的 AI 动作序列、异常退出和资源清理。测试会临时监听本机回环端口；若沙箱禁止回环端口或 POSIX 共享内存，对应测试会显示 `skipped`，应在设备环境补跑。`python/test/` 其余历史测试含硬件依赖和旧接口断言，不属于这套离线验收。

实车待现场验证，以下记录不能用离线测试替代：

1. 先架空车轮，分别运行 `--manual`、`--manual --camera`、`--manual --voice`、全部附加功能；检查首次画面、麦克风与雷达就绪信息。没有语音硬件/模型时应启动失败并列出原因。
2. 用 `--manual --camera --lidar` 打开预览，核对页面时间每秒刷新、画面时间跟随视频更新、雷达 JSON 点数与距离更新；断开雷达后核对故障/过期状态，勿把旧距离视为当前障碍距离。另起独立调试时先退出主程序，再用 `lidar_probe.py --follow` 检查连续 JSON 行和 `Ctrl+C` 后的 SDK 退出。
3. 在同一段低速行驶中保持网页视频，连续按 `p`、说“拍照”、点击网页截图；核对文件数、完整画面和成功/失败日志，确认没有第二个相机进程抢占设备。
4. 说“前进”后立即按 `s`，等待超过语音动作时长；确认旧计时没有打断后退。说话过程中按键接管，确认延迟识别的旧运动被丢弃。分别用空格和语音“停止”验证急停。
5. 对比只开手动与全功能时的 CPU、内存、视频帧率、雷达每秒点数，并记录按键到车轮响应的平均/最大延迟；至少连续运行 10 分钟。当前控制轮询间隔 20 ms 是软件设置，不代表已测得的实车延迟。
6. 低速/架空条件下检查相机断开、麦克风停止、雷达断开、磁盘不可写、`Ctrl+C`、`SIGTERM` 和 SSH 输入断开：应报告故障、停车，且无残留录音/SDK/相机进程。截图单次写盘失败只报告该截图失败，驾驶仍可响应。
