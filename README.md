# AstraPlusCar 设备端（`codex/camerafix`）

本分支把 Orbbec Astra+ 的彩色画面接入小车，并提供独立拍照与电脑浏览器监看。[主程序操作指令总表](#主程序操作指令总表)列出了当前全部模式、手动按键和命令模式输入。小车地址为 `root@192.168.8.204`，车载项目目录为：

```text
/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python
```

SSH 会提示输入密码；不要把密码写进命令或脚本。以下命令对应这台已调试过的小车，换设备时应重新确认路径与依赖。

## 当前功能与状态

| 功能 | 入口 | 模型 | 当前状态 |
| --- | --- | --- | --- |
| Astra+ USB 检查 | `lsusb` | 无 | 此前已识别 RGB `2bc5:0536` 和深度 `2bc5:0636`；实际项目只取彩色流 |
| 独立拍照与连续取帧 | `camera_probe.py` | 无 | 已拍到非黑色 1920×1080 JPG；10 分钟收到 17,920 帧 |
| 电脑浏览器实时监看 | `camera_preview.py` | 无 | 已验证 1280×720、15 fps；原生 MJPEG 直接转发，经 SSH 隧道访问 |
| 主程序相机共享内存 | `src/utils/camera_broadcaster.py` | 无 | 已单独验证真实画面写入共享内存；尚未运行完整 `main.py` |
| 手动驾驶与按 `p` 拍照 | `main.py --mode manual` | 无 | 代码具备，车轮着地期间未运行主程序 |
| 标识辅助转向 | `main.py --mode easy` 或 `cmd` 中输入 `Helper` | `weights/yolo.om` | 仓库有模型文件；推理与电机动作尚未实车验收 |
| 巡线 | `cmd` 中输入 `LF` | `weights/lfnet.om` | 仓库缺少模型；舵机和转向调用也需修复，不可直接使用 |
| 目标跟踪 | `cmd` 中输入 `Tracking` | `weights/tracking.om` | 仓库缺少模型；舵机调用也需修复，不可直接使用 |
| 语音模式 | `main.py --mode voice` | — | 代码明确抛出 `NotImplementedError`，未实现 |

`Helper` 当前只读取 `yolo.om`；旧文档提到的 `cls.om` 未在该场景中加载。`easy` 只启动 `Helper`。`cmd` 不能切换到 `Manual`。

## 安全边界与环境

**车轮着地时，只运行 USB 检查、`camera_probe.py` 和 `camera_preview.py`。不要运行 `main.py`，也不要为了测试相机导入 `src.utils`。** 当前车控模块在导入时就实例化底盘控制器，并访问电机 I²C 设备。下文主程序命令仅供车轮架空或电机断电、且车控准备妥当后使用；本分支尚未在该条件下完成主程序验收。

探针、网页预览和主程序都会打开 Astra+。同一时间只运行其中一个；启动下一个前先退出当前程序。`vi_l1_sample` 是 MIPI 摄像头样例，不是 Astra+ 的图像源。

车上已经安装适配 Astra+ 的 Orbbec SDK v1 Python 3.9 环境。其 binding 位于 `/home/HwHiAiUser/pyorbbecsdk/install/lib`，不要用系统 Python 3.10 直接运行这些相机脚本。

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
```

检查 USB、SDK 和模型文件；这些命令不会触碰电机：

```bash
lsusb | grep -E '2bc5:(0536|0636)'
$CAMERA_PY -c 'import cv2, pyorbbecsdk; print("Orbbec SDK ready")'
ls -lh weights/*.om
```

运行主程序前还须在同一环境中确认其依赖；`requirements.txt` 不包含全部当前运行依赖：

```bash
$CAMERA_PY -c 'import acl, ais_bench, yaml, serial, filelock, torch, smbus2; print("main dependencies ready")'
```

依赖检查通过只表示模块可导入，不表示车控已经验收。不要用运行 `main.py --help` 来代替安全检查，因为导入主程序也会导入车控模块。

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

## 主程序操作指令总表

**以下 `main.py` 命令可能接触电机，只能在车轮架空或电机断电、车控准备妥当后使用。** 先按第 1 节登录、进入 `python` 目录、设置环境，并退出独立相机探针或网页预览。以下命令中的 `$CAMERA_PY` 是第 1 节设置的 Python 3.9 路径。

| 启动命令（小车 SSH 终端） | 进入后如何操作 | 当前状态 |
| --- | --- | --- |
| `$CAMERA_PY main.py` 或 `$CAMERA_PY main.py --mode manual` | 直接按下方手动按键，不用回车 | 手动驾驶和拍照代码已接入，完整主程序尚未实车验收 |
| `$CAMERA_PY main.py --mode cmd` | 输入下方场景命令，**每条都要回车** | 场景命令入口已实现，场景状态见下表 |
| `$CAMERA_PY main.py --mode easy` | 自动启动 `Helper`；按 `Esc` 退出，其他按键无作用 | 依赖 `weights/yolo.om`，尚未实车验收 |
| `$CAMERA_PY main.py --mode voice` | 无可用语音命令 | 未实现，启动会抛出 `NotImplementedError` |

### manual：单键操作

SSH 登录须保留终端，例如 `ssh -tt root@192.168.8.204`。手动模式为单键输入，**不用按回车**；默认速度值为 `40`。动作键发出一次控制指令后，程序不会因松开按键自动停车，请用空格停车。当前手动模式没有终端预览窗口。

| 按键 | 代码中的操作 | 当前说明 |
| --- | --- | --- |
| `w` | 前进 | `Advance` |
| `s` | 后退 | `BackUp` |
| `a` | 左转 | `TurnLeft` |
| `d` | 右转 | `TurnRight` |
| `q` | 原地逆时针旋转 | `SpinAntiClockwise` |
| `e` | 原地顺时针旋转 | `SpinClockwise` |
| `z` 或 `←` | 左平移 | `ShiftLeft`；`z` **不会**掉头，后面的掉头分支无法执行 |
| `c` 或 `→` | 右平移 | `ShiftRight` |
| `Space`（空格） | 停车 | `Stop`，仍留在手动模式 |
| `Esc` | 停车并退出主程序 | 向手动场景发送退出消息 |
| `p` | 拍照 | 将共享内存中的当前彩色帧写入小车 `capture/`，文件名为时间戳 JPG |
| `↑` / `↓` | 代码意图是速度 `+1` / `-1`，范围 `0–100` | **当前有缺陷，不要使用**：按键后仍执行上一个动作；首次按可能因上一个动作为空而使场景报错 |
| 大写 `A` / `B` / `C` / `D` | 被误识别为 `↑` / `↓` / `→` / `←` | `getkey()` 把这些字母的 ASCII 值当成方向键代码；请只用表中的小写动作键 |
| `g` | 代码意图是舵机动作 | **当前不可用**：控制器没有初始化 `board`，执行会报错 |

其他按键（包括 `t`、`r`、`x`）没有手动控制功能。`p` 的截图只表示当前共享帧已写盘；若要独立验证相机取帧，请使用第 2 节的 `camera_probe.py`。在小车 SSH 终端查看最新手动截图：

```bash
ls -lt capture/*.jpg | head
```

### cmd：逐行输入的场景命令

启动 `$CAMERA_PY main.py --mode cmd` 后，输入以下**大小写完全一致**的文本，再按回车。它不接受 `w`、`a` 等手动驾驶按键。

| 输入 | 作用 | 当前状态 |
| --- | --- | --- |
| `Helper` | 启动识别标识后执行转向的自动场景 | 读取现有 `weights/yolo.om`；推理和电机动作尚未实车验收 |
| `LF` | 启动巡线场景 | 缺少 `weights/lfnet.om`；即使补齐，当前舵机调用及部分转向参数也会报错 |
| `Tracking` | 启动目标跟踪场景 | 缺少 `weights/tracking.om`；即使补齐，当前舵机调用也会报错 |
| `clear` | 结束已启动的所有场景并发出停车指令 | 保持在 `cmd`，之后可输入其他场景命令 |
| `stop` | 退出 `cmd` 和主程序 | 退出清理时会发出停车指令 |
| `Manual` | 无法切换手动模式 | 只打印不支持的错误；须退出后用 `--mode manual` 启动 |

未知命令只打印错误。重复输入场景名会再次启动进程，程序不会自动结束旧场景；切换前先输入 `clear`。`LF` 和 `Tracking` 的模型文件及代码问题未解决前不能作为可运行功能；不要照搬旧文档中的 `Ascend310B1` 转换命令来推断当前板卡的模型兼容性。

## 相机链路与验证范围

```text
Astra+ USB → pyorbbecsdk v1 → camera_probe.py → capture/*.jpg
                         ↘ camera_preview.py → 本机 MJPEG 服务 → SSH 隧道 → 电脑浏览器
                         ↘ CameraBroadcaster → 共享内存 → Manual / Helper / LF / Tracking
```

已验证独立取流、非黑截图、10 分钟连续取帧、浏览器预览和广播器共享内存。主程序及所有可能驱动电机的场景尚未在车轮安全条件下实车测试。训练与标注工具分别见 `Lane-Follow-Train/README.md`、`auto_label_tool/README.md` 和 `det_label_split/README.md`；它们不属于上述车载 SSH 运行入口。
